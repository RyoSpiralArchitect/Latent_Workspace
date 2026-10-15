from __future__ import annotations

import copy
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_v15_native_learner as run  # noqa: E402
import verify_v15_native_learner as verify  # noqa: E402
from test_v15_full_update import SPAN  # noqa: E402
from test_v15_native_learner import OPT, owner  # noqa: E402


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


class Tokenizer:
    def encode(self, text, add_special_tokens=False):
        return [1, 8, 9] if "Galen" in text else [1, 9, 8]

    def get_vocab(self):
        return {"fake": 1}


def make_store(monkeypatch, learner):
    row = dict(prompt_ids=list(SPAN.prefix_ids), candidate_ids=[6, 7], span=asdict(SPAN))
    monkeypatch.setattr(run.old, "render_case", lambda *args, **kwargs: copy.deepcopy(row))
    records = run.old.validate()[2]
    return run.LiveStore(learner, Tokenizer(), records, lambda *args, **kwargs: None)


@pytest.mark.parametrize("full", [False, True])
def test_live_store_has_only_token_cache_and_preserves_zero_parity(monkeypatch, full):
    learner = owner(full=full)
    store = make_store(monkeypatch, learner)
    before = store.get(SPAN.prefix_ids).detach().clone()
    assert len(store.contexts) == 10 and len(store.renderings) == 16
    assert all(isinstance(v["ids"], tuple) for v in store.contexts.values())
    with torch.no_grad():
        learner.base.model.embed_tokens.weight[1, 0].add_(0.2)
    after = store.get(SPAN.prefix_ids)
    assert not torch.equal(before, after)
    store.encode(SPAN.prefix_ids)
    assert store.parity[-1]["full_logits_exact"]


@pytest.mark.parametrize("full", [False, True])
def test_complete_runner_window_and_query_hooks(monkeypatch, tmp_path, full):
    learner = owner(full=full)
    routes = run.backward.RouteGradients()
    learner.features.observer = routes.observe
    store = make_store(monkeypatch, learner)
    handle = learner.bridge.query_projection.register_forward_pre_hook(
        lambda _module, inputs: routes.observe("query_to_reader", inputs[0])
    )
    objective = run.old.validate()[0]
    outcome = run.update_window(
        learner, store, routes, objective, "tiny", 1, tmp_path, lambda *a: None
    )
    assert len(outcome["pairs"]) == 16
    for pair in outcome["pairs"]:
        selected = [r for r in pair["routes"] if r["route"] == "query_to_reader"]
        assert len(selected) == 5 and all(r["backward_calls"] == 1 for r in selected)
        assert pair["spill"]["current_gradient_count"] == len(learner.named)
        if full:
            assert len([r for r in pair["routes"] if r["route"] == "context_to_writer"]) == 3
    handle.remove()
    if not full:
        summary = verify.verify_update(outcome, arm="tiny", step=1, full=False, replay=False)
        assert summary["query_gradient_observations"] == 80
        for kind in ("missing", "reordered", "gradient_coverage", "weighted_loss", "step"):
            bad = copy.deepcopy(outcome)
            if kind == "missing":
                bad["pairs"].pop()
            elif kind == "reordered":
                bad["pairs"].reverse()
            elif kind == "gradient_coverage":
                bad["pairs"][0]["spill"]["current_gradient_count"] = 25
            elif kind == "weighted_loss":
                bad["pairs"][0]["components"]["loss"] += 1
            else:
                bad["step"] = 2
            with pytest.raises(ValueError):
                verify.verify_update(bad, arm="tiny", step=1, full=False, replay=False)


def test_prospective_plan_and_new_sources_present():
    plan, _, _, _ = run.validate()
    for key, value in OPT.items():
        assert plan["optimizer"][key] == value
    assert all((run.REPO / name).is_file() for name in run.ADDITIONS)


def test_seal_verifier_is_offline_and_streams_digest(tmp_path):
    file = tmp_path / "evidence.json"
    verify.write_new(file, {"value": "literal ", "missing": None})
    assert verify.read(file)["value"] == "literal "
    assert len(verify.digest(file)) == 64
    with pytest.raises(FileExistsError):
        verify.write_new(file, {})
    with pytest.raises(ValueError, match="Out of range"):
        run.old.write_new(tmp_path / "bad.json", {"value": float("inf")})
