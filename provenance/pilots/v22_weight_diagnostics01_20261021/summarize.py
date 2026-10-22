#!/usr/bin/env python3
"""Offline terminal/byte/panel replay. Never imports a model or issues a call."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / "v22_base_comparison01_20261021"
SOURCE = "35cbe95fa498d95c8f967b428758ddac0bd29966"


def read(path):
    return json.loads(path.read_text())


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(path):
    return {
        p.relative_to(path).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def terminal(path, status):
    end = read(path / "FINISHED.json")
    files = manifest(path)
    files.pop("FINISHED.json")
    require(end["status"] == status and end["files"] == files, f"Terminal: {path}")
    for key in ("new_sequences", "judge_calls", "weight_deletions", "native_weight_updates"):
        require(end[key] == 0, f"Activity {key}")
    require(
        end["old_expression_gate"] == "FAIL"
        and end["non_regression"] == "NOT_ESTABLISHED"
        and end["winner"] == "none",
        "Ceiling",
    )
    return end


def journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def paired(a, b):
    require(set(a) == set(b), "Paired coverage")
    counts = collections.Counter((bool(a[k]), bool(b[k])) for k in a)
    return dict(
        n=len(a),
        base_correct=sum(a.values()),
        v22_correct=sum(b.values()),
        both_correct=counts[True, True],
        base_only=counts[True, False],
        v22_only=counts[False, True],
        both_wrong=counts[False, False],
    )


def weight_totals(rows):
    result = {
        k: sum(r[k] for r in rows)
        for k in (
            "numel",
            "native_changed",
            "master_changed",
            "master_changed_native_unchanged",
            "original_sq",
            "native_delta_sq",
            "master_delta_sq",
            "cast_error_sq",
        )
    }
    result.update(
        tensors=len(rows),
        native_changed_tensors=sum(r["native_changed"] > 0 for r in rows),
        master_changed_tensors=sum(r["master_changed"] > 0 for r in rows),
    )
    result["native_changed_fraction"] = result["native_changed"] / result["numel"]
    result["master_changed_fraction"] = result["master_changed"] / result["numel"]
    result["native_relative_l2"] = math.sqrt(result["native_delta_sq"] / result["original_sq"])
    result["master_relative_l2"] = math.sqrt(result["master_delta_sq"] / result["original_sq"])
    return result


def first_fork(row):
    i = row["first_token_difference"]
    if i is None or i >= len(row["fixed_prefix_tokens"]) or i >= len(row["gold_ids"]):
        return None
    step = row["fixed_prefix_tokens"][i]
    d = step["gold_at_first_fork"]
    teacher = row["teacher_tokens"][i]
    return dict(
        index=i,
        gold_token_id=row["gold_ids"][i],
        recorded_token_id=row["recorded_ids"][i],
        gold_token=d["token"],
        recorded_token=step["token"],
        native=d["native"],
        fp32_head=d["fp32_head"],
        gold_probability=math.exp(d["native"]["gold_logprob"]),
        teacher_gold_probability=math.exp(teacher["native"]["gold_logprob"]),
        teacher_fork_nll_fraction=-teacher["native"]["gold_logprob"] / row["teacher"]["nll_sum"],
    )


def compute(bundle):
    witness = read(bundle / "REMOTE_TERMINAL_CHECK.json")
    require(
        witness["status"] == "POST_TERMINAL_READ_ONLY_CHECK_PASS"
        and witness["no_checkpoint_writes"]
        and witness["model_calls"] == witness["weight_deletions"] == 0
        and all(not v["process_exists"] for v in witness["workers"].values())
        and witness["verifier_sha256"]
        == sha(HERE / "verify_remote.py")
        == sha(bundle / "verify_remote.py")
        and witness["checkpoint"]["sha256"]
        == "cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68"
        and witness["checkpoint"]["bytes"] == 29004418636,
        "Post-terminal original checkpoint/process witness",
    )
    spec = importlib.util.spec_from_file_location(
        "old_comparison_replay", PREVIOUS / "summarize.py"
    )
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    previous_summary, previous_rows = old.compute(PREVIOUS / "furnace")
    require(previous_summary == read(PREVIOUS / "SUMMARY.json"), "Prior summary unchanged")
    require(
        old.bank(previous_rows) == (PREVIOUS / "ANSWER_BANK.md").read_text(), "Prior literal bank"
    )
    seal = read(bundle / "SOURCE_SEAL.json")
    require(
        seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 734, "Source identity"
    )
    for name, digest in seal["source_hashes"].items():
        raw = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=ROOT)
        require(hashlib.sha256(raw).hexdigest() == digest, f"Frozen source: {name}")
    plan = read(ROOT / "configs/v22/WEIGHT_DIAGNOSTICS_01.json")
    qualifications = {}
    for device in ("cpu", "cuda"):
        path = bundle / "qualification" / device
        end = terminal(path, "TINY_V22_DIAGNOSTICS_PASS_NOT_7B")
        require(
            read(path / "STARTED.json")["seal"] == seal
            and read(path / "STARTED.json")["plan"] == plan,
            "Qualification source/plan",
        )
        totals = {
            k: sum(
                int(s.attrib.get(k, 0))
                for s in ElementTree.parse(path / "TESTS.xml").getroot().iter("testsuite")
            )
            for k in ("tests", "errors", "failures", "skipped")
        }
        require(
            totals == end["counts"] == dict(tests=158, errors=0, failures=0, skipped=0),
            "Qualification totals",
        )
        qualifications[device] = dict(counts=totals, elapsed_seconds=end["elapsed_seconds"])
    dispatch = terminal(bundle / "raw", "V22_DIAGNOSTICS_COMPLETE_NOT_RELEASE")
    require(dispatch["completed_roles"] == ["base", "v22"], "Completed arms")
    inputs = json.loads(gzip.decompress((PREVIOUS / "furnace/inputs/INPUTS.json.gz").read_bytes()))
    world_inputs = {r["row_id"]: r for r in inputs["worlds"]}
    arms, resources = {}, {}
    for role in ("base", "v22"):
        folder = bundle / "raw" / role
        end = terminal(folder, "V22_DIAGNOSTIC_ARM_COMPLETE")
        start = read(folder / "STARTED.json")
        require(start["seal"] == seal and start["plan"] == plan, "Role source/plan")
        identity = read(folder / "WEIGHT_IDENTITY.json")
        require(identity["equal"] and identity["before"] == identity["after"], "No weight mutation")
        prior_identity = read(PREVIOUS / "furnace/raw" / role / "WEIGHT_IDENTITY.json")
        require(identity == prior_identity, "Same original/step32 weights")
        if role == "v22":
            require(
                read(folder / "RESTORE.json") == read(PREVIOUS / "furnace/raw/v22/RESTORE.json"),
                "Exact same owner restore",
            )
        mmlu = journal(folder / "mmlu.jsonl")
        worlds = journal(folder / "worlds.jsonl")
        require(len(mmlu) == 570 and len(worlds) == 192, "Arm row denominators")
        old_m = {r["id"]: r for r in previous_rows[role]["mmlu"]}
        old_w = {(r["id"], r["route"]): r for r in previous_rows[role]["worlds"]}
        require({r["id"] for r in mmlu} == set(old_m), "MMLU coverage")
        require({(r["id"], r["route"]) for r in worlds} == set(old_w), "World coverage")
        for r in mmlu:
            require(
                r["native"] == {k: old_m[r["id"]][k] for k in r["native"]}, "Original MMLU retained"
            )
        disagreements, steps = 0, 0
        for r in worlds:
            prior = old_w[r["id"], r["route"]]
            require(
                r["teacher"] == prior["teacher"]
                and r["recorded_ids"] == prior["token_ids"]
                and r["recorded_text"] == prior["text"]
                and r["exact_match"] == prior["exact_match"],
                "Original world retained",
            )
            require(r["gold_ids"] == world_inputs[r["id"]]["answer_ids"], "Frozen gold tokens")
            require(
                len(r["teacher_tokens"]) == len(r["gold_ids"])
                and len(r["fixed_prefix_tokens"]) == len(r["recorded_ids"]),
                "Token panel denominators",
            )
            require(
                math.isclose(
                    sum(-s["native"]["gold_logprob"] for s in r["teacher_tokens"]),
                    r["teacher"]["nll_sum"],
                    rel_tol=1e-6,
                    abs_tol=1e-5,
                ),
                "Token NLL decomposition",
            )
            for j, step in enumerate(r["fixed_prefix_tokens"]):
                require(
                    step["recorded_token"] == r["recorded_ids"][j] == step["native"]["target"],
                    "Recorded token target",
                )
                disagreements += not step["native"]["correct"]
                steps += 1
            fork = first_fork(r)
            if fork:
                j = fork["index"]
                require(
                    r["gold_ids"][:j] == r["recorded_ids"][:j]
                    and r["gold_ids"][j] != r["recorded_ids"][j],
                    "First common-prefix fork",
                )
        require(
            end["outcome"]["fixed_prefix_steps"] == steps
            and end["outcome"]["replay_disagreements"] == disagreements,
            "Trajectory replay accounting",
        )
        resources[role] = dict(elapsed_seconds=end["elapsed_seconds"], **end["outcome"])
        arms[role] = dict(mmlu=mmlu, worlds=worlds)
    mmlu = {}
    for mode in ("native", "fp32_head", "fp32_rounded"):
        mmlu[mode] = paired(
            {r["id"]: r[mode]["correct"] for r in arms["base"]["mmlu"]},
            {r["id"]: r[mode]["correct"] for r in arms["v22"]["mmlu"]},
        )
        mmlu[mode]["strict"] = paired(
            {r["id"]: r[mode]["strict_correct"] for r in arms["base"]["mmlu"]},
            {r["id"]: r[mode]["strict_correct"] for r in arms["v22"]["mmlu"]},
        )
        mmlu[mode]["ties"] = {
            role: sum(r[mode]["ties"] > 1 for r in arms[role]["mmlu"]) for role in arms
        }
    factorial = {
        k: sum(r["head_factorial"][k]["correct"] for r in arms["v22"]["mmlu"])
        for k in arms["v22"]["mmlu"][0]["head_factorial"]
    }
    originals = {r["id"]: r for r in arms["base"]["mmlu"]}
    cases = []
    for r in arms["v22"]["mmlu"]:
        a = originals[r["id"]]
        f = r["head_factorial"]
        require(
            f["hidden_base_head_base"] == a["selected_fp32_self"]
            and f["hidden_v22_head_v22"] == r["selected_fp32_self"],
            "Factorial self replay",
        )
        if a["native"]["correct"] and not r["native"]["correct"]:
            target = r["native"]["target"]
            competitor = max(
                (i for i in range(4) if i != target), key=lambda i: a["native"]["logits"][i]
            )
            margins = {k: v["logits"][target] - v["logits"][competitor] for k, v in f.items()}
            m00, m01, m10, m11 = (
                margins[k]
                for k in (
                    "hidden_base_head_base",
                    "hidden_base_head_v22",
                    "hidden_v22_head_base",
                    "hidden_v22_head_v22",
                )
            )
            cases.append(
                dict(
                    id=r["id"],
                    subject=r["subject"],
                    target=target,
                    competitor=competitor,
                    base={k: a[k] for k in ("native", "fp32_head", "fp32_rounded")},
                    v22={k: r[k] for k in ("native", "fp32_head", "fp32_rounded")},
                    fixed_competitor_margins=margins,
                    hidden_effect=m10 - m00,
                    head_effect=m01 - m00,
                    interaction=m11 - m10 - m01 + m00,
                    total_change=m11 - m00,
                )
            )
    worlds = {}
    latent_failures = []
    for role, measured in arms.items():
        worlds[role] = {}
        groups = collections.defaultdict(list)
        for r in measured["worlds"]:
            groups[f"{r['split']}/{r['route']}/all"].append(r)
            groups[f"{r['split']}/{r['route']}/{r['mode']}"].append(r)
            if role == "v22" and r["route"] == "latent" and not r["exact_match"]:
                source = world_inputs[r["id"]]
                literal = r["recorded_text"].strip().rstrip(".")
                query_names = {
                    k: v
                    for k, v in source["query_spec"].items()
                    if k in ("left", "right", "subject")
                }
                visible = {str(f[k]) for f in source["facts"] for k in ("subject", "value")}
                latent_failures.append(
                    dict(
                        id=r["id"],
                        family=r["family"],
                        split=r["split"],
                        mode=r["mode"],
                        target=r["target"],
                        recorded_text=r["recorded_text"],
                        query=source["query"],
                        memory=source["memory"],
                        query_spec=source["query_spec"],
                        literal_matches_query_fields=[
                            k for k, v in query_names.items() if literal == v
                        ],
                        literal_matches_visible_fact_entity=literal in visible,
                        comparisons={
                            a: {
                                route: {"text": w["recorded_text"], "exact_match": w["exact_match"]}
                                for route in ("latent", "inline")
                                for w in arms[a]["worlds"]
                                if w["id"] == r["id"] and w["route"] == route
                            }
                            for a in ("base", "v22")
                        },
                        mean_teacher_nll=r["teacher"]["nll_sum"]
                        / r["teacher"]["supervised_tokens"],
                        first_fork=first_fork(r),
                    )
                )
        for key, rows in sorted(groups.items()):
            failures = [r for r in rows if not r["exact_match"]]
            forks = [f for r in failures if (f := first_fork(r)) is not None]
            tokens = sum(r["teacher"]["supervised_tokens"] for r in rows)
            worlds[role][key] = dict(
                n=len(rows),
                exact_correct=sum(r["exact_match"] for r in rows),
                supervised_tokens=tokens,
                mean_teacher_nll=sum(r["teacher"]["nll_sum"] for r in rows) / tokens,
                teacher_gold_argmax=sum(
                    s["native"]["correct"] for r in rows for s in r["teacher_tokens"]
                ),
                teacher_first_token_correct=sum(
                    r["teacher_tokens"][0]["native"]["correct"] for r in rows
                ),
                failed_rows=len(failures),
                failed_rows_with_common_fork=len(forks),
                failed_forks_fp32_gold_top1=sum(f["fp32_head"]["correct"] for f in forks),
                failed_fork_positions=dict(
                    sorted(collections.Counter(str(f["index"]) for f in forks).items())
                ),
            )
    weights = journal(bundle / "raw/v22/weights.jsonl")
    require(len(weights) == len({r["name"] for r in weights}) == 291, "Physical tensor census")
    require(sum(r["numel"] for r in weights) == 7248023552, "Parameter denominator")
    grouped = collections.defaultdict(list)
    for r in weights:
        name = r["name"]
        group = (
            "head"
            if name == "lm_head.weight"
            else "norm"
            if "norm" in name
            else "embedding"
            if "embed_tokens" in name
            else "attention"
            if "self_attn" in name
            else "mlp"
        )
        grouped[group].append(r)
    weight_summary = dict(
        total=weight_totals(weights),
        by_kind={k: weight_totals(v) for k, v in sorted(grouped.items())},
        native_unchanged_names=[r["name"] for r in weights if not r["native_changed"]],
        top_native_relative_l2=sorted(weights, key=lambda r: r["native_relative_l2"], reverse=True)[
            :10
        ],
    )
    return dict(
        source_commit=SOURCE,
        source_files=734,
        qualifications=qualifications,
        resources=resources,
        completed=dispatch["summary"],
        mmlu=mmlu,
        head_factorial=factorial,
        mmlu_regression_cases=cases,
        worlds=worlds,
        v22_latent_failures=latent_failures,
        weights=weight_summary,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    ), arms


def panel(summary):
    parts = [
        "# V22 latent-route failures — complete exposed diagnostic panel\n",
        "All 13 previously incorrect latent-route answers, unchanged. The listed token fork "
        "is a token-level event, not an independent semantic judgement. FP32 scores are "
        "diagnostic only; no new continuation was generated.\n",
    ]
    for row in summary["v22_latent_failures"]:
        parts += [
            f"## {row['id']}\n",
            "```json\n" + json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n",
        ]
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    summary, _ = compute(HERE / "furnace")
    texts = {
        "SUMMARY.json": json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        "FAILURE_PANEL.md": panel(summary),
    }
    for name, text in texts.items():
        if args.verify:
            require((HERE / name).read_text() == text, f"Exact publication replay: {name}")
        else:
            with (HERE / name).open("x") as stream:
                stream.write(text)
    print(
        "Verified source, previous bundle, terminal bytes, all row/token denominators "
        "and diagnostic publication."
    )


if __name__ == "__main__":
    main()
