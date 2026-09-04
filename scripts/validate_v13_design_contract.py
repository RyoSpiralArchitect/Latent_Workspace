#!/usr/bin/env python3
"""Read-only V13 design-document checks; never runtime or scientific qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = "latent-workspace-ft-v13-normalization-state-design-v1"
ANCHORS = {
    "src/latent_workspace_ft_v10/engine.py": (
        "aee2a1fe3b95c6c0ff21d89870c0d3bb959da28fc544aaa9aced7ccc0abae133"
    ),
    "configs/v12/CONTRACT.json": "3dd0fe81f5519c9721430c8ae259f3739b6b69e99cb6dda0cc4fca79d7536a60",
    "provenance/pilots/v12_calibrated_route/refinement16/FINAL_RECEIPT.json": (
        "b46e3c2e01d3f384b0e2d02dc613edb57cbb585ad7002601e4d298a9ed9b1c0b"
    ),
    "provenance/pilots/v12_calibrated_route/refinement16/V13_HANDOFF.json": (
        "056bef47819113b5afc0ea9d72e034ef0576fbc6072b1680d7f1a4906a6519e1"
    ),
}
AUTHORITY_FIELDS = {
    "training",
    "base_release",
    "scale_up_14b",
    "remote_jobs",
    "weight_pruning",
    "v14_bridge_training",
}
IMPLEMENTATION = {
    "design_validator": "IMPLEMENTED",
    "paired_metric_repair": "NOT_IMPLEMENTED",
    "hard_task_generator": "NOT_IMPLEMENTED",
    "normalization_trace": "NOT_IMPLEMENTED",
    "coordinate_interventions": "NOT_IMPLEMENTED",
    "transition_interventions": "NOT_IMPLEMENTED",
    "conditional_modulation": "NOT_IMPLEMENTED",
    "scientific_runs": "NOT_RUN",
}
DEPENDENCIES = {
    "S0_INSTRUMENT": set(),
    "S1_VISIBILITY": {"S0_INSTRUMENT"},
    "S2_COORDINATES": {"S0_INSTRUMENT", "S1_VISIBILITY"},
    "S3_TRANSITIONS": {"S0_INSTRUMENT", "S1_VISIBILITY", "S2_COORDINATES"},
    "S4_MODULATION_OPTIONAL": {"S0_INSTRUMENT", "S1_VISIBILITY", "S2_COORDINATES"},
}
STAGE_LANES = {
    "S0_INSTRUMENT": {"retained_inline_diagnostic", "deferred_primary"},
    "S1_VISIBILITY": {"retained_inline_diagnostic"},
    "S2_COORDINATES": {"retained_inline_diagnostic", "deferred_primary"},
    "S3_TRANSITIONS": {"deferred_primary"},
    "S4_MODULATION_OPTIONAL": {"retained_inline_diagnostic", "deferred_primary"},
}
CONTENT_GATES = {
    "instrument_and_artifact_integrity",
    "requalified_task_sufficiency",
    "positive_paired_donor_effect",
    "intact_correct_to_donor_correct_with_full_denominators",
    "matched_content_control_effect",
    "unaffected_retention",
    "heldout_affected_and_unaffected_coverage",
}
UNRESOLVED_FIELDS = {
    "new_dataset_generator_counts_seeds_and_split_manifests",
    "numerical_noop_reconstruction_and_null_tolerances",
    "minimum_sufficiency_effect_and_retention_thresholds",
    "cluster_uncertainty_resampling_and_multiplicity_plan",
    "gain_grid_optimizer_schedule_seed_count_and_compute_budget",
    "recurrent_horizon_and_intermediate_reader_qualification",
    "optional_modulation_site_capacity_and_feature_source",
    "implementation_hashes_and_separate_execution_approval",
}


def _safe_file(repo_root: Path, value: Any) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("expected a plain repository-relative file path without traversal")
    candidate = repo_root.joinpath(*value.split("/"))
    cursor = repo_root
    for part in value.split("/"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("symlink references are not allowed")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(repo_root) or not resolved.is_file():
        raise ValueError("reference must name an existing regular file inside the repository")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_contract(contract: Any, repo_root: Path) -> list[str]:
    """Return design-consistency errors, not permission or runtime-qualification results."""
    errors: list[str] = []

    def mapping(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            errors.append(f"{label}: expected an object")
            return {}
        return value

    def exact(obj: dict[str, Any], key: str, expected: Any, label: str) -> None:
        value = obj.get(key)
        if key not in obj or type(value) is not type(expected) or value != expected:
            errors.append(f"{label}.{key}: must be {expected!r} with its exact JSON type")

    def text_field(obj: dict[str, Any], key: str, label: str) -> None:
        if not isinstance(obj.get(key), str) or not obj[key].strip():
            errors.append(f"{label}.{key}: nonempty measurement/design text is required")

    def members(
        obj: dict[str, Any],
        key: str,
        required: set[str],
        label: str,
        *,
        exact_set: bool = False,
    ) -> set[str]:
        values = obj.get(key)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            errors.append(f"{label}.{key}: expected a list of distinct nonempty strings")
            return set()
        found = set(values)
        if len(found) != len(values):
            errors.append(f"{label}.{key}: duplicate entries are not allowed")
        if not required <= found or (exact_set and found != required):
            errors.append(f"{label}.{key}: required design entries differ: {sorted(required)}")
        return found

    if not isinstance(contract, dict):
        return ["contract: expected a JSON object, not a pass/fail summary"]
    try:
        root = Path(repo_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            return ["repo_root: expected an existing directory"]
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return [f"repo_root: {type(exc).__name__}"]

    exact(contract, "format", FORMAT, "contract")
    exact(contract, "schema_version", 1, "contract")
    exact(contract, "status", "DESIGN_ONLY", "contract")
    exact(contract, "frozen_for_execution", False, "contract")
    exact(contract, "parent_commit", "fce1e8515b6344adefb9ef529939167371d5ba72", "contract")
    text_field(contract, "question", "contract")
    # Harmless extra documentation is allowed; new positive authority claims are not.
    for key in ("execution_ready", "qualified", "runtime_qualified", "scientifically_qualified"):
        if key in contract:
            exact(contract, key, False, "contract")

    anchors = contract.get("historical_anchors")
    seen: set[str] = set()
    if not isinstance(anchors, list) or len(anchors) != len(ANCHORS):
        errors.append("historical_anchors: exactly four pinned anchors are required")
    if isinstance(anchors, list):
        for index, raw_anchor in enumerate(anchors):
            label = f"historical_anchors[{index}]"
            anchor = mapping(raw_anchor, label)
            raw_path = anchor.get("path")
            try:
                path = _safe_file(root, raw_path)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                errors.append(f"{label}.path: {exc}")
                continue
            if raw_path in seen:
                errors.append(f"{label}.path: duplicate anchor")
            seen.add(raw_path)
            expected_hash = ANCHORS.get(raw_path)
            if expected_hash is None:
                errors.append(f"{label}.path: not one of the four historical anchors")
                continue
            exact(anchor, "sha256", expected_hash, label)
            try:
                if _sha256(path) != expected_hash:
                    errors.append(f"{label}: historical anchor content SHA-256 changed")
            except OSError as exc:
                errors.append(f"{label}: cannot read historical anchor ({type(exc).__name__})")
    if seen != set(ANCHORS):
        errors.append("historical_anchors: the complete pinned path set is required")

    authority = mapping(contract.get("execution_authority"), "execution_authority")
    for key in AUTHORITY_FIELDS | set(authority):
        exact(authority, key, False, "execution_authority")
    implementation = mapping(contract.get("implementation_status"), "implementation_status")
    for key, value in IMPLEMENTATION.items():
        exact(implementation, key, value, "implementation_status")
    for key in set(implementation) - set(IMPLEMENTATION):
        if implementation[key] not in ("NOT_IMPLEMENTED", "NOT_RUN", "PARKED_DESIGN_ONLY"):
            errors.append(f"implementation_status.{key}: unqualified implementation claim")

    model = mapping(contract.get("model_anchor"), "model_anchor")
    for key, value in {
        "name_or_path": "mistralai/Mistral-7B-Instruct-v0.3",
        "revision": "c170c708c41dac9275d15a8fff4eca08d52bab71",
        "base_weights": "FROZEN_THROUGHOUT_V13",
        "native_normalizer": "RMSNorm_UNCHANGED",
        "pure_native_b_f1_o3_parity": "DEFERRED_NOT_A_PREREQUISITE",
    }.items():
        exact(model, key, value, "model_anchor")

    state = mapping(contract.get("state_contract"), "state_contract")
    for key in ("readable_now", "transition_effective"):
        text_field(state, key, "state_contract")
    for key, value in {
        "two_views_not_assumed_independent_stores": True,
        "coordinate_source": "RAW_PRE_AFFINE_STATE",
        "factorization": ("m = mu * ones + rho * u; mean(u)=0; RMS(u)=1; rho=sqrt(mean((m-mu)^2))"),
        "factorization_uses_normalizer_epsilon": False,
        "actual_layernorm_formula": "gamma * (rho / sqrt(rho^2 + epsilon)) * u + beta",
        "reconstruct_then_apply_actual_checkpoint_normalizer": True,
        "coordinate_interpretation": "NO_PREASSIGNED_SEMANTICS_OR_CONFIDENCE",
        "degenerate_radius_policy": "MARK_UNKNOWN_AND_REPORT_COVERAGE_DO_NOT_IMPUTE_DIRECTION",
        "slot_matching": "SAME_CHECKPOINT_SAME_SLOT_INDEX_NO_LABEL_BASED_ALIGNMENT",
        "hybrid_slot_map_frozen_across_all_cells_and_patch_modes": True,
        "mean_shift_under_current_pre_norm_architecture": "STRUCTURAL_NULL_NOT_SEMANTIC_SUCCESS",
        "normalizer_policy": "RECORD_ACTUAL_EPS_GAMMA_BETA_DTYPE_AND_PROJECTION",
        "architecture_fingerprint_includes_non_tensor_attributes": True,
        "update_means": "RECURRENT_ACTIVATION_TRANSITION_NOT_OPTIMIZER_STEP",
        "bridge_claim_in_v13": False,
    }.items():
        exact(state, key, value, "state_contract")

    lanes = mapping(contract.get("input_lanes"), "input_lanes")
    for lane_id, information, claim in (
        (
            "retained_inline_diagnostic",
            "ORIGINAL_WORLD_CONTEXT_PRESENT",
            "CONDITIONAL_ACCESSIBILITY_OR_CONFLICT_OVERRIDE_NOT_DEFERRED_SUFFICIENCY",
        ),
        (
            "deferred_primary",
            "QUERY_WITHOUT_ORIGINAL_WORLD_CONTEXT",
            "DEFERRED_SUFFICIENCY_ONLY_AFTER_SAME_ROUTE_QUALIFICATION",
        ),
    ):
        lane = mapping(lanes.get(lane_id), f"input_lanes.{lane_id}")
        exact(lane, "query_and_base_information", information, f"input_lanes.{lane_id}")
        exact(lane, "claim", claim, f"input_lanes.{lane_id}")
    exact(lanes, "record_sources_per_stage", True, "input_lanes")
    exact(lanes, "requalify_reader_and_sufficiency_on_each_route", True, "input_lanes")
    exact(lanes, "pool_metrics_across_lanes", False, "input_lanes")

    measurement = mapping(contract.get("measurement_contract"), "measurement_contract")
    for key in (
        "per_case_predictions_and_logits_required",
        "intact_correct_to_donor_correct_required",
        "report_intact_wrong_rows_and_all_affected_denominator",
        "unaffected_prediction_agreement_required",
        "unaffected_ground_truth_accuracy_separate",
        "content_control_effect_required",
        "require_each_claim_gate_not_f3_f4_only",
        "optimization_seed_variation_separate_from_world_uncertainty",
    ):
        exact(measurement, key, True, "measurement_contract")
    for key, value in {
        "paired_donor_logodds_gain": (
            "(z_swap[donor]-z_swap[original])-(z_intact[donor]-z_intact[original]); "
            "affected rows only"
        ),
        "donor_accuracy_alone_is_causal_evidence": False,
        "uncertainty_unit": "ORIGINAL_WORLD_FAMILY_CLUSTER",
        "missing_or_degenerate_measurement": "UNKNOWN_NOT_PASS",
        "freeform_scope": (
            "CAPTURE_BASE_ONLY_AND_FULL_WRAPPER_SEPARATELY_OR_MARK_WRAPPER_UNSUPPORTED"
        ),
    }.items():
        exact(measurement, key, value, "measurement_contract")
    for key, required in {
        "cluster_includes": {
            "both_sides",
            "all_queries",
            "alternate_edits",
            "renamings",
            "rendering_variants",
            "all_interventions",
        },
        "null_controls": {
            "identity",
            "memory_blind_internal_inversion",
            "fixed_carrier",
            "norm_matched_random",
            "true_bypass",
            "slot_permutation_invariance",
        },
        "matched_eval_surface": {
            "collated_input_ids_masks_labels_choice_ids",
            "batch_shape_and_padding",
            "autocast_and_accumulation_dtype",
            "runtime_math_and_attention_backend",
            "rng_and_dropout",
            "same_input_pre_save_post_reload",
        },
        "artifact_binding": {
            "source_commit_and_source_hash",
            "requested_and_resolved_config_equivalence",
            "base_and_workspace_content_hashes",
            "tokenizer_and_prompt_hashes",
            "data_and_split_hashes",
            "runtime_environment",
            "per_case_trace_hashes",
        },
    }.items():
        members(measurement, key, required, "measurement_contract")

    data = mapping(contract.get("data_contract"), "data_contract")
    for key in (
        "query_selection_uses_both_worlds",
        "same_original_world_query_has_both_affected_statuses_across_edits",
        "must_balance_affected_and_unaffected_within_structural_strata",
        "heldout_template_crosses_affected_status",
        "hop_distance_recorded_for_both_worlds",
        "shuffle_query_order_and_balance_answer_patterns",
        "match_twin_fact_presentation_order",
        "entity_renaming_test_required",
    ):
        exact(data, key, True, "data_contract")
    for key, value in {
        "legacy_v10_corpus_use": "NUMERICAL_DIAGNOSTIC_ONLY_NOT_V13_GENERALIZATION_TEST",
        "primary_query_family": "INTERNAL_NONADJACENT_RELATIONS",
        "twin_edit": "CONSTRAINED_INTERNAL_NONADJACENT_SWAP_OR_BLOCK_REORDER",
        "adjacent_only_twins_allowed_for_primary_claim": False,
        "sampling_order": (
            "ORIGINAL_WORLD_AND_QUERY_THEN_ALTERNATE_EDITS_THEN_PAIRED_ELIGIBILITY_AUDIT"
        ),
        "positive_control": "SYMBOLIC_PATH_ORACLE_AND_PINNED_MATCHED_INLINE_MODEL",
        "split_policy": "SEPARATE_CALIBRATION_DEVELOPMENT_SEALED_TEST_BY_PAIRED_WORLD_FAMILY",
        "numeric_counts_seeds_and_thresholds": "PENDING_PREFLIGHT_FREEZE",
    }.items():
        exact(data, key, value, "data_contract")
    members(
        data,
        "primary_task_shortcut_oracles",
        {
            "direct_edge_endpoint_rule",
            "memory_blind_internal_inversion",
            "query_position_only",
            "query_only",
        },
        "data_contract",
    )

    raw_stages = contract.get("stages")
    stages: dict[str, dict[str, Any]] = {}
    graph: dict[str, set[str]] = {}
    if not isinstance(raw_stages, list):
        errors.append("stages: expected a list of explicit unimplemented stages")
    else:
        for index, raw_stage in enumerate(raw_stages):
            stage = mapping(raw_stage, f"stages[{index}]")
            stage_id = stage.get("id")
            if not isinstance(stage_id, str) or not stage_id:
                errors.append(f"stages[{index}].id: nonempty string required")
                continue
            if stage_id in stages:
                errors.append(f"stages: duplicate stage id {stage_id}")
                continue
            stages[stage_id] = stage
            expected_status = (
                "PARKED_DESIGN_ONLY" if stage_id == "S4_MODULATION_OPTIONAL" else "NOT_IMPLEMENTED"
            )
            exact(stage, "status", expected_status, stage_id)
            text_field(stage, "purpose", stage_id)
            if stage_id in STAGE_LANES:
                members(stage, "input_lanes", STAGE_LANES[stage_id], stage_id, exact_set=True)
            else:
                declared_lanes = members(stage, "input_lanes", set(), stage_id)
                if not declared_lanes or declared_lanes - {
                    "retained_inline_diagnostic",
                    "deferred_primary",
                }:
                    errors.append(f"{stage_id}.input_lanes: unknown or absent input route")
            graph[stage_id] = members(
                stage, "depends_on", DEPENDENCIES.get(stage_id, set()), stage_id
            )
    if not set(DEPENDENCIES) <= set(stages):
        errors.append("stages: all five required stages must be declared")
    for stage_id, dependencies in graph.items():
        if dependencies - set(stages):
            errors.append(f"{stage_id}.depends_on: unknown stage reference")
    # Iterative topological removal also rejects self-cycles without recursive depth limits.
    pending = {name: deps & set(stages) for name, deps in graph.items()}
    while pending:
        ready = {name for name, deps in pending.items() if not deps}
        if not ready:
            errors.append("stages.depends_on: dependency cycle")
            break
        pending = {name: deps - ready for name, deps in pending.items() if name not in ready}

    visibility = stages.get("S1_VISIBILITY", {})
    members(
        visibility,
        "trace_points",
        {
            "raw_slot_state",
            "actual_memory_norm_output",
            "projected_keys_and_values",
            "query_specific_read",
            "gated_update_before_residual_roundtrip",
            "recovered_delta_after_residual_roundtrip",
            "adapter_input_and_output",
            "candidate_residual_before_cast",
            "candidate_residual_after_cast",
            "candidate_logits_after_accumulation",
        },
        "S1_VISIBILITY",
    )
    exact(visibility, "readout_control", "POST_ADAPTER_GAIN_AND_FP32_ACCUMULATION", "S1_VISIBILITY")

    coordinates = stages.get("S2_COORDINATES", {})
    factors = members(
        coordinates, "factors", {"shape", "radius", "mean"}, "S2_COORDINATES", exact_set=True
    )
    levels = members(
        coordinates, "donor_levels", {"original", "twin"}, "S2_COORDINATES", exact_set=True
    )
    exact(coordinates, "factorial_cells", 8, "S2_COORDINATES")
    if len(levels) ** len(factors) != 8:
        errors.append("S2_COORDINATES: full factorial must be 2^3 = 8 design cells")
    for key in ("both_swap_directions_required", "identity_and_self_reconstruction_required"):
        exact(coordinates, key, True, "S2_COORDINATES")
    members(
        coordinates,
        "held_fixed",
        {
            "checkpoint",
            "query",
            "masks",
            "slot_indices",
            "reader",
            "gain",
            "dtype",
        },
        "S2_COORDINATES",
    )
    exact(
        coordinates,
        "followup_if_statistics_help",
        "SEPARATE_STATISTICS_CHANNEL_WITH_CONSTANT_AND_SHUFFLED_STATISTICS_CONTROLS",
        "S2_COORDINATES",
    )

    transitions = stages.get("S3_TRANSITIONS", {})
    if transitions.get("candidate_writer_steps") != [1, 2, 4] or any(
        type(value) is not int for value in transitions.get("candidate_writer_steps", [])
    ):
        errors.append("S3_TRANSITIONS.candidate_writer_steps: integer horizons [1, 2, 4] required")
    exact(transitions, "reader_steps", 1, "S3_TRANSITIONS")
    members(
        transitions,
        "patch_modes",
        {
            "read_now",
            "resume_remaining_transitions",
            "carry_only",
        },
        "S3_TRANSITIONS",
        exact_set=True,
    )
    for key, value in {
        "must_qualify_each_horizon": True,
        "reuse_k1_checkpoint_as_trained_k4_evidence": False,
        "intermediate_readout_distribution_shift_must_be_reported": True,
        "matched_parameter_budget_schedule_and_compute_reporting": True,
        "normalization_topology_changed_with_horizon": False,
    }.items():
        exact(transitions, key, value, "S3_TRANSITIONS")

    modulation = stages.get("S4_MODULATION_OPTIONAL", {})
    for key, value in {
        "formula": "n=N_native(h); n_prime=n+a*(delta_gamma(M,Q)*n+delta_beta(M,Q))",
        "native_normalizer_replaced": False,
        "modulation_head_output_init": "ZERO",
        "outer_gain_init": "FIXED_NONZERO_BOUNDED",
        "single_site": "PENDING_PREFLIGHT_FREEZE",
        "primary_input_lane": "QUERY_ONLY_REQUALIFIED_WITHOUT_ORIGINAL_WORLD_CONTEXT",
        "inline_input_lane_claim": "CONFLICT_OVERRIDE_NOT_DEFERRED_SUFFICIENCY",
    }.items():
        exact(modulation, key, value, "S4_MODULATION_OPTIONAL")
    members(
        modulation,
        "controls",
        {
            "no_op",
            "trained_static",
            "query_only",
            "fixed_carrier",
            "memory_conditioned",
            "matched_non_normalization_site_modulation",
        },
        "S4_MODULATION_OPTIONAL",
    )

    gates = mapping(contract.get("claim_gates"), "claim_gates")
    members(gates, "content_specific_requires_all", CONTENT_GATES, "claim_gates")
    for key in (
        "representation_probe_success_is_causal_success",
        "raw_norm_growth_is_reasoning_progress",
        "conditional_adapter_gain_is_workspace_success",
        "v13_success_requires_positive_semantic_result",
    ):
        exact(gates, key, False, "claim_gates")
    exact(gates, "numerical_thresholds", None, "claim_gates")
    exact(
        gates,
        "threshold_freeze_rule",
        "USE_SEPARATE_CALIBRATION_THEN_FREEZE_BEFORE_COMPARING_CANDIDATES_OR_OPENING_TEST",
        "claim_gates",
    )
    members(contract, "unresolved_execution_fields", UNRESOLVED_FIELDS, "contract")

    v14 = mapping(contract.get("v14_handoff"), "v14_handoff")
    exact(v14, "status", "HYPOTHESIS_ONLY", "v14_handoff")
    exact(v14, "correlation_or_probe_decodability_is_bridge_proof", False, "v14_handoff")
    text_field(v14, "question", "v14_handoff")
    members(
        v14,
        "required_exports",
        {
            "paired_world_and_query_ids",
            "checkpoint_and_runtime_bindings",
            "raw_and_normalized_state_at_each_observed_step",
            "shape_radius_mean_and_degeneracy_masks",
            "read_now_transition_and_carry_only_outcomes",
            "per_case_predictions_logits_and_directional_metrics",
            "null_effect_distributions_and_unknown_coverage",
        },
        "v14_handoff",
    )
    members(
        v14,
        "future_bridge_proof_requires",
        {
            "current_reader_and_next_transition_inputs_can_be_patched_independently",
            "crossed_reader_only_and_transition_only_interventions_executed",
            "transition_effect_persists_with_direct_current_reader_input_held_original",
            "transition_patch_changes_later_readable_state",
            "later_readable_state_changes_answers_in_donor_direction",
            "matched_carry_only_and_gain_controls_do_not_explain_effect",
            "restoring_later_readable_state_removes_effect",
            "transplanting_later_readable_state_reproduces_effect",
            "heldout_replication_with_intact_sufficiency_and_unaffected_retention",
        },
        "v14_handoff",
    )
    return errors


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"nonfinite JSON constant: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--contract",
        default="configs/v13/DESIGN_CONTRACT.json",
        help="Repository-relative design JSON path; no symlinks or traversal.",
    )
    args = parser.parse_args(argv)
    try:
        root = args.repo_root.expanduser().resolve(strict=True)
        path = _safe_file(root, args.contract)
        contract = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        errors = validate_contract(contract, root)
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as exc:
        errors = [f"contract input: {type(exc).__name__}: {exc}"]
    print(
        json.dumps(
            {
                "format": "latent-workspace-ft-v13-design-validation-v1",
                "design_status": "DESIGN_VALID" if not errors else "DESIGN_INVALID",
                "execution_ready": False,
                "execution_status": "BLOCKED_DESIGN_ONLY",
                "execution_blockers": [
                    "No execution freeze or training/remote/base-release authority.",
                    "Scientific stages are not implemented or run.",
                    "Execution fields remain unresolved and numerical thresholds remain null.",
                    "Separate implementation qualification and execution approval are required.",
                ],
                "claim_boundary": (
                    "Success checks only design-document consistency "
                    "and four historical file hashes. "
                    "It is not scientific evidence, runtime qualification, production fail-closed "
                    "validation, or permission to execute."
                ),
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
