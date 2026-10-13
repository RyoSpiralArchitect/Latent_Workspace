"""Receipt corruption checks only; no model or provider calls."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("backward_receipts", HERE / "inspect_results.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    shutil.copytree(HERE / "raw", tmp_path / "raw")
    shutil.copy2(HERE / "SOURCE_SEAL.json", tmp_path / "SOURCE_SEAL.json")
    monkeypatch.setattr(analysis, "BUNDLE", tmp_path)
    return tmp_path


def change(bundle, name, mutate):
    path = bundle / "raw" / name
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))


def test_exact_replay(bundle):
    summary, index = analysis.build()
    assert summary == json.loads((HERE / "SUMMARY.json").read_text())
    assert index == json.loads((HERE / "ARTIFACT_INDEX.json").read_text())


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("optimizer_steps", 1, "Scope violation"),
        ("base_sha256_after", "changed", "Base changed"),
        ("states", ["initial_seed47"], "States incomplete"),
    ],
)
def test_changed_terminal_rejected(bundle, field, value, message):
    change(bundle, "REPORT.json", lambda row: row.__setitem__(field, value))
    with pytest.raises(ValueError, match=message):
        analysis.build()


def test_missing_terminal_rejected(bundle):
    (bundle / "raw/REPORT.json").unlink()
    with pytest.raises(ValueError, match="terminal receipt"):
        analysis.build()


def test_missing_gradient_rejected(bundle):
    change(
        bundle,
        "initial_seed47_w0q0.json",
        lambda row: row["gradients"][0].__setitem__("present", False),
    )
    with pytest.raises(ValueError, match="Missing gradient"):
        analysis.build()


def test_broken_route_accounting_rejected(bundle):
    change(
        bundle,
        "retained_answer_step8_w0q1.json",
        lambda row: row["route_gradients"][0].__setitem__("backward_calls", 0),
    )
    with pytest.raises(ValueError, match="Gradient route accounting"):
        analysis.build()


def test_failed_restore_equality_rejected(bundle):
    change(
        bundle,
        "retained_answer_step8.json",
        lambda row: row["cpu_reference_exact"][0].__setitem__("exact", False),
    )
    with pytest.raises(ValueError, match="CPU reference accounting"):
        analysis.build()
