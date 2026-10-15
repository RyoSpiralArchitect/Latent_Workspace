#!/usr/bin/env python3
"""Read-only post-run checkpoint-file and native-cast audit. No model forward."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import torch


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo / "src"))
    from latent_workspace_ft_v10.v15_native_learner import require, tree_hash

    torch.set_num_threads(2)
    rows, first = [], {}
    for phase in ("reader", "full"):
        raw = args.repo / "runs" / f"v15_native_{phase}_20261010"
        report = json.loads((raw / "REPORT.json").read_text())
        terminal = json.loads((raw / "FINISHED.json").read_text())
        require(terminal["report_sha256"] == sha(raw / "REPORT.json"), "Terminal file identity")
        root = args.repo / "runs" / f"checkpoints_v15_native_{phase}_20261010"
        for arm in report["results"]:
            for receipt in arm["checkpoints"]:
                path = root / arm["arm"] / receipt["path"]
                require(
                    path.stat().st_size == receipt["bytes"] and sha(path) == receipt["sha256"],
                    "Retained checkpoint file changed",
                )
                payload = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
                require(
                    payload["metadata"]["source_commit"] == report["source_commit"]
                    and payload["completed_steps"] == receipt["completed_steps"],
                    "Checkpoint metadata",
                )
                row = dict(
                    phase=phase,
                    arm=arm["arm"],
                    **receipt,
                    file_hash_verified=True,
                    reader=payload["reader"],
                    bridge_sha256=tree_hash(payload["bridge"]),
                    bridge_optimizer_sha256=tree_hash(payload["bridge_optimizer"]),
                )
                if phase == "full" and receipt["completed_steps"] == 1:
                    first[arm["arm"]] = (row["bridge_sha256"], row["bridge_optimizer_sha256"])
                if payload["full_update"]:
                    # The pinned Mistral state has parameters only. Match the
                    # original state_hash byte order using its saved alias map.
                    require(
                        not payload["native_buffers"],
                        "This independent cast audit binds parameter-only Mistral",
                    )
                    native = hashlib.sha256()
                    for name, canonical in payload["base_aliases"].items():
                        schema = payload["native_schema"][canonical]
                        require(schema[1] == "torch.bfloat16", "Pinned native dtype")
                        value = payload["base_masters"][canonical].to(torch.bfloat16).contiguous()
                        native.update(name.encode())
                        native.update(str(value.dtype).encode())
                        native.update(str(tuple(value.shape)).encode())
                        native.update(value.view(torch.uint8).numpy().tobytes())
                    row["reconstructed_native_sha256"] = native.hexdigest()
                    if receipt["completed_steps"] == 2:
                        require(
                            native.hexdigest() == arm["final_base_sha256"],
                            "Retained step-2 cast differs from actual final model",
                        )
                        row["reconstructed_native_matches_final_model"] = True
                rows.append(row)
                del payload
    require(
        first["frozen"] == first["full"],
        "First bridge/AdamW update differs between matched full/frozen arms",
    )
    result = dict(
        status="VERIFIED_RETAINED_CHECKPOINT_FILES_AND_NATIVE_CAST",
        rows=rows,
        files=len(rows),
        total_bytes=sum(r["bytes"] for r in rows),
        step1_frozen_full_bridge_and_adamw_exact=True,
        script_sha256=sha(Path(__file__)),
        model_forwards=0,
        model_updates=0,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "files",
                    "total_bytes",
                    "step1_frozen_full_bridge_and_adamw_exact",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
