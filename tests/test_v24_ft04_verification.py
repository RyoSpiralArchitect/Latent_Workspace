"""Offline new-source and operation-specific receipt verification."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_v24_recruitment_ft04 as verify  # noqa: E402

BUNDLE = ROOT / "provenance/engineering/v24_recruitment_ft04_20261023/furnace"


def qualification_fixture(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    shutil.copy2(BUNDLE / "SOURCE_SEAL.json", folder)
    shutil.copytree(BUNDLE / "qualification", folder / "qualification")
    return folder


def test_closed_qualifications_and_bound_external_observer(tmp_path):
    result = verify.verify(qualification_fixture(tmp_path), "qualification")
    assert result["tests_per_device"] == 643 and result["source_files"] == 856
    assert result["status"] == "QUALIFICATION_ONLY_NO_7B_RESULT"
    assert result["old_expression_gate"] == "FAIL"


@pytest.mark.parametrize("fault", ["xml", "source", "isolation", "observer", "missing", "extra"])
def test_qualification_evidence_is_closed_and_source_bound(tmp_path, fault):
    folder = qualification_fixture(tmp_path)
    if fault == "xml":
        (folder / "qualification/cuda/TESTS.xml").write_text("<testsuite tests='643'/>")
    elif fault == "source":
        value = verify.ex.read(folder / "SOURCE_SEAL.json")
        value["source_commit"] = "09addc856ba6f10da31054f1674c7547b1ab91ad"
        (folder / "SOURCE_SEAL.json").write_text(verify.ex.canonical(value))
    elif fault == "isolation":
        (folder / "qualification/CPU_ISOLATION.json").write_text("{}")
    elif fault == "observer":
        (folder / "qualification/CPU_OBSERVER.jsonl").write_text("{}\n")
    elif fault == "missing":
        (folder / "qualification/CPU_OBSERVER.jsonl").unlink()
    else:
        (folder / "qualification/cpu/extra.json").write_text("{}")
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        verify.verify(folder, "qualification")


def test_tiny_qualification_does_not_promote_unfinished_7b(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify.verify(qualification_fixture(tmp_path), "checks")


def journal(role):
    forecast = {"canary": 32, "replay": 0, "inline": 60, "workspace": 32}[role]
    ops = {
        "canary": [("checkpoint_write", 32), ("payload_hash", 0)],
        "replay": [("checkpoint_read", 0), ("payload_hash", 0)],
        "inline": [("checkpoint_write", 32)],
        "workspace": [("checkpoint_write", 32)],
    }[role]
    return [
        dict(
            phase="admission",
            forecast_bytes=forecast * verify.ex.GIB,
            available_bytes=120 * verify.ex.GIB,
            disk_free_bytes=150 * verify.ex.GIB,
        ),
        *(
            dict(
                phase=f"before_snapshot:{op}",
                forecast_bytes=n * verify.ex.GIB,
                available_bytes=60 * verify.ex.GIB,
                disk_free_bytes=90 * verify.ex.GIB,
            )
            for op, n in ops
        ),
    ]


def check(tmp_path, role, rows):
    (tmp_path / "HOST_RESOURCES.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return verify.verify_accounting(tmp_path, role, dict(checkpoint_max_bytes=28 * verify.ex.GIB))


@pytest.mark.parametrize("role", ["canary", "replay", "inline", "workspace"])
def test_all_role_resource_receipts(role, tmp_path):
    actual = check(tmp_path, role, journal(role))
    assert actual["min_disk_free_bytes"] == 90 * verify.ex.GIB


@pytest.mark.parametrize(
    "fault",
    [
        "read_forecast",
        "write_forecast",
        "disk_floor",
        "host_floor",
        "old_phase",
        "missing",
        "admission",
        "snapshot_host",
    ],
)
def test_relaxation_or_missing_operation_rejected(fault, tmp_path):
    role = "canary" if fault == "write_forecast" else "replay"
    rows = journal(role)
    if fault == "read_forecast":
        rows[1]["forecast_bytes"] = 32 * verify.ex.GIB
    elif fault == "write_forecast":
        rows[1]["forecast_bytes"] = 0
    elif fault == "disk_floor":
        rows[1]["disk_free_bytes"] = 50 * verify.ex.GIB - 1
    elif fault == "host_floor":
        rows[0]["available_bytes"] = 100 * verify.ex.GIB - 1
    elif fault == "old_phase":
        rows.append(dict(rows[-1], phase="before_checkpoint"))
    elif fault == "missing":
        rows.pop()
    elif fault == "admission":
        rows[0]["forecast_bytes"] = 1
    else:
        rows[1]["available_bytes"] = 56 * verify.ex.GIB - 1
    with pytest.raises(ValueError):
        check(tmp_path, role, rows)


def test_historical_ft03_cannot_be_relabelled_ft04():
    with pytest.raises(ValueError, match="Exact execution source"):
        verify.verify(ROOT / "provenance/engineering/v24_recruitment_ft03_20261023/furnace")
