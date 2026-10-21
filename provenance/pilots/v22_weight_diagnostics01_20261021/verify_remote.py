#!/usr/bin/env python3
"""Post-terminal read-only environment/checkpoint witness; no model imports."""

import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
OUT = ROOT / "latent-v22-diagnostics01-20261021"
SOURCE = "35cbe95fa498d95c8f967b428758ddac0bd29966"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.output == OUT / "REMOTE_TERMINAL_CHECK.json" and not args.output.exists()
    checkouts = {}
    for name, expected in (
        ("latent-v22-diagnostics01-20261021", SOURCE),
        ("latent-v22-comparison01-20261021", "5bd6f5cca45ec25d57c37b14b410b9297abe67d5"),
        ("latent-v22-full-ft-recovery01-20261021", "13c1192fc2727d8ca61ee215a927c0cd77f75b16"),
    ):
        cwd = ROOT / "worktrees" / name
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
        assert head == expected and not dirty
        checkouts[name] = dict(head=head, clean=True)
    workers = {}
    for role in ("base", "v22"):
        start = json.loads((OUT / "raw" / role / "STARTED.json").read_text())
        live = Path(f"/proc/{start['pid']}").exists()
        assert not live
        workers[role] = dict(pid=start["pid"], process_exists=live)
    writes = list((OUT / "no-checkpoint-writes").iterdir())
    assert not writes
    body = ROOT / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt"
    digest = sha(body)
    assert body.stat().st_size == 29004418636
    assert digest == "cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68"
    clients = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader"],
        text=True,
    ).strip()
    receipt = dict(
        status="POST_TERMINAL_READ_ONLY_CHECK_PASS",
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        checkouts=checkouts,
        workers=workers,
        no_checkpoint_writes=True,
        checkpoint=dict(path=str(body), bytes=body.stat().st_size, sha256=digest),
        gpu_compute_clients=clients,
        verifier_sha256=sha(Path(__file__)),
        model_calls=0,
        weight_deletions=0,
    )
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(receipt["status"])


if __name__ == "__main__":
    main()
