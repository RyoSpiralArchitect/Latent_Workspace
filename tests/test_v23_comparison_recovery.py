"""Recovery changes provenance and CPU visibility, never the numerical plan."""

import subprocess
import sys
from types import SimpleNamespace

import pytest
import run_v23_comparison_recovery as recovery


def test_actual_entry_masks_before_transitive_torch_import():
    code = (
        "import sys,os; sys.path[:0]=['src','scripts']; "
        "sys.argv=['entry','qualify','--device','cpu']; "
        "import run_v23_comparison_recovery as r; import torch; "
        "import qualification_isolation as q; "
        "assert q._MASKED_PID == os.getpid(); "
        "assert os.environ['CUDA_VISIBLE_DEVICES'] == ''; "
        "assert torch.cuda.device_count() == 0 and not torch.cuda.is_initialized(); "
        "import importlib; importlib.reload(r); "
        "assert q._MASKED_PID == os.getpid(); "
        "assert torch.cuda.device_count() == 0 and not torch.cuda.is_initialized()"
    )
    subprocess.run([sys.executable, "-B", "-c", code], cwd=recovery.ROOT, check=True)


def test_collection_under_qualify_argv_reenters_registered_process():
    code = (
        "import sys; sys.path[:0]=['src','scripts']; "
        "sys.argv=['entry','qualify','--device','cpu']; "
        "import qualification_isolation as q; q.isolate_cli_before_imports(); "
        "import torch,pytest; "
        "raise SystemExit(pytest.main(['--collect-only','-q','-p','no:cacheprovider',"
        "'tests/test_v23_comparison_recovery.py']))"
    )
    subprocess.run([sys.executable, "-B", "-c", code], cwd=recovery.ROOT, check=True)


def test_one_whole_arm_and_unchanged_numeric_plan():
    plan = recovery.ex.read(recovery.ROOT / recovery.PLAN)
    recovery.validate(plan)
    assert recovery.reference(plan) == recovery.ex.read(recovery.ROOT / recovery.original.PLAN)
    assert recovery.RUN.roles == ("on",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["base", "off", "on"]),
        ("no_retry", False),
        ("planned", {}),
        ("original_source", "0" * 40),
    ],
)
def test_recovery_scope_rejects_change(field, value):
    plan = recovery.ex.read(recovery.ROOT / recovery.PLAN)
    plan[field] = value
    with pytest.raises((ValueError, KeyError)):
        recovery.validate(plan)


def test_runner_reuses_original_body_plan_and_fresh_output(tmp_path, monkeypatch):
    plan = recovery.ex.read(recovery.ROOT / recovery.PLAN)
    calls = []
    monkeypatch.setattr(recovery, "verify_original", lambda p: {"preserved": True})
    monkeypatch.setattr(
        recovery.original, "run", lambda c, a, p, s: calls.append(p) or {"ok": True}
    )
    assert recovery.run(None, SimpleNamespace(role="on", output=tmp_path), plan, {}) == {"ok": True}
    assert calls == [recovery.reference(plan)]
    with pytest.raises(ValueError, match="Never regenerate"):
        recovery.run(None, SimpleNamespace(role="off", output=tmp_path), plan, {})
