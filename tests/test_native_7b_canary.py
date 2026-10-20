"""Tiny protocol checks only. No pretrained weights, downloads or 7B calls."""

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_7b_canary as canary  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace.native_owner import NativeFullUpdateOwner  # noqa: E402
from latent_workspace.optimizer_state import tree_hash  # noqa: E402


class Tokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs == dict(tokenize=True, add_generation_prompt=True)
        assert len(messages) == 1 and messages[0]["role"] == "user"
        return [1, 11, 12]

    def encode(self, text, **kwargs):
        assert kwargs == dict(add_special_tokens=False)
        return [3 + sum(map(ord, word)) % 39 for word in text.split()]


def plan():
    return ex.read(canary.ROOT / canary.PLAN)


def test_frozen_plan_counts_bounds_and_no_quality_promotion():
    selected = plan()
    canary.validate(selected)
    assert selected["planned_unique_updates"] == 2
    assert selected["planned_replay_updates"] == 1
    assert selected["planned_backward_rows"] == 6
    assert selected["checkpoint_steps"] == [1, 2]
    assert selected["no_retry"] and not selected["judge_calls"]
    assert selected["old_expression_gate"] == "FAIL"
    assert selected["non_regression"] == "NOT_ESTABLISHED"
    assert selected["qualification_cpu_mkldnn_enabled"] is False


@pytest.mark.parametrize("field", ["seed", "planned_backward_rows", "rows", "no_retry"])
def test_any_plan_drift_is_rejected(field):
    selected = plan()
    selected[field] = "changed"
    with pytest.raises(ValueError, match="Frozen"):
        canary.validate(selected)


def test_native_chat_answer_labels_and_unequal_token_denominators():
    selected = plan()
    rows = canary.encode_rows(Tokenizer(), selected)
    assert rows[0]["memory_ids"] and not rows[1]["memory_ids"]
    assert rows[2]["memory_ids"] and not rows[3]["memory_ids"]
    for row in rows:
        assert row["input_ids"][:3] == [1, 11, 12]
        assert row["labels"][:3] == [-100] * 3
        assert row["labels"][3:] == row["input_ids"][3:]
        assert row["labels"][-1] == 2
        assert row["supervised_tokens"] == len(row["input_ids"]) - 3
    assert rows[0]["supervised_tokens"] != rows[1]["supervised_tokens"]
    mini = canary.batch(rows[1], "cpu")
    assert "memory_ids" not in mini and mini["labels"].dtype == torch.long


@pytest.mark.parametrize(
    "limit",
    [
        "memory_tokens",
        "query_tokens_including_answer",
        "answer_tokens_including_eos",
    ],
)
def test_long_sequences_fail_instead_of_silent_truncation(limit):
    selected = plan()
    selected["bounds"][limit] = 1
    with pytest.raises(ValueError, match="bounds"):
        canary.encode_rows(Tokenizer(), selected)


@pytest.mark.parametrize("fault", ["key", "order", "denominator", "first_label"])
def test_bad_rows_or_windows_rejected(fault):
    selected = plan()
    rows = canary.encode_rows(Tokenizer(), selected)
    if fault == "key":
        rows[-1]["key"] = rows[0]["key"]
    elif fault == "order":
        rows.reverse()
    elif fault == "denominator":
        rows[-1]["supervised_tokens"] += 1
    else:
        rows[-1]["labels"][0] = 1
    with pytest.raises(ValueError):
        canary.validate_rows(rows, selected["windows"])


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_complete_protocol_rows_gradients_and_checkpoint_replay(tmp_path, dtype):
    from test_native_owner import setup

    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        owner, _ = setup(dtype=dtype)
        original = copy.deepcopy(owner.graph)
        selected = plan()
        rows = canary.encode_rows(Tokenizer(), selected)
        guard = lambda *args, **kwargs: None  # noqa: E731
        first, second, replay = (tmp_path / n for n in ("first", "second", "replay"))
        for path in (first, second, replay):
            path.mkdir()
        canary.update(owner, rows, selected["windows"][0], guard, first, 1)
        saved = owner.payload()
        actual = canary.update(owner, rows, selected["windows"][1], guard, second, 2)
        restored = NativeFullUpdateOwner.restore(
            original,
            saved,
            config=owner.config,
            expected_run_contract=owner.run_contract,
            expected_state_sha256=tree_hash(saved),
        )
        repeated = canary.update(restored, rows, selected["windows"][1], guard, replay, 2)
        canary.exact(actual, repeated, "tiny full protocol")
        assert tree_hash(owner.payload()) == tree_hash(restored.payload())
        assert len(list(first.glob("step1_row*.json"))) == 2
        assert all(r["accumulated_gradient_sha256"] for r in actual["rows"])
    finally:
        torch.set_num_threads(previous)


def test_training_receipts_count_updates_and_unknown_failure(tmp_path):
    from test_latent_workspace_execution import role_args, runner

    run = runner(tmp_path)
    run.updates_native = True
    args = role_args(tmp_path, "a")
    assert run.run_role(args, lambda *_: dict(native_weight_updates=2)) == 0
    receipt = ex.read(args.output / "FINISHED.json")
    assert receipt["native_weight_updates"] == 2

    def fail(*_args):
        raise RuntimeError("fixture interruption after unknown progress")

    args = role_args(tmp_path, "b")
    assert run.run_role(args, fail) == 1
    receipt = ex.read(args.output / "FINISHED.json")
    assert receipt["native_weight_updates"] is None and receipt["status"] == ex.INCOMPLETE


@pytest.mark.parametrize("value", [None, True, -1, 1.0, "2"])
def test_activity_requires_a_measured_integer(value):
    result = dict(ex.CEILING)
    with pytest.raises(ValueError, match="Measured"):
        canary.RUN.activity(result, {"native_weight_updates": value})


@pytest.mark.parametrize("fault", ["status", "count", "replay"])
def test_summary_rejects_incomplete_or_miscounted_roles(tmp_path, fault):
    for role, n in (("primary", 2), ("replay", 1)):
        path = tmp_path / role
        path.mkdir()
        data = dict(
            status=canary.STATUSES[role], native_weight_updates=n, outcome={"exact_replay": True}
        )
        if role == "replay":
            if fault == "status":
                data["status"] = ex.INCOMPLETE
            elif fault == "count":
                data["native_weight_updates"] = 0
            else:
                data["outcome"]["exact_replay"] = False
        (path / "FINISHED.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        canary.summary(tmp_path, plan())


def test_summary_reports_physical_and_unique_updates_separately(tmp_path):
    for role, n in (("primary", 2), ("replay", 1)):
        path = tmp_path / role
        path.mkdir()
        ex.write_new(
            path / "FINISHED.json",
            dict(
                status=canary.STATUSES[role],
                native_weight_updates=n,
                outcome={"exact_replay": True},
            ),
        )
    summary = canary.summary(tmp_path, plan())
    assert summary["native_weight_updates"] == 3
    assert summary["unique_updates"] == 2 and summary["replay_updates"] == 1
    assert summary["backward_rows"] == 6 and summary["retained_checkpoints"] == 2
