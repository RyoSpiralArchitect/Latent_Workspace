"""Resource probe has no permission to update or save weights."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_resource_probe as probe  # noqa: E402
from test_native_7b_canary import Tokenizer  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402


def plan():
    return ex.read(probe.ROOT / probe.PLAN)


def test_sealed_plan_preserves_original_arithmetic_and_zero_updates():
    selected = plan()
    probe.validate(selected)
    effective = probe.effective_plan(selected)
    reference = ex.read(probe.ROOT / selected["reference_plan"])
    for key in ("backbone", "optimizer", "seed", "expected_runtime"):
        assert effective[key] == reference[key]
    assert effective["storage_forecast_bytes"] == selected["native_weight_updates"] == 0


@pytest.mark.parametrize("field", ["profiles", "resources"])
def test_plan_drift_is_rejected(field):
    selected = plan()
    selected[field] = None
    with pytest.raises(ValueError, match="Frozen"):
        probe.validate(selected)


def test_exact_lengths_and_causal_denominators():
    selected = plan()
    rows = probe.resource_rows(Tokenizer(), selected["profiles"])
    for row, profile in zip(rows, selected["profiles"], strict=True):
        assert len(row["memory_ids"]) == profile["memory_tokens"]
        assert len(row["input_ids"]) == len(row["labels"]) == profile["query_tokens"]
        assert sum(t != -100 for t in row["labels"]) == profile["answer_tokens"]
        assert row["labels"][0] == -100 and row["labels"][-1] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("memory_tokens", 129),
        ("query_tokens", 129),
        ("answer_tokens", 128),
        ("memory_tokens", True),
    ],
)
def test_invalid_profiles_are_not_silently_truncated(field, value):
    profiles = copy.deepcopy(plan()["profiles"])
    profiles[0][field] = value
    with pytest.raises(ValueError, match="bounds"):
        probe.resource_rows(Tokenizer(), profiles)


def test_real_tiny_owner_accumulates_without_update_or_save(tmp_path, monkeypatch):
    from test_native_owner import setup

    owner, _ = setup()

    def forbidden(*args, **kwargs):
        raise AssertionError("Diagnostic must not update or save")

    monkeypatch.setattr(owner, "step", forbidden)
    monkeypatch.setattr(owner, "save", forbidden)
    profiles = [
        dict(key="direct", memory_tokens=0, query_tokens=12, answer_tokens=3),
        dict(key="memory", memory_tokens=4, query_tokens=12, answer_tokens=3),
    ]
    rows = probe.resource_rows(Tokenizer(), profiles)
    result = probe.backward_window(owner, rows, lambda *a, **k: None, tmp_path)
    assert result["backward_rows"] == 2
    assert result["native_unchanged"] and result["masters_unchanged"]
    assert owner.completed_steps == 0
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_resource_contract_is_accepted_by_actual_owner_and_old_limits_unchanged():
    from test_native_owner import setup

    from latent_workspace.native_owner import NativeFullUpdateOwner

    owner, _ = setup()
    selected = plan()
    old = ex.read(probe.ROOT / "configs/v1_0/NATIVE_RESOURCE_PROBE_01.json")
    allowed = {"schema", "recovery_of", "qualification_cases"}
    assert {k: v for k, v in old.items() if k not in allowed} == {
        k: v for k, v in selected.items() if k not in allowed
    }
    rows = probe.resource_rows(
        Tokenizer(), [dict(key="probe", memory_tokens=4, query_tokens=12, answer_tokens=3)]
    )
    contract = probe.resource_contract(owner.run_contract, rows)
    rebuilt = NativeFullUpdateOwner(owner.graph, config=owner.config, run_contract=contract)
    assert rebuilt.run_contract["objective"] == "query_only_token_weighted_causal_nll"
    assert rebuilt.run_contract["data_sha256"] == ex.plan_hash(rows)
