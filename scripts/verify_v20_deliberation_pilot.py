#!/usr/bin/env python3
"""Offline receipt verification of the V20 Deliberation pilot (D1); no model execution.

Rehashes the sealed sources, both qualification bundles, the dispatch and every
role manifest. Recomputes every correctness flag from the saved adapted logits
and row labels, the step-0 base equality, the pre-registered endpoints and
verdict, the fresh-process replay and the pre-declared descriptive tables.
Feature files (several GB) and checkpoint bodies are rehashed only where they
are present: run it on Furnace with ``--checkpoints`` for the complete check.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "v20_deliberation_contract", Path(__file__).with_name("run_v20_deliberation_pilot.py")
)
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)
LARGE = re.compile(r"(^|/)FEATURES_[a-z]+\.safetensors$")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify_manifest(folder, expected):
    """Every listed file must match; only large feature files may be absent."""
    actual = RUN.v19().manifest(folder)
    actual.pop("FINISHED.json", None)
    for name in expected:
        pure = PurePosixPath(name)
        require(str(pure) == name and not pure.is_absolute() and ".." not in pure.parts, name)
    missing = sorted(set(expected) - set(actual))
    require(all(LARGE.search(name) for name in missing), f"Missing receipts: {missing}")
    require(set(actual) <= set(expected), f"Unlisted files in {folder}")
    require(
        all(actual[n] == expected[n] for n in actual), f"Artifact bytes/manifest mismatch: {folder}"
    )
    return [n for n in expected if n not in missing and LARGE.search(n)]


def verify_sources(seal, repo):
    require(set(seal) == {"source_commit", "source_hashes"}, "Seal schema")
    require(re.fullmatch(r"[0-9a-f]{40}", seal["source_commit"]) is not None, "Seal commit")
    needed = {
        RUN.ENTRY,
        RUN.PLAN,
        "scripts/run_source_sealed.py",
        "scripts/verify_v20_deliberation_pilot.py",
        "scripts/run_v19_frozen_diagnostic.py",
        "tests/test_v20_deliberation.py",
        "src/latent_workspace_ft_v10/v20_deliberation.py",
        "src/latent_workspace_ft_v10/engine.py",
        "src/latent_workspace_ft_v10/workspace_core.py",
    }
    require(needed <= set(seal["source_hashes"]), "Critical source missing from seal")
    for name, digest in seal["source_hashes"].items():
        path = repo / name
        require(path.resolve().is_relative_to(repo.resolve()) and not path.is_symlink(), name)
        require(RUN.v19().digest(path) == digest, f"Source content changed: {name}")


def verify_role(bundle, role, seal, plan, qualified, status):
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["role"] == end["role"] == role, f"{role} identity")
    require(start["seal"] == seal and start["plan"] == plan, f"{role} seal/plan")
    require(start["qualification"] == qualified, f"{role} qualification binding")
    require(end["status"] == status, f"{role} did not pass: {end.get('error')}")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), f"{role} ceiling")
    rehashed = verify_manifest(bundle, end["files"])
    return start, end, rehashed


def correct(adapted, rows):
    return [a[r["label"]] > a[1 - r["label"]] for a, r in zip(adapted, rows, strict=True)]


def accuracy(flags):
    return sum(flags) / len(flags)


def strata(flags, rows):
    tables = {}
    for key, value in (
        ("hop", lambda r: str(r["hop"])),
        ("affected", lambda r: "affected" if r["affected"] else "unaffected"),
        ("wording", lambda r: r["wording"]),
    ):
        groups = {}
        for flag, row in zip(flags, rows, strict=True):
            groups.setdefault(value(row), []).append(flag)
        tables[key] = {k: [sum(v), len(v)] for k, v in sorted(groups.items())}
    return tables


def content_following(flags, rows):
    """Affected (world, query) pairs answered right on both the intact and twin side."""
    sides = {}
    for flag, row in zip(flags, rows, strict=True):
        if row["affected"]:
            sides.setdefault((row["world"], row["query"]), []).append(flag)
    return [sum(all(v) for v in sides.values()), len(sides)]


def verify_arm(bundle, plan, role, rows, checkpoints):
    spec, _ = RUN.parse_role(plan, role)
    record = {}
    for split in ("dev", "final"):
        base = [r["base_logits"] for r in rows[split]]
        for step in plan[f"{split}_evaluation_steps"]:
            saved = RUN.v19().read_gz(bundle / f"eval_{split}_step{step}.json.gz")
            flags = correct(saved["adapted_logits"], rows[split])
            require(saved["correct"] == flags, f"{role} {split} {step} correctness")
            if step == 0:
                require(saved["adapted_logits"] == base, f"{role} {split} step 0 not base")
            record[f"{split}:{step}"] = flags
    if spec["steps"] > 1:
        for steps in plan["truncation_steps"]:
            if steps < spec["steps"]:
                saved = RUN.v19().read_gz(
                    bundle / f"eval_final_step{plan['endpoints']['step']}_k{steps}.json.gz"
                )
                flags = correct(saved["adapted_logits"], rows["final"])
                require(saved["correct"] == flags, f"{role} truncation {steps}")
                record[f"final:{plan['endpoints']['step']}:k{steps}"] = flags
    updates = [json.loads(line) for line in (bundle / "updates.jsonl").read_text().splitlines()]
    require(
        [u["step"] for u in updates] == list(range(1, plan["training"]["updates"] + 1)),
        f"{role} update log",
    )
    prints = RUN.read(bundle / "FINGERPRINTS.json")
    expected = {
        0,
        *plan["checkpoint_steps"],
        plan["replay"]["execute_step"],
        plan["training"]["updates"],
    }
    require(set(map(int, prints)) == expected, f"{role} fingerprints")
    for step in plan["checkpoint_steps"]:
        receipt = RUN.read(bundle / f"CHECKPOINT_step{step}.json")
        require(
            receipt["completed_steps"] == step and receipt["fingerprint"] == prints[str(step)],
            f"{role} checkpoint {step}",
        )
        if checkpoints is not None:
            body = checkpoints / role / receipt["path"]
            require(
                body.stat().st_size == receipt["bytes"]
                and RUN.v19().digest(body) == receipt["sha256"],
                f"{role} checkpoint bytes",
            )
    gates = [u["gate_mean"] for u in updates]
    residual = [u["delta_abs_mean"] for u in updates]
    summary = {
        "steps": spec["steps"],
        "workspace_loss_weight": spec["workspace_loss_weight"],
        "dev_curve": {k: accuracy(v) for k, v in record.items() if k.startswith("dev:")},
        "final_accuracy": accuracy(record[f"final:{plan['endpoints']['step']}"]),
        "truncated_final_accuracy": {
            k.rsplit(":", 1)[1]: accuracy(v) for k, v in record.items() if ":k" in k
        },
        "first_last_task_loss": [updates[0]["task_loss"], updates[-1]["task_loss"]],
        "gate_mean_last": gates[-1],
        "residual_abs_mean_last": residual[-1],
    }
    return record, summary


def verify(bundle, qualification, seal_path, repo=ROOT, checkpoints=None):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace_ft_v10 import v20_deliberation as deliberation

    seal = RUN.read(seal_path)
    verify_sources(seal, repo)
    plan = RUN.read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    qualified = RUN.qualification(qualification, seal, plan)
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    require(start["qualification"] == qualified, "Dispatch qualification binding")
    require(end["status"] == RUN.PASS and end["completed_roles"] == RUN.roles(plan), "Dispatch")
    require(all(end[k] == v for k, v in RUN.CEILING.items()), "Dispatch ceiling")
    verify_manifest(bundle, end["files"])
    statuses = {"extract": RUN.EXTRACT_PASS, "replay": RUN.REPLAY_PASS}
    roles = {
        role: verify_role(
            bundle / role, role, seal, plan, qualified, statuses.get(role, RUN.ARM_PASS)
        )
        for role in RUN.roles(plan)
    }
    require(len({roles[r][0]["pid"] for r in roles}) == len(roles), "Distinct processes")
    result = verify_results(bundle, plan, roles, checkpoints, deliberation)
    require(end["verdict"] == result["verdict"], "Dispatch verdict")
    return {
        "status": "OFFLINE_V20_DELIBERATION_PILOT_RECEIPT_PASS",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        **result,
        "resources": {
            role: {
                k: roles[role][1].get(k)
                for k in (
                    "elapsed_seconds",
                    "peak_cuda_allocated_bytes",
                    "peak_cuda_reserved_bytes",
                )
            }
            for role in roles
        },
        "forward_calls": 0,
        **RUN.CEILING,
    }


def verify_results(bundle, plan, roles, checkpoints, deliberation):
    """Content checks on receipts; ``roles`` maps role -> (STARTED, FINISHED, rehashed)."""
    rows = {s: RUN.v19().read_gz(bundle / "extract" / f"ROWS_{s}.json.gz") for s in RUN.SPLITS}
    outcome = roles["extract"][1]["outcome"]
    for split in RUN.SPLITS:
        receipt = outcome["splits"][split]
        require(
            receipt["rows"] == len(rows[split]) == 16 * plan["data"][split]["world_pairs"]
            and receipt["tokens"] == sum(len(r["prompt_ids"]) for r in rows[split])
            and receipt["base_inline_correct"]
            == sum(correct([r["base_logits"] for r in rows[split]], rows[split])),
            f"Extraction receipt {split}",
        )
    records, summaries = {}, {}
    for role in RUN.seed_roles(plan):
        records[role], summaries[role] = verify_arm(bundle / role, plan, role, rows, checkpoints)
    endpoints = RUN.endpoints_for(bundle, plan)
    require(RUN.read(bundle / "ENDPOINTS.json") == json.loads(json.dumps(endpoints)), "Endpoints")
    replay = RUN.read(bundle / "replay" / "REPLAY.json")
    rule = plan["replay"]
    source = f"{rule['arm']}_s{plan['seeds'].index(rule['seed']) + 1}"
    arm_updates = (bundle / source / "updates.jsonl").read_text().splitlines()
    require(
        replay["exact"] is True
        and replay["role"] == source
        and replay["replayed_fingerprint"]
        == RUN.read(bundle / source / "FINGERPRINTS.json")[str(rule["execute_step"])]
        and replay["update"] == json.loads(arm_updates[rule["execute_step"] - 1])
        and replay["arm_pid"] == roles[source][0]["pid"]
        and replay["replay_pid"] == roles["replay"][0]["pid"],
        "Replay identity",
    )
    step = plan["endpoints"]["step"]
    base = correct([r["base_logits"] for r in rows["final"]], rows["final"])
    descriptive = {
        "base_inline": {
            "final_accuracy": accuracy(base),
            "strata": strata(base, rows["final"]),
            "content_following": content_following(base, rows["final"]),
        }
    }
    for role, record in records.items():
        flags = record[f"final:{step}"]
        descriptive[role] = {
            **summaries[role],
            "strata": strata(flags, rows["final"]),
            "content_following": content_following(flags, rows["final"]),
            "repairs": sum(f and not b for f, b in zip(flags, base, strict=True)),
            "regressions": sum(b and not f for f, b in zip(flags, base, strict=True)),
            "gain_over_base": deliberation.gain(
                flags, base, [r["world"] for r in rows["final"]], plan["endpoints"]
            ),
        }
    return {
        "verdict": endpoints["verdict"],
        "endpoints": endpoints,
        "descriptive": descriptive,
        "extraction": outcome["splits"],
        "replay_exact": True,
        "features_rehashed": roles["extract"][2],
        "checkpoint_bodies_rehashed": checkpoints is not None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    result = verify(args.bundle, args.qualification, args.source_seal, checkpoints=args.checkpoints)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
