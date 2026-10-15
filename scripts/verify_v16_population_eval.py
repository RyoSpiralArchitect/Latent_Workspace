#!/usr/bin/env python3
"""Offline population receipt replay and bounded paired summaries; no model load."""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v16_population_eval as run  # noqa: E402


def bootstrap(strata, repetitions=2000, seed=16101599):
    """Percentile paired bootstrap, resampling units within fixed strata.

    Functional units are complete worlds, not reciprocal queries. MMLU units
    are questions within subject. This does not estimate training-seed variance.
    """
    rng = random.Random(seed)
    values = [x for group in strata for x in group]
    if not values or any(not group for group in strata):
        raise ValueError("Nonempty bootstrap units/strata required")
    draws = sorted(
        sum(rng.choice(group) for group in strata for _ in group) / len(values)
        for _ in range(repetitions)
    )
    return {
        "estimate": sum(values) / len(values),
        "interval_95": [
            draws[int(0.025 * (repetitions - 1))],
            draws[int(0.975 * (repetitions - 1))],
        ],
        "units": len(values),
        "strata": len(strata),
        "replicates": repetitions,
        "method": "paired_percentile_within_fixed_strata_not_training_seed_uncertainty",
    }


def verify(path, seal, qualification_dir):
    core = run.load("run_v16_adapter_migration")
    core.load_runtime()
    from latent_workspace_ft_v10.v16_population_probe import choice4

    previous = run.load("verify_v16_full_comparison")
    plan = run.read(run.ROOT / run.PLAN)
    worlds, mmlu, _ = run.inputs(core, plan)
    start, end = [run.read(path / f"{s}.json") for s in ("STARTED", "FINISHED")]
    observed = run.manifest(core, path)
    observed.pop("FINISHED.json")
    run.require(end["files"] == observed, "Dispatcher manifest")
    run.require(start["seal"] == seal and start["plan"] == plan, "Dispatcher identity")
    run.require(
        end["status"] == run.PASS and end["completed_arms"] == plan["arms"],
        "Incomplete population run; retain missingness",
    )
    qualified = run.qualification(core, qualification_dir, seal)
    reports, originals, original_mmlu = {}, None, None
    token_receipt = None
    for arm in plan["arms"]:
        directory = path / arm
        begin, finish = [run.read(directory / f"{s}.json") for s in ("STARTED", "FINISHED")]
        files = run.manifest(core, directory)
        files.pop("FINISHED.json")
        run.require(files == finish["files"], "Arm manifest")
        run.require(
            begin["source"] == seal
            and begin["plan"] == plan
            and begin["qualification"] == qualified
            and finish["arm"] == arm,
            "Arm identity",
        )
        run.require(
            finish["status"] == run.PASS
            and finish["completed_worlds"] == len(worlds)
            and finish["completed_mmlu"] == len(mmlu),
            "Arm completion counts",
        )
        run.require(all(finish[k] == v for k, v in run.CEILING.items()), "Claim ceiling")
        run.require(
            finish["peak_cuda_reserved_bytes"] <= plan["resources"]["allocator_cap_gib"] * 2**30
            and finish["elapsed_seconds"] <= plan["resources"]["max_elapsed_seconds"],
            "Resource ceiling",
        )
        run.require(
            finish["state_unchanged"]
            and run.read(directory / "BEFORE.json") == run.read(directory / "AFTER.json"),
            "State changed",
        )
        restore = run.read(directory / "RESTORE.json")
        run.require(restore["old_evaluation_replay_exact"], "Historical restore parity")
        tokens = run.read(directory / "TOKENS.json")
        if token_receipt is None:
            token_receipt = tokens
        run.require(tokens == token_receipt, "Cross-model token/input mismatch")
        rows = [json.loads(line) for line in (directory / "mmlu.jsonl").read_text().splitlines()]
        run.require(len(rows) == len(mmlu), "MMLU coverage")
        for r, item in zip(rows, mmlu, strict=True):
            run.require(
                (r["id"], r["subject"], r["target"])
                == (item["id"], item["subject"], item["target"]),
                "MMLU frozen selection",
            )
            measured = choice4(r["scores"])
            run.require(all(r[k] == v for k, v in measured.items()), "MMLU score/tie arithmetic")
            run.require(
                r["correct"] == (r["prediction"] == r["target"])
                and r["strict_correct"] == (r["strict_prediction"] == r["target"]),
                "MMLU correctness arithmetic",
            )
        if original_mmlu is None:
            original_mmlu = rows
        strata = defaultdict(list)
        for r, base in zip(rows, original_mmlu, strict=True):
            run.require(
                all(
                    r[k] == base[k] for k in ("id", "target", "prompt_ids_sha256", "candidate_ids")
                ),
                "MMLU paired identity",
            )
            if arm != "original":
                run.require(
                    r["regression"] == (base["correct"] and not r["correct"])
                    and r["repair"] == (not base["correct"] and r["correct"]),
                    "MMLU transition arithmetic",
                )
            strata[r["subject"]].append(int(r["correct"]) - int(base["correct"]))
        bench = dict(
            n=len(rows),
            correct=sum(r["correct"] for r in rows),
            strict_correct=sum(r["strict_correct"] for r in rows),
            ties=sum(r["tie"] for r in rows),
            regressions=sum(b["correct"] and not r["correct"] for b, r in zip(original_mmlu, rows)),
            repairs=sum(not b["correct"] and r["correct"] for b, r in zip(original_mmlu, rows)),
            paired_delta=bootstrap(
                list(strata.values()), plan["bootstrap_replicates"], plan["bootstrap_seed"]
            ),
            per_subject={s: {"n": len(v), "delta_sum": sum(v)} for s, v in strata.items()},
        )
        values = [run.read(directory / f"world_{i:03d}.json") for i in range(len(worlds))]
        if originals is None:
            originals = values
        conditions, factors = defaultdict(Counter), defaultdict(Counter)
        deltas, trace_values = defaultdict(lambda: defaultdict(list)), defaultdict(list)
        for index, (record, value) in enumerate(zip(worlds, values, strict=True)):
            run.require(
                value["world_index"] == index and value["pair_id"] == record["metadata"]["pair_id"],
                "World identity",
            )
            run.require(len(value["direct_base"]) == 8, "Base query count")
            for q, row in enumerate(value["direct_base"]):
                run.require(
                    row["world"] == 0
                    and row["query"] == q
                    and row["labels"] == [a[q] for a in record["answers"]],
                    "World labels",
                )
                gap = row["scores"][1] - row["scores"][0]
                run.require(
                    row["gap"] == gap and row["prediction"] == (None if gap == 0 else int(gap > 0)),
                    "Direct choice arithmetic",
                )
            if arm == "original":
                continue
            run.require(
                value["original_base"] == originals[index]["direct_base"]
                and value["parameter_versions_unchanged"],
                "World original/state binding",
            )
            replay = copy.deepcopy(value)
            # This flag is derived from the verified whole-arm BEFORE == AFTER above.
            replay["owned_state_fingerprint_unchanged"] = True
            summary = previous.verify_evaluation(
                replay, {"worlds": [0], "queries": list(range(8))}, 2
            )
            for condition, row in summary["conditions"].items():
                conditions[condition].update({k: v for k, v in row.items() if isinstance(v, int)})
                if row["labelled_n"]:
                    delta = (row["repairs_from_original"] - row["regressions_from_original"]) / row[
                        "labelled_n"
                    ]
                    deltas[condition][record["metadata"]["data_seed"]].append(delta)
            for factor, row in summary["factors"].items():
                factors[factor].update({k: v for k, v in row.items() if isinstance(v, int)})
            run.require(len(value["traces"]) == 16, "Trace denominator")
            for trace in value["traces"]:
                if trace["interaction_present"]:
                    run.require(
                        trace["interaction_reconstruction_exact"]
                        and not trace["shadow_weights_are_production_output"],
                        "Trace ceiling",
                    )
                    for key, v in trace.items():
                        if isinstance(v, float):
                            trace_values[key].append(v)
        reports[arm] = dict(
            mmlu=bench,
            worlds=len(values),
            conditions=dict(conditions),
            factors=dict(factors),
            world_cluster_paired_deltas={
                c: bootstrap(
                    list(groups.values()), plan["bootstrap_replicates"], plan["bootstrap_seed"]
                )
                for c, groups in deltas.items()
            },
            traces={
                k: {"n": len(v), "mean": sum(v) / len(v), "min": min(v), "max": max(v)}
                for k, v in trace_values.items()
            },
            elapsed_seconds=finish["elapsed_seconds"],
            peak_cuda_reserved_bytes=finish["peak_cuda_reserved_bytes"],
        )
    return {
        "status": run.PASS,
        "arms": reports,
        "independent_training_seeds": 1,
        "mmlu_scope": plan["mmlu"]["workspace"],
        **run.CEILING,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--seal", required=True, type=Path)
    parser.add_argument("--qualification", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.bundle, run.read(args.seal), args.qualification)
    if args.output:
        run.load("run_v16_adapter_migration").write_new(args.output, report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
