#!/usr/bin/env python3
"""Offline replay of terminal migration receipts; never imports Torch or runs models."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def exact(a, b, label):
    require(
        json.dumps(a, sort_keys=True, allow_nan=False)
        == json.dumps(b, sort_keys=True, allow_nan=False),
        f"mismatch: {label}",
    )


def verify_window(row):
    pairs = row["pairs"]
    require(
        [(r["world"], r["query"]) for r in pairs] == [(w, q) for w in range(2) for q in range(8)],
        "window must contain all 16 ordered pairs",
    )
    require(
        all(re.fullmatch("[0-9a-f]{64}", r["accumulated_gradients_sha256"]) for r in pairs),
        "missing accumulated gradient hashes",
    )
    require(row["update"]["completed_step"] == row["state"]["completed_steps"], "step mismatch")
    require(row["update"]["transfer"]["spill_count"] == 16, "wrong spill denominator")
    require(
        bool(row["state"]["native_state"]) and bool(row["state"]["bridge_state"]), "empty state"
    )
    json.dumps(row, allow_nan=False)


def verify(bundle):
    started, finished = read(bundle / "STARTED.json"), read(bundle / "FINISHED.json")
    expected = set(finished["files"]) | {"FINISHED.json"}
    require({p.name for p in bundle.iterdir()} == expected, "terminal file set changed")
    for name, entry in finished["files"].items():
        require(Path(name).name == name, "unsafe file entry")
        p = bundle / name
        require(
            p.is_file()
            and not p.is_symlink()
            and p.stat().st_size == entry["bytes"]
            and digest(p) == entry["sha256"],
            f"raw file mismatch: {name}",
        )
    for name, sha in started["seal"]["source_hashes"].items():
        p = ROOT / name
        require(p.resolve().is_relative_to(ROOT) and digest(p) == sha, f"source changed: {name}")
    exact(started["plan"], read(ROOT / "configs/v16/ADAPTER_MIGRATION_PLAN.json"), "plan")
    for key, value in {
        "new_sequences": 0,
        "judge_calls": 0,
        "weight_deletions": 0,
        "old_expression_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }.items():
        exact(finished[key], value, key)
    completed, replayed, pairs_seen = [], [], 0
    for path in bundle.glob("*_pairs.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        require(len(rows) <= 16, "over-budget pair journal")
        require(
            [(r["world"], r["query"]) for r in rows]
            == [(w, q) for w in range(2) for q in range(8)][: len(rows)],
            "journal order",
        )
        pairs_seen += len(rows)
    require(pairs_seen <= 160, "over-budget run")
    for mode in ("frozen", "full"):
        if (bundle / f"{mode}_EQUIVALENCE.json").exists():
            exact(
                read(bundle / f"{mode}_legacy_INITIAL.json"),
                read(bundle / f"{mode}_adapter_v2_INITIAL.json"),
                f"{mode}:initial",
            )
            a, b = [
                read(bundle / f"{mode}_{impl}_CONTEXT.json") for impl in ("legacy", "adapter_v2")
            ]
            for key in ("features", "contract"):
                exact(a[key], b[key], f"{mode}:{key}")
            for step in (1, 2):
                a, b = [
                    read(bundle / f"{mode}_{impl}_step{step}.json")
                    for impl in ("legacy", "adapter_v2")
                ]
                verify_window(a)
                verify_window(b)
                exact(a, b, f"{mode}:{step}")
            completed.append(mode)
        if (bundle / f"{mode}_REPLAY.json").exists():
            a, b = (
                read(bundle / f"{mode}_adapter_v2_step2.json"),
                read(bundle / f"{mode}_replay_step2.json"),
            )
            verify_window(b)
            exact(a, b, f"{mode}:replay")
            exact(
                read(bundle / f"{mode}_REPLAY.json")["state_sha256"],
                read(bundle / f"{mode}_adapter_v2_step2_CHECKPOINT.json")["state_sha256"],
                "saved replay",
            )
            replayed.append(mode)
    if finished["status"] == "EXACT_7B_MIGRATION_PASS_NOT_SEMANTIC_QUALIFICATION":
        require(
            completed == replayed == ["frozen", "full"] and pairs_seen == 160, "incomplete PASS"
        )
        require(finished["completed_modes"] == replayed, "mode denominator")
        require(
            (
                finished["complete_unique_windows"],
                finished["complete_replay_windows"],
                finished["complete_backward_pairs"],
            )
            == (8, 2, 160),
            "PASS denominator",
        )
    else:
        require(
            finished["status"] == "INCOMPLETE_NO_RETRY" and finished.get("error"),
            "unknown terminal state",
        )
    return {
        "receipt_verification": "PASS",
        "run_status": finished["status"],
        "matched_modes": completed,
        "replayed_modes": replayed,
        "journaled_backward_pairs": pairs_seen,
        "planned_backward_pairs": 160,
        "checkpoint_bytes_reloaded_offline": False,
        "old_expression_gate": "FAIL",
        "winner": "none",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    print(json.dumps(verify(parser.parse_args().bundle), indent=2, sort_keys=True))
