"""Put the engine's ``src`` on the path for any pytest launch (pyproject.toml is pinned)."""

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
