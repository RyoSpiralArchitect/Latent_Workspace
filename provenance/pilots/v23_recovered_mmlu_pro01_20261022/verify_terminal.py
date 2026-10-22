"""Replay the stopped attempt without resuming or filling missing observations."""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import run_v23_recovered_mmlu_pro as runner  # noqa: E402
import v23_recovered_bank as bank  # noqa: E402


def verify():
    folder = Path(__file__).resolve().parent / "furnace"
    seal = bank.source_seal(folder, "cda0a8ae8c3648c41fae2be45b3208c9a5f1a9b6")
    assert len(seal["source_hashes"]) == 799
    plan = bank.ex.read(ROOT / runner.PLAN)
    runner.RUN.qualification(folder / "qualification", seal, plan)
    for device in ("cpu", "cuda"):
        path = folder / "qualification" / device
        end = bank.ex.read(path / "FINISHED.json")
        total = dict(tests=0, failures=0, errors=0, skipped=0)
        for suite in ElementTree.parse(path / "TESTS.xml").getroot().iter("testsuite"):
            for k in total:
                total[k] += int(suite.attrib.get(k, 0))
        assert total == end["counts"] == dict(tests=301, failures=0, errors=0, skipped=0)
    end = bank.terminal(folder / "raw", "INCOMPLETE_NO_RETRY")
    role = bank.terminal(folder / "raw/base", "INCOMPLETE_NO_RETRY")
    assert not end["completed_roles"] and end["new_sequences"] is None
    assert role["new_sequences"] is None and "generation:107" in role["error"]
    for name in ("off", "on"):
        assert not (folder / "raw" / name).exists()
    path = folder / "raw/base"
    assert bank.ex.read(path / "STARTED.json")["seal"] == seal
    assert not (path / "WEIGHT_IDENTITY.json").exists()
    direct = bank.judge.read_lines(path / "direct.jsonl")
    assert len(direct) == len({r["id"] for r in direct}) == 280
    policy = runner.reference(plan)
    panel = bank.ex.read_gz(ROOT / policy["panel"])
    # Replay scores, targets and the exact frozen order, including ties.
    assert [r["id"] for r in direct] == [r["id"] for r in panel["rows"]]
    for row, item in zip(direct, panel["rows"], strict=True):
        scores = row["logits"]
        prediction = max(range(len(scores)), key=scores.__getitem__)
        ties = scores.count(max(scores))
        assert row["target"] == item["target"]
        assert row["prediction"] == prediction and row["ties"] == ties
        assert row["correct"] == (prediction == row["target"])
        assert row["strict_correct"] == (row["correct"] and ties == 1)
        assert row["gold_margin"] == scores[row["target"]] - max(
            v for i, v in enumerate(scores) if i != row["target"]
        )
    assert (path / "reasoning.jsonl").read_bytes() == b""
    resources = bank.judge.read_lines(path / "RESOURCES.jsonl")
    last = resources[-1]
    assert last["phase"] == "generation:107"
    assert last["free_bytes"] < plan["resources"]["abort_free_gib"] * 2**30
    assert all(p["pid"] == last["own_pid"] for p in last["processes"])
    result = dict(
        status="INCOMPLETE_NO_RETRY",
        source=seal["source_commit"],
        source_files=799,
        qualification=dict(cpu=301, cuda=301, cpu_isolation="PASS"),
        completed_roles=[],
        retained_base_direct_rows=280,
        planned_direct_rows=840,
        base_direct_correct=sum(r["correct"] for r in direct),
        base_tie_free_correct=sum(r["strict_correct"] for r in direct),
        base_top_option_ties=sum(r["ties"] > 1 for r in direct),
        completed_reasoning_rows=0,
        planned_reasoning_rows=84,
        terminal_sequence_activity=None,
        first_reasoning_status="Interrupted before step 107; partial tokens not journaled",
        stopped_resources=last,
        maximum_live_allocated_bytes=max(r.get("peak_allocated", 0) for r in resources),
        native_post_identity="NOT_REACHED",
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    target = Path(__file__).resolve().parent / "TERMINAL_ANALYSIS.json"
    if target.exists():
        assert bank.ex.read(target) == result
    else:
        bank.ex.write_new(target, result)
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
