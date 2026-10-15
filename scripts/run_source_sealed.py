#!/usr/bin/env python3
"""Check a committed execution tree BEFORE importing its code, then launch -I.

This additive entry point is for new, explicitly authorized runs. It does not
repair or reissue historical execution receipts. The interpreter/environment
is a separately trusted runtime; this is a provenance guard, not a sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo)


def safe_source(repo, name):
    if not isinstance(name, str):
        raise ValueError("Source paths must be strings")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in ("..", ".git") for p in path.parts):
        raise ValueError("Source path escapes the execution tree")
    target = repo.joinpath(*path.parts)
    if not target.is_file() or any(p.is_symlink() for p in [target, *target.parents] if p != repo):
        raise ValueError("Source must be an existing nonsymlink file")
    return target


def verify(repo, seal, entry):
    """Standard library only. No model, repository or third-party imports."""
    repo = Path(repo).resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        raise ValueError("Expected the exact checkout root")
    if git(repo, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("Dirty execution source (including untracked files)")
    # -I removes cwd/script-dir/PYTHONPATH. Repository import roots are later
    # added by the authorized entry, so ignored importable code is checked too.
    ignored = (
        git(
            repo,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            "src",
            "scripts",
        )
        .decode()
        .split("\0")
    )
    import_suffixes = {".py", ".pyc", ".pyo", ".so", ".pyd", ".zip"}
    for name in filter(None, ignored):
        path = PurePosixPath(name)
        # A fresh pycache_prefix below prevents loading these cached files.
        if path.suffix in import_suffixes and "__pycache__" not in path.parts:
            raise ValueError(f"Ignored importable source is unsealed: {name}")
    tracked = set(git(repo, "ls-files", "-z").decode().split("\0")) - {""}
    for name in tracked:
        if PurePosixPath(name).parts[0] in ("src", "scripts"):
            safe_source(repo, name)
    if set(seal) != {"source_commit", "source_hashes"}:
        raise ValueError("Unknown execution seal schema")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if seal["source_commit"] != head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Execution commit differs from seal")
    hashes = seal["source_hashes"]
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Missing source hashes")
    for name, digest in hashes.items():
        if (
            name not in tracked
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Untracked source or invalid digest in seal")
        if hashlib.sha256(safe_source(repo, name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source hash mismatch: {name}")
    if entry not in hashes or "scripts/run_source_sealed.py" not in hashes:
        raise ValueError("Seal must bind both entry and pre-import launcher")
    target = safe_source(repo, entry)
    if target.suffix != ".py" or PurePosixPath(entry).parts[0] != "scripts":
        raise ValueError("Entry must be a tracked Python script")
    return {
        "schema": "pre-import-source-check-v1",
        "source_commit": head,
        "entry": entry,
        "source_files": len(hashes),
        "untracked_check": "all",
        "isolated_python": True,
        "fresh_bytecode_cache": True,
    }


def main():
    if not sys.flags.isolated:
        raise SystemExit("Use python -I scripts/run_source_sealed.py; no source imported")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", required=True, type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("entry_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    receipt = verify(repo, json.loads(args.seal.read_text()), args.entry)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if args.check_only:
        return 0
    remaining = args.entry_args
    if remaining[:1] == ["--"]:
        remaining = remaining[1:]
    # -B suppresses writes, not reads. A new private prefix prevents importing
    # poisoned/stale repository __pycache__ entries as well as writing new ones.
    with tempfile.TemporaryDirectory(prefix="latent-source-pycache-") as cache:
        env = dict(os.environ)
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONPYCACHEPREFIX"):
            env.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-X",
                f"pycache_prefix={cache}",
                str(repo / args.entry),
                *remaining,
            ],
            cwd=repo,
            env=env,
            check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
