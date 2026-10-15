#!/usr/bin/env python3
"""Reproduce path-normalized evidence for the two sealed V14 portability canaries.

No model load, network, training or raw-receipt modification. This curator is
post-run reporting code, not part of the preregistered execution implementation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "provenance/raw/v14_portability_20260904"
OUT = REPO / "provenance/pilots/v14_portability_20260904"
PLAN = REPO / "configs/v14/PORTABILITY_RUN_PLAN.json"
PLAN_SHA = "e7f6da28213f5d61a57ec8ff2e8d55cde731dabf0819fffae02e51f150b58ca3"
# Recorded on Furnace, then matched to the transferred local bytes.
RAW_SHA = {
    "LAUNCH.json": "a1bb30e15b2da88bf87247a90ea983682c63d5aa2360c71a24bf94b588899f77",
    "EAGER_LAUNCH.json": "b568178fc3e94c7a9bc18a9e664faae080cefa49b4d437eef2ff2c6b8c603b03",
    "sdpa/PORTABILITY_CANARY.json": (
        "dc8a2e530b76841ad37c2cf3585080f72d4501d21b75b53206b0b7dd00db3d1b"
    ),
    "eager/PORTABILITY_CANARY.json": (
        "e4e4589cc4244628c8f7d3b7753376979d10668231b32b182835b74201604005"
    ),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def emit(name: str, value: dict) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path = OUT / name
    if path.exists():
        require(path.read_bytes() == payload, f"Refusing to overwrite different evidence: {name}")
    else:
        path.write_bytes(payload)


def normalize_paths(value, replacements):
    if isinstance(value, str):
        for original, label in replacements:
            value = value.replace(original, label)
        require("/home/" not in value and "/Users/" not in value, "Private absolute path remains")
        return value
    if isinstance(value, list):
        return [normalize_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            normalize_paths(key, replacements): normalize_paths(item, replacements)
            for key, item in value.items()
        }
    return value


def main() -> None:
    require(sha(PLAN) == PLAN_SHA, "Preregistered plan changed")
    plan = json.loads(PLAN.read_text())
    documents = {}
    for relative, digest in RAW_SHA.items():
        require(sha(RAW / relative) == digest, f"Raw receipt or transfer hash changed: {relative}")
        documents[relative] = json.loads((RAW / relative).read_text())
    launch = documents["LAUNCH.json"]
    anchors = plan["preregistered_source_anchors"]
    require(launch["plan_sha256"] == PLAN_SHA, "Launch plan binding mismatch")
    require(
        launch["git_commit"] == "d7d6f0a50e1888276146aa111ddb5ccd21f1f607",
        "Unexpected execution commit",
    )
    require(
        documents["EAGER_LAUNCH.json"]["previous_receipt_sha256"]
        == RAW_SHA["sdpa/PORTABILITY_CANARY.json"],
        "Sequential launch binding mismatch",
    )
    model_path = Path(launch["model_path"])
    require(model_path.name == plan["model"]["revision"], "Snapshot revision mismatch")
    replacements = sorted(
        [
            (str(model_path), "$MODEL_SNAPSHOT"),
            (str(model_path.parent.parent), "$MODEL_CACHE"),
            (launch["worktree"], "$REPO"),
            ("/home/ryospiralarchitect/.local/lib/python3.14/site-packages", "$PYTHON_SITE"),
            ("/usr/bin/python", "$PYTHON_EXECUTABLE"),
        ],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    cells = []
    previous_inventory = None
    for backend in ("sdpa", "eager"):
        relative = f"{backend}/PORTABILITY_CANARY.json"
        report = documents[relative]
        canary = report["canary"]
        gradients = canary["gradient_check"]
        require(report["status"] == canary["status"] == "COMPLETE", "Cell is not complete")
        require(report["scientific_success"] is False, "Invalid scientific claim")
        require(report["training_performed"] is False, "Training outside canary scope")
        require(report["model_path"] == str(model_path), "Different model path")
        require(report["requested_device"] == "cuda", "Not the declared CUDA cell")
        require(report["requested_dtype"] == canary["precision"] == "bfloat16", "Wrong dtype")
        require(report["actual_attention_implementation"] == backend, "Wrong attention backend")
        require(report["requested_gradient_check"] is True, "Gradient comparison missing")
        require(canary["prompts"] == plan["inputs"]["prompts"], "Prompt drift")
        require(canary["boundary_layers"] == [0, 8, 16], "Boundary drift")
        require(canary["use_cache"] is False and canary["padding_side"] == "right", "Input drift")
        require(
            canary["tolerances"]
            == {
                "logits_atol": 0.015625,
                "logits_rtol": 0.0078125,
                "grad_atol": 1e-5,
                "grad_rtol": 0.02,
            },
            "Tolerance drift",
        )
        require(
            report["runtime"]["torch"] == plan["runtime"]["expected_torch_version"], "Torch drift"
        )
        require(
            report["runtime"]["transformers"] == plan["runtime"]["expected_transformers_version"],
            "Transformers drift",
        )
        require(
            report["implementation_fingerprint"]["sha256"] == anchors["package_fingerprint_sha256"],
            "Package implementation drift",
        )
        require(
            report["source_sha256"][launch["worktree"] + "/" + anchors["canary_file"]]
            == anchors["canary_file_sha256"],
            "Canary script drift",
        )
        inventory = report["model_payload_inventory"]
        if previous_inventory is not None:
            require(inventory == previous_inventory, "Snapshot differs across cells")
        previous_inventory = inventory
        require(report["snapshot_postcheck"]["all_payload_sha256_unchanged"], "Snapshot changed")
        require(
            next(row["sha256"] for row in inventory if row["path"] == "config.json")
            == plan["model"]["config_sha256"],
            "Model config drift",
        )
        require(len(canary["boundaries"]) == 3, "Missing logit comparison")
        require(
            all(row["finite"] and row["within_tolerance"] for row in canary["boundaries"]),
            "Logit failure",
        )
        rows = gradients["parameters"]
        require(
            len(rows) == len({row["parameter"] for row in rows}) == gradients["parameter_count"],
            "Gradient denominator mismatch",
        )
        require(
            sum(row["parameter_elements"] for row in rows) == gradients["parameter_elements"],
            "Element denominator mismatch",
        )
        require(
            all(
                row["native_gradient_present"]
                and row["split_gradient_present"]
                and row["finite"]
                and row["within_tolerance"]
                for row in rows
            ),
            "Incomplete gradient coverage",
        )
        require(gradients["boundary_layer"] == 8, "Gradient boundary drift")
        require(len(canary["generation"]) == 2, "Missing greedy comparison")
        require(
            all(
                row["token_ids_equal"]
                and row["native_token_ids"] == row["split_token_ids"]
                and len(row["native_token_ids"]) == 4
                for row in canary["generation"]
            ),
            "Greedy mismatch",
        )
        require(
            canary["named_norm_observation"]["observation_checks_passed"], "Observation failure"
        )
        require(
            canary["named_norm_observation"]["passthrough_numeric_exact"], "Observer changed logits"
        )
        require(
            canary["parameter_identity_versions_unchanged"] and canary["gradients_cleared"],
            "Model state failure",
        )
        cells.append(
            {
                "id": f"olmo2_base_bf16_{backend}",
                "receipt": f"{backend.upper()}_CANARY.json",
                "raw_receipt_sha256": RAW_SHA[relative],
                "status": report["status"],
                "logit_comparisons": [
                    {k: v for k, v in row.items() if k != "descriptor"}
                    for row in canary["boundaries"]
                ],
                "gradient_parameter_tensors": gradients["parameter_count"],
                "gradient_parameter_elements": gradients["parameter_elements"],
                "gradient_different_elements": sum(row["different_elements"] for row in rows),
                "max_abs_gradient_difference": gradients["max_abs_gradient_difference"],
                "native_fixed_next_token_ce": gradients["native_loss"],
                "split_fixed_next_token_ce": gradients["split_loss"],
                "generation": canary["generation"],
                "named_norm_observation_passed": canary["named_norm_observation"][
                    "observation_checks_passed"
                ],
                "cuda_memory": report["cuda_memory"],
                "elapsed_seconds_bookkeeping_only": report["elapsed_seconds"],
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    for relative, name in [
        ("LAUNCH.json", "LAUNCH_BINDING.json"),
        ("EAGER_LAUNCH.json", "EAGER_LAUNCH_BINDING.json"),
        ("sdpa/PORTABILITY_CANARY.json", "SDPA_CANARY.json"),
        ("eager/PORTABILITY_CANARY.json", "EAGER_CANARY.json"),
    ]:
        emit(
            name,
            {
                "curation": {
                    "raw_sha256": RAW_SHA[relative],
                    "transform": (
                        "Absolute local paths replaced with labelled roots; "
                        "numerical/content fields retained."
                    ),
                    "curator_sha256": sha(Path(__file__)),
                    "not_byte_identical_to_raw_receipt": True,
                },
                "receipt": normalize_paths(documents[relative], replacements),
            },
        )
    emit(
        "RESULTS.json",
        {
            "format": "latent-workspace-v14-portability-results-v1",
            "status": "BOUNDED_PORTABILITY_CANARIES_COMPLETE",
            "plan_sha256": PLAN_SHA,
            "execution_commit": launch["git_commit"],
            "model": plan["model"]["repository_id"],
            "revision": plan["model"]["revision"],
            "cells": cells,
            "numerical_identity_not_general_bitwise_guarantee": True,
            "cross_backend_full_tensor_identity_tested": False,
            "cross_backend_observed_native_ce_eager_minus_sdpa": (
                cells[1]["native_fixed_next_token_ce"] - cells[0]["native_fixed_next_token_ce"]
            ),
            "cross_backend_ce_difference_is_quality_result": False,
            "scientific_success": False,
            "workspace_generation_or_utility_qualified": False,
            "reader_transition_bridge_established": False,
            "training_performed": False,
            "weight_deletion": False,
            "raw_model_snapshot_unchanged_in_both_cells": True,
        },
    )
    print(
        json.dumps({"status": "CURATED", "cells": len(cells), "raw_transfer_hashes_verified": True})
    )


if __name__ == "__main__":
    main()
