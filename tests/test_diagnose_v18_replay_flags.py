"""Small synthetic fixtures only; no historical fit or GPU study is rerun."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import diagnose_v18_replay_flags as diagnostic  # noqa: E402


@pytest.fixture(autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def reader(factor="centered_ordered"):
    bridge = assay.make_reader(9187, factor)
    with torch.no_grad():
        bridge.up.weight.copy_(torch.eye(32))
    return bridge


def test_exact_two_flag_policies_same_storage_and_values():
    bridge = reader()
    fingerprint = assay.state_fingerprint(bridge)
    historical = diagnostic.apply_policy(bridge, diagnostic.POLICIES[0])
    frozen = diagnostic.apply_policy(bridge, diagnostic.POLICIES[1])
    diagnostic.check_metadata(historical, diagnostic.POLICIES[0])
    diagnostic.check_metadata(frozen, diagnostic.POLICIES[1], historical)
    assert sum(item["requires_grad"] for item in historical.values()) == 6
    assert not any(item["requires_grad"] for item in frozen.values())
    assert all(not item["gradient_present"] for item in historical.values())
    assert all(
        historical[name]["storage_pointer"] == frozen[name]["storage_pointer"] for name in frozen
    )
    assert assay.state_fingerprint(bridge) == fingerprint
    assert all(not module.training for module in bridge.modules())


@pytest.mark.parametrize("policy", ["unknown", None, "train_all"])
def test_unknown_policy_rejected(policy):
    with pytest.raises(ValueError, match="Unknown"):
        diagnostic.apply_policy(reader(), policy)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("storage_pointer", 0),
        ("storage_offset", 100),
        ("stride", [100]),
        ("gradient_present", True),
        ("dtype", "torch.bfloat16"),
        ("is_leaf", False),
    ],
)
def test_changed_metadata_rejected(field, replacement):
    metadata = diagnostic.apply_policy(reader(), diagnostic.POLICIES[0])
    changed = copy.deepcopy(metadata)
    changed["up.weight"][field] = replacement
    with pytest.raises(ValueError):
        diagnostic.check_metadata(changed, diagnostic.POLICIES[0], metadata)


@pytest.fixture
def fixture():
    pop = assay.population(seed=9187, frames=1)
    bridge = reader()
    bridge.eval()
    with torch.no_grad():
        native, delta = assay.forward(bridge, pop.inputs, "centered_ordered")
        perm = diagnostic.PLAN["slot_permutation"]
        permuted = assay.Inputs(
            pop.inputs.states, pop.inputs.memory[:, perm], pop.inputs.mask[:, perm]
        )
        perm_native, perm_delta = assay.forward(bridge, permuted, "centered_ordered")
    refs = {
        "historical_logits": native,
        "prior_original_0_logits": native,
        "prior_original_0_delta": delta,
        "prior_permuted_0_logits": perm_native,
        "prior_permuted_0_delta": perm_delta,
    }
    control = assay.controls(bridge, "centered_ordered", pop, "cpu", lambda: None, 1e-6)
    return bridge, pop, refs, control


def test_abba_runtime_flags_and_no_learning(fixture, monkeypatch):
    bridge, pop, refs, control = fixture

    def prohibited(*_args, **_kwargs):
        pytest.fail("No writer, update, optimizer, or backward is permitted")

    monkeypatch.setattr(torch.optim, "AdamW", prohibited)
    monkeypatch.setattr(torch.Tensor, "backward", prohibited)
    monkeypatch.setattr(assay, "update", prohibited)
    monkeypatch.setattr(bridge, "write_memory", prohibited)
    raw, saved = diagnostic.diagnose_fit(
        bridge,
        pop,
        "centered_ordered",
        "cpu",
        lambda: None,
        refs,
        control,
        control,
    )
    assert [visit["policy"] for visit in saved["visits"]] == diagnostic.PLAN["policy_visit_order"]
    assert [visit["repetition"] for visit in saved["visits"]] == [0, 0, 1, 1]
    assert all(not visit["grad_enabled"] and visit["all_eval"] for visit in saved["visits"])
    assert saved["forward_calls"] == 20
    assert saved["training_updates"] == saved["optimizer_instances"] == 0
    assert saved["state_values_unchanged"] and saved["input_tensors_unchanged"]
    replay = diagnostic.verify_fit(raw, saved, refs, "centered_ordered")
    assert replay["outcome"] == "NO_FLAG_EFFECT_IN_THIS_DIAGNOSTIC"


@pytest.fixture
def observed(fixture):
    bridge, pop, refs, control = fixture
    raw, saved = diagnostic.diagnose_fit(
        bridge,
        pop,
        "centered_ordered",
        "cpu",
        lambda: None,
        refs,
        control,
        control,
    )
    return raw, saved, refs


@pytest.mark.parametrize("tamper", ["policy", "visit_order", "storage", "raw", "control", "gate"])
def test_offline_tampering_rejected(observed, tamper):
    raw, saved, refs = copy.deepcopy(observed)
    if tamper == "policy":
        del raw[diagnostic.POLICIES[0]]
    elif tamper == "visit_order":
        saved["visits"][0]["policy"] = diagnostic.POLICIES[1]
    elif tamper == "storage":
        saved["visits"][2]["metadata"]["up.weight"]["storage_pointer"] += 64
    elif tamper == "raw":
        raw[diagnostic.POLICIES[0]]["original_0_logits"][0, 0] += 0.01
    elif tamper == "control":
        saved["policies"][diagnostic.POLICIES[0]]["reobserved_controls"]["max_delta_norm"] = 0.01
    else:
        saved["old_gate"]["status"] = "PASS"
    with pytest.raises(ValueError):
        diagnostic.verify_fit(raw, saved, refs, "centered_ordered")


def test_missing_historical_reproduction_remains_visible(observed):
    raw, saved, refs = copy.deepcopy(observed)
    refs["historical_logits"] = refs["historical_logits"].clone()
    refs["historical_logits"][0, 0] += 0.01
    controls = {
        policy: saved["policies"][policy]["reobserved_controls"] for policy in diagnostic.POLICIES
    }
    first = saved["policies"][diagnostic.POLICIES[0]]
    result = diagnostic.summary(
        raw, controls, refs, first["historical_controls"], first["prior_controls"]
    )
    assert result["outcome"] == "NO_FLAG_EFFECT_IN_THIS_DIAGNOSTIC"
    assert not any(
        row["historical_original_logits"]["exact"] for row in result["policies"].values()
    )
    assert result["promotion"] == "NONE_DIAGNOSTIC_ONLY"
    assert result["old_gate"]["status"] == "FAIL"


def test_nonrepeatability_not_confused_with_policy_effect(observed):
    raw, saved, refs = copy.deepcopy(observed)
    raw[diagnostic.POLICIES[1]]["original_1_delta"][0, 0, 0] += 0.01
    controls = {
        policy: saved["policies"][policy]["reobserved_controls"] for policy in diagnostic.POLICIES
    }
    first = saved["policies"][diagnostic.POLICIES[0]]
    result = diagnostic.summary(
        raw, controls, refs, first["historical_controls"], first["prior_controls"]
    )
    assert result["outcome"] == "UNRESOLVED_REPEATABILITY"


def test_repeatable_policy_bit_difference_detected_independent_of_history(observed):
    raw, saved, refs = copy.deepcopy(observed)
    for repetition in range(2):
        raw[diagnostic.POLICIES[1]][f"original_{repetition}_delta"][0, 0, 0] += 1e-7
    controls = {
        policy: saved["policies"][policy]["reobserved_controls"] for policy in diagnostic.POLICIES
    }
    first = saved["policies"][diagnostic.POLICIES[0]]
    result = diagnostic.summary(
        raw, controls, refs, first["historical_controls"], first["prior_controls"]
    )
    assert result["outcome"] == "POLICY_DEPENDENT_OUTPUT_WITH_REPEATABILITY"
    assert result["cross_policy"]["original_0_logits"]["exact"]
    assert not result["cross_policy"]["original_0_delta"]["exact"]
    assert result["promotion"] == "NONE_DIAGNOSTIC_ONLY"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("elapsed_seconds", 901, TimeoutError),
        ("peak_rss_bytes", 4 * 1024**3 + 1, MemoryError),
        ("peak_cuda_allocated_bytes", 4 * 1024**3 + 1, MemoryError),
    ],
)
def test_bounds_remain_frozen(field, value, error, monkeypatch):
    guard = assay.ResourceGuard(diagnostic.PLAN, "cpu")
    usage = {"elapsed_seconds": 1, "peak_rss_bytes": 100, "peak_cuda_allocated_bytes": 0}
    usage[field] = value
    monkeypatch.setattr(guard, "snapshot", lambda: usage)
    with pytest.raises(error):
        guard()


def test_default_dry_run_no_forward_or_output(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [diagnostic.ENTRY])
    monkeypatch.setattr(diagnostic, "run", lambda *args: pytest.fail("No execution"))
    diagnostic.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "DRY_RUN_NO_FORWARDS"
    assert result["plan"]["policy_cells_per_device"] == 24
    assert result["plan"]["control_atol"] == 1e-6


def test_unisolated_execute_rejected(tmp_path):
    with pytest.raises(ValueError, match="isolated"):
        diagnostic.sealed_guard(tmp_path / "missing.json")


def test_ancestor_seals_checked_without_project_imports(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("pass\n")
    hashes = {"source.py": hashlib.sha256(source.read_bytes()).hexdigest()}
    original, prior = tmp_path / "original.json", tmp_path / "prior.json"
    original.write_text(
        json.dumps({"source_commit": diagnostic.ORIGINAL_COMMIT, "source_hashes": hashes})
    )
    prior.write_text(
        json.dumps({"source_commit": diagnostic.PRIOR_COMMIT, "source_hashes": hashes})
    )
    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    guard = SimpleNamespace(safe_source=lambda root, name: root / name)
    diagnostic.verify_ancestor_seals(guard, {"source_hashes": hashes}, original, prior)
    source.write_text("changed\n")
    with pytest.raises(ValueError, match="source bytes differ"):
        diagnostic.verify_ancestor_seals(guard, {"source_hashes": hashes}, original, prior)
