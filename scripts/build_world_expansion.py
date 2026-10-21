#!/usr/bin/env python3
"""Build/verify additive oracle worlds. No model execution; no old-bank edits."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import world_expansion as wb  # noqa: E402


def run(command, output):
    ex.require(command in ("build", "verify"), "Command")
    plan = ex.read(ROOT / "configs/v23/WORLD_BANK_02.json")
    prior = ROOT / plan["prior_rows"]
    ex.require(ex.digest(prior) == plan["prior_rows_sha256"], "Prior bank identity")
    rows = wb.build(plan)
    summary = wb.audit(rows, ex.read_gz(prior), plan)
    if command == "build":
        output.mkdir(parents=True, exist_ok=False)
        ex.write_new(output / "PLAN.json", plan)
        for split in ("train", "dev", "confirmation", "ood"):
            ex.write_gz(output / f"{split}.json.gz", [r for r in rows if r["split"] == split])
        ex.write_new(output / "AUDIT.json", summary)
        ex.write_new(
            output / "MANIFEST.json",
            dict(
                source_commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                generator_sha256=ex.digest(ROOT / "src/latent_workspace/world_expansion.py"),
                plan_sha256=ex.plan_hash(plan),
                files=ex.manifest(output),
            ),
        )
    else:
        manifest = ex.read(output / "MANIFEST.json")
        actual = ex.manifest(output)
        actual.pop("MANIFEST.json")
        ex.require(actual == manifest["files"], "Bank bytes changed")
        ex.require(ex.read(output / "PLAN.json") == plan, "Plan mismatch")
        ex.require(ex.read(output / "AUDIT.json") == summary, "Audit mismatch")
        for split in ("train", "dev", "confirmation", "ood"):
            ex.require(
                ex.read_gz(output / f"{split}.json.gz") == [r for r in rows if r["split"] == split],
                "Split regeneration",
            )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(ex.canonical(run(args.command, args.output)))


if __name__ == "__main__":
    main()
