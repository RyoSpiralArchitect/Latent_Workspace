#!/usr/bin/env python3
"""Offline V15 receipt replay; no Torch, model loads, training, decoding or network."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import verify_v15_5_native_answer as old

REPO = Path(__file__).resolve().parents[1]
require, read = old.require, old.read


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def verify_update(row, *, arm, step, full, replay):
    require(
        (row["arm"], row["step"], row["replay"], row["expected_pairs"]) == (arm, step, replay, 16),
        "Update identity",
    )
    pairs = row["pairs"]
    require(
        [(r["world"], r["query"]) for r in pairs] == list(itertools.product(range(2), range(8))),
        "Full ordered pair window",
    )
    expected_parameters = 317 if full else 26
    for index, pair in enumerate(pairs, 1):
        spill = pair["spill"]
        require(
            spill["spill_count"] == index
            and spill["current_gradient_count"] == expected_parameters
            and spill["accumulated_parameter_count"] == expected_parameters,
            "Per-pair gradient coverage",
        )
        query_routes = [r for r in pair["routes"] if r["route"] == "query_to_reader"]
        require(
            len(query_routes) == 5 and all(r["backward_calls"] == 1 for r in query_routes),
            "Reader query gradient observations",
        )
        if full:
            for route in ("context_to_writer", "query_or_completion"):
                selected = [r for r in pair["routes"] if r["route"] == route]
                require(
                    len(selected) == 3 and all(r["backward_calls"] == 1 for r in selected),
                    "Live feature gradient observations",
                )
        values = pair["components"]
        expected_loss = (
            values["answer_ce"]
            + 0.25 * values["donor_hinge"]
            + 0.25 * values["unaffected_gap_square"]
            + 0.25 * values["unrelated_gap_square"]
            + 0.001 * values["residual_norm_square"]
        )
        # Independent Python arithmetic vs the recorded FP32 weighted sum.
        require(
            math.isclose(values["loss"], expected_loss, rel_tol=2e-6, abs_tol=2e-8),
            "Objective arithmetic",
        )
    for key, total in row["totals"].items():
        require(sum(p["components"][key] for p in pairs) == total, "Window reduction")
    update = row["update"]
    require(
        update["completed_step"] == step
        and update["transfer"]["spill_count"] == 16
        and update["transfer"]["consumed_parameter_count"] == expected_parameters,
        "Complete update coverage",
    )
    changes = update["base_changes"]
    require(
        len(changes) == (291 if full else 0) and len(update["bridge_changes"]) == 26,
        "Parameter update denominator",
    )
    require(len({r["name"] for r in changes}) == len(changes), "Unique physical base tensors")
    for r in changes:
        require(
            0 <= r["native_changed_elements"] <= r["elements"]
            and r["master_changed"] == (r["master_sha256_before"] != r["master_sha256_after"]),
            "Precision update accounting",
        )
    require(
        update["master_elements"] == (7_248_023_552 if full else 0), "Full base element coverage"
    )
    query = [r["l2"] for p in pairs for r in p["routes"] if r["route"] == "query_to_reader"]
    return dict(
        step=step,
        replay=replay,
        pairs=16,
        query_gradient_observations=len(query),
        mean_query_gradient_l2=sum(query) / len(query),
        total_loss=row["totals"]["loss"],
        base_tensors=len(changes),
        master_changed_tensors=sum(r["master_changed"] for r in changes),
        native_changed_tensors=sum(r["native_changed_elements"] > 0 for r in changes),
        native_changed_elements=sum(r["native_changed_elements"] for r in changes),
        normalization_changes=[r for r in changes if "norm" in r["name"]],
        bridge_changed_tensors=sum(r["changed"] for r in update["bridge_changes"]),
        preclip_base_l2=update["preclip_base_l2"],
        preclip_bridge_l2=update["preclip_bridge_l2"],
    )


def factor_summary(panel, evaluation):
    blocks, rows = panel["blocks"], panel["rows"]
    expected = set(
        itertools.product(
            range(2), (0, 2, 4, 6), ("actual", "common_slots", "same_memory", "random_pair")
        )
    )
    require(
        len(blocks) == 32
        and {(r["world"], r["even_query"], r["variant"]) for r in blocks} == expected,
        "Factor block denominator",
    )
    require(
        len(rows) == 128
        and len({(r["world"], r["query"], r["variant"], r["side"]) for r in rows}) == 128,
        "Four-corner denominator",
    )
    observed = {(r["world"], r["query"], r["control"]): r for r in evaluation}
    for row in rows:
        if row["variant"] == "actual":
            key = row["world"], row["query"], "intact" if row["side"] == 0 else "twin"
            require(
                row["native_scores"] == observed[key]["native_scores"],
                "Factor panel does not match evaluation",
            )
    for b in blocks:
        if b["variant"] == "same_memory":
            require(
                all(
                    b["factors"][stage][name]["l2"] == 0
                    for stage in ("r", "z", "x", "d")
                    for name in ("memory", "interaction")
                ),
                "Factor null",
            )
        binding = b["binding"]
        require(
            binding["both_donor_margins_positive"]
            == (binding["signed_interaction"] > abs(binding["memory_axis"])),
            "Factor binding inequality",
        )
    actual = [b for b in blocks if b["variant"] == "actual"]
    affected = [b for b in actual if b["even_query"] == 0]
    result = dict(
        blocks=32,
        corners=128,
        mean_delta_factors={
            name: sum(b["factors"]["d"][name]["l2"] for b in actual) / 8
            for name in ("common", "question", "memory", "interaction")
        },
        affected_binding=[dict(world=b["world"], **b["binding"]) for b in affected],
        projected_both_directions=sum(
            b["binding"]["both_donor_margins_positive"] for b in affected
        ),
        projected_direction_denominator=2,
        spectrum=panel["spectrum"],
    )
    return result


def build_phase(raw, seal, *, allow_incomplete=False):
    started = read(raw / "STARTED.json")
    require(
        started["source_commit"] == seal["source_commit"]
        and started["source_hashes"] == seal["source_hashes"]
        and started["plan"] == seal["plan"],
        "Source/plan receipt mismatch",
    )
    phase, plan = started["phase"], started["plan"]
    contract = plan[f"{phase}_phase"]
    complete = (raw / "FINISHED.json").is_file()
    require(complete or allow_incomplete, "No terminal completion; preserve missingness")
    report = read(raw / "REPORT.json") if complete else None
    if complete:
        require(not (raw / "FAILED.json").exists(), "Both terminal outcomes present")
        require(
            read(raw / "FINISHED.json")["report_sha256"] == digest(raw / "REPORT.json"),
            "Terminal report hash",
        )
        require(
            report["old_expression_gate"] == "FAIL"
            and report["winner"] == "none"
            and not report["semantic_promotion"]
            and report["non_regression"] == "NOT_ESTABLISHED"
            and report["judge_calls"] == 0,
            "Claim ceiling changed",
        )
    records = [
        json.loads(line)
        for line in (REPO / "data/v10/functional_train.jsonl").read_text().splitlines()
        if line
    ][:2]
    arms = {}
    for arm in contract["arms"]:
        full = phase == "full" and arm == "full"
        value = dict(updates=[], evaluation={}, generation={}, factors={}, checkpoint_receipts=[])
        for step in range(1, contract["steps"] + 1):
            path = raw / f"{arm}_{step}_update.json"
            if path.exists():
                value["updates"].append(
                    verify_update(read(path), arm=arm, step=step, full=full, replay=False)
                )
            else:
                require(not complete, "Missing completed update")
        for step in contract["evaluation_steps"]:
            path = raw / f"{arm}_{step}_evaluation.json"
            if path.exists():
                rows = read(path)["rows"]
                value["evaluation"][str(step)] = old.eval_summary(rows, records, step)
                factor = raw / f"{arm}_{step}_factors.json"
                if factor.exists():
                    value["factors"][str(step)] = factor_summary(read(factor), rows)
                elif step in contract["factor_steps"]:
                    require(not complete, "Missing completed factors")
            else:
                require(not complete, "Missing completed evaluation")
        for step in contract["generation_steps"]:
            path = raw / f"{arm}_{step}_generation.json"
            if path.exists():
                value["generation"][str(step)] = old.generation_summary(read(path)["rows"], records)
            else:
                require(not complete, "Missing completed generation")
        for step in contract["checkpoint_steps"]:
            path = raw / f"{arm}_{step}_checkpoint.json"
            if path.exists():
                receipt = read(path)
                require(
                    receipt["completed_steps"] == step and receipt["bytes"] > 0,
                    "Checkpoint boundary receipt",
                )
                value["checkpoint_receipts"].append(receipt)
            else:
                require(not complete, "Missing completed checkpoint receipt")
        if phase == "full":
            path = raw / f"{arm}_RESUME.json"
            if path.exists():
                resume = read(path)
                value["resume"] = resume
                expected = read(raw / f"{arm}_2_checkpoint.json")
                require(
                    resume["state_sha256"]
                    == resume["expected_state_sha256"]
                    == expected["state_sha256"]
                    and resume["exact"]
                    and resume["native_base_sha256"] == resume["expected_native_base_sha256"],
                    "Resume mismatch",
                )
                value["replay_update"] = verify_update(
                    read(raw / f"{arm}_2_replay_update.json"),
                    arm=arm,
                    step=2,
                    full=full,
                    replay=True,
                )
                original = read(raw / f"{arm}_2_update.json")
                replay = read(raw / f"{arm}_2_replay_update.json")
                require(
                    original["totals"] == replay["totals"]
                    and original["update"] == replay["update"],
                    "Resume objective/update receipts differ",
                )
            else:
                require(not complete, "Missing exact-resume outcome")
        arms[arm] = value
    return dict(
        phase=phase,
        status=report["status"] if report else "INCOMPLETE_NO_RETRY",
        report=report,
        failure=read(raw / "FAILED.json") if (raw / "FAILED.json").exists() else None,
        arms=arms,
        planned_evaluation_rows=576,
        planned_generated_sequences=80,
        stored_evaluation_rows=sum(len(v["evaluation"]) * 96 for v in arms.values()),
        stored_generated_sequences=sum(len(v["generation"]) * 20 for v in arms.values()),
    )


def file_index(bundle):
    return {
        str(path.relative_to(bundle)): dict(bytes=path.stat().st_size, sha256=digest(path))
        for path in sorted((bundle / "raw").rglob("*"))
        if path.is_file()
    }


def build(bundle, allow_incomplete=False):
    seal = read(bundle / "SOURCE_SEAL.json")
    for name, expected in seal["source_hashes"].items():
        require(digest(REPO / name) == expected, f"Current sealed source changed: {name}")
    require(
        read(bundle / "ARTIFACT_INDEX.json") == file_index(bundle), "Raw artifact index differs"
    )
    phases = {
        phase: build_phase(bundle / "raw" / phase, seal, allow_incomplete=allow_incomplete)
        for phase in ("reader", "full")
        if (bundle / "raw" / phase / "STARTED.json").exists()
    }
    require(bool(phases), "No phase started")
    if not allow_incomplete:
        require(set(phases) == {"reader", "full"}, "Missing phase")
    if len(phases) == 2 and all(p["report"] for p in phases.values()):
        # Identical step zero across all arms; no frozen historical score substitution.
        references = []
        for phase, summary in phases.items():
            for arm in summary["arms"]:
                references.append(read(bundle / "raw" / phase / f"{arm}_0_evaluation.json")["rows"])
        require(
            all(rows == references[0] for rows in references), "Fresh step-zero comparison mismatch"
        )
    return dict(
        source_commit=seal["source_commit"],
        phases=phases,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        semantic_promotion=False,
        judge_calls=0,
        claim="Exposed-set native learner engineering, not FT-beta quality qualification",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.write_index:
        write_new(args.bundle / "ARTIFACT_INDEX.json", file_index(args.bundle))
    result = build(args.bundle, args.allow_incomplete)
    if args.write_summary:
        write_new(args.bundle / "SUMMARY.json", result)
    elif (args.bundle / "SUMMARY.json").exists():
        require(read(args.bundle / "SUMMARY.json") == result, "Stored analysis differs")
    print(
        json.dumps(
            dict(
                status="OFFLINE_RECEIPTS_VERIFIED",
                phases={
                    k: dict(
                        status=v["status"],
                        evaluation_rows=v["stored_evaluation_rows"],
                        generated_sequences=v["stored_generated_sequences"],
                    )
                    for k, v in result["phases"].items()
                },
            )
        )
    )


if __name__ == "__main__":
    main()
