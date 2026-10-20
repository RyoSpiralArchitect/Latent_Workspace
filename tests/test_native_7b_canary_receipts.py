"""Offline verifier rejection tests; all artifacts are synthetic tiny fixtures."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "canary_verifier", ROOT / "scripts/verify_native_7b_canary.py"
)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
SEAL = {"source_commit": "a" * 40, "source_hashes": {}}


def write(path, value):
    path.write_text(json.dumps(value))


def finish(folder, end):
    end["files"] = v.manifest(folder)
    write(folder / "FINISHED.json", end)


@pytest.fixture
def qualification(tmp_path):
    plan = v.read(ROOT / v.PLAN)
    expected = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
    for device in ("cpu", "cuda"):
        folder = tmp_path / "qualification" / device
        folder.mkdir(parents=True)
        write(folder / "STARTED.json", dict(seal=SEAL, plan=plan, device=device))
        (folder / "TESTS.xml").write_text(
            f'<testsuites><testsuite tests="{expected["tests"]}" failures="0" '
            'errors="0" skipped="0"/></testsuites>'
        )
        finish(
            folder,
            dict(
                status=v.TINY_PASS,
                counts=expected,
                pytest_exit_code=0,
                device=device,
                native_weight_updates=0,
                real_model_updates=0,
                elapsed_seconds=1,
                cpu_mkldnn_enabled=False,
                peak_cuda_allocated_bytes=1024,
                **v.CEILING,
            ),
        )
    return tmp_path, plan


def test_qualification_denominators(qualification):
    root, plan = qualification
    actual = v.verify_qualification(root, SEAL, plan)
    assert actual["cpu"]["tests"] == actual["cuda"]["tests"] == 228


@pytest.mark.parametrize(
    "fault",
    [
        "status",
        "counts",
        "device",
        "xml",
        "seal",
        "updates",
        "backend",
        "wall",
        "peak",
        "bytes",
    ],
)
def test_qualification_damage_is_not_success(qualification, fault):
    root, plan = qualification
    folder = root / "qualification/cuda"
    end = v.read(folder / "FINISHED.json")
    if fault == "status":
        end["status"] = "wrong"
    elif fault == "counts":
        end["counts"]["skipped"] = 1
    elif fault == "device":
        end["device"] = "cpu"
    elif fault in ("xml", "bytes"):
        (folder / "TESTS.xml").write_text('<testsuite tests="0"/>')
    elif fault == "seal":
        start = v.read(folder / "STARTED.json")
        start["seal"]["source_commit"] = "b" * 40
        write(folder / "STARTED.json", start)
    elif fault == "updates":
        end["native_weight_updates"] = 2
    elif fault == "backend":
        end["cpu_mkldnn_enabled"] = True
    elif fault == "wall":
        end["elapsed_seconds"] = 901
    else:
        end["peak_cuda_allocated_bytes"] = 5 * 2**30
    if fault != "bytes":
        finish(folder, end)
    with pytest.raises(ValueError):
        v.verify_qualification(root, SEAL, plan)


@pytest.fixture
def run(tmp_path):
    plan = v.read(ROOT / v.PLAN)
    raw = tmp_path / "raw"
    raw.mkdir()
    write(raw / "STARTED.json", dict(seal=SEAL, plan=plan))
    inputs = [
        dict(
            **r,
            input_ids=[1, 4, 2],
            labels=[-100, 4, 2],
            memory_ids=[5] if r["memory"] else [],
            supervised_tokens=2,
        )
        for r in plan["rows"]
    ]
    context = dict(
        contract=dict(
            source_commit=SEAL["source_commit"],
            data_sha256=v.hashlib.sha256(v.canonical(inputs).encode()).hexdigest(),
        ),
        parameter_elements=plan["backbone"]["parameters"],
        physical_parameters=1,
        runtime=plan["expected_runtime"],
    )
    for role, count, status in (
        ("primary", 2, "TWO_NATIVE_UPDATES_SAVED"),
        ("replay", 1, "EXACT_NATIVE_STEP2_REPLAY"),
    ):
        folder = raw / role
        folder.mkdir()
        write(folder / "STARTED.json", dict(seal=SEAL, plan=plan, role=role))
        write(folder / "INPUTS.json", inputs)
        write(folder / "CONTEXT.json", context)
        for step in (1, 2) if role == "primary" else (2,):
            rows = [dict(key=key) for key in plan["windows"][step - 1]]
            for index, row in enumerate(rows):
                write(folder / f"step{step}_row{index}.json", row)
            write(
                folder / f"step{step}.json",
                dict(
                    rows=rows,
                    update=dict(changes=[dict(master_changed=True, native_changed_elements=1)]),
                    state=dict(completed_steps=step),
                ),
            )
        if role == "primary":
            write(folder / "CHECKPOINT_step2.json", dict(state_sha256="c" * 64))
        else:
            write(folder / "RESTORE.json", dict(exact_step1=True))
            write(
                folder / "REPLAY.json",
                dict(exact=True, state_sha256="c" * 64, replay_weight_file_written=False),
            )
        finish(
            folder,
            dict(
                status=status,
                native_weight_updates=count,
                elapsed_seconds=1,
                outcome=dict(peak_cuda_allocated_bytes=1024),
                **v.CEILING,
            ),
        )
    finish(
        raw,
        dict(
            status=plan["pass_status"],
            completed_roles=["primary", "replay"],
            native_weight_updates=3,
            summary=dict(
                native_weight_updates=3,
                unique_updates=2,
                replay_updates=1,
                backward_rows=6,
                retained_checkpoints=2,
                exact_replay=True,
                old_expression_gate="FAIL",
                non_regression="NOT_ESTABLISHED",
            ),
            **v.CEILING,
        ),
    )
    return raw, plan


def reseal(raw):
    for folder in (raw / "primary", raw / "replay", raw):
        finish(folder, v.read(folder / "FINISHED.json"))


def test_complete_and_incomplete_are_distinct(run):
    raw, plan = run
    assert (
        v.verify_run(raw, SEAL, plan)["status"] == "OFFLINE_NATIVE_7B_CANARY_VERIFIED_NOT_QUALITY"
    )
    end = v.read(raw / "FINISHED.json")
    end.update(
        status="INCOMPLETE_NO_RETRY", completed_roles=["primary"], native_weight_updates=None
    )
    finish(raw, end)
    result = v.verify_run(raw, SEAL, plan)
    assert result["status"] == "VERIFIED_INCOMPLETE_NO_RETRY"
    assert result["native_weight_updates"] is None


@pytest.mark.parametrize("fault", ["roles", "counts", "input", "contract", "rows", "state", "gate"])
def test_resealed_terminal_damage_is_rejected(run, fault):
    raw, plan = run
    if fault in ("roles", "counts", "gate"):
        path = raw / "FINISHED.json"
        data = v.read(path)
        if fault == "roles":
            data["completed_roles"] = ["primary"]
        elif fault == "counts":
            data["summary"]["backward_rows"] = 4
        else:
            data["old_expression_gate"] = "PASS"
    elif fault == "input":
        path = raw / "replay/INPUTS.json"
        data = v.read(path)
        data[0]["answer"] = "posthoc changed"
    elif fault == "contract":
        path = raw / "replay/CONTEXT.json"
        data = v.read(path)
        data["contract"]["data_sha256"] = "0" * 64
    elif fault == "rows":
        path = raw / "replay/step2_row0.json"
        data = v.read(path)
        data["key"] = "wrong"
    else:
        path = raw / "replay/REPLAY.json"
        data = v.read(path)
        data["state_sha256"] = "0" * 64
    write(path, data)
    reseal(raw)
    with pytest.raises(ValueError):
        v.verify_run(raw, SEAL, plan)


def test_shared_input_rewrite_cannot_hide_behind_cross_role_equality(run):
    raw, plan = run
    for role in ("primary", "replay"):
        path = raw / role / "INPUTS.json"
        changed = copy.deepcopy(v.read(path))
        changed[0]["memory"] = "different facts"
        write(path, changed)
    reseal(raw)
    with pytest.raises(ValueError, match="Fixed input"):
        v.verify_run(raw, SEAL, plan)
