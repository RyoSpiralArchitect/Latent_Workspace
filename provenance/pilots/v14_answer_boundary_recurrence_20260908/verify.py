#!/usr/bin/env python3
"""Verify the V14 answer-boundary recurrence evidence bundle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def mean(values: list[float]) -> float:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Cannot summarize empty or nonfinite values")
    return sum(values) / len(values)


def close(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-15)


def learned_rows(
    rows: list[dict[str, Any]],
    model: str,
    *,
    horizon: int | None = None,
    affected: bool | None = None,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["model"] == model
        and row["control"] == "learned_pair"
        and (horizon is None or row["horizon"] == horizon)
        and (affected is None or row["affected"] is affected)
    ]


def path_values(values: list[dict[str, Any]], path: tuple[str, ...]) -> list[float]:
    output: list[float] = []
    for value in values:
        selected: Any = value
        for key in path:
            selected = selected[key]
        output.append(float(selected))
    return output


def verify_summary(report: dict[str, Any], summary: dict[str, Any]) -> dict[str, bool]:
    rows = report["rows"]
    checks: dict[str, bool] = {}
    for model in ("task", "semantic"):
        h0 = learned_rows(rows, model, horizon=0, affected=True)
        full_effect = [
            row["no_cache"]["repeated_full_route_reference"]["signed_pair_effect"]
            for row in h0
        ]
        last_effect = [
            row["no_cache"]["repeated_last_token"]["signed_pair_effect"] for row in h0
        ]
        cache_effect = [row["cache"]["repeated_carry"]["signed_pair_effect"] for row in h0]
        target = summary["measurement_1_signed_answer_boundary"][
            "affected_horizon_zero"
        ][model]
        checks[f"{model}_h0_signed_effects"] = (
            len(h0) == 4
            and close(mean(full_effect), target["full_reader_route_mean_pair_effect"])
            and close(mean(last_effect), target["last_token_only_mean_pair_effect"])
            and close(mean(cache_effect), target["native_cache_mean_pair_effect"])
        )
        changes = sum(
            row["no_cache"]["repeated_full_route_reference"]["intact"]["prediction"]
            != row["no_cache"]["repeated_full_route_reference"]["twin"]["prediction"]
            for row in h0
        )
        checks[f"{model}_h0_prediction_changes"] = changes == target[
            "intact_twin_prediction_changes"
        ]

        projection = [
            row["no_cache"]["answer_projection_at_horizon_zero"] for row in h0
        ]
        projection_target = summary["measurement_2_answer_projection_at_horizon_zero"][
            "affected_learned_pair"
        ][model]
        local = [float(value["local_linear_pair_prediction"]) for value in projection]
        observed = [float(value["observed_pair_effect"]) for value in projection]
        raw = [float(value["raw_unembedding_pair_projection"]) for value in projection]
        checks[f"{model}_h0_projection"] = (
            close(mean(local), projection_target["local_gradient_pair_projection_mean"])
            and close(mean(observed), projection_target["observed_mean_margin_shift"])
            and close(mean(raw), projection_target["raw_unembedding_pair_projection_mean"])
            and sum(value > 0.0 for value in local)
            == projection_target["local_gradient_positive_cases"]
        )

        all_learned = learned_rows(rows, model)
        visibility = [
            row["no_cache"]["repeated_last_token"][member]["visibility"]
            for row in all_learned
            for member in ("intact", "twin")
        ]
        visibility_target = summary["measurement_3_bf16_and_rmsnorm_visibility"][model]
        measurements: dict[str, tuple[str, ...]] = {
            "requested_update_rms_mean": ("requested", "rms"),
            "actual_native_update_rms_mean": ("actual_native_delta", "rms"),
            "lost_requested_component_fraction_mean": ("lost_requested_fraction",),
            "directional_ulp_ratio_q50_mean": ("ulp_ratio", "q50"),
            "requested_components_at_least_half_ulp_fraction_mean": (
                "ulp_ratio_at_least_half_fraction",
            ),
            "requested_components_at_least_one_ulp_fraction_mean": (
                "ulp_ratio_at_least_one_fraction",
            ),
            "post_rmsnorm_delta_rms_mean": ("rmsnorm", "native_delta", "rms"),
        }
        checks[f"{model}_visibility"] = all(
            close(mean(path_values(visibility, path)), visibility_target[name])
            for name, path in measurements.items()
        )

    recurrence = summary["measurement_4_recurrence_factorization"][
        "affected_learned_pair"
    ]
    for model in ("task", "semantic"):
        endpoint = learned_rows(rows, model, horizon=4, affected=True)
        last = [
            float(row["no_cache"]["repeated_last_token"]["signed_pair_effect"])
            for row in endpoint
        ]
        full = [
            float(
                row["no_cache"]["repeated_full_route_reference"][
                    "signed_pair_effect"
                ]
            )
            for row in endpoint
        ]
        history = [float(row["cache"]["repeated_history_effect"]) for row in endpoint]
        target = recurrence[model]
        checks[f"{model}_endpoint_recurrence"] = (
            close(mean(last), target["no_cache_last_token_endpoint_mean"])
            and close(mean(full), target["full_reader_route_endpoint_mean"])
            and close(mean(history), target["cache_repeated_history_endpoint_mean"])
        )
    return checks


def main() -> int:
    index = load(BUNDLE / "ARTIFACT_INDEX.json")
    artifact_checks: dict[str, bool] = {}
    for artifact in index["artifacts"]:
        path = (REPO / artifact["path"]).resolve()
        path.relative_to(REPO)
        artifact_checks[artifact["path"]] = (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == artifact["bytes"]
            and digest(path) == artifact["sha256"]
        )
    report = load(BUNDLE / "raw/report.json")
    recovery = load(BUNDLE / "raw/mechanical_recovery.json")
    summary = load(BUNDLE / "SUMMARY.json")
    rows = report.get("rows", [])
    dimensional_cells = {
        (row["model"], row["case_id"], row["control"], row["horizon"])
        for row in rows
    }
    checks = {
        "all_indexed_artifacts_match": all(artifact_checks.values()),
        "raw_failure_preserved": (
            report.get("status") == "BLOCKED_EXECUTION"
            and report.get("mechanical_execution_qualified") is False
        ),
        "raw_row_closure": len(rows) == 320 and len(dimensional_cells) == 320,
        "raw_integrity_held": all(
            all(identity["integrity"].values())
            for identity in report["model_identities"].values()
        ),
        "recovery_is_mechanical_only": (
            recovery.get("status") == "QUALIFIED_VERIFIER_RECOVERY"
            and recovery.get("recovered_mechanical_execution_qualified") is True
            and recovery.get("target_model_reexecuted") is False
            and recovery.get("scientific_values_recomputed_or_selected") is False
        ),
        "no_winner_preserved": (
            report.get("winner") == "none"
            and recovery.get("winner") == "none"
            and summary.get("winner") == "none"
            and summary.get("semantic_effect_qualified") is False
        ),
        "summary_execution_matches": (
            summary["execution"]["rows"] == 320
            and close(
                summary["execution"]["elapsed_seconds"], report["elapsed_seconds"]
            )
            and summary["execution"]["cuda_peak_allocated_bytes"]
            == report["cuda_peak_allocated_bytes"]
        ),
        **verify_summary(report, summary),
    }
    result = {
        "format": "latent-workspace-v14-answer-boundary-recurrence-bundle-verification-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifact_checks": artifact_checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
