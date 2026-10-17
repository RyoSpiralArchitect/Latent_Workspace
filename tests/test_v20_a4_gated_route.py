"""Tiny harness for V20 A4, the content-gated cut-4 route (not a real-model receipt)."""

import copy
import json
import os
import re
from argparse import Namespace

import pytest
import torch
from test_v15_full_update import tiny
from test_v20_a2_depth_ladder import RULE, planted_score, tiny_rows, write_extract
from test_v20_a2_depth_ladder import tiny_plan as ladder_plan

from latent_workspace import DecoderHost, composition
from scripts import run_v16_adapter_migration as core
from scripts import run_v20_a4_gated_route as run

LADDER = run.LADDER
DEVICE = os.environ.get("LATENT_V20_TEST_DEVICE", "cpu")
PLAN = run.ex.read(run.ROOT / run.PLAN)
UPDATES = 6


@pytest.fixture(autouse=True)
def setup():
    core.load_runtime()
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


def test_plan_hash_and_semantics():
    run.validate_plan(PLAN)
    changed = copy.deepcopy(PLAN)
    changed["gating"]["weight"] = 0.0
    with pytest.raises(ValueError, match="plan"):
        run.validate_plan(changed)
    assert run.ROLES[0] == "reproduce" and run.ROLES[-2:] == ("replay", "endpoints")
    assert run.seed_of(PLAN, "gated_s2") == PLAN["seeds"][1]
    assert PLAN["route"] == LADDER.ex.read(run.ROOT / LADDER.PLAN)["route"]


def test_mismatch_memory_never_names_both_entities():
    records = LADDER.v19().load_records(PLAN)["train"]
    run.check_entities(records)
    stride, count = PLAN["mismatch"]["stride"], len(records)
    steps = []
    for w, record in enumerate(records):
        for q, pair in enumerate(record["metadata"]["query_pairs"]):
            other, k = run.mismatch_world(records, w, q, stride)
            assert other == (w + stride * k) % count != w
            assert not set(pair) <= set(records[other]["metadata"]["orders"][0])
            assert all(
                set(pair) <= set(records[(w + stride * j) % count]["metadata"]["orders"][0])
                for j in range(1, k)
            )
            for context in records[other]["contexts"]:
                facts = core.legacy.old.canonical_facts(context)
                assert not all(re.search(rf"\b{name}\b", facts) for name in pair)
            steps.append(k)
    assert len(steps) == 2048 and steps.count(1) > 0.7 * len(steps)


NAMES = ["Ann", "Bo", "Cy", "Di", "Ed", "Flo", "Gus"]


def tiny_records(worlds=4, queries=2):
    """Records whose name sets overlap, so some mismatch memories need a second step."""
    records = []
    for w in range(worlds):
        names = [NAMES[(w + i) % len(NAMES)] for i in range(4)]
        pairs = [[names[(2 * q) % 4], names[(2 * q + 1) % 4]] for q in range(queries)]
        records.append(
            dict(
                queries=[f"Is {a} ranked above {b}? Answer:" for a, b in pairs],
                metadata=dict(query_pairs=pairs, orders=[names, names[::-1]]),
            )
        )
    return records


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_extraction_reads_each_row_with_its_mismatch_memory(dtype):
    base, _, _ = tiny(dtype)
    base.to(DEVICE).eval().requires_grad_(False)
    host = DecoderHost(base)
    questions, memories = tiny_rows(worlds=4)
    records = tiny_records()
    plan = copy.deepcopy(PLAN)
    plan.update(candidate_ids=[6, 7], parity_every=1)
    plan["mismatch"]["stride"] = 3
    with torch.no_grad():
        stored, _, _ = LADDER.extract_split(
            torch, host, 1, questions, memories, ladder_plan(), "train", lambda _p: None
        )
        tensors, meta, checked = run.extract_mismatch(
            torch, host, 1, records, questions, memories, stored, plan, lambda _p: None
        )
    assert checked == len(meta) == 16 and torch.equal(tensors["offsets"], stored["offsets"])
    assert {1, 2} <= {m["stride_steps"] for m in meta}
    prefix = composition.CutPrefixRoute(host, 1)
    keys = len(LADDER.MEMORY_KEYS)
    for n, row in enumerate(meta):
        assert row["mismatch_world"] != row["world"]
        pair = set(records[row["world"]]["metadata"]["query_pairs"][row["query"]])
        assert not pair <= set(records[row["mismatch_world"]]["metadata"]["orders"][0])
        query = torch.tensor([questions[row["question"]]["prompt_ids"]], device=DEVICE)
        memory = torch.tensor([memories[row["mismatch_world"] * keys + row["side"]]["ids"]])
        memory = memory.to(DEVICE)
        with torch.no_grad():
            states, logits, _ = prefix(
                host.to_cut(query, torch.ones_like(query), 1),
                torch.ones_like(query),
                host.to_cut(memory, torch.ones_like(memory), 1),
                torch.ones_like(memory),
            )
        start, end = tensors["offsets"][n : n + 2].tolist()
        assert torch.equal(
            tensors["question_states"][start:end], states[0, memory.shape[1] :].cpu()
        )
        assert torch.equal(tensors["host_logits"][n], logits[0, -1, [6, 7]].float().cpu())
    changed = dict(stored, host_logits=stored["host_logits"] + 1.0)
    with torch.no_grad(), pytest.raises(ValueError, match="stored features"):
        run.extract_mismatch(
            torch, host, 1, records, questions, memories, changed, plan, lambda _p: None
        )


# ---- the CPU roles on a synthetic ladder --------------------------------------------


def role_args(root, role):
    return Namespace(
        role=role,
        output=root / "raw" / role,
        checkpoints=root / "checkpoints",
        seal=None,
        qualification=None,
    )


def pin(folder, names):
    return {
        name: {"bytes": (folder / name).stat().st_size, "sha256": run.ex.digest(folder / name)}
        for name in names
    }


def write_ladder(tmp_path, pattern=None):
    """A synthetic ladder in the sealed layout: cut-4 features and three trained routes."""
    plan = ladder_plan()
    raw = tmp_path / "ladder" / "raw"
    questions = write_extract(raw / "extract_cut4", plan, pattern=pattern)
    for index in range(1, run.SEEDS + 1):
        args = role_args(tmp_path / "ladder", f"route_cut4_s{index}")
        args.output.mkdir(parents=True)
        LADDER.train_arms(torch, args, plan)
        run.ex.write_new(args.output / "FINISHED.json", dict(status=LADDER.ARM_PASS))
    (raw / "endpoints").mkdir()
    run.ex.write_new(raw / "endpoints" / "ENDPOINTS.json", dict(ladder="synthetic"))
    return raw, questions


def a4_plan(raw):
    plan = copy.deepcopy(PLAN)
    tiny = ladder_plan()
    for key in ("route", "candidate_ids", "training", "checkpoint_steps", "parity_every"):
        plan[key] = copy.deepcopy(tiny[key])
    plan["replay"].update(from_step=3, execute_step=4)
    plan["endpoints"]["rule"] = RULE
    plan["source"]["raw"] = "../../ladder/raw"
    rename = {
        name: name.replace("step512", f"step{UPDATES}") for name in PLAN["source"]["receipts"]
    }
    plan["source"]["features"] = pin(raw, PLAN["source"]["features"])
    plan["source"]["receipts"] = pin(raw, rename.values())
    plan["reproduce"].update(
        scores=plan["reproduce"]["scores"].replace("step512", f"step{UPDATES}"),
        fingerprint=run.ex.read(raw / "route_cut4_s1" / "FINGERPRINTS.json")["route"][str(UPDATES)],
    )
    return plan


def write_mismatch(root, ladder):
    """Mismatch rows aligned with the ladder's train rows, with their own random states."""
    from safetensors.torch import load_file, save_file

    folder = root / "raw" / "extract_mismatch"
    folder.mkdir(parents=True)
    train = load_file(str(ladder / "extract_cut4" / "FEATURES_train.safetensors"))
    generator = torch.Generator().manual_seed(9)
    states = torch.randn(train["question_states"].shape, generator=generator)
    save_file(
        {
            "question_states": states.to(torch.bfloat16),
            "offsets": train["offsets"],
            "host_logits": torch.zeros_like(train["host_logits"]),
        },
        str(folder / "FEATURES_mismatch.safetensors"),
    )
    meta = [
        dict(m, mismatch_world=(m["world"] + 1) % 6, stride_steps=1)
        for m in run.ex.read_gz(ladder / "extract_cut4" / "ROWS_train.json.gz")
    ]
    run.ex.write_gz(folder / "ROWS_mismatch.json.gz", meta)
    run.ex.write_gz(folder / "HOST_SCORES_mismatch.json.gz", [[0.0, 0.0]] * len(meta))
    run.ex.write_new(folder / "FINISHED.json", dict(status=run.EXTRACT_PASS))


def test_roles_reproduce_the_ladder_then_train_gated_and_replay_exactly(tmp_path):
    ladder, _ = write_ladder(tmp_path)
    plan = a4_plan(ladder)
    root = tmp_path / "a4"
    write_mismatch(root, ladder)
    args = role_args(root, "reproduce")
    args.output.mkdir(parents=True)
    report = run.reproduce_run(torch, args, plan)
    assert report["exact"] and report["receipts_equal"] and report["scores_equal"]
    args = role_args(root, "gated_s1")
    args.output.mkdir(parents=True)
    run.ex.write_new(args.output / "STARTED.json", dict(pid=1))
    outcome = run.train_gated(torch, args, plan)
    assert set(outcome["fingerprints"]) == {"0", "3", "4", str(UPDATES)}
    for split in ("final", "train", "mismatch"):
        assert (args.output / f"eval_gated_{split}_step{UPDATES}.json.gz").exists()
    receipts = [json.loads(line) for line in (args.output / "updates_gated.jsonl").open()]
    assert len(receipts) == UPDATES and all(r["mismatch_penalty"] >= 0 for r in receipts)
    gated = run.ex.read_gz(args.output / f"eval_gated_final_step{UPDATES}.json.gz")
    ungated = run.ex.read_gz(ladder / "route_cut4_s1" / f"eval_route_final_step{UPDATES}.json.gz")
    assert gated != ungated
    replay = role_args(root, "replay")
    replay.output.mkdir(parents=True)
    report = run.replay_run(torch, replay, plan)
    assert report["exact"] and report["execute_step"] == 4
    changed = copy.deepcopy(plan)
    changed["reproduce"]["fingerprint"] = "0" * 64
    args = role_args(root, "reproduce_again")
    args.output.mkdir(parents=True)
    with pytest.raises(ValueError, match="did not reproduce"):
        run.reproduce_run(torch, args, changed)
    (ladder / "extract_cut4" / "ROWS_final.json.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Ladder file changed"):
        run.verify_ladder(ladder, plan, features=False)


def plant_scores(path, questions, meta, pattern):
    scores = [
        planted_score(questions[m["question"]], m["condition"], m["side"], pattern) for m in meta
    ]
    run.ex.write_gz(path, {"adapted_logits": scores})


def test_endpoints_compare_the_gated_and_the_ungated_route(tmp_path):
    ladder, questions = write_ladder(tmp_path, pattern="blind")
    meta = run.ex.read_gz(ladder / "extract_cut4" / "ROWS_final.json.gz")
    root = tmp_path / "a4" / "raw"
    for index in range(1, run.SEEDS + 1):
        path = ladder / f"route_cut4_s{index}" / f"eval_route_final_step{UPDATES}.json.gz"
        path.unlink()
        plant_scores(path, questions, meta, "directional")
        (root / f"gated_s{index}").mkdir(parents=True)
        plant_scores(
            root / f"gated_s{index}" / f"eval_gated_final_step{UPDATES}.json.gz",
            questions,
            meta,
            "content",
        )
    plan = a4_plan(ladder)
    result = run.endpoints_for(root, ladder, plan)
    outcome = run.outcome_of(result)
    assert outcome == dict(
        gated="CONTENT_REACHES_ANSWERS",
        gated_per_seed=["CONTENT_REACHES_ANSWERS"] * 3,
        ungated="DIRECTIONAL_ONLY",
        ungated_per_seed=["DIRECTIONAL_ONLY"] * 3,
        host="NOT_ESTABLISHED",
    )
    moved = result["gated"]["per_seed"][0]["gap_moved"]
    assert moved["none"] == 0.0 and moved["random_intact"] == pytest.approx(0.2)
    with pytest.raises(ValueError, match="recorded cut-4 verdicts"):
        run.check_comparator(outcome, plan)
    plan["comparator"].update(verdict="DIRECTIONAL_ONLY", per_seed=["DIRECTIONAL_ONLY"] * 3)
    run.check_comparator(outcome, plan)


def test_offline_verifier_accepts_what_the_runner_writes(tmp_path):
    from scripts import verify_v20_a4_gated_route as verifier

    ladder, questions = write_ladder(tmp_path, pattern="blind")
    plan = a4_plan(ladder)
    plan["data"]["train"]["world_pairs"] = 6
    meta = run.ex.read_gz(ladder / "extract_cut4" / "ROWS_final.json.gz")
    host = run.ex.read_gz(ladder / "extract_cut4" / "HOST_SCORES_final.json.gz")
    root = tmp_path / "a4"
    raw = root / "raw"
    write_mismatch(root, ladder)
    records = tiny_records(6, queries=8)
    rows = run.ex.read_gz(raw / "extract_mismatch" / "ROWS_mismatch.json.gz")
    stride = plan["mismatch"]["stride"]
    for row in rows:
        chosen = run.mismatch_world(records, row["world"], row["query"], stride)
        row["mismatch_world"], row["stride_steps"] = chosen
    (raw / "extract_mismatch" / "ROWS_mismatch.json.gz").unlink()
    run.ex.write_gz(raw / "extract_mismatch" / "ROWS_mismatch.json.gz", rows)
    for index in range(1, run.SEEDS + 1):
        folder = raw / f"gated_s{index}"
        folder.mkdir()
        run.ex.write_gz(folder / "eval_gated_final_step0.json.gz", {"adapted_logits": host})
        plant_scores(folder / f"eval_gated_final_step{UPDATES}.json.gz", questions, meta, "content")
    run.ex.write_new(raw / "gated_s1" / "FINGERPRINTS.json", {"gated": {"3": "a", "4": "b"}})
    run.ex.write_new(raw / "gated_s1" / "CHECKPOINT_gated_step3.json", {"fingerprint": "a"})
    (raw / "reproduce").mkdir()
    fingerprint = plan["reproduce"]["fingerprint"]
    run.ex.write_new(
        raw / "reproduce" / "REPRODUCE.json",
        dict(
            exact=True,
            receipts_equal=True,
            scores_equal=True,
            fingerprint=fingerprint,
            expected_fingerprint=fingerprint,
        ),
    )
    (raw / "replay").mkdir()
    update = {"step": 4, "task_loss": 0.5}
    run.ex.write_new(
        raw / "replay" / "REPLAY.json",
        dict(
            exact=True,
            role="gated_s1",
            replayed_fingerprint="b",
            restored_fingerprint="a",
            update=update,
            original_update=update,
        ),
    )
    (raw / "endpoints").mkdir()
    result = run.endpoints_for(raw, ladder, plan)
    run.ex.write_new(raw / "endpoints" / "ENDPOINTS.json", result)
    outcome = run.outcome_of(result)
    plan["comparator"].update(
        verdict=outcome["ungated"], per_seed=outcome["ungated_per_seed"], host=outcome["host"]
    )
    roles = {"endpoints": ({}, {"outcome": outcome}, True)}
    verified = verifier.verify_results(raw, ladder, plan, roles, records)
    assert verified["verdicts"]["gated"] == "CONTENT_REACHES_ANSWERS"
    assert verified["ladder_features_rehashed"]
    path = raw / "gated_s2" / "eval_gated_final_step0.json.gz"
    tampered = run.ex.read_gz(path)
    tampered["adapted_logits"][0] = [0.0, -0.5]
    path.unlink()
    run.ex.write_gz(path, tampered)
    with pytest.raises(ValueError, match="step 0"):
        verifier.verify_results(raw, ladder, plan, roles, records)
