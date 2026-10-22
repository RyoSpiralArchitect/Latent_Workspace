"""Replay closed tiny qualification/audit only; no claim about active 7B roles."""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import run_v23_recovered_mmlu_pro02 as runner  # noqa: E402


def verify():
    bundle = Path(__file__).resolve().parent / "furnace"
    seal = runner.bank.source_seal(bundle, "b2f569740636e2cffb80e4091323d551ea7de4c2")
    assert len(seal["source_hashes"]) == 804
    plan = runner.ex.read(ROOT / runner.PLAN)
    runner.RUN.qualification(bundle / "qualification", seal, plan)
    devices = {}
    for device in ("cpu", "cuda"):
        path = bundle / "qualification" / device
        end = runner.ex.read(path / "FINISHED.json")
        totals = dict(tests=0, errors=0, failures=0, skipped=0)
        for suite in ElementTree.parse(path / "TESTS.xml").getroot().iter("testsuite"):
            for k in totals:
                totals[k] += int(suite.attrib.get(k, 0))
        assert totals == end["counts"] == dict(tests=315, errors=0, failures=0, skipped=0)
        assert 0 < end["elapsed_seconds"] < 900
        if device == "cuda":
            assert end["peak_cuda_allocated_bytes"] <= 4 * 2**30
        devices[device] = {k: end[k] for k in ("status", "counts", "elapsed_seconds")}
    audit = runner.ex.read(bundle / "qualification/CPU_ISOLATION.json")
    return dict(
        status="QUALIFICATION_315_AND_CPU_ISOLATION_PASS_NOT_7B_RESULT",
        source=seal["source_commit"],
        source_files=804,
        devices=devices,
        cpu_isolation=audit["status"],
        cpu_samples=len(audit["samples"]),
        real_model_calls=0,
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
