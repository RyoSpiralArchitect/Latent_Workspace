import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_v24_recruitment_ft03 as verify  # noqa: E402

BUNDLE = ROOT / "provenance/engineering/v24_recruitment_ft03_20261023/furnace"


def fixture(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    shutil.copy2(BUNDLE / "SOURCE_SEAL.json", folder)
    shutil.copytree(BUNDLE / "qualification", folder / "qualification")
    return folder


def test_exact_new_source_and_complete_external_observer_only_qualify(tmp_path):
    result = verify.verify(fixture(tmp_path), "qualification")
    assert result["tests_per_device"] == 608
    assert result["source_commit"] == "09addc856ba6f10da31054f1674c7547b1ab91ad"
    assert result["status"] == "QUALIFICATION_ONLY_NO_7B_RESULT"
    assert result["winner"] == "none" and result["old_expression_gate"] == "FAIL"


@pytest.mark.parametrize("damage", ["xml", "source", "isolation", "extra", "observer", "missing"])
def test_qualification_requires_all_frozen_bytes(tmp_path, damage):
    folder = fixture(tmp_path)
    if damage == "xml":
        (folder / "qualification/cuda/TESTS.xml").write_text("<testsuite tests='608'/>")
    elif damage == "source":
        value = verify.ex.read(folder / "SOURCE_SEAL.json")
        value["source_commit"] = "d43382833f6dc85787720bda80aec511c66f58be"
        (folder / "SOURCE_SEAL.json").write_text(verify.ex.canonical(value))
    elif damage == "isolation":
        path = folder / "qualification/CPU_ISOLATION.json"
        value = verify.ex.read(path)
        value["monitor_errors"] = ["ValueError"]
        path.write_text(verify.ex.canonical(value))
    elif damage == "extra":
        (folder / "qualification/cpu/extra.json").write_text("{}")
    elif damage == "observer":
        (folder / "qualification/CPU_OBSERVER.jsonl").write_text("{}\n")
    else:
        (folder / "qualification/CPU_OBSERVER.jsonl").unlink()
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        verify.verify(folder, "qualification")


def test_tiny_pass_does_not_promote_missing_7b_checks(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify.verify(fixture(tmp_path), "checks")


def stopped_fixture(tmp_path):
    folder = fixture(tmp_path)
    for name in ("raw", "checks"):
        shutil.copytree(BUNDLE / name, folder / name)
    return folder


def test_storage_stop_preserves_two_updates_and_missing_replay(tmp_path):
    folder = stopped_fixture(tmp_path)
    result = verify.verify(folder, "storage-stopped")
    assert result["terminal_native_weight_updates"] is None
    assert result["observed_completed_canary_updates"] == 2
    assert result["observed_training_tokens"] == 2220
    assert result["exact_next_update_replay"] == "NOT_RUN"
    assert result["scientific_updates"] == 0 and result["first_update_exactly_matches_ft01"]
    assert result["disk_forecast_bytes_at_failure"] == 32 * 2**30
    for phase in ("checks", "training"):
        with pytest.raises(ValueError):
            verify.verify(folder, phase)


@pytest.mark.parametrize("damage", ["step2", "terminal", "host", "payload", "replay", "retirement"])
def test_changed_storage_failure_rejected(tmp_path, damage):
    folder = stopped_fixture(tmp_path)
    if damage == "step2":
        (folder / "raw/canary/step2.json").write_text("{}")
    elif damage == "terminal":
        path = folder / "raw/FINISHED.json"
        value = verify.ex.read(path)
        value["native_weight_updates"] = 2
        path.write_text(verify.ex.canonical(value))
    elif damage == "host":
        (folder / "raw/canary/HOST_RESOURCES.jsonl").write_text("{}\n")
    elif damage == "payload":
        (folder / "raw/canary/STEP2_PAYLOAD.json").write_text("{}")
    elif damage == "replay":
        (folder / "raw/replay").mkdir()
    else:
        (folder / "CANARY_RETIREMENT.json").write_text("{}")
    with pytest.raises(ValueError):
        verify.verify(folder, "storage-stopped")
