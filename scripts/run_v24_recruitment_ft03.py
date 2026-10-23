#!/usr/bin/env python3
"""New audit-only source/attempt; original V24 numerical bodies remain unchanged."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import isolate_cli_before_imports  # noqa: E402

isolate_cli_before_imports()
from qualification_isolation_v2 import IsolatedQualificationMixin  # noqa: E402

# Separate module namespace: qualification tests can import/mock the old runner
# without mutating this attempt's dispatcher. The entire original file remains
# source-sealed and byte-for-byte unchanged, including all numerical functions.
spec = importlib.util.spec_from_file_location(
    f"_v24_ft03_body_{__name__}", ROOT / "scripts/run_v24_recruitment_ft.py"
)
body = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = body
spec.loader.exec_module(body)
ex = body.ex
ENTRY = "scripts/run_v24_recruitment_ft03.py"
PLAN = "configs/v24/RECRUITMENT_FT_03.json"
OLD_PLAN = "configs/v24/RECRUITMENT_FT_01.json"
OLD_PLAN_SHA = "57f8995d6decda911b0c237f4753d682459b88636c2bde102d7b3f379adcc1f2"
OLD_AUDIT = (
    "provenance/engineering/v24_recruitment_ft02_20261023/"
    "latent-v24-recruitment-ft02-20261023/qualification/CPU_ISOLATION.json"
)
OLD_AUDIT_SHA = "ead025364dde04d9b5ea6b8c876b318523c1f1eaeefa37341a05998bae09a127"
ADDED_TESTS = ["tests/test_qualification_observer.py", "tests/test_v24_recruitment_ft03.py"]


def validate(plan):
    old = ex.read(ROOT / OLD_PLAN)
    body.validate(plan)
    ex.require(ex.plan_hash(old) == OLD_PLAN_SHA, "Original FT protocol unchanged")
    fields = {"qualification_cases", "qualification_test_files", "audit_recovery"}
    ex.require(
        {k: v for k, v in plan.items() if k not in fields}
        == {k: v for k, v in old.items() if k not in fields},
        "No numerical, data, source-recipe, safety or claim changes",
    )
    ex.require(
        plan["qualification_test_files"] == old["qualification_test_files"] + ADDED_TESTS,
        "Keep all original tests and add audit regressions",
    )
    ex.require(plan["qualification_cases"] == 608, "Exact expanded qualification count")
    ex.require(ex.digest(ROOT / OLD_AUDIT) == OLD_AUDIT_SHA, "Original failed audit preserved")
    ex.require(
        plan["audit_recovery"]
        == dict(
            original_audit=OLD_AUDIT,
            original_audit_sha256=OLD_AUDIT_SHA,
            original_source="d43382833f6dc85787720bda80aec511c66f58be",
            observer="scripts/qualification_observer.py",
            root_cause="UNKNOWN; original recorded only ValueError",
            change="Separate observer process with strict, bounded command/parse diagnostics",
        ),
        "Explicit observer-only recovery identity",
    )


class RouteRun(IsolatedQualificationMixin, ex.SealedRun):
    pass


RUN = RouteRun(
    root=ROOT,
    entry=ENTRY,
    plan_path=PLAN,
    tiny_pass="V24_ROUTE_FT_TINY_PASS_NOT_7B",
    roles=body.ROLES,
    role_status=body.STATUSES,
    validate=validate,
    load=body.common.load,
    updates_native=True,
)
body.RUN, body.ENTRY = RUN, ENTRY


if __name__ == "__main__":
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["LTWS_CPU_SDPA_BACKEND"] = "math"
    raise SystemExit(body.main())
