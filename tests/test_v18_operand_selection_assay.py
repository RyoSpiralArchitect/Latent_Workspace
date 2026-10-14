from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    old = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(old)


def test_population_counts_split_independence_and_question_no_rank_input():
    a, same, other = assay.population(1103, 2), assay.population(1103, 2), assay.population(2207, 2)
    assert len(a.labels) == 72
    assert torch.equal(a.inputs.memory, same.inputs.memory)
    assert not torch.equal(a.inputs.memory, other.inputs.memory)
    assert (a.labels != a.twin_labels).sum() == 24
    assert torch.equal(a.inputs.states, a.twin.states)
    assert torch.equal(a.inputs.states[:6], a.inputs.states[6:12])
    identities = a.inputs.memory[0, :, :8]
    assert torch.allclose(identities @ identities.T, torch.eye(3), atol=1e-6)
    assert torch.allclose(identities.sum(-1), torch.zeros(3), atol=1e-6)
    assert a.labels.sum() == len(a.labels) // 2


def test_query_controls_preserve_ordered_information_in_final():
    pop = assay.population(1103, 1)
    states = pop.inputs.states
    ordered = assay.query(states, "centered_ordered")
    symmetric = assay.query(states, "centered_symmetric")
    final = assay.query(states, "centered_final")
    assert torch.equal(ordered[0], -ordered[2])
    assert torch.equal(symmetric[0], symmetric[2])
    assert not torch.equal(final[0], final[2])
    assert torch.equal(final[0, 0, :8], states[0, 0, :8])
    assert torch.equal(final[0, 0, 8:16], states[0, 1, :8])


def test_factors_share_initial_parameters_common_zero_and_one_step_only():
    plan = assay.load_plan()
    pop = assay.population(1103, 1)
    reference = assay.make_reader(17, "centered_final")
    for factor in assay.FACTORS:
        bridge = assay.make_reader(17, factor)
        assert all(
            torch.equal(v, reference.state_dict()[k]) for k, v in bridge.state_dict().items()
        )
        before = {k: v.clone() for k, v in bridge.common.state_dict().items()}
        logits, delta = assay.forward(bridge, pop.inputs, factor)
        assert delta.eq(0).all()
        assert torch.equal(logits[:, 0], logits[:, 1])
        loss = assay.update(
            bridge, pop.inputs, pop.labels, factor, assay.optimizer_for(bridge, plan), plan
        )
        assert loss > 0
        assert all(torch.equal(v, before[k]) for k, v in bridge.common.state_dict().items())
        assert not bridge.up.weight.eq(0).all()


def test_native_readout_uses_full_vocab_and_does_not_mutate_input():
    pop = assay.population(1103, 1)
    states = pop.inputs.states.bfloat16()
    original = states.clone()
    delta = torch.zeros(len(states), 1, 32)
    delta[:, :, 30] = 0.125
    logits = assay.full_vocab_head(states, delta)
    assert logits.shape == (36, 7)
    assert torch.equal(states, original)
    assert logits[:, 0].eq(1).all() and logits[:, 1].eq(-1).all()
    assert logits[:, 2:].eq(-4).all()


def oracle_reader():
    """Construction witness only; never used to initialize a study fit."""
    bridge = assay.make_reader(17, "centered_ordered")
    with torch.no_grad():
        bridge.query_projection.weight.zero_()
        bridge.query_projection.weight[:8, :8] = torch.eye(8)
        bridge.attention.in_proj_weight.zero_()
        for head, sign in ((0, 1), (1, -1)):
            begin = head * 16
            bridge.attention.in_proj_weight[begin : begin + 8, :8] = sign * torch.eye(8)
            bridge.attention.in_proj_weight[32 + begin : 32 + begin + 8, :8] = torch.eye(8)
            bridge.attention.in_proj_weight[64 + begin, 16:19] = torch.tensor([-1.0, 0.0, 1.0])
        bridge.attention.out_proj.weight.copy_(torch.eye(32))
        bridge.up.weight.zero_()
        bridge.up.weight[30, 0], bridge.up.weight[30, 16] = 1, -1
    return bridge


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_actual_reader_two_head_oracle_capacity_and_controls(dtype):
    pop = assay.population(9109, 2)
    bridge = oracle_reader()
    with torch.no_grad():
        logits, _ = assay.forward(bridge, pop.inputs, "centered_ordered", native_dtype=dtype)
        twin, _ = assay.forward(bridge, pop.twin, "centered_ordered", native_dtype=dtype)
    metrics = assay.summarize(logits, twin, pop)
    assert metrics["strict_native_accuracy"] == 1
    assert metrics["reciprocal_both_correct_rate"] == 1
    assert metrics["affected_donor_flip_rate"] == 1
    assert metrics["unaffected_prediction_agreement"] == 1
    result = assay.controls(bridge, "centered_ordered", pop, "cpu", lambda: None, 1e-6)
    assert result["pass"]


def test_source_guard_rejects_nonmatching_commit():
    with pytest.raises(ValueError, match="Exact frozen source"):
        assay.source_receipt("0" * 40)


def test_gate_cannot_upgrade_negative_or_one_seed_failure():
    plan = assay.load_plan()
    metrics = {
        "strict_native_accuracy": 1,
        "reciprocal_both_correct_rate": 1,
        "affected_donor_flip_rate": 1,
        "unaffected_strict_accuracy": 1,
        "unaffected_prediction_agreement": 1,
    }
    results = {}
    for seed in plan["model_seeds"]:
        results[f"{seed}:centered_ordered"] = {
            "held_out_float32": dict(metrics),
            "controls": {"pass": True},
        }
        results[f"{seed}:centered_final"] = {"held_out_float32": dict(metrics)}
    value = assay.gates(results, plan)
    assert value["toy_learnable_all_seeds"]
    assert not value["selection_advantage_all_seeds"]
    results["43:centered_ordered"]["controls"]["pass"] = False
    assert not assay.gates(results, plan)["toy_learnable_all_seeds"]
    assert value["old_scientific_gate"] == "FAIL" and value["winner"] == "none"


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("training", "updates", 255),
        ("gates", "strict_native_accuracy_min", 0.5),
        (None, "native_answer_head_scale", 9.0),
    ],
)
def test_plan_rejects_any_frozen_field_change(tmp_path, monkeypatch, section, key, value):
    plan = assay.load_plan()
    (plan if section is None else plan[section])[key] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(assay, "PLAN_PATH", path)
    with pytest.raises(ValueError, match="Exact frozen plan"):
        assay.load_plan()


def test_unisolated_execute_is_rejected_before_loading_seal(tmp_path):
    with pytest.raises(ValueError, match="run_source_sealed"):
        assay.sealed_guard(tmp_path / "does-not-exist.json")


def test_import_closure_uses_direct_metadata_and_rejects_escape(tmp_path):
    paths = {
        "assay_v18_operand_selection": assay.ENTRY,
        "latent_workspace_ft_v10.v18_selection_reader": (
            "src/latent_workspace_ft_v10/v18_selection_reader.py"
        ),
        "latent_workspace_ft_v10.precision_bridge": (
            "src/latent_workspace_ft_v10/precision_bridge.py"
        ),
    }
    seal = {
        "source_hashes": {
            relative: hashlib.sha256((assay.ROOT / relative).read_bytes()).hexdigest()
            for relative in paths.values()
        }
    }
    modules = {
        name: SimpleNamespace(__file__=str(assay.ROOT / relative))
        for name, relative in paths.items()
    }

    class VirtualNamespace:
        __file__ = "_ops.py"

        def __getattr__(self, name):
            raise AssertionError("Guard must not invoke dynamic module attributes")

    modules["torch.ops.qualification_example"] = VirtualNamespace()
    assert assay.imported_sources(seal, modules) == paths
    with pytest.raises(ValueError, match="Missing critical"):
        assay.imported_sources(seal, {})
    wrong_seal = {"source_hashes": dict(seal["source_hashes"])}
    wrong_seal["source_hashes"][assay.ENTRY] = "0" * 64
    with pytest.raises(ValueError, match="not sealed"):
        assay.imported_sources(wrong_seal, modules)
    modules["latent_workspace_ft_v10.escaped"] = SimpleNamespace(
        __file__=str(tmp_path / "escaped.py")
    )
    with pytest.raises(ValueError, match="escaped sealed source"):
        assay.imported_sources(seal, modules)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("elapsed_seconds", 901, TimeoutError),
        ("peak_rss_bytes", 4 * 1024**3 + 1, MemoryError),
        ("peak_cuda_allocated_bytes", 4 * 1024**3 + 1, MemoryError),
    ],
)
def test_resource_gates_fail_closed(monkeypatch, field, value, error):
    guard = assay.ResourceGuard(assay.load_plan(), "cpu")
    snapshot = {"elapsed_seconds": 1, "peak_rss_bytes": 1, "peak_cuda_allocated_bytes": 0}
    snapshot[field] = value
    monkeypatch.setattr(guard, "snapshot", lambda: snapshot)
    with pytest.raises(error):
        guard()


def test_exact_population_artifact_is_exclusive_and_replayable(tmp_path):
    pop = assay.population(9109, 1)
    manifest = assay.population_artifacts(tmp_path, {"witness": pop})
    payload = torch.load(tmp_path / "POPULATIONS.pt", weights_only=True)
    assert torch.equal(payload["witness"]["labels"], pop.labels)
    assert manifest["witness"]["tensors"]["states"] == assay.tensor_fingerprint(pop.inputs.states)
    with pytest.raises(FileExistsError):
        assay.population_artifacts(tmp_path, {"witness": pop})


def test_default_cli_is_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [assay.ENTRY])
    monkeypatch.setattr(assay, "run", lambda *args: pytest.fail("Dry run must not train"))
    assay.main()
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN_NO_TRAINING"
