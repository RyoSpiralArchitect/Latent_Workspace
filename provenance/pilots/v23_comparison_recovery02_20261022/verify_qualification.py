"""Offline replay of both tiny suites and the CPU visibility audit; no model calls."""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import v23_recovered_bank as bank  # noqa: E402

BUNDLE = Path(__file__).resolve().parent / "furnace"


def verify():
    seal = bank.source_seal(BUNDLE, "af9cd1a727d98d942df1845c35a14628f8f7481b")
    assert len(seal["source_hashes"]) == 792
    plan = bank.ex.read(ROOT / bank.recovery.PLAN)
    bank.recovery.RUN.qualification(BUNDLE / "qualification", seal, plan)
    result = {}
    for device in ("cpu", "cuda"):
        folder = BUNDLE / "qualification" / device
        end = bank.ex.read(folder / "FINISHED.json")
        totals = dict(tests=0, failures=0, errors=0, skipped=0)
        for suite in ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite"):
            for key in totals:
                totals[key] += int(suite.attrib.get(key, 0))
        assert totals == end["counts"] == dict(tests=248, failures=0, errors=0, skipped=0)
        assert 0 < end["elapsed_seconds"] < 900
        if device == "cuda":
            assert 0 < end["peak_cuda_allocated_bytes"] <= 4 * 2**30
        result[device] = {k: end[k] for k in ("status", "counts", "elapsed_seconds")}
    audit = bank.ex.read(BUNDLE / "qualification/CPU_ISOLATION.json")
    return dict(
        status="QUALIFICATION_AND_CPU_ISOLATION_REPLAY_PASS_NOT_7B_RESULT",
        source=seal["source_commit"],
        source_files=792,
        devices=result,
        cpu_isolation=dict(
            status=audit["status"],
            samples=len(audit["samples"]),
            own_gpu_clients=[],
            child_probe=audit["child_probe"],
        ),
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
