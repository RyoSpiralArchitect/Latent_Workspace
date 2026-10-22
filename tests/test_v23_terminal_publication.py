"""Offline analysis checks; no model or network and no edits to sealed evidence."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "provenance/engineering/v23_preservation_ft01_20261022"
sys.path.insert(0, str(BUNDLE))
spec = importlib.util.spec_from_file_location(
    "v23_terminal_publication", BUNDLE / "verify_terminal.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_real_public_raw_manifests_and_replay():
    raw = BUNDLE / "furnace/raw"
    end = audit.replay_manifest(raw, (audit.PRIVATE,))
    assert end["native_weight_updates"] == 67
    assert audit.read(raw / "canary/step2.json") == audit.read(raw / "replay/step2.json")


def test_dev_is_target_weighted_not_mean_of_bucket_means():
    value = audit.read(BUNDLE / "furnace/raw/off/DEV_BASE.json")
    result = audit.dev_summary(value)
    assert result["targets"] == 4694 and result["rows"] == 40
    assert result["mean_nll"] != sum(value["mean_nll_by_bucket"].values()) / 7


@pytest.mark.parametrize("damage", ["denominator", "order", "missing", "nan"])
def test_bad_dev_or_pairing_is_rejected(damage):
    left = audit.read(BUNDLE / "furnace/raw/off/DEV_BASE.json")
    right = copy.deepcopy(left)
    if damage == "denominator":
        right["tokens_by_bucket"]["code"] += 1
    elif damage == "order":
        right["rows"].reverse()
    elif damage == "missing":
        right["rows"].pop()
    else:
        right["rows"][0]["loss_sum"] = float("nan")
    with pytest.raises(ValueError):
        audit.dev_summary(right)
        audit.paired_dev(left, right)


def test_remote_body_receipt_matches_immutable_saved_receipts():
    body = audit.read(BUNDLE / "BODY_VERIFICATION.json")
    for arm, name in (
        ("canary", "canary_step1.pt"),
        ("off", "off_step32.pt"),
        ("on", "on_step32.pt"),
    ):
        receipt = audit.read(BUNDLE / f"furnace/raw/{arm}/CHECKPOINT_{name}.json")
        assert body["files"][f"checkpoints/{name}"] == {k: receipt[k] for k in ("bytes", "sha256")}
    teacher = audit.read(BUNDLE / "furnace/raw/teacher/TEACHER_TARGETS.json")
    assert body["files"][f"raw/{audit.PRIVATE}"] == {k: teacher[k] for k in ("bytes", "sha256")}
