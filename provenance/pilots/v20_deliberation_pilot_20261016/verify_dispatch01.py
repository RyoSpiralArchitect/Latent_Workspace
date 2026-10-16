#!/usr/bin/env python3
"""Offline check of V20 D1 dispatch 01, whose endpoint step failed; no model execution.

Every role (extract, 12 arms, replay) passed, but the dispatcher could not import
the package when computing the endpoints, so it wrote no ``ENDPOINTS.json`` and
ended ``INCOMPLETE_NO_RETRY``. This additive check loads the sealed verifier from a
clean checkout of the execution commit (``--repo``) and reuses it unchanged:
sources, qualification, the dispatch binding and every role receipt are verified
as usual; the endpoints are computed by the sealed ``endpoints_for`` from the
verified receipts and handed to the sealed ``verify_results`` through an overlay
directory, the only place a dispatcher-written ``ENDPOINTS.json`` would sit.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

DISPATCH_ERROR = "ModuleNotFoundError: No module named 'latent_workspace_ft_v10'"


def load_verifier(repo):
    path = repo / "scripts/verify_v20_deliberation_pilot.py"
    spec = importlib.util.spec_from_file_location("v20_deliberation_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def overlay(bundle, endpoints, directory):
    for child in bundle.iterdir():
        (directory / child.name).symlink_to(child.resolve())
    (directory / "ENDPOINTS.json").write_text(json.dumps(endpoints, indent=2, sort_keys=True))


def verify(repo, bundle, qualification, seal_path, checkpoints=None):
    VERIFY = load_verifier(repo)
    RUN, require = VERIFY.RUN, VERIFY.require
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace_ft_v10 import v20_deliberation as deliberation

    seal = RUN.read(seal_path)
    VERIFY.verify_sources(seal, repo)
    plan = RUN.read(repo / RUN.PLAN)
    RUN.validate_plan(plan)
    qualified = RUN.qualification(qualification, seal, plan)
    start, end = RUN.read(bundle / "STARTED.json"), RUN.read(bundle / "FINISHED.json")
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch seal/plan")
    require(start["qualification"] == qualified, "Dispatch qualification binding")
    require(
        end["status"] == "INCOMPLETE_NO_RETRY"
        and end["completed_roles"] == RUN.roles(plan)
        and end["error"] == DISPATCH_ERROR,
        "Dispatch 01 receipt",
    )
    require(all(end[k] == v for k, v in RUN.CEILING.items()), "Dispatch ceiling")
    VERIFY.verify_manifest(bundle, end["files"])
    require(not (bundle / "ENDPOINTS.json").exists(), "No dispatcher endpoints exist")
    statuses = {"extract": RUN.EXTRACT_PASS, "replay": RUN.REPLAY_PASS}
    roles = {
        role: VERIFY.verify_role(
            bundle / role, role, seal, plan, qualified, statuses.get(role, RUN.ARM_PASS)
        )
        for role in RUN.roles(plan)
    }
    require(len({roles[r][0]["pid"] for r in roles}) == len(roles), "Distinct processes")
    endpoints = RUN.endpoints_for(bundle, plan)
    with tempfile.TemporaryDirectory() as directory:
        view = Path(directory)
        overlay(bundle, endpoints, view)
        result = VERIFY.verify_results(view, plan, roles, checkpoints, deliberation)
    return {
        "status": "OFFLINE_V20_D1_DISPATCH01_ROLES_PASS_ENDPOINTS_COMPUTED_OFFLINE",
        "source_commit": seal["source_commit"],
        "source_files": len(seal["source_hashes"]),
        "dispatch": {
            "status": end["status"],
            "completed_roles": end["completed_roles"],
            "error": end["error"],
            "endpoints_written_by_dispatcher": False,
        },
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="clean checkout of e18657b")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    result = verify(
        args.repo.resolve(),
        args.bundle,
        args.qualification,
        args.source_seal,
        checkpoints=args.checkpoints,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
