"""Bind every Python implementation module after the V14 source split."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def implementation_fingerprint(package_dir: Path | None = None) -> dict[str, Any]:
    root = package_dir if package_dir is not None else Path(__file__).resolve().parent
    paths = sorted(root.glob("*.py"))
    if not paths or any(path.is_symlink() for path in paths):
        raise ValueError("Implementation source must be nonempty regular local modules")
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    payload = {"scope": "package_top_level_python_modules_v1", "files": files}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "sha256": digest}
