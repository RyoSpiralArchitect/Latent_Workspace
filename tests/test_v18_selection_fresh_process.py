"""Tiny CPU process-restart mechanics, not CUDA/7B or semantic qualification.

Each case starts exactly two independent interpreters: a producer saves window 1
and computes window 2; after it exits, a resumer loads with ``weights_only=True``
and reproduces window 2. Children use -I -S -B, explicit dependency roots (no
editable .pth execution), an offline minimal environment, and 60-second timeouts.
Only the existing tiny selection-learner fixture and its dependencies are used.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = tuple(
    (dtype, full, factor, "ordered_difference")
    for dtype in ("float32", "bfloat16")
    for full in (False, True)
    for factor in ("raw_matched_control", "slot_contrast")
) + (
    ("bfloat16", True, "slot_contrast", "final"),
    ("bfloat16", True, "slot_contrast", "symmetric_mean"),
)

# This is a process entry point, never evaluated in the pytest process. No forked
# Python object or shared in-memory checkpoint crosses the restart boundary.
CHILD = r"""
import copy
import hashlib
import json
import os
import platform
import random
import sys
from pathlib import Path

root, folder, role = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
dependencies = json.loads(sys.argv[4])
dependency_roots = dependencies["roots"]
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path[:0] = [str(root / "src"), str(root / "tests"), *dependency_roots]

import numpy as np
import torch
import pytest
import transformers
for dependency in (np, torch, pytest, transformers):
    expected = dependencies["modules"][dependency.__name__]
    assert str(Path(dependency.__file__).resolve()) == expected["file"]
    assert str(dependency.__version__) == expected["version"]
from test_v18_selection_learner import META, build, policy, state, update
from latent_workspace_ft_v10.v15_native_learner import rng_state, tree_hash
from latent_workspace_ft_v10.v18_selection_learner import FORMAT, SelectionNativeLearner

torch.set_num_threads(2)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
torch.set_default_dtype(torch.float32)
random.seed(19081)
np.random.seed(19082)
torch.manual_seed(19083)
assert not torch.cuda.is_initialized()
assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
assert os.environ["CUDA_VISIBLE_DEVICES"] == ""

case = json.loads((folder / "case.json").read_text())
dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}[case["dtype"]]
learner = build(dtype=dtype, full=case["full"], mode=case["query"], factor=case["factor"])
assert all(p.device.type == "cpu" for _, p in learner.base_named + learner.bridge_named)
expected_policy = policy(case["query"])
expected_contract = copy.deepcopy(learner.run_contract)
runtime = {
    "python": platform.python_version(), "torch": str(torch.__version__),
    "numpy": np.__version__, "machine": platform.machine(), "device": "cpu",
    "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
    "deterministic": torch.are_deterministic_algorithms_enabled(),
    "default_dtype": str(torch.get_default_dtype()), "isolated": sys.flags.isolated,
    "no_site": sys.flags.no_site, "explicit_dependency_roots": dependency_roots,
    "dependency_modules": dependencies["modules"],
}

def emit(name, value):
    with (folder / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")

def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def finish_window2(owner):
    update_receipt = update(owner)
    payload = owner.payload(META)
    assert owner.completed_steps == 2
    assert not torch.cuda.is_initialized()
    rng_before = tree_hash(rng_state())
    draws = (random.random(), float(np.random.rand()), torch.rand(7))
    return {
        "update": update_receipt,
        "update_sha256": tree_hash(update_receipt),
        "payload_sha256": tree_hash(payload),
        "payload_fields_sha256": {name: tree_hash(value) for name, value in payload.items()},
        "owned_state_sha256": state(owner),
        "rng_before_draws_sha256": rng_before,
        "rng_draws_sha256": tree_hash(draws),
        "rng_draws": [draws[0], draws[1], draws[2].tolist()],
        "rng_after_draws_sha256": tree_hash(rng_state()),
        "completed_steps": owner.completed_steps,
    }

checkpoint = folder / "window1.pt"
if role == "producer":
    window1 = update(learner)
    checkpoint_receipt = learner.save(checkpoint, META)
    assert checkpoint_receipt["format"] == FORMAT
    checkpoint_hash = file_hash(checkpoint)
    # Exercise the actual exclusive save entry: no overwrite or additional update.
    try:
        learner.save(checkpoint, META)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Checkpoint save overwrote an existing file")
    assert file_hash(checkpoint) == checkpoint_hash
    result = {
        "case": case, "runtime": runtime, "pid": os.getpid(),
        "independent_policy": expected_policy,
        "independent_contract_sha256": tree_hash(expected_contract),
        "window1_update_sha256": tree_hash(window1),
        "checkpoint_receipt": checkpoint_receipt, "checkpoint_file_sha256": checkpoint_hash,
        "window2": finish_window2(learner),
    }
    assert file_hash(checkpoint) == checkpoint_hash
    emit("producer.json", result)
elif role == "resumer":
    expected = json.loads((folder / "producer.json").read_text())
    assert expected["case"] == case and expected["runtime"] == runtime
    assert expected["pid"] != os.getpid()
    assert expected["independent_policy"] == expected_policy
    assert expected["independent_contract_sha256"] == tree_hash(expected_contract)
    checkpoint_hash = file_hash(checkpoint)
    assert checkpoint_hash == expected["checkpoint_file_sha256"]
    assert checkpoint.stat().st_size == expected["checkpoint_receipt"]["bytes"]
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    original_payload_hash = tree_hash(payload)
    assert original_payload_hash == expected["checkpoint_receipt"]["state_sha256"]
    # Make the ambient RNG deliberately different, so a missing restore cannot
    # pass merely because a freshly built model consumed the same fixed draws.
    random.seed(301)
    np.random.seed(302)
    torch.manual_seed(303)
    random.random(), np.random.rand(), torch.rand(5)
    assert tree_hash(rng_state()) != tree_hash(payload["rng"])
    learner = SelectionNativeLearner.restore(
        learner.binding, learner.bridge, payload,
        expected_selection_policy=expected_policy,
        expected_metadata=META, expected_run_contract=expected_contract,
        expected_state_sha256=expected["checkpoint_receipt"]["state_sha256"],
    )
    assert learner.completed_steps == 1
    assert tree_hash(learner.payload(META)) == original_payload_hash
    observed = finish_window2(learner)
    # Canonical JSON compares every loss/spill/update field, in addition to the
    # typed tree hash (which also preserves tuple/list distinctions).
    canonical = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    assert canonical(observed) == canonical(expected["window2"])
    assert tree_hash(payload) == original_payload_hash
    assert file_hash(checkpoint) == checkpoint_hash
    emit("resumer.json", {
        "case": case, "runtime": runtime, "pid": os.getpid(),
        "producer_pid": expected["pid"], "checkpoint_file_sha256": checkpoint_hash,
        "checkpoint_payload_unchanged": True, "window2": observed, "status": "EXACT",
    })
else:
    raise AssertionError("Unknown process role")
"""


def dependency_configuration():
    """Supply installed packages directly without executing unrelated .pth files."""
    selected = set()
    modules = {}
    for name in ("numpy", "torch", "pytest", "transformers"):
        specification = importlib.util.find_spec(name)
        assert specification is not None and specification.origin is not None
        root = Path(specification.origin).resolve().parents[1]
        assert root.name in {"site-packages", "dist-packages"}, (name, root)
        selected.add(root)
        modules[name] = {
            "file": str(Path(specification.origin).resolve()),
            "version": importlib.metadata.version(name),
        }
    # Preserve the caller's import precedence rather than sorting user/global roots.
    roots = list(
        dict.fromkeys(
            str(Path(entry).resolve())
            for entry in sys.path
            if entry and Path(entry).resolve() in selected
        )
    )
    assert set(map(Path, roots)) == selected
    return {"roots": roots, "modules": modules}


def child_environment(folder):
    # Never inherit keys, cloud credentials, arbitrary Python paths or user config.
    isolated_cache_root = folder / "isolated-cache"
    isolated_cache_root.mkdir()
    return {
        "PATH": os.defpath,
        "TMPDIR": str(folder),
        "LANG": "C",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "VECLIB_MAXIMUM_THREADS": "2",
        "NUMEXPR_NUM_THREADS": "2",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HOME": str(isolated_cache_root / "huggingface"),
        "CUDA_VISIBLE_DEVICES": "",
    }


@pytest.mark.parametrize(
    ("dtype", "full", "factor", "query"),
    CASES,
    ids=[
        f"{dtype}-{'full' if full else 'frozen'}-{factor}-{query}"
        for dtype, full, factor, query in CASES
    ],
)
def test_two_windows_exact_after_fresh_process_restart(tmp_path, dtype, full, factor, query):
    folder = tmp_path.resolve()
    case = {"dtype": dtype, "full": full, "factor": factor, "query": query}
    with (folder / "case.json").open("x") as stream:
        json.dump(case, stream, sort_keys=True)
    environment = child_environment(folder)
    dependencies = json.dumps(dependency_configuration())
    for role in ("producer", "resumer"):
        # One attempt per role. Timeout/nonzero exit is a test failure, never a retry.
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                CHILD,
                str(ROOT),
                str(folder),
                role,
                dependencies,
            ],
            cwd=folder,
            env=environment,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, (
            f"{role} failed ({completed.returncode})\n{completed.stdout}\n{completed.stderr}"
        )
    producer = json.loads((folder / "producer.json").read_text())
    resumer = json.loads((folder / "resumer.json").read_text())
    assert resumer["status"] == "EXACT"
    assert producer["pid"] != resumer["pid"]
    assert producer["window2"] == resumer["window2"]
    assert producer["runtime"] == resumer["runtime"]
    assert resumer["checkpoint_payload_unchanged"] is True
    assert (
        hashlib.sha256((folder / "window1.pt").read_bytes()).hexdigest()
        == producer["checkpoint_file_sha256"]
        == resumer["checkpoint_file_sha256"]
    )
