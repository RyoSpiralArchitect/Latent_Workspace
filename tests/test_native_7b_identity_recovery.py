"""Hash-scheme repair: tiny tensors and offline receipts, never pretrained weights."""

import ast
import copy
import hashlib
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_7b_canary as canary  # noqa: E402
import verify_native_7b_canary as verifier  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace.optimizer_state import tree_hash  # noqa: E402


def legacy_hash():
    # Execute only the historical function definition, not the experiment module.
    source = ast.parse((canary.ROOT / "scripts/run_v14_precision_bridge.py").read_text())
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "state_hash")
    namespace = dict(hashlib=hashlib, torch=torch)
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "<historical state_hash>", "exec"),
        namespace,
    )
    return namespace["state_hash"]


def fixture():
    model = torch.nn.Linear(3, 2, bias=False).to(dtype=torch.bfloat16)
    with torch.no_grad():
        model.weight.copy_(torch.arange(6).reshape(2, 3))
    legacy = legacy_hash()
    expected = {
        "legacy_state_v1_sha256": legacy(model),
        "state_tree_v1_sha256": tree_hash(model.state_dict()),
    }
    return model, legacy, expected


def test_named_identity_matches_two_different_algorithms_and_records_both(tmp_path):
    model, legacy, expected = fixture()
    assert expected["legacy_state_v1_sha256"] != expected["state_tree_v1_sha256"]
    assert canary.original_identity(model, expected, tmp_path, legacy_hash=legacy) == expected
    ex.write_new(
        tmp_path / "CONTEXT.json",
        {"contract": {"original_base_sha256": expected["state_tree_v1_sha256"]}},
    )
    verifier.verify_identity(tmp_path, {"backbone": {"identity": expected}}, complete=True)


@pytest.mark.parametrize("fault", ["swapped", "legacy", "tree", "model"])
def test_wrong_scheme_or_changed_weights_fail_with_observations_preserved(tmp_path, fault):
    model, legacy, expected = fixture()
    if fault == "swapped":
        expected = dict(zip(expected, reversed(list(expected.values())), strict=True))
    elif fault == "legacy":
        expected["legacy_state_v1_sha256"] = "0" * 64
    elif fault == "tree":
        expected["state_tree_v1_sha256"] = "0" * 64
    else:
        with torch.no_grad():
            model.weight.add_(1)
    with pytest.raises(ValueError, match="Pinned original"):
        canary.original_identity(model, expected, tmp_path, legacy_hash=legacy)
    record = ex.read(tmp_path / "ORIGINAL_IDENTITY.json")
    assert record["observed"]["legacy_state_v1_sha256"] == legacy(model)
    assert record["observed"]["state_tree_v1_sha256"] == tree_hash(model.state_dict())
    assert not all(record["matches"].values())
    plan = {"backbone": {"identity": expected}}
    verifier.verify_identity(tmp_path, plan, complete=False)
    with pytest.raises(ValueError, match="Original model identity"):
        verifier.verify_identity(tmp_path, plan, complete=True)


@pytest.mark.parametrize("fault", ["missing", "extra"])
def test_unnamed_or_incomplete_scheme_set_is_rejected(tmp_path, fault):
    model, legacy, expected = fixture()
    if fault == "missing":
        expected.pop("state_tree_v1_sha256")
    else:
        expected["legacy_state_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="scheme keys"):
        canary.original_identity(model, expected, tmp_path, legacy_hash=legacy)
    assert not (tmp_path / "ORIGINAL_IDENTITY.json").exists()


def test_identity_receipt_is_exclusive_not_overwritten(tmp_path):
    model, legacy, expected = fixture()
    canary.original_identity(model, expected, tmp_path, legacy_hash=legacy)
    saved = (tmp_path / "ORIGINAL_IDENTITY.json").read_bytes()
    with pytest.raises(FileExistsError):
        canary.original_identity(model, expected, tmp_path, legacy_hash=legacy)
    assert (tmp_path / "ORIGINAL_IDENTITY.json").read_bytes() == saved


@pytest.mark.parametrize("fault", ["observed", "matches", "expected", "contract", "schema"])
def test_resealed_bad_identity_evidence_does_not_become_success(tmp_path, fault):
    model, legacy, expected = fixture()
    canary.original_identity(model, expected, tmp_path, legacy_hash=legacy)
    record = ex.read(tmp_path / "ORIGINAL_IDENTITY.json")
    context = {"contract": {"original_base_sha256": expected["state_tree_v1_sha256"]}}
    if fault in ("observed", "expected"):
        record[fault]["legacy_state_v1_sha256"] = "0" * 64
    elif fault == "matches":
        record["matches"]["legacy_state_v1_sha256"] = False
    elif fault == "schema":
        record["schema"] = "unknown"
    else:
        context["contract"]["original_base_sha256"] = "0" * 64
    (tmp_path / "ORIGINAL_IDENTITY.json").write_text(ex.canonical(record))
    ex.write_new(tmp_path / "CONTEXT.json", context)
    with pytest.raises(ValueError):
        verifier.verify_identity(tmp_path, {"backbone": {"identity": expected}}, complete=True)


def test_recovery_changes_only_identity_qualification_and_provenance():
    old = ex.read(canary.ROOT / "configs/v1_0/NATIVE_7B_CANARY.json")
    new = ex.read(canary.ROOT / canary.PLAN)
    canary.validate(new)
    same = copy.deepcopy(new)
    for key in ("identity_reference", "recovery_of"):
        same.pop(key)
    same["schema"] = old["schema"]
    same["backbone"].pop("identity")
    same["backbone"]["legacy_state_sha256"] = old["backbone"]["legacy_state_sha256"]
    assert same["qualification_test_files"][:-1] == old["qualification_test_files"]
    same["qualification_test_files"] = old["qualification_test_files"]
    same["qualification_cases"] = old["qualification_cases"]
    assert same == old


def test_expected_named_hashes_are_the_historical_pair_not_a_posthoc_measurement():
    plan = ex.read(canary.ROOT / canary.PLAN)
    historical = ex.read(canary.ROOT / plan["identity_reference"]["path"])["contract"]
    expected = plan["backbone"]["identity"]
    assert expected == dict(
        legacy_state_v1_sha256=historical["original_legacy_identity_sha256"],
        state_tree_v1_sha256=historical["original_base_sha256"],
    )
    assert (
        ex.digest(canary.ROOT / plan["identity_reference"]["path"])
        == (plan["identity_reference"]["sha256"])
    )
    assert Path(canary.ROOT / plan["recovery_of"]["terminal"]).is_file()
