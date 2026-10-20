#!/usr/bin/env python3
"""Source-sealed tiny CPU/CUDA qualification; no 7B or training role is exposed."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import execution as ex  # noqa: E402

ENTRY = "scripts/qualify_native_owner.py"
PLAN = "configs/v1_0/NATIVE_OWNER_QUALIFICATION.json"
PLAN_SHA256 = "3d91c6e01bcb7f053f667563c72fac15f8ede01c0f27c7e66bf910985a667b68"
PASS = "TINY_NATIVE_OWNER_AND_REPLAY_PASS_NOT_7B"


def load(name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def validate(plan):
    ex.require(ex.plan_hash(plan) == PLAN_SHA256, "Frozen native-owner qualification plan changed")
    ex.require(plan["full_7b_dispatch"] is False and plan["retry"] is False, "Tiny no-retry scope")
    ex.require(plan["scratch_cpu_sdpa_backend"] == "math", "Explicit scratch CPU backend")


RUN = ex.SealedRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass=PASS,
    roles=(),
    role_status={},
    validate=validate,
    load=load,
)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("prepare-seal", "qualify"):
        raise SystemExit("Only prepare-seal and qualify are authorized by this entry")
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    # Applies only to the scratch fixture's CPU calls, also in graph-only CPU
    # tests within the CUDA suite. HF eager and native CUDA policies stay put.
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(RUN.main({}, None))
