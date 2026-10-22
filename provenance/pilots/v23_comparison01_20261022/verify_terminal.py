"""Offline failure replay and complete-arm comparisons; never repair missingness."""

import argparse
import importlib.util
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old = load("v22_publication", HERE.parent / "v22_base_comparison01_20261021/summarize.py")
qualification = load("v23_qualification", HERE / "verify_qualification.py")


def verify():
    root = HERE / "furnace"
    quals = qualification.verify(root, ROOT)
    end = old.terminal(root / "raw", "INCOMPLETE_NO_RETRY")
    old.require(end["completed_roles"] == ["base", "off"], "Closed roles")
    plan = old.read(ROOT / "configs/v23/COMPARISON_01.json")
    reference = old.read(ROOT / plan["reference_evaluation_plan"])
    seal = old.read(root / "SOURCE_SEAL.json")
    old.require(old.read(root / "raw/STARTED.json")["seal"] == seal, "Dispatcher seal")
    inputs_root = HERE.parent / "v22_base_comparison01_20261021/furnace/inputs"
    manifest = old.read(inputs_root / "MANIFEST.json")
    actual = old.manifest(inputs_root)
    actual.pop("MANIFEST.json")
    old.require(actual == manifest["files"], "Original input bytes")
    import gzip
    import json

    inputs = json.loads(gzip.decompress((inputs_root / "INPUTS.json.gz").read_bytes()))
    expected_mmlu = {r["id"]: r for r in inputs["mmlu"]}
    expected_worlds = {r["row_id"]: r for r in inputs["worlds"]}
    expected_free = {
        (r["id"], s): r for r in inputs["free"] for s in reference["generation"]["seeds"]
    }
    counts, measures = {}, {}
    for role in ("base", "off", "on"):
        folder = root / "raw" / role
        terminal = old.terminal(
            folder, "INCOMPLETE_NO_RETRY" if role == "on" else "V23_EVALUATION_ARM_COMPLETE"
        )
        start = old.read(folder / "STARTED.json")
        old.require(start["seal"] == seal and start["plan"] == plan, "Role source/plan")
        rows = {
            n: old.journal(folder / f"{n}.jsonl") if (folder / f"{n}.jsonl").exists() else []
            for n in ("mmlu", "worlds", "free")
        }
        for row in rows["mmlu"]:
            source = expected_mmlu[row["id"]]
            scores = row["logits"]
            old.require(
                row["target"] == source["target"]
                and len(scores) == 4
                and all(math.isfinite(v) for v in scores),
                "MMLU inputs/scores",
            )
            pred = max(range(4), key=lambda i: scores[i])
            ties = scores.count(max(scores))
            old.require(
                row["prediction"] == pred
                and row["ties"] == ties
                and row["correct"] == (pred == row["target"])
                and row["strict_correct"] == (pred == row["target"] and ties == 1),
                "Score replay",
            )
        if role == "on":
            old.require(
                [r["id"] for r in rows["mmlu"]] == [r["id"] for r in inputs["mmlu"][:79]]
                and not rows["worlds"]
                and not rows["free"],
                "Exact retained prefix",
            )
            old.require(terminal["new_sequences"] is None, "Do not turn unknown activity into zero")
        else:
            old.require(
                len(rows["mmlu"]) == 570 and len(rows["worlds"]) == 192 and len(rows["free"]) == 24,
                "Complete arm counts",
            )
            old.require({r["id"] for r in rows["mmlu"]} == set(expected_mmlu), "MMLU coverage")
            old.require(
                {(r["id"], r["route"]) for r in rows["worlds"]}
                == {(i, route) for i in expected_worlds for route in ("latent", "inline")},
                "World coverage",
            )
            old.require(
                {(r["id"], r["seed"]) for r in rows["free"]} == set(expected_free),
                "Free prompt/seed coverage",
            )
            identity = old.read(folder / "WEIGHT_IDENTITY.json")
            old.require(
                identity["equal"] and identity["before"] == identity["after"], "Native identity"
            )
            for r in rows["worlds"]:
                src = expected_worlds[r["id"]]
                old.require(
                    r["target"] == src["answer"]
                    and r["exact_match"] == (old.norm(r["text"]) == old.norm(src["answer"])),
                    "World oracle target",
                )
                old.require(
                    r["teacher"]["supervised_tokens"] == len(src["answer_ids"]), "NLL denominator"
                )
                old.generation_check(r, reference["world_generation"])
            for r in rows["free"]:
                old.require(
                    r["prompt"] == expected_free[r["id"], r["seed"]]["prompt"], "Free prompt"
                )
                old.generation_check(r, reference["generation"])
            old.require(terminal["outcome"]["new_sequences"] == 216, "Complete sequence count")
        counts[role] = {n: len(v) for n, v in rows.items()}
        measures[role] = rows
    collision = old.journal(root / "raw/on/RESOURCES.jsonl")[-1]
    cpu_root = HERE.parent / "v23_mmlu_pro01_20261022/furnace/qualification/cpu"
    cpu_start = old.read(cpu_root / "STARTED.json")
    cpu_end = old.terminal(cpu_root, "TINY_V23_MMLU_PRO_PASS_NOT_7B")
    others = [p for p in collision["processes"] if p["pid"] != collision["own_pid"]]
    old.require(
        len(others) == 1
        and others[0]["pid"] == cpu_start["pid"]
        and collision["phase"] == "mmlu:79",
        "Exact competing PID attribution",
    )
    complete = {k: measures[k] for k in ("base", "off")}
    direct = old.pair(
        {r["id"]: r["correct"] for r in complete["base"]["mmlu"]},
        {r["id"]: r["correct"] for r in complete["off"]["mmlu"]},
    )
    direct = {k.replace("v22", "off"): v for k, v in direct.items()}
    arms = {}
    for role, rows in complete.items():
        arms[role] = dict(
            mmlu_correct=sum(r["correct"] for r in rows["mmlu"]),
            mmlu_tie_free_correct=sum(r["strict_correct"] for r in rows["mmlu"]),
            mmlu_ties=sum(r["ties"] > 1 for r in rows["mmlu"]),
            worlds={
                route: dict(
                    n=96,
                    correct=sum(r["exact_match"] for r in rows["worlds"] if r["route"] == route),
                    length=sum(
                        r["stop_reason"] == "length" for r in rows["worlds"] if r["route"] == route
                    ),
                )
                for route in ("latent", "inline")
            },
            free=dict(
                n=24,
                eos=sum(r["stop_reason"] == "eos" for r in rows["free"]),
                length=sum(r["stop_reason"] == "length" for r in rows["free"]),
            ),
        )
    return dict(
        status="INCOMPLETE_NO_RETRY",
        qualification=quals,
        retained_rows=counts,
        complete_arm_statistics=arms,
        base_off_mmlu=direct,
        recorded_sequences=432,
        planned_sequences=648,
        all_three_arm_comparison="BLOCKED_INCOMPLETE_ON",
        on_full_score=None,
        on_terminal_new_sequences=None,
        failure=dict(
            phase=collision["phase"],
            evaluation_pid=collision["own_pid"],
            competing_pid=cpu_start["pid"],
            competing_gpu_bytes=others[0]["bytes"],
            competing_source=cpu_start["seal"]["source_commit"],
            cpu_counts=cpu_end["counts"],
            attribution="Our parallel CPU qualification became a CUDA client; isolation error.",
            first_cuda_initializing_call="NOT_ISOLATED",
        ),
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true")
    p.add_argument("--verify-publication", action="store_true")
    args = p.parse_args()
    result = verify()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write:
        with (HERE / "TERMINAL_ANALYSIS.json").open("x") as stream:
            stream.write(text)
    if args.verify_publication:
        old.require((HERE / "TERMINAL_ANALYSIS.json").read_text() == text, "Published analysis")
    print(text)
