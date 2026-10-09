#!/usr/bin/env python3
"""Seal or read-only verify the bounded CPU learner-audit receipts, without models.

This checks recorded contracts and numerical summaries, not the original tensors,
backpropagation, checkpoint bodies, CUDA equivalence, or model-quality claims.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "provenance/pilots/ft_beta_learner_audit_20261009"
STATES = ("initial", "legacy_task256", "legacy_semantic256", "centered_semantic256")
CONTROLS = (
    "intact", "twin", "zero", "fixed_carrier", "norm_matched_random", "unrelated",
    "different_schema", "same_world_reserialization",
)
GROUPS = (
    "writer", "query_projection", "query_norm", "reader_q", "reader_k", "reader_v",
    "reader_out", "up",
)
TERMS = (
    "paired_ce", "donor_hinge", "unaffected_gap_square", "unrelated_gap_square",
    "residual_norm_square",
)
DIAGNOSTICS = ("donor_even_hinge", "donor_odd_hinge")
SOURCES = (
    "scripts/run_ft_beta_learner_audit.py",
    "src/latent_workspace_ft_v10/learner_gradient_audit.py",
)
RAW_NAMES = {"STARTED.json", "FEATURES.json", "REPORT.json"} | {
    f"{state}_{kind}.json" for state in STATES for kind in ("gradients", "reader", "controls")
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_tree(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite JSON value")
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def load(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or symlinked file: {path}")
    value = json.loads(path.read_text())
    finite_tree(value)
    return value


def aggregate(rows, excluded):
    return {
        key: {
            "mean": sum(row[key] for row in rows) / len(rows),
            "mean_abs": sum(abs(row[key]) for row in rows) / len(rows),
            "max": max(row[key] for row in rows),
        }
        for key in rows[0] if key not in excluded
    }


def verify_controls(control, records, initial=False):
    rows = control["rows"]
    expected = set(itertools.product(range(2), range(8), (0, 1), CONTROLS))
    keys = [(r["world"], r["query"], r["side"], r["control"]) for r in rows]
    require(len(rows) == 256 and set(keys) == expected, "Control denominator/grid changed")
    require(control["zero_full_logit_checks"] == 16, "Zero native parity denominator changed")
    require(control["scope"] == "CPU_train_only_two_candidate_no_generation", "Control scope")
    require(control["different_schema_amplitude_matched"] is False, "Amplitude claim inflated")
    require(control["random_matching"] == "historical_global_raw_memory_L2", "Random contract")
    baselines = {}
    for row in rows:
        world, query, side = row["world"], row["query"], row["side"]
        require(len(row["scores"]) == len(row["base_scores"]) == 2, "Candidate width changed")
        key = world, query
        require(baselines.setdefault(key, row["base_scores"]) == row["base_scores"],
                "Base candidate scores differ within common prefix")
        require(row["original_label"] == records[world]["answers"][side][query] and
                row["twin_label"] == records[world]["answers"][1 - side][query],
                "Recorded train labels changed")
        require(row["yes_minus_no"] == row["scores"][1] - row["scores"][0], "Gap mismatch")
        require(0 <= row["delta_l2"] <= 1.000001, "Residual outside fixed norm cap")
        if row["control"] == "zero" or initial:
            require(row["delta_l2"] == 0 and row["scores"] == row["base_scores"],
                    "Exact zero/candidate-base parity failed")


def verify_reader(reader, state_summary):
    protocol = reader["protocol"]
    require(protocol["world_selection"] == "first_training_worlds" and
            protocol["world_count"] == 2 and protocol["sides"] == [0, 1] and
            protocol["query_indices"] == list(range(8)), "Reader selection changed")
    require(protocol["held_out_evidence"] is False and
            protocol["manual_reconstruction"] is False and
            protocol["attention_path"] == "actual_Q_K_V_production_need_weights_false",
            "Reader claim changed")
    rows, pairs = reader["rows"], reader["pairs"]
    require(len(rows) == 32 and {
        (r["world"], r["side"], r["query_index"]) for r in rows
    } == set(itertools.product(range(2), (0, 1), range(8))), "Reader row grid changed")
    require(len(pairs) == 16 and {
        (r["world"], r["side"], r["even_query"], r["odd_query"]) for r in pairs
    } == {(w, s, q, q + 1) for w, s, q in itertools.product(range(2), (0, 1), range(0, 8, 2))},
            "Reverse-query grid changed")
    summary = {
        "row_count": 32, "pair_count": 16,
        "row_metrics": aggregate(rows, {"world", "side", "query_index"}),
        "pair_metrics": aggregate(pairs, {"world", "side", "even_query", "odd_query"}),
    }
    require(reader["summary"] == summary == state_summary, "Reader summary mismatch")
    return summary


def verify_gradients(gradients, cell):
    require(gradients["format"] == "latent-workspace-loss-gradient-audit-v1", "Gradient format")
    require(gradients["optimizer_steps"] == 0, "Optimizer step was recorded")
    for key in ("bridge_state_unchanged", "parameter_grads_unchanged", "module_modes_unchanged"):
        require(gradients[key] is True, f"Mutation receipt failed: {key}")
    require(gradients["frozen_input_names"] == ["context", "head_rows", "query"],
            "Frozen input contract changed")
    batch = gradients["batch"]
    require(batch["world_query_order"] == [[w, q] for w in range(2) for q in range(8)] and
            batch["affected_count"] == 4 and batch["unaffected_count"] == 12 and
            len(batch["donor_margins"]) == 16, "Gradient batch denominator changed")
    require(batch["objective_cell"] == cell and batch["not_a_training_schedule_replay"] is True and
            batch["query_representation"] == "original_final_normalized_last_prefix_position",
            "Gradient objective/query contract changed")
    reconstruction = gradients["reconstruction"]
    require(reconstruction["atol"] == 1e-6 and reconstruction["rtol"] == 1e-5,
            "Gradient reconstruction tolerance changed")
    require(reconstruction["passed"] is True and set(reconstruction["groups"]) == set(GROUPS) and
            all(row["passed"] is True for row in reconstruction["groups"].values()),
            "Gradient reconstruction receipt failed")
    terms = gradients["terms"]
    require(set(terms) == set(TERMS + DIAGNOSTICS), "Objective component set changed")
    coefficients = dict.fromkeys(TERMS, 0.25 if cell == "semantic" else 0.0)
    coefficients.update(paired_ce=1.0, residual_norm_square=0.001)
    for name, term in terms.items():
        require(set(term["raw"]) == set(GROUPS), "Gradient group coverage changed")
        if name in TERMS:
            require(term["included_in_objective"] is True and term["weight"] == coefficients[name]
                    and set(term["weighted"]) == set(GROUPS), "Objective weighting changed")
        else:
            require(term["included_in_objective"] is False and term["weight"] is None and
                    term["weighted"] is None, "Diagnostic entered training objective")
        for group in GROUPS:
            raw = term["raw"][group]
            require(raw["status"] in {"missing", "zero", "nonzero"}, "Unknown gradient status")
            if raw["status"] == "missing":
                require(raw["l2"] is None and raw["present_elements"] == 0, "Missing disguised")
            else:
                require(raw["l2"] is not None and raw["l2"] >= 0 and
                        raw["present_elements"] > 0, "Invalid observed gradient")
                require((raw["status"] == "zero") == (raw["l2"] == 0) and
                        (raw["nonzero_elements"] == 0) == (raw["l2"] == 0),
                        "Zero/nonzero gradient status mismatch")
            if name in TERMS:
                weighted = term["weighted"][group]
                expected_norm = None if raw["l2"] is None else raw["l2"] * abs(term["weight"])
                require(weighted["l2"] is None if expected_norm is None else
                        weighted["l2"] is not None and math.isclose(
                            weighted["l2"], expected_norm, rel_tol=1e-12, abs_tol=0
                        ), "Raw/weighted gradient norm mismatch")
    pairs = gradients["pairwise"]
    require(len(pairs) == 21 and {
        frozenset((p["first"], p["second"])) for p in pairs
    } == {frozenset(pair) for pair in itertools.combinations(TERMS + DIAGNOSTICS, 2)},
            "Gradient pairwise denominator changed")
    donor_pair = next(p for p in pairs if {p["first"], p["second"]} == set(DIAGNOSTICS))
    cancellation = {}
    for group in GROUPS:
        combined = terms["donor_hinge"]["raw"][group]["l2"]
        even, odd = [terms[name]["raw"][group]["l2"] for name in DIAGNOSTICS]
        denominator = None if even is None or odd is None else 0.5 * (even + odd)
        cancellation[group] = {
            "combined_l2": combined, "even_l2": even, "odd_l2": odd,
            "combined_over_mean_direction_norm": (
                combined / denominator if combined is not None and denominator else None
            ),
            "even_odd_cosine": donor_pair["raw"][group]["cosine"],
        }
    return {
        "reciprocal_hinge_gradient_geometry": cancellation,
        "loss_gradient_norms": {
            name: {group: {"raw": terms[name]["raw"][group]["l2"],
                           "weighted": terms[name]["weighted"][group]["l2"]}
                   for group in GROUPS} for name in TERMS
        },
    }


def verify_contracts(bundle, repo=REPO):
    raw = bundle / "raw"
    require(raw.is_dir() and not raw.is_symlink(), "Raw directory missing or symlinked")
    require({p.name for p in raw.iterdir()} == RAW_NAMES, "Raw artifact inventory changed")
    data = {name: load(raw / name) for name in RAW_NAMES}
    report, features = data["REPORT.json"], data["FEATURES.json"]
    receipt = report["receipt"]
    require(data["STARTED.json"] == receipt, "Start/final receipt mismatch")
    require(re.fullmatch(r"[0-9a-f]{40}", receipt["source_commit"]) is not None, "Source commit")
    require(set(receipt["source_hashes"]) == set(SOURCES), "Source coverage changed")
    for name, expected in receipt["source_hashes"].items():
        require(digest(repo / name) == expected, f"Source hash mismatch: {name}")
    require(receipt["device"] == "cpu" and receipt["cuda_visible_devices"] == "" and
            receipt["optimizer_steps"] == 0 and receipt["world_indices"] == [0, 1] and
            receipt["dataset_split"] == "train_only_exposed", "CPU/train/no-update contract")
    require(report["status"] == "COMPLETED_CPU_TRAIN_ONLY_DIAGNOSTIC" and
            report["cuda_initialized"] is False and report["cuda_allocated_bytes"] == 0,
            "CPU execution receipt failed")
    require(report["winner"] == "none" and report["statistical_or_quality_qualification"] is False
            and report["free_text_legacy_controls"] == "NOT_RUN" and
            report["new_offload_parity"] == "NOT_TESTED", "Claim ceiling inflated")
    require(report["base_parameter_count"] == 7248023552 and
            report["base_parameter_bytes"] == 14496047104, "Pinned base size changed")
    historical = {
        "legacy": load(repo / "provenance/pilots/v14_precision_bridge_20261009/raw/report.json"),
        "centered": load(repo / "provenance/pilots/v14_mech_repair_20261009/repair/report.json"),
    }
    require(report["base_state_sha256_before"] == report["base_state_sha256_after"] ==
            historical["legacy"]["base_state_sha256_before"], "Base hash/mutation mismatch")
    require(report["historical_cuda_peak_allocated_bytes"] ==
            historical["legacy"]["peak_cuda_bytes"],
            "Historical memory receipt mismatch")
    plan = load(repo / "configs/v14/PRECISION_BRIDGE_PLAN.json")
    require(plan["data"]["train"]["path"] == "data/v10/functional_train.jsonl" and
            digest(repo / "data/v10/functional_train.jsonl") == plan["data"]["train"]["sha256"],
            "Training data identity changed")
    lines = (repo / "data/v10/functional_train.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines if line.strip()][:2]
    require(sum(records[w]["answers"][0][q] != records[w]["answers"][1][q]
                for w in range(2) for q in range(8)) == 4, "Train affected denominator changed")
    require(features["CPU_CUDA_numerical_equivalence"] == "NOT_TESTED" and
            features["feature_dtype"] == "torch.bfloat16" and
            features["prefix_forwards"] == 16 and features["candidate_ids"] == [1476, 5849],
            "Feature contract changed")
    tokens = features["query_token_ids"]
    require(len(tokens) == 2 and all(len(row) == 8 for row in tokens), "Query prefix grid")
    gates = features["native_gates"]
    require(len(gates) == 16 and len({g["prefix_sha256"] for g in gates}) == 16,
            "Native parity gate denominator changed")
    for prefix, gate in zip(itertools.chain.from_iterable(tokens), gates):
        prefix_hash = hashlib.sha256(json.dumps(prefix, separators=(",", ":")).encode()).hexdigest()
        require(gate["full_logits_exact"] is True and gate["vocabulary_size"] == 32768 and
                gate["token_count"] == len(prefix) and gate["prefix_sha256"] == prefix_hash,
                "Native parity/token identity receipt failed")
    require(set(report["states"]) == set(STATES), "Checkpoint state grid changed")
    summary = {}
    for state in STATES:
        cell = "task" if state == "legacy_task256" else "semantic"
        family = "centered" if state.startswith("centered") else "legacy"
        previous = historical[family]["training"][cell]
        current = report["states"][state]
        expected_hash = previous["initial_state_sha256" if state == "initial"
                                 else "final_state_sha256"]
        expected_checkpoint = None if state == "initial" else next(
            p for p in previous["checkpoints"] if p["path"].endswith(f"/{cell}_step256.pt")
        )
        require(current["state_sha256"] == expected_hash and
                current["checkpoint"] == expected_checkpoint and current["unchanged"] is True and
                current["parameters"] == 4200192 and current["zero_checks"] == 16,
                f"Checkpoint identity/mutation receipt failed: {state}")
        verify_controls(data[f"{state}_controls.json"], records, initial=state == "initial")
        reader = verify_reader(data[f"{state}_reader.json"], current["reader_summary"])
        summary[state] = verify_gradients(data[f"{state}_gradients.json"], cell)
        summary[state]["reverse_query_relative_l2"] = {
            stage: reader["pair_metrics"][f"{stage}_relative_l2"]
            for stage in ("query", "projected_query", "attention_output", "raw_delta", "delta")
        }
    return {
        "format": "ft-beta-learner-audit-summary-v1", "states": summary,
        "denominators": {"training_worlds": 2, "world_queries": 16,
                         "affected_world_queries": 4, "unaffected_world_queries": 12,
                         "control_rows_per_state": 256, "reader_rows_per_state": 32,
                         "reverse_pairs_per_state": 16, "native_prefix_checks": 16},
        "claim_boundary": "CPU train-only gradient geometry; no optimizer step or efficacy claim",
    }


def artifact_index(bundle):
    return {
        "format": "ft-beta-learner-audit-raw-index-v1",
        "artifacts": [
            {"path": f"raw/{name}", "bytes": (bundle / "raw" / name).stat().st_size,
             "sha256": digest(bundle / "raw" / name)} for name in sorted(RAW_NAMES)
        ],
    }


def validation():
    return {
        "status": "PASS_RECORDED_CONTRACTS_AND_RAW_INTEGRITY_ONLY", "raw_artifacts": 15,
        "gradients_recomputed": False, "checkpoint_bodies_rehashed": False,
        "quality_qualification": False, "optimizer_steps": 0,
    }


def verify_bundle(bundle, repo=REPO):
    require(load(bundle / "ARTIFACT_INDEX.json") == artifact_index(bundle),
            "Raw artifact index/hash mismatch")
    summary = verify_contracts(bundle, repo)
    require(load(bundle / "SUMMARY.json") == summary, "Derived summary mismatch")
    require(load(bundle / "VALIDATION.json") == validation(), "Validation claim changed")
    return validation()


def seal_bundle(bundle, repo=REPO):
    outputs = ("ARTIFACT_INDEX.json", "SUMMARY.json", "VALIDATION.json")
    require(not any((bundle / name).exists() or (bundle / name).is_symlink() for name in outputs),
            "Seal output collision; existing evidence will not be overwritten")
    summary = verify_contracts(bundle, repo)
    for name, value in zip(outputs, (artifact_index(bundle), summary, validation())):
        with (bundle / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
    return verify_bundle(bundle, repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    operation = seal_bundle if args.seal else verify_bundle
    print(json.dumps(operation(args.bundle.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
