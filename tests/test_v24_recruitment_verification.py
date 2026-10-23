import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_v24_recruitment_ft as verify  # noqa: E402

BUNDLE = ROOT / "provenance/engineering/v24_recruitment_ft01_20261023/furnace"


def fixture(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    shutil.copy2(BUNDLE / "SOURCE_SEAL.json", folder)
    shutil.copytree(BUNDLE / "qualification", folder / "qualification")
    return folder


def test_qualified_device_receipts_are_not_a_7b_or_training_result(tmp_path):
    folder = fixture(tmp_path)
    result = verify.verify(folder, "qualification")
    assert result["tests_per_device"] == 570 and result["source_files"] == 831
    assert result["status"] == "QUALIFICATION_ONLY_NO_7B_RESULT"
    assert result["local_weight_body_rehash"] is False
    assert result["winner"] == "none" and result["old_expression_gate"] == "FAIL"


@pytest.mark.parametrize("damage", ["xml", "source", "isolation", "extra"])
def test_changed_qualification_is_not_accepted(tmp_path, damage):
    folder = fixture(tmp_path)
    if damage == "xml":
        (folder / "qualification/cuda/TESTS.xml").write_text("<testsuite tests='1'/>")
    elif damage == "source":
        path = folder / "SOURCE_SEAL.json"
        value = verify.ex.read(path)
        value["source_commit"] = "0" * 40
        path.write_text(verify.ex.canonical(value))
    elif damage == "isolation":
        path = folder / "qualification/CPU_ISOLATION.json"
        value = verify.ex.read(path)
        value["final_visible_devices"] = 1
        path.write_text(verify.ex.canonical(value))
    else:
        (folder / "qualification/cpu/extra.json").write_text("{}")
    with pytest.raises(ValueError):
        verify.verify(folder, "qualification")


def test_missing_checks_cannot_be_promoted_from_tiny_pass(tmp_path):
    folder = fixture(tmp_path)
    with pytest.raises(FileNotFoundError):
        verify.verify(folder, "checks")


def stopped_fixture(tmp_path):
    folder = fixture(tmp_path)
    for name in ("raw", "checks"):
        shutil.copytree(BUNDLE / name, folder / name)
    return folder


def test_interrupted_check_keeps_null_terminal_and_missing_replay(tmp_path):
    folder = stopped_fixture(tmp_path)
    result = verify.verify(folder, "stopped")
    assert result["status"] == "VERIFIED_INTERRUPTED_CHECKS_NOT_REPLAY_OR_TRAINING"
    assert result["terminal_native_weight_updates"] is None
    assert result["observed_completed_canary_updates"] == 1
    assert result["planned_canary_updates"] == 2
    assert result["observed_training_tokens"] == 1171
    assert result["scientific_updates"] == 0
    assert result["exact_next_update_replay"] == "NOT_RUN"
    assert result["foreign_gpu_clients"][0]["pid"] == 4140617
    with pytest.raises(ValueError):
        verify.verify(folder, "checks")
    with pytest.raises(ValueError):
        verify.verify(folder, "training")


@pytest.mark.parametrize("damage", ["step", "terminal", "gpu", "successor", "retirement"])
def test_stopped_verification_rejects_changed_evidence(tmp_path, damage):
    folder = stopped_fixture(tmp_path)
    if damage == "step":
        (folder / "raw/canary/step1.json").write_text("{}")
    elif damage == "terminal":
        path = folder / "raw/FINISHED.json"
        value = verify.ex.read(path)
        value["native_weight_updates"] = 1
        path.write_text(verify.ex.canonical(value))
    elif damage == "gpu":
        (folder / "raw/canary/RESOURCES.jsonl").write_text("{}\n")
    elif damage == "successor":
        (folder / "raw/replay").mkdir()
    else:
        (folder / "CANARY_RETIREMENT.json").write_text("{}")
    with pytest.raises(ValueError):
        verify.verify(folder, "stopped")
