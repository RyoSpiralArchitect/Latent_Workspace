#!/usr/bin/env python3
"""Verify the fixed-weight MI, fresh-world repair, and four-turn receipts.

This is a read-only CPU verifier. By default, checkpoint metadata is checked;
--verify-weights additionally hashes the retained bodies on Furnace. No model
is loaded and no GPU experiment is repeated.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
MI_PLAN = "configs/v14/BRIDGE_MECHANISTIC_PLAN.json"
REPAIR_PLAN = "configs/v14/CENTERED_BRIDGE_PLAN.json"
OLD_PLAN = "configs/v14/PRECISION_BRIDGE_PLAN.json"
OLD_VERIFY = "provenance/pilots/v14_precision_bridge_20261009/verify.py"
STATES = ("initial", "task128", "task256", "semantic128", "semantic256")
CELLS = ("task", "semantic")
VARIANTS = ("legacy", "centered")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import verifier dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def finite_tree(value: Any, where: str = "JSON") -> None:
    if isinstance(value, float):
        require(math.isfinite(value), f"Nonfinite value at {where}")
    elif isinstance(value, dict):
        for key, item in value.items():
            finite_tree(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite_tree(item, f"{where}[{index}]")


def read_json(path: Path, previous: Any) -> dict[str, Any]:
    result = previous.load(path)
    finite_tree(result, str(path))
    return result


def check_receipt(receipt: dict[str, Any], repo: Path, previous: Any) -> None:
    path = previous.inside(repo, receipt["path"])
    require(path.is_file() and not path.is_symlink(), f"Receipt path absent: {path}")
    require(previous.digest(path) == receipt["sha256"], f"Receipt hash changed: {path}")
    if "bytes" in receipt:
        require(path.stat().st_size == receipt["bytes"], f"Receipt byte count changed: {path}")


def verify_sources(report: dict[str, Any], plan: dict[str, Any], repo: Path, previous: Any) -> None:
    require(report["source_identity"] == plan["source_identity"], "Source identity map mismatch")
    require(bool(report["source_identity"]), "Unfrozen source identity")
    for path, sha in report["source_identity"].items():
        check_receipt({"path": path, "sha256": sha}, repo, previous)


def verify_started(path: Path, plan_sha: str, previous: Any) -> str:
    started = read_json(path, previous)
    require(started["plan_sha256"] == plan_sha, "Started/plan mismatch")
    commit = started["source_commit"]
    require(
        isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
        "Missing full source commit",
    )
    return commit


def verify_mechanistic(
    report: dict[str, Any],
    plan: dict[str, Any],
    old_report: dict[str, Any],
    records: list[dict[str, Any]],
    repo: Path,
    previous: Any,
    verify_weights: bool,
) -> dict[str, Any]:
    require(report["status"] == "QUALIFIED_EXECUTION", "MI execution did not qualify")
    require(report["winner"] == "none" and plan["semantic_promotion"] is False, "MI promotion")
    require(report["training"] is False and report["eval_data_used"] is False, "MI data leakage")
    require(report["frozen_weights_unchanged"] is True, "MI checkpoint mutation")
    require(plan["dataset_split"] == "train_only", "MI split changed")
    require(
        plan["world_indices"] == list(range(16)) and plan["states"] == list(STATES),
        "MI frozen grid changed",
    )
    require(plan["manual_replication_atol"] == 1e-5, "MI reconstruction tolerance widened")
    require(report["plan_sha256"] == previous.digest(repo / MI_PLAN), "MI plan hash changed")
    verify_sources(report, plan, repo, previous)
    check_receipt(plan["predecessor"], repo, previous)

    expected_inventory = {
        f"{cell}{step}": save
        for cell in CELLS
        for step, save in zip((128, 256), old_report["training"][cell]["checkpoints"], strict=True)
    }
    require(report["checkpoint_inventory"] == expected_inventory, "MI checkpoint inventory")
    if verify_weights:
        for receipt in expected_inventory.values():
            check_receipt(receipt, repo, previous)
    identities = report["identities"]
    require(set(identities) == set(STATES), "MI state inventory")
    require(
        identities["initial"]["state_sha256"]
        == old_report["training"]["task"]["initial_state_sha256"]
        == old_report["training"]["semantic"]["initial_state_sha256"],
        "MI initial identity",
    )
    for cell in CELLS:
        require(
            identities[f"{cell}256"]["state_sha256"]
            == old_report["training"][cell]["final_state_sha256"],
            "MI final state identity",
        )

    rows, pairs = report["rows"], report["pairs"]
    index = {(r["state"], r["world_index"], r["side"], r["query_index"]): r for r in rows}
    expected = set(itertools.product(STATES, range(16), range(2), range(8)))
    require(len(rows) == len(index) == 1280 and set(index) == expected, "MI trace grid closure")
    for (state, world, side, query), row in index.items():
        source = records[world]
        require(row["pair_id"] == source["metadata"]["pair_id"], "MI training pair drift")
        require(row["query_text"] == source["queries"][query], "MI query drift")
        require(
            0 <= row["manual_delta_max_error"] <= plan["manual_replication_atol"],
            "Manual reader reconstruction failed",
        )
        require(
            row["metrics"]["manual_delta_allclose"] is True
            and row["metrics"]["manual_attention_allclose"] is True,
            "Manual trace mismatch",
        )
        require(set(row["interventions"]) == set(plan["interventions"]), "MI intervention set")
        permutation = row["interventions"]["slot_permutation"]
        require(
            all(v == 0 for v in permutation["contrast"].values())
            and permutation["gap_change"] == 0,
            "Slot-permutation placebo not exact",
        )
        require(row["metrics"]["delta_l2_mean"] <= 1.0, "MI residual cap exceeded")
        if state == "initial":
            require(row["delta_gap"] == row["metrics"]["delta_l2_mean"] == 0, "Initial nonzero")
    pair_index = {
        (r["state"], r["world_index"], r["side"], tuple(r["query_indices"])): r for r in pairs
    }
    expected_pairs = set(
        itertools.product(STATES, range(16), range(2), ((0, 1), (2, 3), (4, 5), (6, 7)))
    )
    require(
        len(pairs) == len(pair_index) == 640 and set(pair_index) == expected_pairs,
        "MI reverse-pair closure",
    )
    for (state, world, side, (first, second)), pair in pair_index.items():
        require(set(pair["stages"]) == set(plan["stages"]), "MI stage inventory")
        expected_gap = (
            index[(state, world, side, second)]["delta_gap"]
            - index[(state, world, side, first)]["delta_gap"]
        )
        require(pair["gap_difference"] == expected_gap, "MI reverse-pair gap mismatch")
        for stage in pair["stages"].values():
            require(
                set(stage) == {"l2", "relative_l2", "max_abs"}
                and all(v >= 0 for v in stage.values()),
                "MI contrast norm invalid",
            )
    from run_v14_bridge_mechanistic import summarize

    require(summarize(rows, pairs) == report["summary"], "MI summary does not rebuild")
    return {
        "trace_rows": len(rows),
        "reverse_pairs": len(pairs),
        "manual_delta_max_error": max(r["manual_delta_max_error"] for r in rows),
        "slot_permutation_exact": True,
        "training_worlds_only": 16,
    }


def verify_fresh_data(plan: dict[str, Any], repo: Path, previous: Any) -> dict[str, Any]:
    check_receipt(plan["fresh_preparation"], repo, previous)
    prep_path = repo / plan["fresh_preparation"]["path"]
    prep = read_json(prep_path, previous)
    require(
        prep["status"] == "PREPARED_NOT_EVALUATED" and prep["seed"] == 901009,
        "Fresh preparation contract",
    )
    require(plan["fresh_eval_scored_before_design"] is False, "Fresh outcome-driven design")
    check_receipt(
        {"path": "scripts/prepare_v14_mech_corpus.py", "sha256": prep["preparer_source_sha256"]},
        repo,
        previous,
    )
    check_receipt(
        {"path": prep["generator"]["path"], "sha256": prep["generator"]["source_sha256"]},
        repo,
        previous,
    )
    datasets = {}
    for split, receipt in plan["data"].items():
        check_receipt(receipt, repo, previous)
        datasets[split] = [
            json.loads(line)
            for line in (repo / receipt["path"]).read_text().splitlines()
            if line.strip()
        ]
    require(
        len(datasets["train"]) == 256 and len(datasets["eval"]) == 64, "Fresh data denominators"
    )
    require(
        previous.digest(prep_path.parent / prep["fresh_corpus"]["path"])
        == prep["fresh_corpus"]["sha256"]
        == plan["data"]["eval"]["sha256"],
        "Fresh identity",
    )
    prior_records = []
    for receipt in prep["prior_corpora"]:
        check_receipt(receipt, repo, previous)
        records = [
            json.loads(line)
            for line in (repo / receipt["path"]).read_text().splitlines()
            if line.strip()
        ]
        require(len(records) == receipt["rows"], "Prior corpus denominator")
        prior_records.extend(records)
    from prepare_v14_mech_corpus import audit_disjoint, select_disjoint

    from latent_workspace_ft_v10.engine import make_functional_relation_pair_records

    require(
        audit_disjoint(prior_records, datasets["eval"]) == prep["split_audit"],
        "Fresh disjointness audit mismatch",
    )
    require(
        prep["candidate_pool_world_pairs"] == 128 and prep["accepted_world_pairs"] == 64,
        "Fresh sampling budget",
    )
    candidates = make_functional_relation_pair_records(
        worlds=128,
        seed=901009,
        width=6,
        queries_per_world=8,
        heldout_template="Does {left} outrank {right}? Answer:",
        heldout_fraction=0.5,
    )
    accepted, rejected = select_disjoint(candidates, prior_records)
    for row in accepted:
        row["choices"] = [" no", " yes"]
    require(accepted == datasets["eval"], "Fresh deterministic generation mismatch")
    require(rejected == prep["rejections_before_completion"], "Fresh rejection receipt")
    require(
        [r["metadata"]["world_index"] for r in accepted] == prep["accepted_generator_indices"],
        "Fresh selection order",
    )
    return {"datasets": datasets, "preparation": prep}


def verify_reader_panels(panels: dict[str, Any], report: dict[str, Any]) -> None:
    from latent_workspace_ft_v10.bridge_reader_panel import _aggregate

    expected_names = {f"{family}_{cell}" for family in VARIANTS for cell in CELLS}
    require(set(panels) == expected_names, "Reader panel condition closure")
    require(report["panel_uses_training_worlds_only"] is True, "Reader panel split")
    for name, panel in panels.items():
        require(
            panel["protocol"]
            == {
                "world_selection": "first_training_worlds",
                "world_count": 16,
                "sides": [0, 1],
                "query_indices": list(range(8)),
                "relative_l2_denominator": "0.5 * (norm(a) + norm(b)) + 1e-12",
                "attention_path": "actual_Q_K_V_production_need_weights_false",
                "manual_reconstruction": False,
                "held_out_evidence": False,
            },
            f"Reader panel protocol changed: {name}",
        )
        rows, pairs = panel["rows"], panel["pairs"]
        index = {(r["world"], r["side"], r["query_index"]): r for r in rows}
        require(
            len(rows) == len(index) == 256
            and set(index) == set(itertools.product(range(16), range(2), range(8))),
            f"Reader row closure: {name}",
        )
        pair_index = {(r["world"], r["side"], r["even_query"], r["odd_query"]): r for r in pairs}
        expected = {
            (world, side, query, query + 1)
            for world, side, query in itertools.product(range(16), range(2), (0, 2, 4, 6))
        }
        require(
            len(pairs) == len(pair_index) == 128 and set(pair_index) == expected,
            f"Reader pair closure: {name}",
        )
        for row in rows:
            require(0 <= row["delta_l2"] <= 1.0, f"Reader residual norm: {name}")
            require(
                row["permutation_delta_max_abs_error"] <= 1e-5,
                f"Reader slot-permutation invariance: {name}",
            )
        for pair in pairs:
            require(
                pair["keys_relative_l2"] == pair["values_relative_l2"] == 0,
                f"Memory changed across reverse queries: {name}",
            )
        rebuilt = {
            "row_count": len(rows),
            "pair_count": len(pairs),
            "row_metrics": _aggregate(rows, {"world", "side", "query_index"}),
            "pair_metrics": _aggregate(pairs, {"world", "side", "even_query", "odd_query"}),
        }
        require(
            rebuilt == panel["summary"] == report["panel_summary"][name],
            f"Reader summary drift: {name}",
        )


def verify_repair(
    report: dict[str, Any],
    plan: dict[str, Any],
    old_plan: dict[str, Any],
    old_report: dict[str, Any],
    mi_report: dict[str, Any],
    data: dict[str, Any],
    bundle: Path,
    repo: Path,
    previous: Any,
    verify_weights: bool,
) -> dict[str, Any]:
    require(report["status"] == "QUALIFIED_EXECUTION", "Repair did not qualify")
    require(
        report["winner"] == "none"
        and report["semantic_promotion"] is False
        and plan["semantic_promotion"] is False,
        "Repair promotion",
    )
    require(report["plan_sha256"] == previous.digest(repo / REPAIR_PLAN), "Repair plan hash")
    require(
        report["runtime"]
        == plan["expected_runtime"]
        == old_plan["expected_runtime"]
        == mi_report["runtime"],
        "Runtime changed",
    )
    verify_sources(report, plan, repo, previous)
    for name in ("predecessor", "predecessor_trace", "fresh_preparation"):
        require(report[name] == plan[name], f"Repair {name} receipt drift")
        check_receipt(plan[name], repo, previous)
    for name in (
        "model",
        "bridge",
        "training",
        "data_config_parent",
        "scenarios",
        "expected_runtime",
    ):
        require(plan[name] == old_plan[name], f"Matched training contract changed: {name}")
    require(plan["data"]["train"] == old_plan["data"]["train"], "Training corpus changed")
    require(
        plan["conditions"] == [f"{family}_{cell}" for family in VARIANTS for cell in CELLS],
        "Repair condition inventory",
    )
    require(
        plan["repair"] == "center_value_only_after_memory_norm_keep_keys_queries_cap_and_loss",
        "Selected repair changed",
    )
    require(
        report["base_state_sha256_before"]
        == report["base_state_sha256_after"]
        == old_report["base_state_sha256_before"],
        "Original base changed",
    )
    require(
        report["base_unchanged"] is True and report["base_native_split_exact"] is True,
        "Original base integrity",
    )
    require(report["base_control"] == "independently_loaded_pinned_original", "Base provenance")
    require(report["split_audit"] == data["preparation"]["split_audit"], "Fresh split audit drift")

    initial = read_json(bundle / "repair/INITIAL_IDENTITY.json", previous)
    require(initial == report["initial_identity"], "Initial identity receipt mismatch")
    require(
        initial["base_native_split_exact"] is True
        and initial["sample"] == "training world0 side0 query0",
        "Initial native identity",
    )
    require(set(initial["families"]) == set(VARIANTS), "Initial family closure")
    for family in VARIANTS:
        require(
            initial["families"][family]["zero_delta_native_fp32_exact"] is True,
            "Initial bridge not zero-exact",
        )
        require(
            initial["families"][family]["initial_state_sha256"]
            == old_report["training"]["task"]["initial_state_sha256"],
            "Initial state drift",
        )
    identity = read_json(bundle / "repair/CENTERED_INTERVENTION_IDENTITY.json", previous)
    require(identity == report["centered_intervention_identity"], "Intervention identity drift")
    require(
        identity["passed"] is True
        and identity["absolute_tolerance"] == 1e-5
        and 0 <= identity["max_absolute_error"] <= 1e-5,
        "Repair/intervention equivalence",
    )
    require(
        identity["clone_saved"] is False
        and identity["legacy_trace_used_only_on_legacy_class"] is True,
        "Intervention gate provenance",
    )

    require(
        report["legacy_checkpoint_inventory"] == mi_report["checkpoint_inventory"],
        "Legacy inventory drift",
    )
    expected_states = {cell: old_report["training"][cell]["final_state_sha256"] for cell in CELLS}
    require(
        report["legacy_states_before"] == report["legacy_states_after"] == expected_states,
        "Legacy bridge changed",
    )
    require(report["legacy_checkpoint_bodies_unchanged"] is True, "Legacy body mutation")
    require(
        report["training_matches_archived_initialization_schedule_and_parameter_count"] is True,
        "Unmatched training",
    )
    checkpoint_bytes = previous.verify_training(report, plan, repo, verify_weights)
    for cell in CELLS:
        training = report["training"][cell]
        require(
            training == read_json(bundle / f"repair/training_{cell}.json", previous),
            f"Training raw/report mismatch: {cell}",
        )
        require(training["resumed_from_old_weights"] is False, "Repair warm-start confound")
        for field in ("initial_state_sha256", "schedule_sha256", "trainable_parameters"):
            require(
                training[field] == old_report["training"][cell][field],
                f"Matched training changed: {cell}/{field}",
            )

    from v14_precision_bridge_eval import summarize_multiturn, summarize_single

    singles, multis = {}, {}
    for family, cell in itertools.product(VARIANTS, CELLS):
        name = f"{family}_{cell}"
        raw = read_json(bundle / f"repair/single_{name}.json", previous)
        singles[name] = previous.verify_single(raw, data["datasets"]["eval"], step0=False)
        require(
            summarize_single(raw["rows"]) == raw["summary"] == report["single_summary"][name],
            f"Single summary drift: {name}",
        )
    for key in singles["legacy_task"]:
        require(
            all(
                index[key]["base_dual_readout"] == singles["legacy_task"][key]["base_dual_readout"]
                for index in singles.values()
            ),
            "Single original base scores changed between families/cells",
        )
    for family in VARIANTS:
        raw = read_json(bundle / f"repair/multiturn_{family}.json", previous)
        previous.verify_multi(raw, data["datasets"]["eval"])
        require(
            summarize_multiturn(raw["rows"])
            == raw["summary"]
            == report["multiturn_summary"][family],
            f"Four-turn summary drift: {family}",
        )
        multis[family] = {
            tuple(
                row[k]
                for k in ("condition", "scenario", "history_mode", "selected_readout", "regime")
            ): row
            for row in raw["rows"]
            if row["model"] == "base"
        }
    require(multis["legacy"] == multis["centered"], "Four-turn base changed across families")
    panels = read_json(bundle / "repair/reader_panels.json", previous)
    verify_reader_panels(panels, report)
    expected_denominators = {"single_rows": 24576, "trajectories": 1792, "turns": 7168}
    require(report["denominators"] == expected_denominators, "Repair denominator drift")
    return {
        **expected_denominators,
        "new_checkpoint_count": 4,
        "new_checkpoint_bytes": checkpoint_bytes,
        "reader_panel_rows": 1024,
        "reader_panel_reverse_pairs": 512,
        "initial_zero_exact": True,
        "zero_controls_exact_base": True,
        "matched_uniforms_recomputed": True,
        "fixed_history_intact_twin_prefixes_equal": True,
    }


def verify(bundle: Path, repo: Path, *, verify_weights: bool) -> dict[str, Any]:
    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "scripts"))
    previous = load_module("v14_precision_bridge_previous_verifier", repo / OLD_VERIFY)
    artifact_index = read_json(bundle / "ARTIFACT_INDEX.json", previous)
    artifacts = artifact_index["artifacts"]
    by_path = {item["path"]: item for item in artifacts}
    require(len(artifacts) == len(by_path) > 0, "Empty or duplicate artifact index")
    for receipt in artifacts:
        check_receipt(receipt, repo, previous)
    required = [
        repo / MI_PLAN,
        repo / REPAIR_PLAN,
        repo / OLD_VERIFY,
        bundle / "verify.py",
        bundle / "SUMMARY.json",
        bundle / "REPAIR_DECISION.md",
        bundle / "mechanistic/STARTED.json",
        bundle / "mechanistic/report.json",
    ]
    raw_names = (
        "STARTED.json",
        "report.json",
        "INITIAL_IDENTITY.json",
        "CENTERED_INTERVENTION_IDENTITY.json",
        "reader_panels.json",
        "training_task.json",
        "training_semantic.json",
    )
    required += [bundle / "repair" / name for name in raw_names]
    required += [
        bundle / f"repair/single_{family}_{cell}.json"
        for family, cell in itertools.product(VARIANTS, CELLS)
    ]
    required += [bundle / f"repair/multiturn_{family}.json" for family in VARIANTS]
    plan = read_json(repo / REPAIR_PLAN, previous)
    required += [repo / plan["fresh_preparation"]["path"]]
    required += [repo / spec["path"] for spec in plan["data"].values()]
    require(all(str(path.relative_to(repo)) in by_path for path in required), "Unindexed evidence")
    old_plan = read_json(repo / OLD_PLAN, previous)
    old_report = read_json(repo / plan["predecessor"]["path"], previous)
    mi_plan = read_json(repo / MI_PLAN, previous)
    mi = read_json(bundle / "mechanistic/report.json", previous)
    report = read_json(bundle / "repair/report.json", previous)
    data = verify_fresh_data(plan, repo, previous)
    mi_result = verify_mechanistic(
        mi, mi_plan, old_report, data["datasets"]["train"], repo, previous, verify_weights
    )
    repair_result = verify_repair(
        report, plan, old_plan, old_report, mi, data, bundle, repo, previous, verify_weights
    )
    mi_commit = verify_started(bundle / "mechanistic/STARTED.json", mi["plan_sha256"], previous)
    repair_commit = verify_started(bundle / "repair/STARTED.json", report["plan_sha256"], previous)
    require(repair_commit == report["source_commit"], "Repair source commit mismatch")
    summary = read_json(bundle / "SUMMARY.json", previous)
    for key, expected in (
        ("mechanistic_summary", mi["summary"]),
        ("single_summary", report["single_summary"]),
        ("multiturn_summary", report["multiturn_summary"]),
        ("panel_summary", report["panel_summary"]),
    ):
        require(summary[key] == expected, f"Published summary mismatch: {key}")
    require(
        summary["winner"] == "none" and summary["semantic_promotion"] is False,
        "Published promotion",
    )
    return {
        "format": "latent-workspace-v14-mech-repair-bundle-verification-v1",
        "status": "PASS",
        "mechanistic": mi_result,
        "repair": repair_result,
        "fresh_worlds": 64,
        "disjoint_from_train_and_prior_eval_worlds": 320,
        "fresh_generation_recomputed": True,
        "summaries_recomputed": True,
        "checkpoint_payload_validation": "sha256_and_size"
        if verify_weights
        else "receipt_metadata_only",
        "legacy_checkpoint_count": 4,
        "artifact_hashes_checked": len(artifacts),
        "mechanistic_source_commit": mi_commit,
        "repair_source_commit": repair_commit,
        "winner": "none",
        "semantic_promotion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--verify-weights", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(
            args.bundle.resolve(), args.repo.resolve(), verify_weights=args.verify_weights
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
