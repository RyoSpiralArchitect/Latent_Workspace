"""CPU-only runner contract tests; no downloads, CUDA or model weights."""

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
import run_v15_elicitation as runner
import torch
from torch import nn

from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


@pytest.fixture
def plan():
    return json.loads(runner.PLAN.read_text())


@pytest.fixture
def isolated_validate(monkeypatch, tmp_path, plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "PLAN", path)
    monkeypatch.setattr(runner.previous, "validate", lambda: (None, {"parent": True}, None, None))
    monkeypatch.setattr(runner, "verify_previous", lambda _: {"status": "VERIFIED_RECEIPTS"})
    return path


def test_validate_accepts_complete_frozen_contract(isolated_validate, plan):
    actual, parent, cases = runner.validate()
    assert actual == plan and parent == {"parent": True}
    assert len(cases) == len({case["case_id"] for case in cases}) == 36


@pytest.mark.parametrize(
    "path,value",
    [
        (("corpus_seed",), 15002),
        (("exposed_cases",), 5),
        (("confirmation_families",), 9),
        (("confirmation_cases",), 31),
        (("renderers",), ["native_chat", "raw"]),
        (("information",), ["inline"]),
        (("maximum_prompt_tokens",), 1024),
        (("max_new_tokens",), 65),
        (("expected_unique_prefixes",), 145),
        (("expected_generation_sequences",), 287),
        (("stop_rule",), "first newline"),
        (("parser",), "first word"),
        (("choice_suffixes",), [" No", " Yes"]),
        (("optimizer_steps",), 1),
        (("workspace_loaded",), True),
        (("primary_renderer",), "raw"),
        (("gate", "valid_eos_required"), 31),
        (("gate", "correct_per_view_required"), 11),
        (("gate", "correct_per_view_wording_required"), 5),
        (("resources", "allocator_cap_gib"), 19),
        (("claims", "training_performed"), True),
        (("regimes", 1, "seed"), 212),
        (("regimes", 1, "temperature"), 0.8),
    ],
)
def test_validate_rejects_methodology_mutation(isolated_validate, plan, path, value):
    target = plan
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    isolated_validate.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="contract changed"):
        runner.validate()


def test_validate_rejects_unverified_predecessor(isolated_validate, monkeypatch):
    monkeypatch.setattr(runner, "verify_previous", lambda _: {"status": "UNKNOWN"})
    with pytest.raises(RuntimeError, match="verification failed"):
        runner.validate()


def test_validate_rejects_duplicate_case_inventory(isolated_validate, monkeypatch):
    monkeypatch.setattr(runner, "make_cases", lambda _: [{"case_id": "same"}] * 36)
    with pytest.raises(RuntimeError, match="Case inventory mismatch"):
        runner.validate()


@pytest.fixture
def pinned_metadata(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    snapshot = tmp_path / "snapshot"
    config_dir = root / "configs/v14"
    config_dir.mkdir(parents=True)
    snapshot.mkdir()
    names = (
        "config.json",
        "generation_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer.model.v3",
        "tokenizer_config.json",
    )
    rows = []
    for name in names:
        content = (
            json.dumps({"chat_template": "pinned-single-template"})
            if name == "tokenizer_config.json"
            else "fixed-metadata"
        )
        payload = content.encode()
        (snapshot / name).write_bytes(payload)
        rows.append(
            {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    plan_path = config_dir / "MISTRAL_PROMPT_GATE_PLAN.json"
    plan = {"model": {"snapshot": str(snapshot), "snapshot_content_anchor": rows}}
    plan_path.write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "REPO", root)
    return snapshot, plan_path, plan


def test_tokenizer_identity_checks_complete_frozen_files_and_active_template(pinned_metadata):
    snapshot, _, plan = pinned_metadata
    result = runner.tokenizer_identity()
    assert result == {
        "snapshot": str(snapshot),
        "files": plan["model"]["snapshot_content_anchor"],
        "chat_template_sha256": hashlib.sha256(b"pinned-single-template").hexdigest(),
    }


@pytest.mark.parametrize(
    "filename",
    [
        "config.json",
        "generation_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer.model.v3",
        "tokenizer_config.json",
    ],
)
def test_tokenizer_identity_rejects_same_length_metadata_mutation(pinned_metadata, filename):
    snapshot, _, _ = pinned_metadata
    path = snapshot / filename
    payload = path.read_bytes()
    path.write_bytes(b"!" + payload[1:])
    with pytest.raises(RuntimeError, match="Pinned metadata mismatch"):
        runner.tokenizer_identity()


@pytest.mark.parametrize("override", ["chat_template.jinja", "chat_templates"])
def test_tokenizer_identity_rejects_unanchored_template_override(pinned_metadata, override):
    snapshot, _, _ = pinned_metadata
    if override.endswith(".jinja"):
        (snapshot / override).write_text("override")
    else:
        (snapshot / override).mkdir()
    with pytest.raises(RuntimeError, match="Unanchored"):
        runner.tokenizer_identity()


def test_tokenizer_identity_rejects_missing_anchor_coverage(pinned_metadata):
    _, plan_path, plan = pinned_metadata
    plan["model"]["snapshot_content_anchor"].pop()
    plan_path.write_text(json.dumps(plan))
    with pytest.raises(RuntimeError, match="coverage changed"):
        runner.tokenizer_identity()


def test_tokenizer_identity_rejects_anchored_non_string_template(pinned_metadata):
    snapshot, plan_path, plan = pinned_metadata
    payload = json.dumps({"chat_template": {"default": "template"}}).encode()
    (snapshot / "tokenizer_config.json").write_bytes(payload)
    row = next(
        r for r in plan["model"]["snapshot_content_anchor"] if r["path"] == "tokenizer_config.json"
    )
    row.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    plan_path.write_text(json.dumps(plan))
    with pytest.raises(RuntimeError, match="single chat template"):
        runner.tokenizer_identity()


def replay_panel():
    old, new = [], []
    for case in ("w0_q0", "w0_q1", "w1_q0", "w1_q1"):
        for regime in ("greedy", "sample211"):
            for condition in ("base", "base_inline"):
                row = {
                    "case_id": case,
                    "regime": regime,
                    "condition": condition,
                    "prompt_ids": [1, 2],
                    "generated_ids": [3, 4],
                    "answer": "yes",
                    "finish_reason": "eos",
                    "token_trace": [{"step": 0, "token_id": 3, "probability": 0.5}],
                }
                old.append(row)
                new.append({**copy.deepcopy(row), "split": "exposed", "renderer": "raw"})
    return new, old


def test_exposed_replay_requires_all_16_identical_raw_sequences():
    new, old = replay_panel()
    assert runner.replay_exposed(new, old) == 16
    with pytest.raises(RuntimeError, match="denominator"):
        runner.replay_exposed(new[:-1], old)


@pytest.mark.parametrize(
    "key,value",
    [
        ("prompt_ids", [2, 1]),
        ("generated_ids", [4, 3]),
        ("answer", "Yes"),
        ("finish_reason", "length"),
        ("token_trace", [{"step": 0, "token_id": 3, "probability": 0.5001}]),
    ],
)
def test_replay_rejects_every_published_trace_difference(key, value):
    new, old = replay_panel()
    new[0][key] = value
    with pytest.raises(RuntimeError, match="replay mismatch"):
        runner.replay_exposed(new, old)


def test_native_and_confirmation_rows_do_not_replace_missing_raw_replay():
    new, old = replay_panel()
    additions = [
        {**copy.deepcopy(new[0]), "renderer": "native_chat"},
        {**copy.deepcopy(new[0]), "split": "confirmation"},
    ]
    assert runner.replay_exposed(new + additions, old) == 16
    with pytest.raises(RuntimeError, match="denominator"):
        runner.replay_exposed(new[:-1] + additions, old)


class TinyBase(nn.Module):
    def __init__(self):
        super().__init__()
        self.lm_head = nn.Linear(2, 4, bias=False).requires_grad_(False)
        with torch.no_grad():
            self.lm_head.weight.copy_(torch.tensor([[0, 0], [1, 0], [0, 1], [-1, -1.0]]))
        self.device = torch.device("cpu")
        self.calls = []
        self.generation_config = SimpleNamespace(eos_token_id=3)
        self.break_ordinary = False

    def model(self, ids, **kwargs):
        self.calls.append((ids.clone(), kwargs.copy()))
        assert set(kwargs) == {"attention_mask", "use_cache"}
        assert kwargs["use_cache"] is False
        assert torch.equal(kwargs["attention_mask"], torch.ones_like(ids))
        hidden = torch.stack((ids.float(), ids.float() + 1), dim=-1)
        return SimpleNamespace(last_hidden_state=hidden)

    def forward(self, ids, **kwargs):
        hidden = self.model(ids, **kwargs).last_hidden_state
        logits = self.lm_head(hidden)
        if self.break_ordinary:
            logits = logits + 1
        return SimpleNamespace(logits=logits)


def test_base_backend_uses_full_prefix_no_cache_and_shared_native_readout():
    base = TinyBase()
    backend = runner.BaseBackend(base, NativeWorkspaceReadout(base.lm_head))
    hidden = backend.encode((0, 1, 2))
    out = backend.readout(hidden, torch.zeros(1, 1, 2))
    assert out.logits.shape == (1, 3, 4)
    assert torch.equal(out.logits, base.lm_head(hidden))
    assert torch.count_nonzero(out.applied_delta) == 0
    assert backend.parity_checks == 1
    assert base.calls[0][0].tolist() == [[0, 1, 2]]


def test_base_backend_rejects_workspace_and_nonzero_residual():
    base = TinyBase()
    backend = runner.BaseBackend(base, NativeWorkspaceReadout(base.lm_head))
    hidden = backend.encode((0, 1))
    with pytest.raises(RuntimeError, match="must not invoke a workspace"):
        backend.delta("intact", hidden, (0, 1))
    with pytest.raises(RuntimeError, match="Nonzero residual"):
        backend.readout(hidden, torch.ones(1, 1, 2))
    assert backend.parity_checks == 0


def test_initial_choices_use_native_ids_and_recompute_exact_parity():
    base = TinyBase()
    guard_calls = []
    row = {
        "case_id": "toy",
        "renderer": "raw",
        "information": "inline",
        "prompt_ids": [0, 1],
        "candidate_ids": [1, 2],
        "target_label": "deliberately invalid and never forwarded",
        "answer": "must not enter model",
    }
    results = runner.initial_choices(
        base, NativeWorkspaceReadout(base.lm_head), [row], guard_calls.append
    )
    assert guard_calls == ["initial:0"]
    assert results[0]["native"] == {"scores": [1.0, 2.0], "gap": 1.0, "prediction": 1}
    assert results[0]["top1_token_id"] == 2
    expected_probabilities = torch.softmax(torch.tensor([0.0, 1.0, 2.0, -3.0]).double(), -1)
    assert results[0]["candidate_probabilities"] == expected_probabilities[[1, 2]].tolist()
    assert results[0]["ordinary_shared_full_logits_exact"] is True
    assert results[0]["shared_historical_full_logits_exact"] is True
    assert results[0]["zero_delta_exact"] is True
    assert len(base.calls) == 2
    assert "target_label" not in results[0] and "answer" not in results[0]


def test_initial_choices_detect_ordinary_native_disagreement():
    base = TinyBase()
    base.break_ordinary = True
    row = {
        "case_id": "toy",
        "renderer": "raw",
        "information": "inline",
        "prompt_ids": [0, 1],
        "candidate_ids": [1, 2],
    }
    with pytest.raises(RuntimeError, match="Ordinary/shared"):
        runner.initial_choices(base, NativeWorkspaceReadout(base.lm_head), [row], lambda _: None)


def test_render_inputs_forwards_text_only_not_labels_or_family_metadata(monkeypatch):
    observed = []

    def renderer(_tokenizer, **kwargs):
        observed.append(kwargs)
        return {"prompt_ids": [1]}

    monkeypatch.setattr(runner, "render_case", renderer)
    cases = [
        {
            "case_id": "toy",
            "query": "Question?",
            "context": "Facts",
            "target_label": "wrong type",
            "family_id": "answer-leak bait",
            "view": "also never forwarded",
            "hop": -999,
        }
    ]
    plan = {
        "renderers": ["raw"],
        "information": ["inline"],
        "maximum_prompt_tokens": 1,
        "expected_unique_prefixes": 1,
    }
    rows = runner.render_inputs(object(), cases, plan)
    assert observed == [
        {"query": "Question?", "context": "Facts", "renderer": "raw", "information": "inline"}
    ]
    assert rows == [
        {"case_id": "toy", "renderer": "raw", "information": "inline", "prompt_ids": [1]}
    ]


def test_render_inputs_never_truncates_overlength_prompt(monkeypatch):
    monkeypatch.setattr(runner, "render_case", lambda *_args, **_kwargs: {"prompt_ids": [1, 2]})
    plan = {
        "renderers": ["raw"],
        "information": ["inline"],
        "maximum_prompt_tokens": 1,
        "expected_unique_prefixes": 1,
    }
    with pytest.raises(RuntimeError, match="no truncation"):
        runner.render_inputs(object(), [{"case_id": "toy", "query": "Q", "context": "C"}], plan)


def test_generation_reuses_case_sampling_key_without_forwarding_target(monkeypatch):
    observed = []

    def generate_stub(**kwargs):
        observed.append(kwargs)
        rows = [
            {
                "id": "toy__greedy__" + condition,
                "case_id": kwargs["case_id"],
                "condition": condition,
                "regime": kwargs["regime"]["id"],
                "answer": "yes",
                "finish_reason": "eos",
            }
            for condition in kwargs["prompts"]
        ]
        return rows, {"toy_receipt": True}

    monkeypatch.setattr(runner, "generate_matched", generate_stub)
    base = TinyBase()
    tokenizer = SimpleNamespace(eos_token_id=3, decode=lambda *_args, **_kwargs: "yes")
    cases = [
        {
            "case_id": "toy",
            "split": "exposed",
            "family_id": "label-blind",
            "view": "historical",
            "wording": "ranked_above",
            "target_label": 0,
        }
    ]
    renderings = [
        {
            "case_id": "toy",
            "renderer": renderer,
            "information": information,
            "prompt_ids": [1],
        }
        for renderer in ("raw", "native_chat")
        for information in ("query_only", "inline")
    ]
    plan = {
        "renderers": ["raw", "native_chat"],
        "regimes": [{"id": "greedy", "seed": 0, "temperature": 0.0}],
        "max_new_tokens": 64,
        "expected_generation_sequences": 4,
    }
    result = runner.generate(
        base,
        NativeWorkspaceReadout(base.lm_head),
        tokenizer,
        cases,
        renderings,
        plan,
        lambda _: None,
    )
    assert len(observed) == 2
    assert [kwargs["case_id"] for kwargs in observed] == ["toy", "toy"]
    assert all("target_label" not in kwargs and "family_id" not in kwargs for kwargs in observed)
    assert all(kwargs["zero_pairs"] == () and kwargs["max_new_tokens"] == 64 for kwargs in observed)
    assert all(row["valid_eos"] and not row["strict_correct"] for row in result["rows"])
    assert len({row["id"] for row in result["rows"]}) == 4
    assert base.calls == []
