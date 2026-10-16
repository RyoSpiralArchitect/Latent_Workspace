"""The V20 dispatcher computes endpoints in a process that never ran load_runtime.

Dispatch 01 failed there because the run interpreter does not have the package
installed. A meta-path finder blocks the package unless ``src`` is on
``sys.path``, so this holds even where an editable install would hide the bug.
Kept outside the frozen plan's qualification files.
"""

import subprocess
import sys
from pathlib import Path

from scripts import run_v20_deliberation_pilot as run

ROOT = Path(__file__).resolve().parents[1]
CODE = r"""
import importlib.abc, importlib.util, sys
from pathlib import Path

root, raw = Path(sys.argv[1]), Path(sys.argv[2])
src = str(root / "src")
sys.path = [p for p in sys.path if p != src]


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "latent_workspace_ft_v10" and src not in sys.path:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return None


sys.meta_path.insert(0, Block())
spec = importlib.util.spec_from_file_location(
    "runner", root / "scripts" / "run_v20_deliberation_pilot.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
print(runner.endpoints_for(raw, runner.read(root / runner.PLAN))["verdict"])
"""


def test_dispatcher_computes_endpoints_without_the_runtime_path(tmp_path):
    plan = run.read(ROOT / run.PLAN)
    rows = [
        dict(world=w, label=1, base_logits=[0.0, -1.0] if q < 4 else [0.0, 1.0])
        for w in range(128)
        for q in range(16)
    ]
    (tmp_path / "extract").mkdir()
    run.v19().write_gz(tmp_path / "extract" / "ROWS_final.json.gz", rows)
    accuracy = {"k4": 16, "k1": 12, "k4_lw": 16, "readout": 12}
    for role in run.seed_roles(plan):
        (tmp_path / role).mkdir()
        correct = [q < accuracy[role.rsplit("_s", 1)[0]] for _ in range(128) for q in range(16)]
        run.v19().write_gz(
            tmp_path / role / f"eval_final_step{plan['endpoints']['step']}.json.gz",
            {"correct": correct},
        )
    result = subprocess.run(
        [sys.executable, "-I", "-c", CODE, str(ROOT), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "DELIBERATION_STEP_GAIN"
