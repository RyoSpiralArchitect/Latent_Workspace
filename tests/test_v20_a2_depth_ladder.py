"""Tiny harness for V20 A2, the depth ladder (not a real-model receipt)."""

import copy
import os
from argparse import Namespace

import pytest
import torch
from test_v15_full_update import tiny

from latent_workspace import DecoderHost, availability
from scripts import run_v16_adapter_migration as core
from scripts import run_v20_a2_depth_ladder as run

DEVICE = os.environ.get("LATENT_V20_TEST_DEVICE", "cpu")
PLAN = run.ex.read(run.ROOT / run.PLAN)
RULE = dict(
    chance_control="random_pair",
    sign_test_alpha=0.05,
    minimum_actual_flips=3,
    minimum_flip_margin_over_random=2,
)


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def tiny_plan():
    plan = copy.deepcopy(PLAN)
    plan["route"].update(hidden_dim=16, vocab_size=43, workspace_dim=8, attention_heads=2, rank=4)
    plan["candidate_ids"] = [6, 7]
    plan["training"].update(updates=6, batch_size=8, threads=2)
    plan["checkpoint_steps"] = [3]
    plan["replay"].update(from_step=3, execute_step=4)
    plan["parity_every"] = 1
    plan["endpoints"]["rule"] = RULE
    return plan


def test_plan_hash_and_semantics():
    run.validate_plan(PLAN)
    changed = copy.deepcopy(PLAN)
    changed["cuts"] = [0, 4, 8]
    with pytest.raises(ValueError, match="plan"):
        run.validate_plan(changed)
    assert run.ROLES[:4] == tuple(f"extract_cut{k}" for k in run.CUTS)
    assert len(run.ARM_ROLES) == 12 and run.ROLES[-2:] == ("replay", "endpoints")
    assert run.parse_role(PLAN, "route_cut8_s2") == (8, PLAN["seeds"][1])


def fake_old(calls):
    old = core.legacy.old

    def render_case(_tokenizer, *, query, context, renderer, cue, information):
        calls.append((renderer, cue, information))
        return dict(
            prompt_ids=[1, 2 + len(query) % 7, 3], candidate_ids=list(PLAN["candidate_ids"])
        )

    class Old:
        canonical_facts = staticmethod(old.canonical_facts)
        prior = old.prior

    Old.render_case = staticmethod(render_case)
    return Old


class FakeTokenizer:
    @staticmethod
    def encode(text, add_special_tokens):
        assert add_special_tokens is False
        return [3 + len(line) % 31 for line in text.splitlines()]


def test_rows_render_like_v15_live_store():
    calls = []
    old = fake_old(calls)
    records = run.v19().load_records(PLAN)["dev"][:3]
    questions, memories = run.render(old, FakeTokenizer, records, PLAN)
    assert len(questions) == 24 and len(memories) == 15
    assert {c for c in calls} == {("native_chat", "present", "query_only")}
    assert [q["labels"] for q in questions[:8]] == [
        [records[0]["answers"][0][q], records[0]["answers"][1][q]] for q in range(8)
    ]
    assert [m["key"] for m in memories[:5]] == [name for name, _ in run.MEMORY_KEYS]
    canonical = core.legacy.old.canonical_facts
    assert memories[0]["ids"] == FakeTokenizer.encode(canonical(records[0]["contexts"][0]), False)
    assert memories[3]["ids"] == FakeTokenizer.encode(
        canonical(records[0]["contexts"][1], reverse=True), False
    )
    train = run.split_rows(questions, "train")
    assert train[:9] == [(q, "intact", 0) for q in range(8)] + [(0, "twin", 1)]
    final = run.split_rows(questions, "final")
    assert len(final) == 24 * len(run.CONDITIONS) and final[24] == (0, "twin", 1)


def tiny_rows(worlds=2):
    generator = torch.Generator().manual_seed(4)
    questions, memories = [], []
    for w in range(worlds):
        for q in range(2):
            labels = [q % 2, 1 - q % 2] if q == 0 else [1, 1]
            ids = torch.randint(1, 43, (4 + q,), generator=generator).tolist()
            questions.append(
                dict(
                    world=w,
                    query=q,
                    labels=labels,
                    affected=labels[0] != labels[1],
                    hop=1,
                    wording="ranked_above",
                    prompt_ids=ids,
                )
            )
        for name, _ in run.MEMORY_KEYS:
            memories.append(
                dict(
                    world=w, key=name, ids=torch.randint(1, 43, (5,), generator=generator).tolist()
                )
            )
    return questions, memories


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("cut", [0, 1])
def test_extraction_writes_memory_at_each_cut(cut, dtype):
    base, _, _ = tiny(dtype)
    base.to(DEVICE).eval().requires_grad_(False)
    host = DecoderHost(base)
    questions, memories = tiny_rows()
    plan = tiny_plan()
    with torch.no_grad():
        tensors, meta, checked = run.extract_split(
            torch, host, cut, questions, memories, plan, "final", lambda _p: None
        )
    assert len(meta) == len(questions) * len(run.CONDITIONS) == checked
    assert tensors["offsets"][-1] == tensors["question_states"].shape[0]
    for n, row in enumerate(meta):
        question = questions[row["question"]]
        start, end = tensors["offsets"][n : n + 2].tolist()
        assert end - start == len(question["prompt_ids"])
        if row["condition"] == "none":
            ids = torch.tensor([question["prompt_ids"]], device=DEVICE)
            with torch.no_grad():
                native = host.final_states(ids, torch.ones_like(ids))[0].cpu()
            assert torch.equal(tensors["question_states"][start:end], native)
            assert row["memory_length"] == 0
    with torch.no_grad():
        again, _, _ = run.extract_split(
            torch, host, cut, questions, memories, plan, "final", lambda _p: None
        )
    assert all(torch.equal(again[k], tensors[k]) for k in tensors)
    train_tensors, train_meta, _ = run.extract_split(
        torch, host, cut, questions, memories, plan, "train", lambda _p: None
    )
    assert [m["condition"] for m in train_meta] == ["intact", "intact", "twin", "twin"] * 2


def test_random_memory_is_norm_matched_and_fixed():
    states = [torch.randn(5, 16) for _ in range(2 * len(run.MEMORY_KEYS))]
    a = run.random_memories(torch, states, [0, 1], 470016)
    b = run.random_memories(torch, states, [0, 1], 470016)
    assert all(torch.equal(a[k], b[k]) for k in a)
    assert torch.allclose(a[1, 1].norm(), states[len(run.MEMORY_KEYS) + 1].norm())
    generator = torch.Generator().manual_seed(470016)
    expected = availability.norm_matched_random(
        states[0][None], torch.ones(1, 5, dtype=torch.long), generator
    )
    assert torch.equal(a[0, 0], expected[0])


def write_extract(folder, plan, worlds=6, hidden=16, seed=0, pattern=None):
    """Synthetic extraction receipts in the runner's layout, 8 questions per world (two
    affected, as in the data); ``pattern`` plants host scores."""
    from safetensors.torch import save_file

    folder.mkdir(parents=True)
    generator = torch.Generator().manual_seed(seed)
    questions = []
    for w in range(worlds):
        flip = w % 2
        for q in range(8):
            labels = [flip, 1 - flip] if q == 0 else [1 - flip, flip] if q == 1 else [q % 2] * 2
            questions.append(
                dict(
                    world=w,
                    query=q,
                    labels=labels,
                    affected=q < 2,
                    hop=1 if q < 2 else 3,
                    wording="ranked_above",
                    prompt_ids=[1, 2, 3],
                )
            )
    for split in run.SPLITS:
        rows = run.split_rows(questions, split)
        meta, scores = [], []
        for index, condition, side in rows:
            q = questions[index]
            meta.append(
                dict(
                    question=index,
                    world=q["world"],
                    query=q["query"],
                    condition=condition,
                    side=side,
                    label=q["labels"][side],
                    labels=q["labels"],
                    affected=q["affected"],
                    hop=q["hop"],
                    wording=q["wording"],
                    memory_length=0 if condition == "none" else 5,
                )
            )
            scores.append(planted_score(q, condition, side, pattern) if pattern else [0.0, 0.0])
        lengths = torch.full((len(rows),), 3)
        offsets = torch.cat([torch.zeros(1, dtype=torch.long), lengths.cumsum(0)])
        save_file(
            {
                "question_states": torch.randn(int(offsets[-1]), hidden, generator=generator).to(
                    torch.bfloat16
                ),
                "offsets": offsets,
                "host_logits": torch.tensor(scores, dtype=torch.float32),
            },
            str(folder / f"FEATURES_{split}.safetensors"),
        )
        run.ex.write_gz(folder / f"ROWS_{split}.json.gz", meta)
        run.ex.write_gz(folder / f"HOST_SCORES_{split}.json.gz", scores)
    run.ex.write_gz(folder / "QUESTIONS_final.json.gz", questions)
    run.ex.write_new(folder / "FINISHED.json", dict(status=run.EXTRACT_PASS))
    return questions


def planted_score(question, condition, side, pattern):
    """content: right on every real memory; directional: donor-directed but never flipped;
    blind: the same scores whatever the memory."""
    if pattern == "blind" or condition in ("none", "unrelated"):
        return [0.0, 0.5]
    if condition.startswith("random_"):
        return [0.0, 0.3]
    sign = 2 * question["labels"][side] - 1
    if pattern == "content":
        return [0.0, float(sign)]
    intact = 2 * question["labels"][0] - 1
    return [0.0, float(intact) * (2.0 if side == 0 else 1.0)]


def role_args(tmp_path, role):
    raw = tmp_path / "raw"
    return Namespace(
        role=role,
        output=raw / role,
        checkpoints=tmp_path / "checkpoints",
        seal=None,
        qualification=None,
    )


def test_route_role_trains_both_arms_and_replays_exactly(tmp_path):
    plan = tiny_plan()
    write_extract(tmp_path / "raw" / "extract_cut4", plan)
    args = role_args(tmp_path, "route_cut4_s1")
    args.output.mkdir(parents=True)
    run.ex.write_new(args.output / "STARTED.json", dict(pid=1))
    outcome = run.train_arms(torch, args, plan)
    assert set(outcome["arms"]) == {"route", "readout"}
    for arm in run.ARMS:
        for split, step in (("final", 0), ("final", 6), ("train", 6)):
            assert (args.output / f"eval_{arm}_{split}_step{step}.json.gz").exists()
    assert (args.output / "CHECKPOINT_route_step3.json").exists()
    assert not (args.output / "CHECKPOINT_readout_step3.json").exists()
    replay = role_args(tmp_path, "replay")
    replay.output.mkdir(parents=True)
    report = run.replay_run(torch, replay, plan)
    assert report["exact"] and report["execute_step"] == 4


def write_arms(raw, cut, questions, pattern, steps=6):
    meta = run.ex.read_gz(raw / f"extract_cut{cut}" / "ROWS_final.json.gz")
    for index in range(1, run.SEEDS + 1):
        folder = raw / f"route_cut{cut}_s{index}"
        folder.mkdir(parents=True)
        scores = [
            planted_score(questions[m["question"]], m["condition"], m["side"], pattern)
            for m in meta
        ]
        for arm in run.ARMS:
            run.ex.write_gz(
                folder / f"eval_{arm}_final_step{steps}.json.gz", {"adapted_logits": scores}
            )


def test_endpoints_read_each_cut_and_the_read_depth(tmp_path):
    plan = tiny_plan()
    raw = tmp_path / "raw"
    patterns = {0: "content", 4: "directional", 8: "blind", 16: "blind"}
    for cut, pattern in patterns.items():
        questions = write_extract(raw / f"extract_cut{cut}", plan, pattern=pattern)
        write_arms(raw, cut, questions, pattern)
    result = run.endpoints_for(raw, plan)
    outcome = run.outcome_of(result)
    assert outcome["host"] == {
        "0": "CONTENT_REACHES_ANSWERS",
        "4": "DIRECTIONAL_ONLY",
        "8": "NOT_ESTABLISHED",
        "16": "NOT_ESTABLISHED",
    }
    assert outcome["route"] == outcome["host"]
    assert outcome["read_depth_host"] == outcome["read_depth_route"] == 4
    assert result["ladder"]["0"]["host"]["accuracy"]["intact"] == 1.0
    assert run.read_depth(run.CUTS, ["NOT_ESTABLISHED"] * 4) is None


def test_offline_verifier_accepts_what_the_runner_writes(tmp_path):
    from scripts import verify_v20_a2_depth_ladder as verifier

    plan = tiny_plan()
    worlds = 6
    for split in run.SPLITS:
        plan["data"][split]["world_pairs"] = worlds
    raw = tmp_path / "raw"
    patterns = {0: "content", 4: "directional", 8: "blind", 16: "blind"}
    for cut, pattern in patterns.items():
        questions = write_extract(raw / f"extract_cut{cut}", plan, worlds=worlds, pattern=pattern)
        write_arms(raw, cut, questions, pattern)
        host = run.ex.read_gz(raw / f"extract_cut{cut}" / "HOST_SCORES_final.json.gz")
        for index in range(1, run.SEEDS + 1):
            for arm in run.ARMS:
                path = raw / f"route_cut{cut}_s{index}" / f"eval_{arm}_final_step0.json.gz"
                run.ex.write_gz(path, {"adapted_logits": host})
    source = raw / "route_cut4_s1"
    run.ex.write_new(source / "FINGERPRINTS.json", {"route": {"3": "a", "4": "b"}, "readout": {}})
    run.ex.write_new(source / "CHECKPOINT_route_step3.json", {"fingerprint": "a"})
    (raw / "replay").mkdir()
    update = {"step": 4, "task_loss": 0.5}
    run.ex.write_new(
        raw / "replay" / "REPLAY.json",
        dict(
            exact=True,
            role="route_cut4_s1",
            replayed_fingerprint="b",
            restored_fingerprint="a",
            update=update,
            original_update=update,
        ),
    )
    (raw / "endpoints").mkdir()
    result = run.endpoints_for(raw, plan)
    run.ex.write_new(raw / "endpoints" / "ENDPOINTS.json", result)
    roles = {"endpoints": ({}, {"outcome": run.outcome_of(result)}, True)}
    verified = verifier.verify_results(raw, plan, roles)
    assert verified["verdicts"]["read_depth_host"] == 4
    scores = raw / "extract_cut8" / "HOST_SCORES_final.json.gz"
    tampered = run.ex.read_gz(scores)
    tampered[0] = [0.0, -0.5]
    scores.unlink()
    run.ex.write_gz(scores, tampered)
    with pytest.raises(ValueError, match="step 0"):
        verifier.verify_results(raw, plan, roles)
