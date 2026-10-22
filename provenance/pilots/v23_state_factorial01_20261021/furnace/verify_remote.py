#!/usr/bin/env python3
"""Post-terminal byte/tensor/identity witness and token decoding; no model forward."""

import hashlib
import json
import os
import struct
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

BASE = Path("/home/ryospiralarchitect/spiralreality/SpiralReality")
OUT = BASE / "latent-v23-state-factorial01-20261021"
WORK = BASE / "worktrees/latent-v23-state-factorial01-20261021"
SOURCE = "6064c69ab722330f3d51574768a1c52e887d6866"
ROLES = ("base", "v22", "base_cross")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(folder):
    return {
        p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def terminal(folder, status):
    end = read(folder / "FINISHED.json")
    files = manifest(folder)
    files.pop("FINISHED.json")
    require(end["status"] == status and end["files"] == files, f"Terminal {folder}")
    return end


def check_bank(folder):
    receipt = read(folder / "CUT_BANK.json")
    path = folder / "cut_states.safetensors"
    require(path.stat().st_size == receipt["bytes"] and sha(path) == receipt["sha256"], "Bank body")
    with path.open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        header = json.loads(stream.read(length))
        require(set(header) == set(receipt["tensors"]), "Bank header keys")
        for key, entry in receipt["tensors"].items():
            meta = header[key]
            require(meta["dtype"] == "BF16" and meta["shape"] == entry["shape"], "Tensor metadata")
            start, stop = meta["data_offsets"]
            stream.seek(8 + length + start)
            require(
                hashlib.sha256(stream.read(stop - start)).hexdigest() == entry["sha256"],
                "Tensor bytes",
            )
    return dict(bytes=receipt["bytes"], sha256=receipt["sha256"], tensors=len(header))


def main():
    witness = OUT / "REMOTE_TERMINAL_CHECK.json"
    require(not witness.exists() and not (OUT / "PUBLICATION.tar.gz").exists(), "Exclusive witness")
    seal = read(OUT / "SOURCE_SEAL.json")
    require(seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 744, "Source seal")
    for name, digest in seal["source_hashes"].items():
        require(sha(WORK / name) == digest, f"Current source {name}")
        raw = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=WORK)
        require(hashlib.sha256(raw).hexdigest() == digest, f"Committed source {name}")
    for device in ("cpu", "cuda"):
        end = terminal(OUT / "qualification" / device, "TINY_V23_STATE_FACTORIAL_PASS_NOT_7B")
        require(end["counts"] == dict(tests=216, failures=0, errors=0, skipped=0), "Qualification")
    dispatch = terminal(OUT / "raw", "V23_STATE_FACTORIAL_COMPLETE_NOT_TRAINING_OR_RELEASE")
    require(dispatch["completed_roles"] == list(ROLES), "All roles")
    banks, workers = {}, {}
    for role in ROLES:
        folder = OUT / "raw" / role
        end = terminal(folder, "V23_STATE_FACTORIAL_ARM_COMPLETE")
        require(
            end["new_sequences"] == end["native_weight_updates"] == end["judge_calls"] == 0,
            "No execution expansion",
        )
        pid = read(folder / "STARTED.json")["pid"]
        exists = Path(f"/proc/{pid}").exists()
        require(not exists, "Role still running")
        workers[role] = dict(pid=pid, process_exists=exists)
        if role != "base_cross":
            banks[role] = check_bank(folder)
    checkpoint = BASE / "latent-v22-full-ft-recovery01-20261021/checkpoints/training_step32.pt"
    checkpoint_sha = sha(checkpoint)
    require(
        checkpoint_sha == "cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68",
        "Unchanged step32 body",
    )
    worktrees = {}
    for name in (
        "latent-v23-state-factorial01-20261021",
        "latent-v22-causality01-20261021",
        "latent-v22-diagnostics01-20261021",
        "latent-v22-comparison01-20261021",
        "latent-v22-full-ft-recovery01-20261021",
    ):
        path = BASE / "worktrees" / name
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=path, text=True
        )
        require(not status, f"Immutable worktree {name}")
        worktrees[name] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True
        ).strip()
    require(not any((OUT / "no-checkpoint-writes").iterdir()), "No checkpoint output")
    # Offline tokenizer only: make exact next-token examples independently legible.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import AutoTokenizer

    snapshot = Path(
        "/home/ryospiralarchitect/.cache/huggingface/hub/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/c170c708c41dac9275d15a8fff4eca08d52bab71"
    )
    tokenizer = AutoTokenizer.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False
    )
    ids = set()
    for role in ROLES:
        for line in (OUT / "raw" / role / "cells.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row["kind"] == "world":
                ids.update((row["target"], row["score"]["top1"]))
    with (OUT / "TOKEN_TEXT.json").open("x") as stream:
        json.dump(
            dict(
                snapshot=str(snapshot),
                tokenizer_json_sha256=sha(snapshot / "tokenizer.json"),
                skip_special_tokens=False,
                tokens={
                    str(i): tokenizer.decode([i], skip_special_tokens=False) for i in sorted(ids)
                },
            ),
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    result = dict(
        status="V23_STATE_FACTORIAL_OFFLINE_TERMINAL_PASS",
        source=SOURCE,
        source_files=744,
        model_calls=0,
        new_sequences=0,
        native_weight_updates=0,
        checkpoint_saves=0,
        workers=workers,
        banks=banks,
        checkpoint_sha256=checkpoint_sha,
        worktrees=worktrees,
        no_checkpoint_writes=True,
        decoded_token_ids=len(ids),
        verifier_sha256=sha(Path(__file__)),
        utc=datetime.now(UTC).isoformat(),
        gpu_clients=subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader",
            ],
            text=True,
        ).strip(),
    )
    with witness.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Small publication copy only. Remote activation bodies remain untouched.
    files = manifest(OUT)
    excluded = {
        name: meta for name, meta in files.items() if name.endswith("/cut_states.safetensors")
    }
    require(
        set(excluded) == {f"raw/{r}/cut_states.safetensors" for r in ("base", "v22")},
        "Exact two remote-only bodies",
    )
    with (OUT / "PUBLICATION_MANIFEST.json").open("x") as stream:
        json.dump(
            dict(
                included={k: v for k, v in files.items() if k not in excluded}, remote_only=excluded
            ),
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    with tarfile.open(OUT / "PUBLICATION.tar.gz", "x:gz") as archive:
        for name in sorted(set(files) - set(excluded) | {"PUBLICATION_MANIFEST.json"}):
            archive.add(OUT / name, arcname=f"furnace/{name}", recursive=False)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
