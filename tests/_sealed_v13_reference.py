"""Stage hash-checked historical test inputs without repinning V13 contracts."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

SEALED_COMMIT = "ed5ce398e08b55d3118a316cfda61e36b8cc4b54"
WORKTREE_ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = "configs/v13/DESIGN_CONTRACT.json"
PLAN_PATH = "configs/v13/VISIBILITY_RUN_PLAN.json"
ENGINE_PATH = "src/latent_workspace_ft_v10/engine.py"
EVAL_PATH = "data/v10/functional_eval.jsonl"
PINNED_SHA256 = {
    DESIGN_PATH: "88d924979c29837ef2c8576a51efc1ce534bfe07a27e0b98def0ef8d3c545d86",
    PLAN_PATH: "f1e312e448cd973b8f59e7d4a2c4ba4f3f3bfc9eabd3cec4b35157dabfeaaa76",
    ENGINE_PATH: "aee2a1fe3b95c6c0ff21d89870c0d3bb959da28fc544aaa9aced7ccc0abae133",
    EVAL_PATH: "fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e",
}


def stage_sealed_files(destination: Path, expected_hashes: dict[str, str]) -> None:
    for relative, expected in expected_hashes.items():
        try:
            blob = subprocess.run(
                ["git", "show", f"{SEALED_COMMIT}:{relative}"],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                check=True,
                timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.skip(f"Sealed V13 reference unavailable: {SEALED_COMMIT}:{relative}: {exc}")
        assert hashlib.sha256(blob).hexdigest() == expected, f"Sealed V13 hash mismatch: {relative}"
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
