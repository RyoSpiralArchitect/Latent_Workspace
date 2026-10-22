"""Publish completed engineering gates while the finite panel audit continues.

Never copies a live row log, calls a model, or labels the parent run complete.
The full terminal publication goes into a DIFFERENT directory afterward.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "66467502064b08b1ea8e246edc6696bd9d35a60e"
PRIVATE = "raw/base/PRIVATE_TEACHER_TARGETS.safetensors"


def verify(root, repo):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace import execution as ex

    m = ex.read(root / "INTERIM_MANIFEST.json")
    actual = ex.manifest(root)
    actual.pop("INTERIM_MANIFEST.json")
    assert actual == m["included"]
    assert m["status"] == "INTERIM_CANARIES_QUALIFIED_PANEL_NOT_COMPLETE"
    assert m["source_commit"] == SOURCE and set(m["omitted"]) == {PRIVATE}
    seal = ex.read(root / "SOURCE_SEAL.json")
    assert seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 761
    for name, sha in seal["source_hashes"].items():
        assert ex.digest(repo / name) == sha
        original = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=repo)
        assert hashlib.sha256(original).hexdigest() == sha
    full = actual | m["omitted"]
    for role in ("qualification/cpu", "qualification/cuda", "raw/base"):
        end = ex.read(root / role / "FINISHED.json")
        assert ex.read(root / role / "STARTED.json")["seal"] == seal
        for name, metadata in end["files"].items():
            assert full[f"{role}/{name}"] == metadata
        if role.startswith("qualification"):
            assert end["counts"] == dict(tests=338, errors=0, failures=0, skipped=0)
            assert end["status"] == "TINY_V23_GRADIENT_SPILL_PASS_NOT_7B"
        else:
            assert end["status"] == "V23_GRADIENT_AUDIT_ARM_COMPLETE"
    assert ex.read(root / "raw/v22/STARTED.json")["seal"] == seal
    assert ex.read(root / "raw/v22/RESTORE.json")["exact"] is True
    for role in ("base", "v22"):
        c = ex.read(root / f"raw/{role}/CANARY.json")
        assert c["parameter_count"] == c["pass_count"] == len(c["parameter_residuals"]) == 291
        assert all(
            r["max_abs_residual"] <= c["atol"] + c["rtol"] * r["left_max_abs"]
            for r in c["parameter_residuals"]
        )
    u = ex.read(root / "raw/base/UNCHANGED.json")
    assert u["native_before"] == u["native_after"]
    t = ex.read(root / "raw/base/TEACHER_TARGETS.json")
    assert len(t["rows"]) == 12 and sum(r["supervised_tokens"] for r in t["rows"]) == 932
    assert t["tensor_bytes"] == 122159104
    assert m["omitted"][PRIVATE] == dict(bytes=t["bytes"], sha256=t["sha256"])
    assert not (root / "raw/FINISHED.json").exists()
    assert not (root / "raw/v22/FINISHED.json").exists()
    return dict(
        status=m["status"],
        cpu_tests=338,
        cuda_tests=338,
        base_canary_tensors=291,
        v22_canary_tensors=291,
        teacher_rows=12,
        teacher_positions=932,
        panel_complete=False,
        checked_at_utc=m["checked_at_utc"],
        **ex.CEILING,
    )


def snapshot(root, repo, output):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace import execution as ex

    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() == SOURCE
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo
    )
    assert not (root / "raw/FINISHED.json").exists()
    assert not (root / "raw/v22/FINISHED.json").exists()
    worker = ex.read(root / "raw/v22/STARTED.json")["pid"]
    os.kill(worker, 0)  # Read-only existence check, not a stop signal.
    names = {
        "SOURCE_SEAL.json",
        "raw/STARTED.json",
        "raw/DISPATCH_base.json",
        "raw/DISPATCH_v22.json",
    }
    omitted = {}
    for role in ("qualification/cpu", "qualification/cuda", "raw/base"):
        end = ex.read(root / role / "FINISHED.json")
        names.add(f"{role}/FINISHED.json")
        for name, metadata in end["files"].items():
            key = f"{role}/{name}"
            assert ex.digest(root / key) == metadata["sha256"]
            if key == PRIVATE:
                omitted[key] = metadata
            else:
                names.add(key)
    for name in (
        "STARTED.json",
        "ORIGINAL_IDENTITY.json",
        "RESTORE.json",
        "INFERENCE_POLICY.json",
        "AUDIT_POLICY.json",
        "CANARY.json",
    ):
        names.add(f"raw/v22/{name}")
    output.mkdir(parents=True, exist_ok=False)
    included = {}
    for name in sorted(names):
        src, dest = root / name, output / name
        expected = dict(bytes=src.stat().st_size, sha256=ex.digest(src))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        assert ex.digest(dest) == expected["sha256"] and src.stat().st_size == expected["bytes"]
        included[name] = expected
    ex.write_new(
        output / "INTERIM_MANIFEST.json",
        dict(
            status="INTERIM_CANARIES_QUALIFIED_PANEL_NOT_COMPLETE",
            source_commit=SOURCE,
            source_worktree_clean=True,
            checked_at_utc=datetime.now(UTC).isoformat(),
            included=included,
            omitted=omitted,
            active_worker_pid_at_snapshot=worker,
            worker_process=subprocess.check_output(
                ["ps", "-p", str(worker), "-o", "pid,etime,pcpu,rss,stat"], text=True
            ),
            source_run=str(root),
            verifier_sha256=ex.digest(Path(__file__)),
            future="Do not overwrite this interim record; publish terminal artifacts separately",
            **ex.CEILING,
        ),
    )
    return verify(output, repo)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("snapshot", "verify"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = (
        snapshot(args.root, args.repo, args.output)
        if args.mode == "snapshot"
        else verify(args.root, args.repo)
    )
    print(json.dumps(result, sort_keys=True))
