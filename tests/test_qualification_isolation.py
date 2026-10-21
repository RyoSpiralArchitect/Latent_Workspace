"""Offline boundary tests; no unmasked CUDA calls, no external provider."""

import copy
import json
import os
import subprocess
import sys

import pytest
import qualification_isolation as isolation


def good():
    return dict(
        status="CPU_GPU_ISOLATION_PASS",
        terminal_sha256="a" * 64,
        pid=42,
        mask_before_runtime_import=True,
        final_visible_devices=0,
        final_initialized=False,
        child_probe=dict(visible_devices=0, initialized=False, cuda_init_rejected="RuntimeError"),
        samples=[dict(own_gpu_clients=[])],
        monitor_errors=[],
    )


def test_mask_before_runtime_and_child_inheritance():
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="0")
    isolation.mask_before_import(env, {})
    result = subprocess.check_output(
        [
            sys.executable,
            "-I",
            "-c",
            "import os,json; print(json.dumps(os.environ['CUDA_VISIBLE_DEVICES']))",
        ],
        env=env,
        text=True,
    )
    assert env["CUDA_VISIBLE_DEVICES"] == json.loads(result) == ""


def test_late_mask_rejected_without_environment_mutation():
    env = {"CUDA_VISIBLE_DEVICES": "0"}
    with pytest.raises(ValueError, match="before importing"):
        isolation.mask_before_import(env, {"torch": object()})
    assert env == {"CUDA_VISIBLE_DEVICES": "0"}


def test_audit_accepted_only_for_same_receipt_and_pid():
    isolation.validate_audit(good(), "a" * 64, 42)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "CPU_GPU_ISOLATION_FAILED"),
        ("terminal_sha256", "b" * 64),
        ("pid", 43),
        ("mask_before_runtime_import", False),
        ("final_visible_devices", 1),
        ("final_initialized", True),
        ("samples", []),
        ("samples", [dict(own_gpu_clients=[42])]),
        ("monitor_errors", ["TimeoutExpired"]),
    ],
)
def test_bad_audit_rejected(field, value):
    audit = copy.deepcopy(good())
    audit[field] = value
    with pytest.raises(ValueError):
        isolation.validate_audit(audit, "a" * 64, 42)


def test_snapshot_includes_grandchildren_not_foreign_clients(monkeypatch):
    def output(command, **kwargs):
        return "42 1\n43 42\n44 43\n99 1\n" if command[0] == "ps" else "44\n99\n"

    monkeypatch.setattr(subprocess, "check_output", output)
    assert isolation.snapshot(42) == dict(
        pid=42, descendants=[42, 43, 44], gpu_clients=[44, 99], own_gpu_clients=[44]
    )


def test_cuda_qualification_does_not_change_visibility(monkeypatch):
    class Parent:
        def qualify(self, args):
            return 7

    class Runner(isolation.IsolatedQualificationMixin, Parent):
        pass

    from types import SimpleNamespace

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert Runner().qualify(SimpleNamespace(device="cuda")) == 7
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"
