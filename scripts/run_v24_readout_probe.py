#!/usr/bin/env python3
"""New sealed, zero-update readout diagnostic; never starts training or judging."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from qualification_isolation import (  # noqa: E402
    IsolatedQualificationMixin,
    isolate_cli_before_imports,
)

isolate_cli_before_imports()
import run_v23_comparison as previous  # noqa: E402
from v23_generation_cache import GenerationBoundaryGuard  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import readout_audit as audit  # noqa: E402

ENTRY = "scripts/run_v24_readout_probe.py"
PLAN = "configs/v24/READOUT_PROBE_01.json"
CASES = "configs/v24/readout_probe01/CASES.json.gz"
MMLU = "provenance/pilots/v23_mmlu_pro01_20261022/furnace/inputs"
WORLDS = "provenance/pilots/v22_base_comparison01_20261021/furnace/inputs"
ROLES = ("base", "off", "on")


def prior_inputs(folder):
    path = ROOT / folder
    manifest = ex.read(path / "MANIFEST.json")
    files = ex.manifest(path)
    files.pop("MANIFEST.json")
    ex.require(files == manifest["files"], "Unchanged prior input bytes")
    for name, digest in manifest["source"].items():
        ex.require(ex.digest(ROOT / name) == digest, "Unchanged prior input implementation")
    data = ex.read_gz(path / "INPUTS.json.gz")
    ex.require(data["plan_sha256"] == manifest["plan_sha256"], "Prior input plan")
    return data, dict(path=folder, manifest_sha256=ex.digest(path / "MANIFEST.json"))


def make_cases(tokenizer, plan):
    """Frozen exposed failure probes, not a new benchmark or training dataset."""
    from latent_workspace.objective_audit import oracle_partition

    mmlu, mmlu_origin = prior_inputs(MMLU)
    world, world_origin = prior_inputs(WORLDS)
    ex.require(tokenizer.eos_token_id == 2, "Pinned tokenizer EOS")
    cases = []

    def add(key, family, prefix, target, stages, memory=(), probes=()):
        spec = audit.ReadoutSpec(tuple(prefix), tuple(target), tuple(stages), 2, tuple(probes))
        ex.require(len(prefix) + len(target) <= 4096 and len(memory) <= 128, "Probe token bounds")
        cases.append(dict(id=key, family=family, spec=spec.record(), memory_ids=list(memory)))

    def label_continuation(text, letter):
        prefix = tokenizer.encode(text, add_special_tokens=False)
        full = tokenizer.encode(text + letter, add_special_tokens=False)
        ex.require(
            full[: len(prefix)] == prefix and len(full) > len(prefix), "Stable label boundary"
        )
        return prefix, full[len(prefix) :]

    by_id = {r["id"]: r for r in mmlu["rows"]}
    for uid in plan["mmlu_ids"]:
        row = by_id[uid]
        target = row["choice_ids"][row["target"]]
        letter = chr(65 + row["target"])
        add(
            f"{uid}/direct",
            "binding",
            row["input_ids"],
            [target],
            ["binding"],
            probes=row["choice_ids"],
        )
        # Target=EOS here is a stopping-pressure observation, NOT a correct answer.
        add(f"{uid}/start_eos", "stopping", row["reasoning_ids"], [2], ["stop"])
        content = f" The result is {row['options'][row['target']]}.\n"
        for tag, text in (
            ("unassisted_label", " The answer is ("),
            ("oracle_content_label", content + "The answer is ("),
        ):
            prefix, answer = label_continuation(text, letter)
            probe_tokens = []
            for candidate in range(len(row["options"])):
                p, a = label_continuation(text, chr(65 + candidate))
                ex.require(p == prefix and len(a) == 1, "Single stable diagnostic option token")
                probe_tokens.append(a[0])
            add(
                f"{uid}/{tag}",
                "binding",
                row["reasoning_ids"] + prefix,
                answer,
                ["binding"] * len(answer),
                probes=probe_tokens,
            )
        completed = tokenizer.encode(
            content + f"The answer is ({letter}).", add_special_tokens=False
        )
        add(f"{uid}/complete_eos", "stopping", row["reasoning_ids"] + completed, [2], ["stop"])

    selected_groups = []
    for family in plan["world_families"]:
        pool = [r for r in world["worlds"] if r["family"] == family and r["mode"] == "affected"]
        group = min(r["group_id"] for r in pool)
        selected_groups.append(group)
        twin = sorted((r for r in pool if r["group_id"] == group), key=lambda r: r["side"])
        ex.require(len(twin) == 2 and [r["side"] for r in twin] == [0, 1], "Exact twin pair")
        ex.require(
            twin[0]["prefixes"]["latent"] == twin[1]["prefixes"]["latent"], "Twin query parity"
        )
        for reference in twin:
            ids = reference["answer_ids"]
            partition = oracle_partition(
                tokenizer, reference["answer_value"], [r["answer_value"] for r in twin]
            )
            ex.require(partition["input_ids"] == ids, "Original oracle continuation tokenization")
            roles = {
                "identity": "content",
                "copy": "copy",
                "format": "format",
                "mixed": "unclassified",
            }
            stages = [
                "stop" if t == 2 else roles[p] for t, p in zip(ids, partition["parts"], strict=True)
            ]
            for label, memory in (
                ("s0", twin[0]["memory_ids"]),
                ("s1", twin[1]["memory_ids"]),
                ("empty", []),
            ):
                add(
                    f"{group}/ref{reference['side']}/{label}",
                    "world_content",
                    reference["prefixes"]["latent"],
                    ids,
                    stages,
                    memory,
                )
    return dict(
        schema="ltws-v24-readout-cases-v1",
        exposure="EXPOSED_DIAGNOSTIC_NOT_TRAINING_OR_CONFIRMATION",
        origins=[mmlu_origin, world_origin],
        selected_world_groups=selected_groups,
        cases=cases,
        forwards_per_arm=sum(len(c["spec"]["continuation"]) for c in cases),
    )


def load_cases(plan):
    value = ex.read_gz(ROOT / CASES)
    ex.require(ex.plan_hash(value) == plan["cases_sha256"], "Frozen readout inputs")
    ex.require(len(value["cases"]) == plan["cases_per_arm"], "Case denominator")
    ex.require(value["forwards_per_arm"] == plan["forwards_per_arm"], "Forward denominator")
    return value


def validate(plan):
    ex.require(plan["schema"] == "ltws-v24-readout-probe-01" and plan["no_retry"], "Plan identity")
    ex.require(plan["roles"] == list(ROLES), "Three original checkpoint arms")
    ex.require(
        plan["native_weight_updates"]
        == plan["new_sequences"]
        == plan["checkpoint_saves"]
        == plan["judge_calls"]
        == plan["weight_deletions"]
        == 0,
        "Read-only scope",
    )
    ex.require(plan["full_ft_dispatch"] is False, "FT is a separate decision after diagnosis")
    parent = ex.read(ROOT / previous.PLAN)
    previous.validate(parent)
    ex.require(plan["resources"] == parent["resources"], "Same admitted resource floors")
    load_cases(plan)


def run(core, args, plan, seal):
    from latent_workspace.optimizer_state import tree_hash

    previous.common.engine_imports(seal)
    data = load_cases(plan)
    graph, tokenizer, guard, before = previous.prepare(core, args, ex.read(ROOT / previous.PLAN))
    ex.require(make_cases(tokenizer, plan) == data, "Exact runtime tokenizer/input replay")
    ex.write_new(args.output / "INPUTS.json", data)
    count = 0
    with (
        (args.output / "READOUT.jsonl").open("x") as journal,
        (args.output / "CACHE.jsonl").open("x") as cache_journal,
    ):
        boundary = GenerationBoundaryGuard(guard, next(graph.parameters()).device, cache_journal)
        for case in data["cases"]:
            value = case["spec"]
            spec = audit.ReadoutSpec(
                tuple(value["prefix"]),
                tuple(value["continuation"]),
                tuple(value["stages"]),
                value["eos"],
                tuple(value["probes"]),
            )
            result = audit.trace_continuation(
                graph,
                spec,
                tuple(case["memory_ids"]),
                guard=lambda phase: boundary(f"generation:readout:{case['id']}:{phase}"),
            )
            previous.previous.append(
                journal, dict(id=case["id"], family=case["family"], trace=result)
            )
            count += result["native_forward_calls"]
            print(
                f"{args.role}: {case['id']} ({count}/{data['forwards_per_arm']} forwards)",
                flush=True,
            )
    after = tree_hash(graph.model.state_dict())
    ex.write_new(args.output / "WEIGHT_IDENTITY.json", dict(before=before, after=after))
    ex.require(before == after and count == data["forwards_per_arm"], "Read-only complete arm")
    return dict(
        cases=len(data["cases"]),
        native_forward_calls=count,
        new_sequences=0,
        native_weight_updates=0,
        checkpoint_saves=0,
        engine_imports=previous.common.engine_imports(seal),
        **previous.common.peak(),
    )


def summary(folder, plan):
    ends = [ex.read(folder / r / "FINISHED.json")["outcome"] for r in ROLES]
    ex.require(
        all(
            e["cases"] == plan["cases_per_arm"]
            and e["native_forward_calls"] == plan["forwards_per_arm"]
            for e in ends
        ),
        "All readout denominators",
    )
    ex.require(not list((folder.parent / "checkpoints").iterdir()), "No saved weights")
    return dict(
        native_forward_calls=sum(e["native_forward_calls"] for e in ends),
        new_sequences=0,
        native_weight_updates=0,
        checkpoint_saves=0,
    )


class ReadoutRun(IsolatedQualificationMixin, ex.SealedRun):
    def activity(self, result, outcome=None):
        result["native_forward_calls"] = (
            None if outcome is None else outcome["native_forward_calls"]
        )


RUN = ReadoutRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="TINY_V24_READOUT_PASS_NOT_7B",
    roles=ROLES,
    role_status={r: "V24_READOUT_ARM_COMPLETE_NOT_QUALITY" for r in ROLES},
    validate=validate,
    load=previous.common.load,
)

if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    if len(sys.argv) == 4 and sys.argv[1] == "prepare-cases":
        from transformers import AutoTokenizer

        ex.offline_environment()
        tok = AutoTokenizer.from_pretrained(
            sys.argv[2], local_files_only=True, trust_remote_code=False
        )
        output = Path(sys.argv[3])
        output.parent.mkdir(parents=True, exist_ok=True)
        data = make_cases(tok, ex.read(ROOT / PLAN))
        ex.write_gz(output, data)
        print(
            ex.canonical(
                dict(
                    cases=len(data["cases"]),
                    forwards_per_arm=data["forwards_per_arm"],
                    cases_sha256=ex.plan_hash(data),
                )
            )
        )
    else:
        raise SystemExit(RUN.main({r: run for r in ROLES}, summary))
