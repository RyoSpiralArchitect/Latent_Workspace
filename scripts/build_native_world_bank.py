#!/usr/bin/env python3
"""Build/audit a deterministic bank; no model calls or training."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import world_bank as wb  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = ex.read(ROOT / "configs/v1_0/WORLD_BANK_01.json")
    if args.command == "build":
        args.output.mkdir(parents=True, exist_ok=False)
        rows, instructions = wb.build(plan)
        summary = wb.audit(rows, instructions)
        inputs = wb.teacher_inputs(rows, instructions, plan)
        ex.write_new(args.output / "PLAN.json", plan)
        ex.write_gz(args.output / "world_rows.json.gz", rows)
        ex.write_new(args.output / "instruction_seeds.json", instructions)
        ex.write_new(args.output / "teacher_inputs.json", inputs)
        ex.write_new(args.output / "AUDIT.json", summary)
        ex.write_new(
            args.output / "MANIFEST.json",
            dict(
                source_commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                files=ex.manifest(args.output),
                plan_sha256=ex.plan_hash(plan),
                generator_sha256=ex.digest(ROOT / "src/latent_workspace/world_bank.py"),
            ),
        )
    else:
        manifest = ex.read(args.output / "MANIFEST.json")
        actual = ex.manifest(args.output)
        actual.pop("MANIFEST.json")
        ex.require(actual == manifest["files"], "Bank bytes changed")
        ex.require(ex.read(args.output / "PLAN.json") == plan, "Bank plan differs")
        rows = ex.read_gz(args.output / "world_rows.json.gz")
        instructions = ex.read(args.output / "instruction_seeds.json")
        summary = wb.audit(rows, instructions)
        ex.require(summary == ex.read(args.output / "AUDIT.json"), "Audit replay differs")
        expected_rows, expected_instructions = wb.build(plan)
        ex.require(
            rows == expected_rows and instructions == expected_instructions, "Regeneration differs"
        )
        ex.require(
            wb.teacher_inputs(rows, instructions, plan)
            == ex.read(args.output / "teacher_inputs.json"),
            "Teacher selection differs",
        )
    print(ex.canonical(summary))


if __name__ == "__main__":
    main()
