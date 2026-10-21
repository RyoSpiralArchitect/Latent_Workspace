import importlib.util
from pathlib import Path

import pytest
import torch
from test_objective_audit import fixture

from latent_workspace import execution as ex

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v23_gradient_runner", ROOT / "scripts/run_v23_gradient_audit.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_actual_canary_orchestration_before_7b(dtype, tmp_path):
    graph, data, parts = fixture("mistral", dtype)
    row = dict(
        key="tiny",
        input_ids=data["input_ids"][0].tolist(),
        memory_ids=data["memory_ids"][0].tolist(),
        labels=data["labels"][0].tolist(),
        parts=parts[0].tolist(),
    )
    result = runner.canary(graph, row, tmp_path, lambda *a: None, ex.read(ROOT / runner.PLAN))
    assert result["pass_count"] == result["parameter_count"] > 0
    assert result["full"]["backwards"] == 1 and result["paths"]["backwards"] == 3
    assert all(p.grad is None for p in graph.parameters())


def test_causal_kl_target_layout_and_component_objective():
    graph, data, parts = fixture()
    row = dict(
        input_ids=data["input_ids"][0].tolist(),
        memory_ids=data["memory_ids"][0].tolist(),
        labels=data["labels"][0].tolist(),
        parts=parts[0].tolist(),
    )
    data = runner.batch(row, next(graph.parameters()).device)
    out = graph(**data)
    active = data["labels"][:, 1:] != -100
    target = out.logits[:, :-1][active].detach().float().log_softmax(-1).cpu()
    assert runner.objective(out, row, "kl", 20, target) == 0
    assert torch.equal(runner.objective(out, row, "ce", 20), out.loss_sum / 20)
    parts = sum(
        runner.objective(out, row, part, 20) for part in ("identity", "copy", "format", "mixed")
    )
    torch.testing.assert_close(parts, runner.objective(out, row, "total", 20))


@pytest.mark.parametrize(
    "field,value",
    [("vocabulary", 10), ("teacher_target_dtype", "bfloat16"), ("teacher_temperature", 2.0)],
)
def test_teacher_contract_cannot_drift(field, value):
    plan = ex.read(ROOT / runner.PLAN)
    runner.validate(plan)
    plan[field] = value
    with pytest.raises(ValueError, match="Frozen full-vocabulary"):
        runner.validate(plan)
