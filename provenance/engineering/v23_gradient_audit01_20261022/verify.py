"""Offline terminal replay/publication. Never imports a model or starts a job."""

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
PASS = "V23_TRAIN_ONLY_GRADIENT_AUDIT_COMPLETE_NOT_TRAINING"
ROLE = "V23_GRADIENT_AUDIT_ARM_COMPLETE"


def verify(root, repo, published):
    sys.path.insert(0, str(repo / "src"))
    from latent_workspace import execution as ex

    all_files = ex.manifest(root)
    omitted = {}
    if published:
        m = ex.read(root / "PUBLICATION_MANIFEST.json")
        all_files.pop("PUBLICATION_MANIFEST.json")
        assert all_files == m["included"]
        omitted = m["omitted"]
        all_files |= omitted
        assert m["source_commit"] == SOURCE and m["source_worktree_clean"]
    seal = ex.read(root / "SOURCE_SEAL.json")
    assert seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 761
    for name, sha in seal["source_hashes"].items():
        original = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=repo)
        assert hashlib.sha256(original).hexdigest() == sha, name
        assert ex.digest(repo / name) == sha, ("Current execution source changed", name)

    def receipt(folder):
        end = ex.read(folder / "FINISHED.json")
        prefix = folder.relative_to(root).as_posix()
        for name, metadata in end["files"].items():
            key = f"{prefix}/{name}"
            assert all_files[key] == metadata, key
        return end

    qualifications = {}
    for device in ("cpu", "cuda"):
        folder = root / "qualification" / device
        result = receipt(folder)
        assert ex.read(folder / "STARTED.json")["seal"] == seal
        assert result["status"] == "TINY_V23_GRADIENT_SPILL_PASS_NOT_7B"
        assert result["counts"] == dict(tests=338, failures=0, errors=0, skipped=0)
        assert result["elapsed_seconds"] < 900
        if device == "cuda":
            assert 0 < result["peak_cuda_allocated_bytes"] <= 4 * ex.GIB
        qualifications[device] = {
            k: result.get(k) for k in ("counts", "elapsed_seconds", "peak_cuda_allocated_bytes")
        }
    terminal = receipt(root / "raw")
    assert terminal["status"] in (PASS, "INCOMPLETE_NO_RETRY")
    assert all(terminal[k] == v for k, v in ex.CEILING.items())
    roles = {}
    for role in ("base", "v22"):
        folder = root / "raw" / role
        if not folder.exists():
            roles[role] = dict(status="UNDISPATCHED")
            continue
        assert ex.read(folder / "STARTED.json")["seal"] == seal
        end = receipt(folder)
        summary = {k: end.get(k) for k in ("status", "error", "elapsed_seconds", "outcome")}
        canary = folder / "CANARY.json"
        if canary.exists():
            c = ex.read(canary)
            assert len(c["parameter_residuals"]) == c["parameter_count"] == 291
            passed = sum(
                r["max_abs_residual"] <= c["atol"] + c["rtol"] * r["left_max_abs"]
                for r in c["parameter_residuals"]
            )
            assert passed == c["pass_count"]
            assert c["full"]["backwards"] == 1 and c["paths"]["backwards"] == 3
            summary["canary"] = dict(key=c["key"], pass_count=passed, total=291)
        unchanged = folder / "UNCHANGED.json"
        if unchanged.exists():
            u = ex.read(unchanged)
            assert u["native_before"] == u["native_after"]
            assert u["peak_cuda_allocated_bytes"] < 30.5 * ex.GIB
            summary["unchanged"] = u
        if end["status"] == ROLE:
            assert unchanged.exists()
        roles[role] = summary
    if roles["base"]["status"] == ROLE:
        t = ex.read(root / "raw/base/TEACHER_TARGETS.json")
        assert len(t["rows"]) == 12 and sum(r["supervised_tokens"] for r in t["rows"]) == 932
        assert t["tensor_bytes"] == 122159104 and t["vocabulary"] == 32768
        assert t["target_dtype"] == "float32" and t["temperature"] == 1.0
        assert all_files["raw/base/PRIVATE_TEACHER_TARGETS.safetensors"] == {
            "bytes": t["bytes"],
            "sha256": t["sha256"],
        }
    if terminal["status"] == PASS:
        assert terminal["completed_roles"] == ["base", "v22"]
        assert roles["base"]["status"] == roles["v22"]["status"] == ROLE
        audit = ex.read(root / "raw/v22/AUDIT.json")
        assert audit == terminal["summary"] == roles["v22"]["outcome"]
        assert (audit["world_rows"], audit["world_groups"], audit["preservation_rows"]) == (
            84,
            14,
            12,
        )
        for term, summary in audit["summaries"].items():
            rows = [
                json.loads(line)
                for line in (root / f"raw/v22/{term}.jsonl").read_text().splitlines()
            ]
            assert len(rows) == summary["rows"]
            assert sum(r["loss"] for r in rows) == summary["loss"]
            assert summary["spill"]["backwards"] == len(rows) - len(summary["zero_component_rows"])
            for ref in ("ce", "kl"):
                if f"vs_{ref}" not in summary:
                    continue
                pairs = ex.read(root / f"raw/v22/{term}_VS_{ref}.json")
                assert len(pairs) == 291
                dot = sum(r["dot"] for r in pairs)
                a, b = (sum(r[k] for r in pairs) for k in ("left_sq", "right_sq"))
                expected = summary[f"vs_{ref}"]
                assert dot == expected["dot"]
                assert expected["cosine"] == (dot / (a * b) ** 0.5 if a and b else None)
        assert ex.read(root / "raw/v22/SCRATCH_RETIRED.json")["files"] == 2
        assert not any("SCRATCH_" in key and key.endswith(".safetensors") for key in all_files)
    assert not list((root / "no-real-checkpoint-writes").glob("*"))
    return dict(
        status=terminal["status"],
        source_commit=SOURCE,
        source_files=761,
        qualifications=qualifications,
        roles=roles,
        completed_roles=terminal["completed_roles"],
        error=terminal.get("error"),
        **ex.CEILING,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.repo, published=args.mode == "verify")
    if args.mode == "snapshot":
        from latent_workspace import execution as ex

        assert (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip()
            == SOURCE
        )
        assert not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=args.repo
        )
        for start in args.root.rglob("STARTED.json"):
            pid = ex.read(start).get("pid")
            if pid is None:
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            raise RuntimeError(f"Recorded PID {pid} exists; inspect before snapshot")
        files = ex.manifest(args.root)
        private = {k: files.pop(k) for k in list(files) if k.endswith(".safetensors")}
        assert all(
            k == "raw/base/PRIVATE_TEACHER_TARGETS.safetensors"
            or (k.startswith("raw/v22/SCRATCH_") and k.endswith(".safetensors"))
            for k in private
        )
        ex.write_new(
            args.root / "PUBLICATION_MANIFEST.json",
            dict(
                source_commit=SOURCE,
                source_worktree_clean=True,
                recorded_workers_absent=True,
                checked_at_utc=datetime.now(UTC).isoformat(),
                included=files,
                omitted=private,
                disk_free_bytes=shutil.disk_usage(args.root).free,
                gpu_processes=subprocess.check_output(
                    ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
                    text=True,
                ),
                result=result,
                verifier_sha256=ex.digest(Path(__file__)),
            ),
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
