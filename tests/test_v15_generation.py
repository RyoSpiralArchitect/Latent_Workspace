from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from latent_workspace_ft_v10.v15_generation import generate_matched
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


class ToyBackend:
    def __init__(self, *, zero_bug=False, delta_bug=None, fractional=False):
        self.head = torch.nn.Linear(3, 3, bias=False)
        with torch.no_grad():
            self.head.weight.copy_(torch.eye(3))
        self.head.requires_grad_(False)
        self.adapter = NativeWorkspaceReadout(self.head)
        self.zero_bug = zero_bug
        self.delta_bug = delta_bug
        self.fractional = fractional
        self.prefixes = []
        self.reader_calls = []
        self.readout_calls = []

    def encode(self, prefix):
        self.prefixes.append(prefix)
        hidden = torch.zeros(1, len(prefix), 3)
        hidden[..., 0] = 1
        return hidden

    def delta(self, condition, hidden, prefix):
        self.reader_calls.append((condition, prefix))
        result = torch.zeros(1, 1, 3)
        if condition == "final_intact" or (condition == "final_zero" and self.zero_bug):
            result[..., 2] = 3 if not self.fractional else 0.2
        if self.delta_bug == "dtype":
            result = result.double()
        elif self.delta_bug == "shape":
            result = result[:, 0]
        elif self.delta_bug == "nonfinite":
            result[..., 2] = float("nan")
        return result

    def readout(self, hidden, delta):
        self.readout_calls.append((hidden.shape, delta.clone()))
        return self.adapter(hidden, delta)


def prompts():
    return {
        "base": [1],
        "base_inline": [2, 1],
        "final_intact": [1],
        "final_zero": [1],
        "mean_intact": [1],
        "mean_zero": [1],
    }


def generate(backend=None, **overrides):
    args = {
        "case_id": "toy",
        "regime": {"id": "greedy", "seed": 47, "temperature": 0.0},
        "prompts": prompts(),
        "backend": backend or ToyBackend(),
        "max_new_tokens": 3,
        "eos_token_ids": {2},
        "decode": lambda ids: ",".join(map(str, ids)),
    }
    args.update(overrides)
    return generate_matched(**args)


def test_full_prefix_grouping_zero_reader_execution_and_termination():
    backend = ToyBackend()
    rows, receipt = generate(backend)
    indexed = {row["condition"]: row for row in rows}
    assert indexed["base"]["generated_ids"] == [0, 0, 0]
    assert indexed["base"]["finish_reason"] == "length"
    assert indexed["final_intact"]["generated_ids"] == [2]
    assert indexed["final_intact"]["finish_reason"] == "eos"
    assert receipt["decoder_calls"] == 6  # Common + inline once each step.
    assert receipt["zero_full_logit_exact_checks"] == 6
    assert receipt["zero_full_logit_exact_checks_by_condition"] == {
        "final_zero": 3,
        "mean_zero": 3,
    }
    assert receipt["base_zero_token_ids_exact"] is True
    assert receipt["persistent_prefix_cache_entries"] == 0
    assert receipt["kv_cache_used"] is False
    assert receipt["maximum_concurrent_prefixes"] == 2
    assert backend.prefixes == [(1,), (2, 1), (1, 0), (2, 1, 0), (1, 0, 0), (2, 1, 0, 0)]
    assert sum(name == "final_zero" for name, _ in backend.reader_calls) == 3
    assert sum(name == "mean_zero" for name, _ in backend.reader_calls) == 3
    assert not any(name in ("base", "base_inline") for name, _ in backend.reader_calls)
    assert all(row["answer"] == ",".join(map(str, row["generated_ids"])) for row in rows)


def test_native_probabilities_are_not_greedy_policy_probability():
    rows, _ = generate()
    first = {row["condition"]: row["token_trace"][0] for row in rows}
    assert first["base"]["sampling_probability"] == 1
    assert 0 < first["base"]["chosen_token_native_probability"] < 1
    intact = first["final_intact"]
    assert intact["native_logit_change_max_abs"] == 3
    assert intact["native_logit_change_l2"] == 3
    assert intact["native_top1_changed"] is True
    assert intact["native_top1_token_id"] == 2
    assert intact["same_prefix_base_native_top1_token_id"] == 0
    assert (
        intact["chosen_token_native_probability"]
        > intact["same_prefix_base_chosen_token_native_probability"]
    )
    assert all(trace["uniform"] == first["base"]["uniform"] for trace in first.values())


def test_sampling_common_random_numbers_and_condition_order_independence():
    regime = {"id": "sample47", "seed": 47, "temperature": 0.7}
    first, _ = generate(ToyBackend(fractional=True), regime=regime, eos_token_ids=set())
    second, _ = generate(
        ToyBackend(fractional=True),
        regime=regime,
        eos_token_ids=set(),
        prompts=dict(reversed(list(prompts().items()))),
    )
    a, b = ({row["condition"]: row for row in rows} for rows in (first, second))
    assert a == b
    assert a["base"]["generated_ids"] == a["mean_zero"]["generated_ids"]
    assert a["base"]["generated_ids"] == a["final_zero"]["generated_ids"]
    for step in range(3):
        uniform = a["base"]["token_trace"][step]["uniform"]
        assert all(row["token_trace"][step]["uniform"] == uniform for row in first)


def test_divergent_histories_recompute_without_cross_step_cache():
    backend = ToyBackend()
    rows, receipt = generate(backend, eos_token_ids=set())
    assert receipt["decoder_calls"] == 8
    assert receipt["maximum_concurrent_prefixes"] == 3
    assert (1, 2) in backend.prefixes and (1, 2, 2) in backend.prefixes
    assert rows[2]["generated_ids"] == [2, 2, 2]
    assert receipt["logit_reference"] == "base_at_same_current_prefix"


def test_no_question_parsing_or_label_input_and_backend_keeps_original_span():
    class BoundSpanBackend(ToyBackend):
        def __init__(self):
            super().__init__()
            self.original_prompt = (1, 0)
            self.bound_span = (0, 1)
            self.pooled = []

        def encode(self, prefix):
            hidden = super().encode(prefix)
            hidden[:, :, 1] = torch.arange(len(prefix))
            return hidden

        def delta(self, condition, hidden, prefix):
            assert prefix[: len(self.original_prompt)] == self.original_prompt
            start, end = self.bound_span
            self.pooled.append(hidden[:, start:end].mean(1, keepdim=True).clone())
            return torch.zeros(1, 1, 3)

    backend = BoundSpanBackend()
    rows, receipt = generate(
        backend,
        prompts={"base": [1, 0], "mean_intact": [1, 0]},
        zero_pairs=(),
        eos_token_ids=set(),
        decode=lambda _: "Question: generated marker never changes the bound span",
    )
    assert len(backend.pooled) == 3
    assert all(torch.equal(value, backend.pooled[0]) for value in backend.pooled)
    assert receipt["reader_span_owner"] == "backend_bound_original_prompt"
    assert "reference" not in rows[0]


def test_broken_zero_control_fails_even_if_native_rounding_hides_it():
    with pytest.raises(RuntimeError, match="exact full-logit base noop"):
        generate(ToyBackend(zero_bug=True))

    class RoundedAway(ToyBackend):
        def delta(self, condition, hidden, prefix):
            result = super().delta(condition, hidden, prefix)
            if condition == "final_zero":
                result[..., 0] = 1e-9  # Native FP32 composition rounds this away.
            return result

    with pytest.raises(RuntimeError, match="exact full-logit base noop"):
        generate(RoundedAway())


def test_zero_guard_compares_all_prefix_logits_not_only_last_token():
    class EarlierRowDrift(ToyBackend):
        def __init__(self):
            super().__init__()
            self.pending_zero = False

        def delta(self, condition, hidden, prefix):
            self.pending_zero = condition == "final_zero"
            return super().delta(condition, hidden, prefix)

        def readout(self, hidden, delta):
            result = super().readout(hidden, delta)
            if self.pending_zero:
                self.pending_zero = False
                logits = result.logits.clone()
                logits[:, 0] += 1
                return SimpleNamespace(logits=logits, last_logits=logits[:, -1].float())
            return result

    with pytest.raises(RuntimeError, match="exact full-logit base noop"):
        generate(EarlierRowDrift(), prompts={name: [1, 0] for name in prompts()})


def test_sub_ulp_reader_delta_does_not_select_from_counterfactual_fp32_logits():
    class SubULP(ToyBackend):
        def __init__(self):
            super().__init__()
            self.head.bfloat16()

        def encode(self, prefix):
            return super().encode(prefix).bfloat16()

        def delta(self, condition, hidden, prefix):
            result = torch.zeros(1, 1, 3)
            if condition == "final_intact":
                result[..., 0] = 0.0001
            return result

    rows, _ = generate(SubULP())
    indexed = {row["condition"]: row for row in rows}
    assert indexed["final_intact"]["generated_ids"] == indexed["base"]["generated_ids"]
    trace = indexed["final_intact"]["token_trace"][0]
    assert trace["delta_l2"] > 0
    assert trace["native_applied_delta_l2"] == 0
    assert trace["native_logit_change_max_abs"] == 0
    assert trace["native_top1_changed"] is False


@pytest.mark.parametrize("bug", ["dtype", "shape", "nonfinite"])
def test_invalid_reader_delta_fails_closed(bug):
    with pytest.raises(ValueError, match="delta"):
        generate(ToyBackend(delta_bug=bug))


@pytest.mark.parametrize("eos", [{-1}, {True}, [2], {3}])
def test_invalid_eos_fails_closed(eos):
    with pytest.raises(ValueError, match="EOS"):
        generate(eos_token_ids=eos)


@pytest.mark.parametrize(
    "override",
    [
        {"max_new_tokens": 0},
        {"max_new_tokens": True},
        {"case_id": ""},
        {"regime": {"id": "sample", "seed": True, "temperature": 1}},
        {"regime": {"id": "sample", "seed": 47, "temperature": float("nan")}},
        {"regime": {"id": "sample", "seed": 47, "temperature": -1}},
        {"regime": {"id": "", "seed": 47, "temperature": 1}},
        {"prompts": {"base": []}},
        {"prompts": {"base": [True]}},
        {"prompts": {"base": [1], "final_zero": [2]}},
        {"zero_pairs": (("base", "missing"),)},
        {"zero_pairs": (("base", "base_inline"),)},
        {"zero_pairs": (("base", "final_zero"), ("base", "final_zero"))},
        {"zero_pairs": (("final_zero", "mean_zero"),)},
    ],
)
def test_invalid_protocol_fails_before_encoding(override):
    backend = ToyBackend()
    with pytest.raises(ValueError):
        generate(backend, **override)
    assert backend.prefixes == []


def test_guard_runs_before_each_encode_and_can_abort_without_mutation():
    backend = ToyBackend()
    calls = []

    def guard():
        calls.append(len(backend.prefixes))
        if len(calls) == 2:
            raise RuntimeError("memory guard")

    with pytest.raises(RuntimeError, match="memory guard"):
        generate(backend, guard=guard)
    assert calls == [0, 1]
    assert backend.prefixes == [(1,)]


def test_full_native_readout_receipt_and_last_logits_must_agree():
    class BadReadout(ToyBackend):
        def readout(self, hidden, delta):
            result = super().readout(hidden, delta)
            return SimpleNamespace(logits=result.logits, last_logits=result.last_logits + 1)

    with pytest.raises(ValueError, match="full-sequence/full-vocabulary"):
        generate(BadReadout())


def test_inputs_and_trainable_tensors_are_not_mutated_or_given_gradients():
    backend = ToyBackend()
    original = backend.head.weight.detach().clone()
    prompt_values = prompts()
    generate(backend, prompts=prompt_values)
    assert prompt_values == prompts()
    assert torch.equal(backend.head.weight, original)
    assert backend.head.weight.grad is None
