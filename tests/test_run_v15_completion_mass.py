"""CPU-only tests for the post-result fixed completion-path scorer."""

import copy
import hashlib
import json

import pytest
import run_v15_completion_mass as runner
import torch
from test_run_v15_elicitation import TinyBase

from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


def test_real_predecessor_and_frozen_plan_validate():
    plan, _, cases = runner.validate()
    assert plan["prefixes"] == 144 and len(cases) == 36
    assert plan["all_cases_exposed"] and plan["new_generation_sequences"] == 0


def test_plan_change_fails_closed(tmp_path, monkeypatch):
    changed = tmp_path / "plan.json"
    plan = json.loads(runner.PLAN.read_text())
    plan["resources"]["allocator_cap_gib"] = 19
    changed.write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "PLAN", changed)
    with pytest.raises(ValueError, match="plan changed"):
        runner.validate()


def test_prefix_digest_stable_and_order_sensitive():
    assert runner.prefix_digest([1, 2]) == hashlib.sha256(b"[1,2]").hexdigest()
    assert runner.prefix_digest([1, 2]) != runner.prefix_digest([2, 1])


@pytest.fixture
def scoring_inputs():
    base = TinyBase()
    row = {
        "case_id": "toy",
        "renderer": "raw",
        "information": "inline",
        "prompt_ids": [0, 1],
        "candidate_ids": [1, 2],
        "bindings": [
            {"target_label": 0, "token_id": 1, "suffixes": [" no", " No"]},
            {"target_label": 1, "token_id": 2, "suffixes": [" yes", " Yes"]},
        ],
    }
    case = {
        "case_id": "toy",
        "target_label": 0,
        "view": "historical",
        "wording": "ranked_above",
        "split": "exposed",
        "family_id": "family",
    }
    old = runner.previous.initial_choices(
        base, NativeWorkspaceReadout(base.lm_head), [row], lambda _: None
    )
    base.calls.clear()
    return base, row, case, old


def test_scores_all_unique_alias_paths_then_immediate_eos(scoring_inputs):
    base, row, case, old = scoring_inputs
    guards = []
    scored, aliases, checks = runner.score(
        base, NativeWorkspaceReadout(base.lm_head), [row], [case], old, 3, guards.append
    )
    assert aliases == 2 and checks == 3 and guards == ["prefix:0"]
    actual = scored[0]
    assert actual["old_lowercase_native"] == old[0]["native"]
    assert actual["prefix_ids"] == [0, 1]
    assert actual["initial_choice_replay_exact"] and actual["ordinary_shared_full_logits_exact"]
    assert [c[0].tolist() for c in base.calls] == [[[0, 1]], [[0, 1]], [[0, 1, 1]], [[0, 1, 2]]]
    initial = torch.tensor([0.0, 1.0, 2.0, -3.0], dtype=torch.float64).log_softmax(-1)
    for alias in actual["aliases"]:
        token = alias["token_id"]
        eos = torch.tensor(
            [0.0, token, token + 1, -2 * token - 1], dtype=torch.float64
        ).log_softmax(-1)[3]
        assert alias["first_log_probability"] == float(initial[token])
        assert alias["eos_log_probability"] == float(eos)
        assert alias["complete_log_probability"] == float(initial[token]) + float(eos)
    assert all(p.grad is None for p in base.parameters())


def test_label_metadata_does_not_enter_forward(scoring_inputs):
    base, row, case, old = scoring_inputs
    first, _, _ = runner.score(
        base, NativeWorkspaceReadout(base.lm_head), [row], [case], old, 3, lambda _: None
    )
    case["target_label"] = 1
    second, _, _ = runner.score(
        base, NativeWorkspaceReadout(base.lm_head), [row], [case], old, 3, lambda _: None
    )
    assert first[0]["aliases"] == second[0]["aliases"]
    assert first[0]["target_label"] != second[0]["target_label"]


@pytest.mark.parametrize(
    "key", ["native", "top1_token_id", "top1_probability", "candidate_probabilities"]
)
def test_any_initial_receipt_drift_rejected(scoring_inputs, key):
    base, row, case, old = scoring_inputs
    old = copy.deepcopy(old)
    old[0][key] = {"scores": [1, 9], "gap": 8, "prediction": 1} if key == "native" else None
    with pytest.raises((RuntimeError, TypeError), match="replay|None|integer|index|changed|Tensor"):
        runner.score(
            base, NativeWorkspaceReadout(base.lm_head), [row], [case], old, 3, lambda _: None
        )


def test_ordinary_shared_disagreement_rejected(scoring_inputs):
    base, row, case, old = scoring_inputs
    base.break_ordinary = True
    with pytest.raises(RuntimeError, match="Ordinary/shared"):
        runner.score(
            base, NativeWorkspaceReadout(base.lm_head), [row], [case], old, 3, lambda _: None
        )


def test_prepare_uses_all_existing_prefixes(monkeypatch):
    monkeypatch.setattr(runner, "load", lambda _: [{"text": "frozen", "prompt_ids": [1, 2]}] * 144)
    calls = []

    def bind(tokenizer, text, ids):
        calls.append((tokenizer, text, ids))
        return ["bound"]

    monkeypatch.setattr(runner, "bind_aliases", bind)
    assert len(runner.prepare("tokenizer")) == 144
    assert calls == [("tokenizer", "frozen", [1, 2])] * 144


def test_prepare_rejects_partial_grid(monkeypatch):
    monkeypatch.setattr(runner, "load", lambda _: [])
    with pytest.raises(RuntimeError, match="denominator"):
        runner.prepare(None)
