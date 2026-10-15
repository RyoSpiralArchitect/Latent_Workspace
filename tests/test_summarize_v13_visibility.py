from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
summary = importlib.import_module("summarize_v13_visibility")


def _receipt() -> dict:
    rows = []
    for mode in summary.REQUIRED_MODES:
        for side in (0, 1):
            rows.append(
                {
                    "sample_index": 0,
                    "family_id": "world-family",
                    "pair_id": "pair",
                    "side": side,
                    "query_index": 0,
                    "case_id": f"pair:side{side}:query0",
                    "mode": mode,
                    "input_sha256": hashlib.sha256(f"input-side{side}".encode()).hexdigest(),
                    "original_label": 0,
                    "donor_label": 1 if side == 0 else 0,
                    "affected": side == 0,
                    "heldout": False,
                    "hop_distance": 1,
                    "candidate_ids": [10, 11],
                    "answer_source_position": 4,
                    "logits": [4.0, 0.0],
                    "bf16": [5.0, 0.0],
                    "fp32": [6.0, 0.0],
                    "direct_base_logits": [4.0, 0.0],
                    "true_bypass_logits": [4.0, 0.0],
                    "residual_precast": [0.01, -0.01],
                    "residual_postcast": [0.01, -0.01],
                    "bf16_ulp_up": [0.03125, 0.03125],
                    "bf16_ulp_down": [0.03125, 0.03125],
                    "residual_to_directional_bf16_ulp": [0.32, 0.32],
                    "diagnostic_fp32_gain_logits": {"1": [6.0, 0.0], "4": [8.0, 0.0]},
                }
            )
    return {
        "format": summary.FORMAT,
        "status": "COMPLETE",
        "lane": "retained_inline_diagnostic",
        "checkpoint_bytes_unchanged": True,
        "parameters_unmodified": True,
        "training_performed": False,
        "gain_selection_performed": False,
        "modes": list(summary.REQUIRED_MODES),
        "gains": [1.0, 4.0],
        "rows": rows,
    }


def _mode_row(receipt: dict, mode: str, side: int = 0) -> dict:
    return next(row for row in receipt["rows"] if row["mode"] == mode and row["side"] == side)


def _add_hashes(receipt: dict) -> None:
    receipt["checkpoint_inventory"] = [
        {"path": "workspace_state.pt", "sha256": "a" * 64, "bytes": 42}
    ]
    receipt["checkpoint_inventory_sha256"] = summary._hash(receipt["checkpoint_inventory"])
    receipt["receipt_sha256"] = summary._hash(receipt)


def test_variant_matched_intact_baseline_and_side_aware_identity() -> None:
    receipt = _receipt()
    target = _mode_row(receipt, "counterfactual_twin")
    for field in ("logits", "bf16", "fp32"):
        target[field] = [0.0, 1.0]
    target["diagnostic_fp32_gain_logits"] = {"1": [0.0, 1.0], "4": [0.0, 1.0]}
    before = copy.deepcopy(receipt)
    pairs = summary.build_pair_rows(receipt)
    assert len(pairs) == 6 * 2 * 5
    assert {row["query_id"] for row in pairs} == {"side0:query0", "side1:query0"}
    selected = {
        row["variant_id"]: row
        for row in pairs
        if row["control_id"] == "counterfactual_twin" and row["query_id"] == "side0:query0"
    }
    assert selected["native"]["intact_logits"] == [4.0, 0.0]
    assert selected["explicit_bf16"]["intact_logits"] == [5.0, 0.0]
    assert selected["fp32"]["intact_logits"] == [6.0, 0.0]
    assert selected["diagnostic_fp32_gain:4"]["intact_logits"] == [8.0, 0.0]
    result = summary.summarize_receipt(receipt)
    groups = {
        row["variant_id"]: row
        for row in result["paired_metrics"]["groups"]
        if row["control_id"] == "counterfactual_twin"
    }
    assert groups["native"]["affected"]["donor_gain"]["values"] == [5.0]
    assert groups["fp32"]["affected"]["donor_gain"]["values"] == [7.0]
    assert groups["diagnostic_fp32_gain:4"]["affected"]["donor_gain"]["values"] == [9.0]
    assert result["paired_metrics"]["family_count"] == 1
    assert receipt == before


def test_visibility_counts_and_bypass_meanings_remain_separate() -> None:
    result = summary.summarize_receipt(_receipt())
    intact = result["mode_summaries"][0]
    assert intact["native_vs_direct_base"]["changed_row_count"] == 0
    assert intact["fp32_vs_direct_base"]["changed_row_count"] == 2
    assert intact["precast_residual_nonzero_but_native_equals_base_rows"] == 2
    assert intact["postcast_residual_nonzero_but_native_equals_base_rows"] == 2
    assert intact["max_residual_to_directional_bf16_ulp"] == 0.32
    assert intact["max_abs_residual_precast"] == 0.01
    assert intact["versus_matched_intact"]["fp32"]["changed_row_count"] == 0
    assert result["true_bypass_vs_direct_base"]["changed_row_count"] == 0
    assert set(result["control_meanings"]) == {"zero", "hard_bypass", "true_bypass"}
    assert result["scientific_success"] is False
    assert result["execution_ready"] is False
    assert result["status"] == "DESCRIPTIVE_ONLY"
    assert result["external_payloads_rehashed"] is False
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("status", "RUNNING"),
        ("checkpoint_bytes_unchanged", False),
        ("checkpoint_bytes_unchanged", "true"),
        ("parameters_unmodified", 1),
        ("training_performed", True),
        ("gain_selection_performed", "false"),
    ],
)
def test_unfinished_or_untrusted_flags_rejected(flag: str, value: object) -> None:
    receipt = _receipt()
    receipt[flag] = value
    with pytest.raises(ValueError):
        summary.build_pair_rows(receipt)


def test_missing_mode_and_partial_mode_case_coverage_rejected() -> None:
    receipt = _receipt()
    receipt["modes"].remove("zero")
    with pytest.raises(ValueError, match="required memory modes"):
        summary.build_pair_rows(receipt)
    receipt = _receipt()
    receipt["rows"].remove(_mode_row(receipt, "zero"))
    with pytest.raises(ValueError, match="Case coverage mismatch"):
        summary.build_pair_rows(receipt)


def test_duplicate_mode_case_rejected_even_with_changed_input() -> None:
    receipt = _receipt()
    duplicate = copy.deepcopy(receipt["rows"][0])
    duplicate["input_sha256"] = "b" * 64
    receipt["rows"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate mode/case"):
        summary.build_pair_rows(receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_sha256", "a" * 64),
        ("heldout", True),
        ("candidate_ids", [10, 12]),
        ("answer_source_position", 5),
        ("family_id", "different-family"),
    ],
)
def test_mismatched_input_metadata_rejected(field: str, value: object) -> None:
    receipt = _receipt()
    _mode_row(receipt, "zero")[field] = value
    with pytest.raises(ValueError, match="Matched input/label identity differs"):
        summary.build_pair_rows(receipt)


def test_mismatched_labels_rejected() -> None:
    receipt = _receipt()
    row = _mode_row(receipt, "zero")
    row.update(original_label=1, donor_label=0)
    with pytest.raises(ValueError, match="Matched input/label identity differs"):
        summary.build_pair_rows(receipt)


def test_missing_gain_and_wrong_vector_shape_rejected() -> None:
    receipt = _receipt()
    _mode_row(receipt, "zero")["diagnostic_fp32_gain_logits"].pop("4")
    with pytest.raises(ValueError, match="gain coverage"):
        summary.build_pair_rows(receipt)
    receipt = _receipt()
    _mode_row(receipt, "zero")["fp32"] = [1.0]
    with pytest.raises(ValueError, match="two finite"):
        summary.build_pair_rows(receipt)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_all_nonfinite_scalars_rejected(value: float) -> None:
    receipt = _receipt()
    _mode_row(receipt, "zero")["residual_to_directional_bf16_ulp"][0] = value
    with pytest.raises(ValueError, match="Nonfinite"):
        summary.summarize_receipt(receipt)


def test_empty_rows_rejected() -> None:
    receipt = _receipt()
    receipt["rows"] = []
    with pytest.raises(ValueError, match="Nonempty"):
        summary.build_pair_rows(receipt)


def test_hashes_checked_if_present_without_faking_model_config() -> None:
    receipt = _receipt()
    _add_hashes(receipt)
    result = summary.summarize_receipt(receipt)
    assert result["source_hash_checks"] == {
        "receipt": "VERIFIED_CONTENT_HASH",
        "checkpoint_inventory": "VERIFIED_CONTENT_HASH",
    }
    assert "loaded_checkpoint_config" not in receipt
    receipt["rows"][0]["logits"][0] += 1
    with pytest.raises(ValueError, match="self-hash mismatch"):
        summary.summarize_receipt(receipt)
    receipt = _receipt()
    _add_hashes(receipt)
    receipt.pop("receipt_sha256")
    receipt["checkpoint_inventory"][0]["bytes"] += 1
    with pytest.raises(ValueError, match="inventory hash mismatch"):
        summary.summarize_receipt(receipt)


def test_cli_binds_source_and_refuses_overwrite(tmp_path: Path) -> None:
    source, output = tmp_path / "trace.json", tmp_path / "summary.json"
    source.write_text(json.dumps(_receipt()))
    command = [
        sys.executable,
        "-S",
        str(SCRIPTS / "summarize_v13_visibility.py"),
        str(source),
        "--output",
        str(output),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    result = json.loads(output.read_text())
    assert result["source_file"] == {
        "path": str(source.resolve()),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    prior = output.read_bytes()
    again = subprocess.run(command, capture_output=True, text=True, check=False)
    assert again.returncode == 1
    assert output.read_bytes() == prior


def test_cli_rejects_bad_json_without_output(tmp_path: Path) -> None:
    source, output = tmp_path / "trace.json", tmp_path / "summary.json"
    source.write_text('{"status":"COMPLETE","status":"RUNNING"}')
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(SCRIPTS / "summarize_v13_visibility.py"),
            str(source),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert not output.exists()
