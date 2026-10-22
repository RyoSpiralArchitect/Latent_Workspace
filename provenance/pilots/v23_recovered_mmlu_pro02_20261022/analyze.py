"""Offline terminal replay/publication. No model, network, retry or GPU work."""

import argparse
import importlib.util
import itertools
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
import v23_mmlu_pro as data_module  # noqa: E402

qualification_spec = importlib.util.spec_from_file_location(
    "v23_mmlu_pro02_qualification", HERE / "verify_qualification.py"
)
verify_qualification = importlib.util.module_from_spec(qualification_spec)
qualification_spec.loader.exec_module(verify_qualification)

bank = verify_qualification.runner.bank
ex = bank.ex
SOURCE = "b2f569740636e2cffb80e4091323d551ea7de4c2"
TOKENIZER_FILES = {
    "tokenizer.json": "e553af6fff7d7ad76e830608b218c5c0b0822998d5a1a96099a74cd3c1cb1a49",
    "tokenizer_config.json": "0533dec9cfe319163801b6618d0f3ec9cfa126b6288e3df5deca6e32acb09cd2",
    "special_tokens_map.json": "6fa06efa2785e450051989a6f8fb4416b10149ded485ddd3f127a40734f5cfd0",
    "tokenizer.model": "37f00374dea48658ee8f5d0f21895b9bc55cb0103939607c8185bfd1c6ca1f89",
}


def direct_check(row, source):
    assert all(row[k] == source[k] for k in ("id", "category", "target"))
    scores = row["logits"]
    assert len(scores) == row["option_count"] == len(source["choice_ids"])
    assert all(math.isfinite(v) for v in scores)
    assert row["prompt_tokens"] == len(source["input_ids"])
    pred = max(range(len(scores)), key=scores.__getitem__)
    ties = scores.count(max(scores))
    assert row["prediction"] == pred and row["ties"] == ties
    assert row["correct"] == (pred == source["target"])
    assert row["strict_correct"] == (row["correct"] and ties == 1)
    assert row["gold_margin"] == scores[source["target"]] - max(
        value for i, value in enumerate(scores) if i != source["target"]
    )


def reasoning_check(row, source, policy):
    assert all(row[k] == source[k] for k in ("id", "category", "target"))
    assert row["prompt_tokens"] == len(source["reasoning_ids"])
    assert all(row[k] == policy[k] for k in ("seed", "temperature", "top_p", "max_new_tokens"))
    ids = row["token_ids"]
    assert 0 < len(ids) == row["generated_tokens"] <= policy["max_new_tokens"]
    assert all(type(v) is int and 0 <= v < 32768 for v in ids)
    assert 2 not in ids[:-1]
    assert row["stop_reason"] == ("eos" if ids[-1] == 2 else "length")
    assert ids[-1] == 2 or len(ids) == policy["max_new_tokens"]
    parsed = data_module.extract(row["text"], len(source["options"]))
    assert all(row[k] == v for k, v in parsed.items())
    assert row["correct"] == (parsed["parsed"] and parsed["prediction"] == source["target"])
    assert row["completed_correct"] == (row["correct"] and row["stop_reason"] == "eos")


def summarize(direct, reasoning):
    return dict(
        direct_n=len(direct),
        direct_correct=sum(r["correct"] for r in direct),
        direct_tie_free_correct=sum(r["strict_correct"] for r in direct),
        direct_top_option_ties=sum(r["ties"] > 1 for r in direct),
        reasoning_n=len(reasoning),
        reasoning_parsed=sum(r["parsed"] for r in reasoning),
        reasoning_correct=sum(r["correct"] for r in reasoning),
        reasoning_completed_correct=sum(r["completed_correct"] for r in reasoning),
        reasoning_stops=dict(Counter(r["stop_reason"] for r in reasoning)),
        generated_tokens=sum(r["generated_tokens"] for r in reasoning),
    )


def replay(tokenizer_path):
    from transformers import AutoTokenizer

    qualification = verify_qualification.verify()
    bundle = HERE / "furnace"
    seal = ex.read(bundle / "SOURCE_SEAL.json")
    plan = ex.read(ROOT / verify_qualification.runner.PLAN)
    policy = ex.read(ROOT / data_module.PLAN)
    panel, _ = data_module.load_panel(policy)
    inputs = HERE.parent / "v23_mmlu_pro01_20261022/furnace/inputs"
    manifest = ex.read(inputs / "MANIFEST.json")
    actual = ex.manifest(inputs)
    actual.pop("MANIFEST.json")
    assert actual == manifest["files"] and manifest["plan_sha256"] == ex.plan_hash(policy)
    assert all(ex.digest(ROOT / n) == h for n, h in manifest["source"].items())
    assert manifest["panel_manifest"] == data_module.load_panel(policy)[1]
    data = ex.read_gz(inputs / "INPUTS.json.gz")
    assert {n: ex.digest(tokenizer_path / n) for n in TOKENIZER_FILES} == TOKENIZER_FILES
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path, local_files_only=True, trust_remote_code=False
    )
    assert data_module.tokenize(panel, tokenizer, policy) == data
    assert len(data["rows"]) == len({r["id"] for r in data["rows"]}) == 280
    assert len(set(data["generation_ids"])) == 28
    original = HERE.parent / "v23_comparison01_20261022/furnace"
    recovered = HERE.parent / "v23_comparison_recovery02_20261022/furnace"
    _, origins = bank.verify(original, recovered, published_copy=True)
    end = bank.terminal(bundle / "raw", "V23_RECLAIMED_MMLU_PRO_COMPLETE_NOT_RELEASE")
    start = ex.read(bundle / "raw/STARTED.json")
    assert start["seal"] == seal and start["plan"] == plan
    assert start["qualification"] == verify_qualification.runner.RUN.qualification(
        bundle / "qualification", seal, plan
    )
    assert end["completed_roles"] == ["base", "off", "on"]
    assert (end["summary"]["direct_rows"], end["new_sequences"]) == (840, 84)
    bank.no_saved_checkpoints(bundle, published_copy=True)
    arms, details = {}, {}
    for arm in ("base", "off", "on"):
        folder = bundle / "raw" / arm
        role = bank.terminal(folder, "V23_MMLU_PRO_ARM_COMPLETE")
        start = ex.read(folder / "STARTED.json")
        assert start["plan"] == plan and start["seal"] == seal
        assert ex.read(folder / "PREDECESSOR.json") == origins
        assert ex.read(folder / "INPUT_MANIFEST.json") == manifest
        prior = (recovered if arm == "on" else original) / "raw" / arm
        for name in ("ORIGINAL_IDENTITY.json", "WEIGHT_IDENTITY.json", "INFERENCE_POLICY.json"):
            assert ex.read(folder / name) == ex.read(prior / name)
        weights = ex.read(folder / "WEIGHT_IDENTITY.json")
        assert weights["equal"] and weights["before"] == weights["after"]
        if arm != "base":
            assert ex.read(folder / "RESTORE.json") == ex.read(prior / "RESTORE.json")
        assert ex.read(folder / "PARITY.json") == dict(
            bitwise_equal=True, fixed_prefixes=2, tokens=32
        )
        rows = {k: bank.judge.read_lines(folder / f"{k}.jsonl") for k in ("direct", "reasoning")}
        assert len(rows["direct"]) == 280 and len(rows["reasoning"]) == 28
        for r, item in zip(rows["direct"], data["rows"], strict=True):
            direct_check(r, item)
        source = {r["id"]: r for r in data["rows"]}
        assert [r["id"] for r in rows["reasoning"]] == data["generation_ids"]
        for r in rows["reasoning"]:
            reasoning_check(r, source[r["id"]], policy["generation"])
            assert tokenizer.decode(r["token_ids"], skip_special_tokens=True) == r["text"]
        audit = bank.judge.read_lines(folder / "GENERATION_CACHE.jsonl")
        assert [r["phase"] for r in audit] == [
            f"generation:{i}" for r in rows["reasoning"] for i in range(r["generated_tokens"])
        ]
        assert all(r["allocated_before"] == r["allocated_after"] for r in audit)
        assert all(r["reserved_after"] <= r["reserved_before"] for r in audit)
        resources = bank.judge.read_lines(folder / "RESOURCES.jsonl")
        host = bank.judge.read_lines(folder / "HOST_RESOURCES.jsonl")
        assert resources[-1]["phase"] == "complete"
        assert all(
            r["free_bytes"] >= plan["resources"]["abort_free_gib"] * 2**30 for r in resources
        )
        assert all(p["pid"] == r["own_pid"] for r in resources for p in r["processes"])
        stats = summarize(**rows)
        assert role["outcome"]["generated_tokens"] == stats["generated_tokens"] == len(audit)
        assert (role["outcome"]["direct_rows"], role["outcome"]["new_sequences"]) == (280, 28)
        for key in ("native_weight_updates", "checkpoint_saves"):
            assert role["outcome"][key] == 0
        details[arm] = dict(
            **stats,
            categories={
                c: summarize(*([r for r in rows[k] if r["category"] == c] for k in rows))
                for c in panel["categories"]
            },
            terminal_sha256=ex.digest(folder / "FINISHED.json"),
            native_state_sha256=weights["before"],
            cache_boundaries=len(audit),
            min_observed_free_gpu_bytes=min(r["free_bytes"] for r in resources),
            peak_allocated_bytes=max(r.get("peak_allocated", 0) for r in resources),
            host_resource_samples=len(host),
        )
        arms[arm] = rows
    assert (
        sum(v["generated_tokens"] for v in details.values())
        == end["summary"]["generated_tokens"]
        == 17005
    )
    assert all(end[k] == 0 for k in ("native_weight_updates", "weight_deletions", "judge_calls"))
    assert end["summary"]["checkpoint_saves"] == 0
    assert ex.digest(bundle / "raw/base/direct.jsonl") == ex.digest(
        HERE.parent / "v23_recovered_mmlu_pro01_20261022/furnace/raw/base/direct.jsonl"
    )
    paired = {}
    for a, b in itertools.combinations(arms, 2):
        paired[f"{a}:{b}"] = {
            f"{kind}:{key}": data_module.transitions(
                {r["id"]: r[key] for r in arms[a][kind]},
                {r["id"]: r[key] for r in arms[b][kind]},
            )
            for kind, key in (
                ("direct", "correct"),
                ("direct", "strict_correct"),
                ("reasoning", "correct"),
                ("reasoning", "completed_correct"),
            )
        }
    result = dict(
        status="ALL_840_SCORE_DECISIONS_84_LITERAL_PARSES_AND_17005_CACHE_BOUNDARIES_PASS",
        source=SOURCE,
        qualification=qualification,
        terminal_sha256=ex.digest(bundle / "raw/FINISHED.json"),
        input_manifest_sha256=ex.digest(inputs / "MANIFEST.json"),
        tokenizer_revision="c170c708c41dac9275d15a8fff4eca08d52bab71",
        tokenizer_files=TOKENIZER_FILES,
        arms=details,
        paired=paired,
        replay_limits=(
            "No forward recomputation; full-vocabulary argmax/logprob not replayable "
            "from choice-only logits."
        ),
        analysis_model_calls=0,
        analysis_new_sequences=0,
        analysis_gpu_work=False,
        original_failure_unchanged=True,
        base_direct_journal_matches_prior=True,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    return data, arms, result


def literal_bank(data, arms):
    lines = [
        "# V23 MMLU-Pro literal reasoning bank",
        "",
        "All 28 frozen questions × three arms (84 outputs). Five-shot, greedy, "
        "1024-token cap; all capped/unparsed outputs retained. Empty-memory route. "
        "The strict parser is unchanged; unparsed is not asserted factually wrong.",
        "",
    ]
    for row in data["rows"]:
        if row["id"] not in data["generation_ids"]:
            continue
        records = {
            a: next(v for v in r["reasoning"] if v["id"] == row["id"]) for a, r in arms.items()
        }
        lines.extend(
            [
                f"## {row['id']}",
                "",
                data_module.question(row),
                "",
                f"Gold: {data_module.LETTERS[row['target']]}. "
                f"Frozen example IDs: {', '.join(row['example_ids'])}.",
                "",
            ]
        )
        for arm, r in records.items():
            fence = "`" * max(3, 1 + max((len(v) for v in re.findall(r"`+", r["text"])), default=0))
            lines.extend(
                [
                    f"### {arm} · {r['stop_reason']} · {r['generated_tokens']} tokens · "
                    f"parsed={r['parsed']} · correct={r['correct']}",
                    "",
                    fence + "text",
                    r["text"],
                    fence,
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("--tokenizer", type=Path, required=True)
    args = parser.parse_args()
    data, arms, result = replay(args.tokenizer)
    folder = HERE / "analysis"
    text = literal_bank(data, arms)
    if args.command == "write":
        folder.mkdir(exist_ok=False)
        ex.write_new(folder / "ANALYSIS.json", result)
        with (folder / "REASONING_BANK.md").open("x") as stream:
            stream.write(text)
        ex.write_new(folder / "MANIFEST.json", ex.manifest(folder))
    assert ex.read(folder / "ANALYSIS.json") == result
    assert (folder / "REASONING_BANK.md").read_text() == text
    actual = ex.manifest(folder)
    actual.pop("MANIFEST.json")
    assert actual == ex.read(folder / "MANIFEST.json")
    print(
        json.dumps(
            {
                "status": result["status"],
                "source": SOURCE,
                "arms": {
                    a: {k: v for k, v in s.items() if k != "categories"}
                    for a, s in result["arms"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
