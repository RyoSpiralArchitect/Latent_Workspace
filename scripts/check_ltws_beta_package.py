#!/usr/bin/env python3
"""Check the LTWS β package against V20 A5's sealed records, in a fresh process; no upload.

``routes`` (CPU): loads the package alone, checking its manifest and fingerprints. Each
member scores the ladder's final features with the engine's batched evaluation, as A5 did.
Its scores must equal A5's sealed scores bitwise, and lane A's verdicts recomputed from them
must equal A5's. The members' mean must equal A5's descriptive mean.

``text`` (GPU): runs the package's latent-memory API end to end from text, through the
pinned host, for every final question with its intact facts, its twin facts and no memory.
It requires, for every question and condition:

- the rendered question to equal the stored prompt ids;
- the memory to equal the run's memory tokens;
- the host's candidate logits and the question-position final states to equal the stored
  ones, bitwise.

It then reports how far the API's single-question route readings lie from A5's batched
scores, and whether every answer agrees.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import run_v20_a5_stable_route as A5  # noqa: E402

LADDER = A5.LADDER
ex = A5.ex
STEP = 512


def sealed_scores(a5_raw, names):
    return {
        name: ex.read_gz(a5_raw / f"stable_{name}" / f"eval_stable_final_step{STEP}.json.gz")[
            "adapted_logits"
        ]
        for name in names
    }


def check_routes(package_path, a5_raw, ladder_raw, plan):
    from latent_workspace import package, training

    torch = LADDER.cpu_runtime(plan)
    LADDER.load("run_v16_adapter_migration").load_runtime()
    descriptor, routes = package.load(package_path)
    A5.verify_pinned(ladder_raw, plan["sources"]["ladder"]["features"], "Ladder")
    A5.verify_pinned(ladder_raw, plan["sources"]["ladder"]["receipts"], "Ladder")
    folder = ladder_raw / f"extract_cut{A5.CUT}"
    final = LADDER.load_bank(torch, folder, "final")
    sealed = sealed_scores(a5_raw, routes)
    questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
    meta = ex.read_gz(folder / "ROWS_final.json.gz")
    rule = plan["endpoints"]["rule"]
    report, scores = {}, {}
    for name, route in routes.items():
        scores[name] = training.evaluate(route, final).tolist()
        verdict = LADDER.diagnose_scores(
            questions, LADDER.condition_scores(meta, scores[name]), rule
        )["verdict"]
        report[name] = dict(scores_equal=scores[name] == sealed[name], verdict=verdict)
    count = len(scores)
    mean = [
        [sum(s[n][k] for s in scores.values()) / count for k in range(2)] for n in range(len(meta))
    ]
    recorded = ex.read(a5_raw / "endpoints" / "ENDPOINTS.json")
    outcome = ex.read(a5_raw / "endpoints" / "FINISHED.json")["outcome"]
    verdict = LADDER.diagnose_scores(questions, LADDER.condition_scores(meta, mean), rule)
    result = dict(
        members=report,
        member_verdicts_equal=[report[f"s{i}"]["verdict"] for i in range(1, 4)]
        == outcome["stable_per_seed"],
        mean_verdict=verdict["verdict"],
        mean_flips_equal=verdict["flips"] == recorded["ensemble"]["flips"],
        mean_verdict_equal=verdict["verdict"] == outcome["ensemble"],
        descriptor_status=descriptor["status"],
    )
    result["exact"] = (
        all(r["scores_equal"] for r in report.values())
        and result["member_verdicts_equal"]
        and result["mean_verdict_equal"]
        and result["mean_flips_equal"]
    )
    return result


def check_text(package_path, a5_raw, ladder_raw, plan, limit):
    from safetensors.torch import load_file

    from latent_workspace import DecoderHost, package

    core = LADDER.load("run_v16_adapter_migration")
    core.load_runtime()
    torch = core.torch
    descriptor, routes = package.load(package_path)
    old = core.legacy.old
    _, _, architecture, _ = core.legacy.validate()
    config = old.engine.ModelConfig(**architecture["model"])
    tokenizer = old.engine.load_tokenizer(config)
    base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
    ex.require(
        core.tree_hash(base.state_dict()) == descriptor["host"]["original_base_sha256"],
        "Pinned base identity",
    )
    host = DecoderHost(base)
    reader = package.LatentMemory(host, tokenizer, descriptor, routes)
    records = LADDER.v19().load_records(plan)["final"]
    run_questions, run_memories = LADDER.render(old, tokenizer, records, plan)
    folder = ladder_raw / f"extract_cut{A5.CUT}"
    stored_questions = ex.read_gz(folder / "QUESTIONS_final.json.gz")
    meta = ex.read_gz(folder / "ROWS_final.json.gz")
    host_scores = ex.read_gz(folder / "HOST_SCORES_final.json.gz")
    features = load_file(str(folder / "FEATURES_final.safetensors"))
    sealed = sealed_scores(a5_raw, routes)
    index = {(m["question"], m["condition"]): n for n, m in enumerate(meta)}
    keys = len(LADDER.MEMORY_KEYS)
    counts = dict(rows=0, prompt=0, memory=0, host=0, states=0, answers=0)
    worst = 0.0
    started = time.monotonic()
    for i, question in enumerate(stored_questions[:limit]):
        record = records[question["world"]]
        query = record["queries"][question["query"]]
        counts["prompt"] += package.render_question(tokenizer, query) == question["prompt_ids"]
        for condition, side in (("intact", 0), ("twin", 1), ("none", 0)):
            n = index[i, condition]
            if condition == "none":
                memory, same_memory = None, True
            else:
                facts = record["contexts"][side]
                expected = run_memories[question["world"] * keys + side]["ids"]
                same_memory = package.render_memory(tokenizer, facts) == expected
                memory = reader.write(facts)
            result = reader.read(query, memory)
            start, end = features["offsets"][n : n + 2].tolist()
            counts["rows"] += 1
            counts["memory"] += same_memory
            counts["host"] += result["host"].tolist() == host_scores[n]
            counts["states"] += torch.equal(
                result["question_states"], features["question_states"][start:end]
            )
            agree = True
            for name, scores in result["members"].items():
                stored = torch.tensor(sealed[name][n])
                worst = max(worst, float((scores - stored).abs().max()))
                agree &= bool((scores[1] > scores[0]) == (stored[1] > stored[0]))
            counts["answers"] += agree
    questions = min(limit, len(stored_questions))
    ex.require(run_questions[0]["prompt_ids"] == stored_questions[0]["prompt_ids"], "Run rendering")
    return dict(
        questions=questions,
        counts=counts,
        max_abs_difference_from_sealed_scores=worst,
        exact=counts["prompt"] == questions
        and all(counts[k] == counts["rows"] for k in ("memory", "host", "states")),
        seconds=round(time.monotonic() - started, 1),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("routes", "text"))
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--a5-raw", type=Path, required=True)
    parser.add_argument("--ladder-raw", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10**9)
    args = parser.parse_args()
    plan = ex.read(ROOT / A5.PLAN)
    A5.validate_plan(plan)
    if args.mode == "routes":
        result = check_routes(args.package, args.a5_raw, args.ladder_raw, plan)
    else:
        result = check_text(args.package, args.a5_raw, args.ladder_raw, plan, args.limit)
    print(json.dumps(dict(mode=args.mode, **result), indent=1, sort_keys=True))
    return 0 if result["exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
