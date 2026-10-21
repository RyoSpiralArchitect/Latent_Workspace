#!/usr/bin/env python3
"""Post-terminal offline decoding/checkpoint/source witness; no model calls."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
OUT = ROOT / "latent-v22-causality01-20261021"
SOURCE = "fd77ee4c84a99a99c22b28aa85d321e95caa843f"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    destination = OUT / "REMOTE_TERMINAL_CHECK.json"
    assert not destination.exists()
    assert read(OUT / "raw/FINISHED.json")["status"] == "V22_CAUSALITY_COMPLETE_NOT_RELEASE"
    checkouts = {}
    for name, expected in (
        ("latent-v22-causality01-20261021", SOURCE),
        ("latent-v22-diagnostics01-20261021", "35cbe95fa498d95c8f967b428758ddac0bd29966"),
        ("latent-v22-comparison01-20261021", "5bd6f5cca45ec25d57c37b14b410b9297abe67d5"),
        ("latent-v22-full-ft-recovery01-20261021", "13c1192fc2727d8ca61ee215a927c0cd77f75b16"),
    ):
        cwd = ROOT / "worktrees" / name
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
        assert head == expected and not dirty
        checkouts[name] = dict(head=head, clean=True)
    workers = {}
    for role in ("base", "v22", "base_cross"):
        start = read(OUT / "raw" / role / "STARTED.json")
        live = Path(f"/proc/{start['pid']}").exists()
        assert not live
        workers[role] = dict(pid=start["pid"], process_exists=live)
    assert not list((OUT / "no-checkpoint-writes").iterdir())
    body = ROOT / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt"
    digest = sha(body)
    assert body.stat().st_size == 29004418636
    assert digest == "cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68"
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    from transformers import AutoTokenizer

    snapshot = Path(
        "/home/ryospiralarchitect/.cache/huggingface/hub/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/c170c708c41dac9275d15a8fff4eca08d52bab71"
    )
    tokenizer = AutoTokenizer.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False
    )
    literal = {}
    for role in ("base", "v22", "base_cross"):
        rows = [
            json.loads(line)
            for line in (OUT / "raw" / role / "interventions.jsonl").read_text().splitlines()
        ]
        for row in rows:
            assert tokenizer.decode(row["token_ids"], skip_special_tokens=True) == row["text"]
        literal[role] = len(rows)
    assert literal == dict(base=384, v22=464, base_cross=80)
    clients = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader"],
        text=True,
    ).strip()
    receipt = dict(
        status="POST_TERMINAL_OFFLINE_CAUSALITY_CHECK_PASS",
        utc=datetime.datetime.now(datetime.UTC).isoformat(),
        source=SOURCE,
        checkouts=checkouts,
        workers=workers,
        no_checkpoint_writes=True,
        checkpoint=dict(path=str(body), bytes=body.stat().st_size, sha256=digest),
        literal_decoded=literal,
        tokenizer_files={p.name: sha(p) for p in snapshot.glob("tokenizer*")},
        gpu_compute_clients=clients,
        verifier_sha256=sha(Path(__file__)),
        model_calls=0,
        new_sequences=0,
        weight_deletions=0,
    )
    with destination.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
