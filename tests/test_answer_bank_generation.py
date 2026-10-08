from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch import nn

from latent_workspace_ft_v10.answer_bank_generation import (
    CONDITIONS,
    choose_token,
    generate_group,
    matched_uniform,
    native_full_readout,
)

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "answer_bank_runner_test", REPO / "scripts/run_v14_answer_bank.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_common_random_numbers_do_not_depend_on_condition_or_history():
    first = matched_uniform("case_a", 211, 0)
    assert first == matched_uniform("case_a", 211, 0)
    assert 0 <= first["value"] < 1 and len(first["sha256"]) == 64
    assert first != matched_uniform("case_a", 212, 0)
    assert first != matched_uniform("case_a", 211, 1)
    assert first != matched_uniform("case_b", 211, 0)


def test_token_id_order_sampling_and_greedy_tie_break():
    logits = torch.log(torch.tensor([0.2, 0.5, 0.3], dtype=torch.float64))
    assert choose_token(logits, 1, 0.0)[0] == 0
    assert choose_token(logits, 1, 0.19)[0] == 0
    assert choose_token(logits, 1, 0.21)[0] == 1
    assert choose_token(logits, 1, 0.71)[0] == 2
    assert choose_token(logits, 1, 1 - 2**-53)[0] == 2
    assert choose_token(torch.tensor([2.0, 2.0, 1.0]), 0, 0.9) == (0, 1.0)


@pytest.mark.parametrize("temperature,uniform", [(-1, 0.3), (float("nan"), 0.3), (1, 1), (1, -0.1)])
def test_sampling_rejects_invalid_coordinates(temperature, uniform):
    with pytest.raises(ValueError):
        choose_token(torch.ones(3), temperature, uniform)


def test_sampling_rejects_nonfinite_logits():
    with pytest.raises(ValueError, match="finite"):
        choose_token(torch.tensor([0.0, float("nan")]), 1, 0.5)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_native_full_head_geometry_and_exact_zero(dtype):
    torch.manual_seed(4)
    head = nn.Linear(8, 17, bias=False).to(dtype)
    hidden = torch.randn(1, 5, 8).to(dtype)
    captured = []
    handle = head.register_forward_pre_hook(
        lambda _module, args: captured.append(tuple(args[0].shape))
    )
    expected = head(hidden)
    actual, trace = native_full_readout(hidden, torch.zeros(1, 1, 8), head)
    handle.remove()
    assert torch.equal(actual, expected)
    assert actual.shape == (1, 5, 17) and captured == [(1, 5, 8), (1, 5, 8)]
    assert trace == {
        "delta_l2": 0.0,
        "native_applied_delta_l2": 0.0,
        "native_applied_fraction": 0.0,
    }


def test_native_sub_ulp_delta_may_disappear_but_is_recorded():
    head = nn.Linear(8, 5, bias=False).bfloat16()
    hidden = torch.ones(1, 3, 8, dtype=torch.bfloat16)
    logits, trace = native_full_readout(hidden, torch.full((1, 1, 8), 0.0001), head)
    assert torch.equal(logits, head(hidden))
    assert trace["delta_l2"] > 0 and trace["native_applied_fraction"] == 0


class ToyBackend:
    def __init__(self, zero_bug=False):
        self.head = nn.Linear(3, 3, bias=False)
        self.head.weight.data.copy_(torch.eye(3))
        self.prefixes = []
        self.zero_bug = zero_bug

    def encode(self, prefix):
        self.prefixes.append(prefix)
        hidden = torch.zeros(1, len(prefix), 3)
        hidden[..., 0] = 1.0
        return hidden

    def delta(self, condition, hidden):
        delta = torch.zeros(1, 1, 3)
        if condition == "centered_semantic" or (condition == "centered_zero" and self.zero_bug):
            delta[..., 2] = 3.0
        return delta


def prompts():
    return {
        condition: {
            "ids": [2, 1] if condition == "base_inline" else [1],
            "messages": [{"role": "user", "content": "same"}],
            "rendered_prompt": "same",
        }
        for condition in CONDITIONS
    }


def generate(backend=None, **kwargs):
    return generate_group(
        case_id="toy",
        lane="general",
        regime={"id": "greedy", "seed": 0, "temperature": 0.0},
        prompts=prompts(),
        backend=backend or ToyBackend(),
        max_new_tokens=3,
        eos_token_ids={2},
        decode=lambda ids: ",".join(map(str, ids)),
        **kwargs,
    )


def test_group_shares_prefixes_and_executes_zero_control():
    backend = ToyBackend()
    answers, receipt = generate(backend)
    by_condition = {answer["condition"]: answer for answer in answers}
    assert len(answers) == 7
    assert by_condition["base"]["generated_ids"] == [0, 0, 0]
    assert by_condition["centered_zero"]["generated_ids"] == [0, 0, 0]
    assert by_condition["centered_semantic"]["generated_ids"] == [2]
    assert by_condition["centered_semantic"]["finish_reason"] == "eos"
    assert by_condition["base"]["finish_reason"] == "length"
    assert receipt["decoder_calls"] == 6  # only common and inline prefixes at each step
    assert receipt["zero_full_logit_exact_checks"] == 3
    assert receipt["persistent_prefix_cache_entries"] == 0
    assert receipt["kv_cache_used"] is False
    assert all(answer["regime"] == "greedy" for answer in answers)
    assert all("answer" in answer and "text" not in answer for answer in answers)
    first_uniforms = [answer["token_trace"][0]["uniform"] for answer in answers]
    assert all(uniform == first_uniforms[0] for uniform in first_uniforms)


def test_group_reports_each_completed_answer():
    emitted = []
    answers, _ = generate(on_answer=emitted.append)
    assert emitted == answers


def test_nonzero_zero_control_fails_closed():
    with pytest.raises(RuntimeError, match="exact full-logit"):
        generate(ToyBackend(zero_bug=True))


def test_prompt_drift_fails_closed():
    values = prompts()
    values["centered_twin"]["ids"] = [4]
    with pytest.raises(ValueError, match="identical"):
        generate_group(
            case_id="x",
            lane="general",
            regime={},
            prompts=values,
            backend=None,
            max_new_tokens=1,
            eos_token_ids={2},
            decode=str,
        )


class Tokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        assert add_generation_prompt
        rendered = "[INST]" + messages[0]["content"] + "[/INST]"
        return list(rendered.encode()) if tokenize else rendered


def test_prompt_builder_keeps_reference_and_rubric_out_of_forward():
    case = {
        "user_prompt": "QUESTION",
        "memory_text": "MEMORY",
        "reference": "SECRET_REFERENCE",
        "rubric": "SECRET_RUBRIC",
    }
    result = runner.prepare_prompts(case, Tokenizer(), 1024)
    assert len({tuple(result[c]["ids"]) for c in CONDITIONS if c != "base_inline"}) == 1
    for condition, prompt in result.items():
        assert "SECRET" not in prompt["rendered_prompt"]
        assert ("MEMORY" in prompt["rendered_prompt"]) == (condition == "base_inline")
    with pytest.raises(ValueError, match="no truncation"):
        runner.prepare_prompts(case, Tokenizer(), 2)


def test_case_validation_denominators_and_distinct_controls():
    cases = [
        {
            "id": f"case{index}",
            "lane": "relation" if index < 8 else "general",
            "user_prompt": "Q",
            "memory_text": "M",
            "twin_memory_text": "T",
            "unrelated_memory_text": "U",
            "reference": {},
            "rubric": [],
        }
        for index in range(16)
    ]
    assert runner.validate_cases({"cases": cases}) == cases
    cases[0]["twin_memory_text"] = "M"
    with pytest.raises(ValueError, match="distinct"):
        runner.validate_cases({"cases": cases})


def test_output_overwrite_is_rejected(tmp_path):
    path = tmp_path / "answer.json"
    runner.write_new(path, {"answer": "first"})
    with pytest.raises(FileExistsError):
        runner.write_new(path, {"answer": "second"})
    assert "first" in path.read_text()


def test_backend_zero_uses_actual_bridge_reader():
    class Bridge:
        def __init__(self):
            self.calls = []

        def read_delta(self, query, memory, mask):
            self.calls.append((query, memory, mask))
            return torch.zeros_like(query, dtype=torch.float32)

    bridge = Bridge()
    memory = torch.zeros(1, 2, 3)
    mask = torch.ones(1, 2)
    backend = runner.FrozenBackend(
        SimpleNamespace(lm_head=None),
        {"centered": bridge},
        {"centered": {"zero": (memory, mask)}},
        "cpu",
    )
    backend.delta("centered_zero", torch.ones(1, 5, 3))
    assert len(bridge.calls) == 1 and bridge.calls[0][1] is memory


def test_memory_encoder_only_reads_memory_and_zeros_written_state():
    seen = []

    class MemoryTokenizer:
        def encode(self, text, add_special_tokens):
            assert add_special_tokens is False
            seen.append(text)
            return [1, 2]

    class Boundary:
        def encode(self, ids, mask, layer):
            assert layer == 16 and ids.shape == mask.shape
            return torch.ones(1, 2, 3)

    class Bridge:
        def write_memory(self, context, mask):
            return context + 4, mask

    case = {
        "memory_text": "MEMORY",
        "twin_memory_text": "TWIN",
        "unrelated_memory_text": "UNRELATED",
        "user_prompt": "QUERY_NEVER_ENCODED_HERE",
        "reference": "SECRET",
        "rubric": "SECRET",
    }
    memories, receipt = runner.prepare_memories(
        case,
        MemoryTokenizer(),
        Boundary(),
        {"legacy": Bridge(), "centered": Bridge()},
        {"boundary_layer": 16, "max_memory_tokens": 1024},
        torch.device("cpu"),
    )
    assert seen == ["MEMORY", "TWIN", "UNRELATED"]
    assert all(entry["query_independent_encoding"] for entry in receipt.values())
    for family in memories:
        assert memories[family]["intact"][0].eq(5).all()
        assert memories[family]["zero"][0].eq(0).all()
        assert memories[family]["zero"][1] is memories[family]["intact"][1]


def test_native_ordinary_forward_gate_is_exact_not_tolerant():
    class Base:
        def __init__(self, shift):
            self.lm_head = nn.Identity()
            self.shift = shift

        def __call__(self, input_ids, attention_mask, use_cache, return_dict):
            assert not use_cache and return_dict
            return SimpleNamespace(logits=torch.ones(1, input_ids.shape[1], 3) + self.shift)

    class Backend:
        def __init__(self, shift):
            self.base = Base(shift)
            self.head = self.base.lm_head
            self.device = "cpu"

        def encode(self, prefix):
            return torch.ones(1, len(prefix), 3)

    assert runner.ordinary_base_gate(Backend(0), [1, 2])["full_logits_exact"]
    with pytest.raises(RuntimeError, match="differs"):
        runner.ordinary_base_gate(Backend(1e-5), [1, 2])
