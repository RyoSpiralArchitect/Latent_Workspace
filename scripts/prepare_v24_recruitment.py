#!/usr/bin/env python3
"""Offline tokenizer/data preparation only; no 7B forwards, targets or updates."""

from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import (  # noqa: E402
    IsolatedQualificationMixin,
    isolate_cli_before_imports,
)

isolate_cli_before_imports()
import run_native_7b_canary as common  # noqa: E402
import run_v22_full_ft as old  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import recruitment_bank as bank  # noqa: E402
from latent_workspace import world_expansion as world  # noqa: E402
from latent_workspace.v22_data import rank  # noqa: E402

ENTRY = "scripts/prepare_v24_recruitment.py"
PLAN = "configs/v24/RECRUITMENT_PREPARATION_01.json"
PASS = "V24_ROUTE_BANK_PREPARED_NO_7B_OR_TRAINING"


def assemble(preservation, raw, tokenizer, plan):
    routes = {route: bank.project(raw, tokenizer, route) for route in bank.ROUTES}
    bank.match_routes(routes["inline"], routes["workspace"])
    for route, rows in routes.items():
        for item in preservation:
            ex.require(
                item["split"] in ("train", "dev")
                and item["language"] == "en"
                and not item["memory_ids"],
                "Train/dev English no-memory preservation",
            )
            ex.require(item["role"] in ("instruction", "prose", "code"), "Preservation role")
            row = dict(
                item,
                route=route,
                source_information_sha256=ex.plan_hash(item),
                target_ids=[t for t in item["labels"] if t != -100],
                duplicate_aliases=[],
            )
            ex.require(len(row["target_ids"]) == row["supervised_tokens"], "Target denominator")
            rows.append(row)
        rows.sort(key=lambda r: r["key"])
        ex.require(len({r["key"] for r in rows}) == len(rows), "Unique row keys")
        groups = {}
        for row in rows:
            ex.require(
                groups.setdefault(row["group_id"], row["split"]) == row["split"], "Group split"
            )
    bank.match_routes(routes["inline"], routes["workspace"])
    windows = bank.schedule(routes["workspace"], plan)
    ex.require(
        windows == bank.schedule(routes["inline"], plan), "Exactly matched training schedule"
    )
    lookup = {r["key"]: r for r in routes["workspace"]}
    exposure, occurrences = Counter(), Counter()
    groups = set()
    for window in windows:
        for key in window:
            row = lookup[key]
            exposure[row["role"]] += row["supervised_tokens"]
            occurrences[row["role"]] += 1
            groups.add(row["group_id"])
    # Engineering canary deliberately covers both routes, not a candidate arm.
    canary_rows = [
        dict(r, key=route + "::" + r["key"])
        for route in bank.ROUTES
        for r in routes[route]
        if r["split"] == "train"
    ]

    def longest(route, role, field, mode=None):
        pool = [
            r
            for r in canary_rows
            if r["route"] == route and r["role"] == role and (mode is None or r.get("mode") == mode)
        ]
        return min(pool, key=lambda r: (-len(r[field]), rank(plan["seed"], r["key"])))

    canary = [
        [r["key"] for r in rows]
        for rows in (
            [
                longest("inline", "instruction", "input_ids"),
                longest("workspace", "world", "memory_ids", "affected"),
                longest("workspace", "reasoning", "memory_ids", "affected"),
                longest("inline", "prose", "input_ids"),
            ],
            [
                longest("workspace", "code", "input_ids"),
                longest("inline", "reasoning", "input_ids", "affected"),
                longest("inline", "world", "input_ids", "unaffected"),
                longest("workspace", "reasoning", "input_ids", "absent"),
            ],
        )
    ]
    dev = []
    for role in ("world", "reasoning"):
        families = sorted({r["family"] for r in routes["workspace"] if r["role"] == role})
        for family in families:
            pool = [
                r
                for r in routes["workspace"]
                if r["role"] == role and r["family"] == family and r["split"] == "dev"
            ]
            group = min({r["group_id"] for r in pool}, key=lambda g: rank(plan["seed"], g))
            dev.extend(r["key"] for r in pool if r["group_id"] == group)
    for role, count in (("instruction", 8), ("prose", 4), ("code", 4)):
        pool = sorted(
            (r for r in preservation if r["role"] == role and r["split"] == "dev"),
            key=lambda r: rank(plan["seed"], r["key"]),
        )
        ex.require(len(pool) >= count, "Preservation development quota")
        dev.extend(r["key"] for r in pool[:count])
    schedule = dict(training=windows, canary=canary, development=dev)
    summary = dict(
        status=PASS,
        training_updates_per_arm=len(windows),
        training_rows_per_arm=sum(occurrences.values()),
        training_tokens_per_arm=sum(exposure.values()),
        training_tokens_by_role=dict(exposure),
        training_rows_by_role=dict(occurrences),
        training_source_groups=len(groups),
        registered_rows_per_arm=len(lookup),
        development_rows_per_route=len(dev),
        routes=list(bank.ROUTES),
        same_training_keys_targets_and_token_budget=True,
        canary_windows=2,
        canary_backward_rows=sum(map(len, canary)),
        maxima={
            route: dict(
                query=max(len(r["input_ids"]) for r in rows),
                memory=max(len(r["memory_ids"]) for r in rows),
            )
            for route, rows in routes.items()
        },
        new_sequences=0,
        native_forward_calls=0,
        native_weight_updates=0,
        judge_calls=0,
        confirmation_model_evaluations=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    return routes, canary_rows, schedule, summary


def validate(plan):
    ex.require(plan["schema"] == "ltws-v24-recruitment-preparation-01" and plan["no_retry"], "Plan")
    ex.require(
        plan["pass_status"] == PASS and plan["qualification_devices"] == ["cpu"], "Data-only scope"
    )
    ex.require(
        plan["native_weight_updates"] == plan["native_forward_calls"] == 0, "No 7B execution"
    )
    recipe = ex.read(ROOT / plan["recipe"])
    ex.require(ex.plan_hash(recipe) == plan["recipe_sha256"], "Frozen route-bank recipe")


def data_role(core, args, plan, seal):
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    ex.require(shutil.disk_usage(args.output).free >= 50 * ex.GIB, "Unchanged disk floor")
    recipe = ex.read(ROOT / plan["recipe"])
    old_plan = ex.read(ROOT / "configs/v22/FULL_FT_RECOVERY_01.json")
    old_rows, _, old_manifest, _ = old.load_data(old_plan)
    preservation = [r for r in old_rows if r["role"] != "world"]
    bp = old_plan["backbone"]
    tokenizer = AutoTokenizer.from_pretrained(
        bp["repository"], revision=bp["revision"], local_files_only=True, trust_remote_code=False
    )
    ex.require(
        tokenizer.eos_token_id == 2 and len(tokenizer) == 32768 and tokenizer.is_fast,
        "Pinned tokenizer",
    )
    cache = Path(
        snapshot_download(bp["repository"], revision=bp["revision"], local_files_only=True)
    )
    tokenizer_files = {
        name: ex.digest(cache / name)
        for name in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")
    }
    # Unchanged earlier bank source is independently re-audited, not taken on trust from a filename.
    world_plan = ex.read(ROOT / recipe["world_plan"])
    raw_world = world.build(world_plan)
    prior = ex.read_gz(ROOT / world_plan["prior_rows"])
    ex.require(
        ex.digest(ROOT / world_plan["prior_rows"]) == world_plan["prior_rows_sha256"], "Old worlds"
    )
    world_audit = world.audit(raw_world, prior, world_plan)
    raw_new = bank.build(recipe)
    raw = [dict(r, role="world") for r in raw_world] + raw_new
    routes, canary_rows, schedule, summary = assemble(preservation, raw, tokenizer, recipe)
    folder = args.output / "bank"
    folder.mkdir(exist_ok=False)
    ex.write_new(folder / "PLAN.json", recipe)
    ex.write_new(folder / "SCHEDULE.json", schedule)
    ex.write_new(folder / "SUMMARY.json", summary)
    ex.write_new(
        folder / "SYNTHETIC_AUDIT.json", dict(reasoning=bank.audit(raw_new), world=world_audit)
    )
    ex.write_gz(folder / "PUBLIC_SYNTHETIC.json.gz", raw)
    ex.write_gz(folder / "PRIVATE_CANARY.json.gz", canary_rows)
    for route, rows in routes.items():
        ex.write_gz(folder / f"PRIVATE_{route}.json.gz", rows)
    sources = [
        ENTRY,
        "src/latent_workspace/recruitment_bank.py",
        "src/latent_workspace/world_expansion.py",
        "src/latent_workspace/world_bank.py",
        "src/latent_workspace/v22_data.py",
        plan["recipe"],
        recipe["world_plan"],
    ]
    ex.write_new(
        folder / "MANIFEST.json",
        dict(
            schema="ltws-v24-route-bank-v1",
            files=ex.manifest(folder),
            source_commit=seal["source_commit"],
            source={name: ex.digest(ROOT / name) for name in sources},
            tokenizer=dict(
                repository=bp["repository"],
                revision=bp["revision"],
                files=tokenizer_files,
                chat_template_sha256=ex.hashlib.sha256(
                    tokenizer.chat_template.encode()
                ).hexdigest(),
            ),
            old_data_manifest_sha256=old_plan["data_manifest_sha256"],
            old_data_source=old_manifest["source"],
            publication=(
                "Private preservation token arrays stay on Furnace; publish only "
                "hashes/counts and synthetic records."
            ),
        ),
    )
    # Read back all written records; a successful producer must not merely assert it wrote them.
    ex.require(ex.read_gz(folder / "PRIVATE_CANARY.json.gz") == canary_rows, "Canary serialization")
    for route in bank.ROUTES:
        ex.require(
            ex.read_gz(folder / f"PRIVATE_{route}.json.gz") == routes[route], "Route serialization"
        )
    return dict(bank_manifest_sha256=ex.digest(folder / "MANIFEST.json"), **summary)


class PreparationRun(IsolatedQualificationMixin, ex.SealedRun):
    pass


RUN = PreparationRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="V24_RECRUITMENT_DATA_TESTS_PASS",
    roles=("data",),
    role_status={"data": PASS},
    validate=validate,
    load=common.load,
)


if __name__ == "__main__":
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(
        RUN.main(
            {"data": data_role}, lambda out, plan: ex.read(out / "data/FINISHED.json")["outcome"]
        )
    )
