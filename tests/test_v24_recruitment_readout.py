"""Frozen readout boundaries, actual tiny native inference, and receipt replay."""

import copy
import json
import os
from types import SimpleNamespace

import pytest
import run_v24_recruitment_readout as run
import torch
from test_latent_workspace_stack import host_model
from test_recruitment_readout import Tokenizer

from latent_workspace.native_memory import NativeMemoryCausalLM
from latent_workspace.optimizer_state import tree_hash


def test_frozen_protocol():
    plan = run.ex.read(run.ROOT / run.PLAN)
    run.validate(plan)
    data = run.load_inputs(plan)
    assert data["fixed_forwards_per_arm"] == 2320
    assert len(data["cases"]) == len({c["id"] for c in data["cases"]}) == 72
    assert data["selection"]["confirmation_rows"] == 0
    assert len(data["selection"]["excluded_exposed_groups"]) == 3
    assert all("dev" in g for g in data["selection"]["selected_groups"])
    frozen = run.frozen_training(plan)
    for role in ("inline", "workspace"):
        receipt = frozen["roles"][role][f"CHECKPOINT_{role}_step32.pt.json"]
        assert receipt["completed_steps"] == 32 and receipt["bytes"] == 29004413900


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["base"]),
        ("runtime_routes", ["workspace"]),
        ("groups_per_family", 3),
        ("selection_seed", "changed"),
        ("planned_new_sequences", 217),
        ("native_weight_updates", 1),
        ("checkpoint_saves", 1),
        ("judge_calls", 1),
        ("weight_deletions", 1),
        ("no_retry", False),
        ("inputs_sha256", "0" * 64),
        ("training_receipts_sha256", "0" * 64),
        ("fixed_forwards_per_arm", 2321),
    ],
)
def test_changed_scope_rejected(field, value):
    plan = copy.deepcopy(run.ex.read(run.ROOT / run.PLAN))
    plan[field] = value
    with pytest.raises(ValueError):
        run.validate(plan)


class Decoder(Tokenizer):
    def decode(self, ids, **kwargs):
        assert kwargs == dict(skip_special_tokens=False, clean_up_tokenization_spaces=False)
        return "".join("</s>" if t == 2 else "x" for t in ids)


@pytest.mark.parametrize("stop,ids", [("eos", [7, 2]), ("length", [7, 8, 9])])
def test_eos_only_removed_and_invalid_json_not_dropped(stop, ids):
    policy = dict(seed=8, max_new_tokens=3, temperature=0.0, top_p=1.0)
    result = dict(token_ids=ids, generated_tokens=len(ids), stop_reason=stop, **policy)
    item = run.score_result(Decoder(), result, dict(answer=7), policy)
    assert item["score"]["parsed"] is False and item["score"]["exact"] is False
    assert "</s>" not in item["scoring_text"]
    assert item["terminal_eos_only_removed"] == (stop == "eos")
    assert item["raw_decoded"].endswith("</s>") == (stop == "eos")


@pytest.mark.parametrize("damage", ["seed", "length", "missing_eos", "early_eos", "cap"])
def test_incomplete_or_changed_generation_receipt_rejected(damage):
    policy = dict(seed=8, max_new_tokens=3, temperature=0.0, top_p=1.0)
    result = dict(token_ids=[7, 2], generated_tokens=2, stop_reason="eos", **policy)
    if damage == "seed":
        result["seed"] = 9
    elif damage == "length":
        result["generated_tokens"] = 3
    elif damage == "missing_eos":
        result["token_ids"][-1] = 8
    elif damage == "early_eos":
        result["token_ids"][0] = 2
    else:
        result["stop_reason"] = "length"
    with pytest.raises(ValueError):
        run.score_result(Decoder(), result, dict(answer=7), policy)


def test_complete_native_role_does_not_assist_generation_or_update_weights(tmp_path, monkeypatch):
    threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        graph = (
            NativeMemoryCausalLM(host_model("mistral"), cut=1)
            .to(os.environ.get("LTWS_TEST_DEVICE", "cpu"))
            .eval()
        )
        before = tree_hash(graph.model.state_dict())
        tok = Decoder()
        ref = dict(
            id="own_answer_first", **run.meter.reference(tok, dict(answer=7), "answer_first")
        )
        case = dict(
            id="mock", prefix_ids=[1, 7], memory_ids=[8], references=[ref], expected=dict(answer=7)
        )
        data = dict(
            cases=[case],
            generations_per_arm=1,
            references_per_arm=1,
            fixed_forwards_per_arm=len(ref["token_ids"]),
        )
        phases, observed = [], []
        native_generate = run.ev.generate

        def generate(graph, prefix, memory, **policy):
            observed.append((list(prefix), list(memory)))
            return native_generate(graph, prefix, memory, **policy)

        monkeypatch.setattr(run.ev, "generate", generate)
        monkeypatch.setattr(run, "load_inputs", lambda _: data)
        monkeypatch.setattr(run, "make_inputs", lambda *a: data)
        monkeypatch.setattr(run.common, "engine_imports", lambda _: {})
        monkeypatch.setattr(run, "prepare", lambda *a: (graph, tok, phases.append, before))
        policy = dict(seed=8, max_new_tokens=3, temperature=0.0, top_p=1.0)
        out = run.run(
            None, SimpleNamespace(output=tmp_path, role="base"), {"generation": policy}, {}
        )
        assert observed == [([1, 7], [8])]
        assert out["native_weight_updates"] == out["checkpoint_saves"] == 0
        assert out["new_sequences"] == out["reference_traces"] == 1
        assert out["native_forward_calls"] == len(phases)
        assert tree_hash(graph.model.state_dict()) == before
        free = [json.loads(s) for s in (tmp_path / "GENERATIONS.jsonl").read_text().splitlines()]
        assert len(free) == 1 and free[0]["id"] == "mock"
        assert free[0]["score"]["reference_assistance"] is False
        import analyze_v24_recruitment_readout as analysis

        arms = analysis.replay_rows(tmp_path, data, {"generation": policy}, tok)
        assert len(arms["fixed"]) == len(arms["free"]) == 1
        # Closed metrics must be recomputed, not blindly read from the journal.
        free[0]["score"]["exact"] = not free[0]["score"]["exact"]
        (tmp_path / "GENERATIONS.jsonl").write_text(json.dumps(free[0]) + "\n")
        with pytest.raises(ValueError, match="strict score replay"):
            analysis.replay_rows(tmp_path, data, {"generation": policy}, tok)
    finally:
        torch.set_num_threads(threads)


def test_failure_activity_is_unknown_not_zero():
    result = {}
    run.RUN.activity(result)
    assert result["new_sequences"] is None and result["native_forward_calls"] is None


def test_old_engine_and_data_implementations_unchanged():
    seal = run.frozen_training(run.ex.read(run.ROOT / run.PLAN))["SOURCE_SEAL.json"]
    for name in (
        "src/latent_workspace/native_memory.py",
        "src/latent_workspace/native_owner.py",
        "src/latent_workspace/native_evaluation.py",
        "src/latent_workspace/readout_audit.py",
        "src/latent_workspace/recruitment_bank.py",
        "scripts/run_v22_comparison.py",
        "scripts/run_v23_comparison.py",
        "scripts/v23_generation_cache.py",
    ):
        assert run.ex.digest(run.ROOT / name) == seal["source_hashes"][name]


def test_analysis_keeps_invalid_capped_and_inapplicable_denominators():
    import analyze_v24_recruitment_readout as analysis

    records = []
    for text, expected, stop in (
        ('{"answer":4,"steps":[4]}', dict(answer=4, steps=[4]), "eos"),
        ('{"answer":null}', dict(answer=None), "eos"),
        ('{"answer":', dict(answer=4, steps=[4]), "length"),
    ):
        records.append(
            dict(
                score=run.meter.score_generation(text, expected),
                generation=dict(stop_reason=stop, generated_tokens=5),
            )
        )
    assert analysis.count_generation(records) == dict(
        rows=3,
        parsed=2,
        correct_answer=2,
        steps_applicable=2,
        correct_steps=1,
        exact=2,
        eos=2,
        length_capped=1,
        generated_tokens=15,
    )


def test_paired_repairs_do_not_hide_losses_or_count_inapplicable_steps():
    import analyze_v24_recruitment_readout as analysis

    def row(text, expected, ids):
        return dict(
            score=run.meter.score_generation(text, expected), generation=dict(token_ids=ids)
        )

    left = dict(
        a=row("bad", dict(answer=4, steps=[4]), [1]),
        b=row('{"answer":null}', dict(answer=None), [2]),
    )
    right = dict(
        a=row('{"answer":4,"steps":[4]}', dict(answer=4, steps=[4]), [3]),
        b=row("bad", dict(answer=None), [4]),
    )
    value = analysis.contrast(left, right, ["a", "b"])
    assert value["metrics"]["exact"] == dict(rows=2, repaired=["a"], lost=["b"])
    assert value["metrics"]["steps_correct"] == dict(rows=1, repaired=["a"], lost=[])
    assert value["changed_tokens"] == ["a", "b"]


@pytest.mark.parametrize("damage", ["missing", "bytes", "ceiling", "activity"])
def test_missing_or_changed_closed_receipt_rejected(tmp_path, damage):
    import analyze_v24_recruitment_readout as analysis

    run.ex.write_new(tmp_path / "STARTED.json", dict(test=True))
    terminal = dict(status="complete", files=run.ex.manifest(tmp_path), **run.ex.CEILING)
    if damage == "ceiling":
        terminal["winner"] = "workspace"
    elif damage == "activity":
        terminal["new_sequences"] = None
    if damage != "missing":
        run.ex.write_new(tmp_path / "FINISHED.json", terminal)
    if damage == "bytes":
        (tmp_path / "STARTED.json").write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        analysis.terminal(tmp_path, "complete", 0)
