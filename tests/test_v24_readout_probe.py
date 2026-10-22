"""Frozen finite scope, portable engine integration, and no old-source changes."""

import copy
import json
import os
from types import SimpleNamespace

import pytest
import run_v24_readout_probe as run
import torch
from test_latent_workspace_stack import host_model

from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash


def test_frozen_panel_and_scope():
    plan = run.ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    data = run.load_cases(plan)
    assert len(data["cases"]) == len({c["id"] for c in data["cases"]}) == 44
    assert data["forwards_per_arm"] == 197
    assert len(data["selected_world_groups"]) == 4
    assert sum(len(c["spec"]["continuation"]) for c in data["cases"]) == 197
    assert all(not c["memory_ids"] for c in data["cases"] if c["family"] != "world_content")
    for group in data["selected_world_groups"]:
        for ref in (0, 1):
            triple = [c for c in data["cases"] if c["id"].startswith(f"{group}/ref{ref}/")]
            assert len(triple) == 3 and all(c["spec"] == triple[0]["spec"] for c in triple)
            assert {c["id"].rsplit("/", 1)[-1] for c in triple} == {"s0", "s1", "empty"}
    assert any("copy" in c["spec"]["stages"] for c in data["cases"])
    assert any("format" in c["spec"]["stages"] for c in data["cases"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["base"]),
        ("new_sequences", 1),
        ("native_weight_updates", 1),
        ("full_ft_dispatch", True),
        ("cases_sha256", "0" * 64),
        ("cases_per_arm", 43),
        ("forwards_per_arm", 196),
    ],
)
def test_changed_scope_or_denominator_is_rejected(field, value):
    plan = copy.deepcopy(run.ex.read(run.ROOT / run.PLAN))
    plan[field] = value
    with pytest.raises(ValueError):
        run.validate(plan)


def test_entire_readout_role_uses_native_engine_without_changes(tmp_path, monkeypatch):
    before_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        graph = (
            NativeMemoryCausalLM(host_model("mistral"), cut=1)
            .to(os.environ.get("LTWS_TEST_DEVICE", "cpu"))
            .eval()
        )
        before = tree_hash(graph.model.state_dict())
        spec = run.audit.ReadoutSpec((1, 8), (7, 2), ("content", "stop"), 2)
        data = dict(
            cases=[dict(id="mock", family="mock", spec=spec.record(), memory_ids=[])],
            forwards_per_arm=2,
        )
        phases = []
        monkeypatch.setattr(run, "load_cases", lambda _: data)
        monkeypatch.setattr(run, "make_cases", lambda *a: data)
        monkeypatch.setattr(run.previous.common, "engine_imports", lambda _: {})
        monkeypatch.setattr(
            run.previous, "prepare", lambda *a: (graph, None, phases.append, before)
        )
        output = run.run(None, SimpleNamespace(output=tmp_path, role="base"), {}, {})
        assert output["native_forward_calls"] == 2 and output["new_sequences"] == 0
        assert output["native_weight_updates"] == output["checkpoint_saves"] == 0
        assert phases == ["generation:readout:mock:readout:0", "generation:readout:mock:readout:1"]
        rows = [json.loads(s) for s in (tmp_path / "READOUT.jsonl").read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["trace"]["native_forward_calls"] == 2
        assert tree_hash(graph.model.state_dict()) == before
    finally:
        torch.set_num_threads(before_threads)


def test_prior_input_sources_still_replay():
    for folder in (run.MMLU, run.WORLDS):
        data, origin = run.prior_inputs(folder)
        assert data["plan_sha256"] and origin["manifest_sha256"]
