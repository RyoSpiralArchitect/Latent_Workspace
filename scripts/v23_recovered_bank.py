"""Explicit mixed-attempt bank; never fabricate an original successful run."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_v23_comparison_recovery02 as recovery  # noqa: E402
import v23_behavior_judge as judge  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402

PLAN = "configs/v23/RECOVERED_FOLLOWUP_01.json"


def plan():
    p = ex.read(ROOT / PLAN)
    ex.require(
        p["schema"] == "ltws-v23-explicit-recovered-bank-01"
        and p["original_source"] == "84073310cd7b2c56b5e3de046fb3bdc99e461bfb"
        and p["recovery_source"] == "af9cd1a727d98d942df1845c35a14628f8f7481b"
        and p["arm_origins"] == dict(base="original", off="original", on="recovery"),
        "Pinned whole-arm origin mapping",
    )
    return p


def source_seal(folder, commit):
    seal = ex.read(folder / "SOURCE_SEAL.json")
    ex.require(seal["source_commit"] == commit, "Historical source commit")
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            commit,
            "--",
            "src",
            "scripts",
            "tests",
            "configs",
            "data/v10",
            "pyproject.toml",
        ],
        cwd=ROOT,
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        expected = {
            member.name: hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            for member in tar.getmembers()
            if member.isfile()
        }
    ex.require(seal["source_hashes"] == expected, "Every historical source byte and path")
    return seal


def terminal(folder, status):
    end = ex.read(folder / "FINISHED.json")
    actual = ex.manifest(folder)
    actual.pop("FINISHED.json")
    ex.require(end["status"] == status and end["files"] == actual, "Terminal status / bytes")
    return end


def role(folder, seal, expected_plan):
    end = terminal(folder, "V23_EVALUATION_ARM_COMPLETE")
    start = ex.read(folder / "STARTED.json")
    ex.require(start["seal"] == seal and start["plan"] == expected_plan, "Whole-arm provenance")
    outcome = end["outcome"]
    ex.require(
        tuple(outcome[k] for k in ("mmlu_rows", "world_rows", "free_rows", "new_sequences"))
        == (570, 192, 24, 216),
        "Complete arm denominator",
    )
    rows = {name: judge.read_lines(folder / f"{name}.jsonl") for name in ("mmlu", "worlds", "free")}
    ex.require(tuple(map(len, rows.values())) == (570, 192, 24), "Actual journal denominator")
    keys = {
        "mmlu": [r["id"] for r in rows["mmlu"]],
        "worlds": [(r["id"], r["route"]) for r in rows["worlds"]],
        "free": [(r["id"], r["seed"]) for r in rows["free"]],
    }
    ex.require(all(len(keys[n]) == len(set(keys[n])) for n in keys), "Unique journal IDs")
    weights = ex.read(folder / "WEIGHT_IDENTITY.json")
    ex.require(weights["equal"] and weights["before"] == weights["after"], "Read-only weights")
    return rows


def no_saved_checkpoints(folder, *, published_copy=False):
    """Git omits empty directories; live execution still requires the directory."""
    path = folder / "checkpoints"
    if published_copy and not path.exists():
        return
    ex.require(path.is_dir() and not list(path.iterdir()), "No saved model bodies")


def verify(original=None, recovered=None, *, published_copy=False):
    p = plan()
    original = Path(p["original_bundle"]) if original is None else Path(original)
    recovered = Path(p["recovery_bundle"]) if recovered is None else Path(recovered)
    ex.require(original.resolve() != recovered.resolve(), "Distinct execution bundles")
    old_plan = ex.read(ROOT / recovery.previous.original.PLAN)
    new_plan = ex.read(ROOT / recovery.PLAN)
    original_provenance = recovery.previous.verify_original(new_plan, original)
    old_seal = source_seal(original, p["original_source"])
    new_seal = source_seal(recovered, p["recovery_source"])
    # Recovery added isolation/dispatch code; every old sealed file stayed exact.
    ex.require(
        all(new_seal["source_hashes"].get(n) == h for n, h in old_seal["source_hashes"].items()),
        "No numerical/input source change between generation attempts",
    )
    qualified = recovery.RUN.qualification(recovered / "qualification", new_seal, new_plan)
    end = terminal(recovered / "raw", "V23_PON_RECOVERY_COMPLETE_NOT_RELEASE")
    ex.require(end["completed_roles"] == ["on"] and end["new_sequences"] == 216, "Whole on only")
    start = ex.read(recovered / "raw/STARTED.json")
    ex.require(
        start["seal"] == new_seal
        and start["plan"] == new_plan
        and start["qualification"] == qualified,
        "Recovery dispatch qualification",
    )
    no_saved_checkpoints(recovered, published_copy=published_copy)
    arms = {
        "base": role(original / "raw/base", old_seal, old_plan),
        "off": role(original / "raw/off", old_seal, old_plan),
        "on": role(recovered / "raw/on", new_seal, new_plan),
    }
    for name in ("mmlu", "worlds", "free"):
        key = lambda r: (r["id"], r.get("route"), r.get("seed"))  # noqa: E731
        expected = list(map(key, arms["base"][name]))
        ex.require(
            all(list(map(key, a[name])) == expected for a in arms.values()), "Paired IDs/order"
        )
    origins = dict(
        schema="explicit-combined-bank-not-an-original-success",
        plan=p,
        original=original_provenance,
        recovery=dict(
            source=p["recovery_source"],
            source_seal_sha256=ex.digest(recovered / "SOURCE_SEAL.json"),
            terminal_sha256=ex.digest(recovered / "raw/FINISHED.json"),
        ),
        arms={
            r: dict(
                attempt=p["arm_origins"][r],
                terminal_sha256=ex.digest(
                    (recovered if r == "on" else original) / "raw" / r / "FINISHED.json"
                ),
            )
            for r in ("base", "off", "on")
        },
        excluded_original_on_rows=79,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    return arms, origins


def cases_from_arms(arms, policy):
    """The original all-answer selection; only source lookup differs."""
    reference = ex.read(ROOT / "configs/v22/BASE_COMPARISON_01.json")
    expected = {
        (r["id"], s): r for r in reference["free_prompts"] for s in reference["generation"]["seeds"]
    }
    indexes = {}
    for arm in ("base", "off", "on"):
        records = arms[arm]["free"]
        rows = {(r["id"], r["seed"]): r for r in records}
        ex.require(
            len(records) == len(rows) == 24 and rows.keys() == expected.keys(), "All 24 answers"
        )
        for k, row in rows.items():
            ex.require(
                row["prompt"] == expected[k]["prompt"]
                and row["max_new_tokens"] == 256
                and row["temperature"] == 0.7
                and row["top_p"] == 0.9
                and row["stop_reason"] in ("eos", "length"),
                "Frozen answer policy",
            )
        indexes[arm] = rows
    cases = []
    for key in sorted(expected):
        for a, b in policy["pairs"]:
            cases.append(
                dict(
                    id=f"{key[0]}:{key[1]}:{a}:{b}",
                    prompt=expected[key]["prompt"],
                    a=indexes[a][key],
                    b=indexes[b][key],
                    arms=[a, b],
                    unit=list(key),
                    repeat=key[0] in policy["repeat_prompts"] and key[1] == policy["repeat_seed"],
                )
            )
        if key[0] in policy["identical_control_prompts"] and key[1] == policy["repeat_seed"]:
            cases.append(
                dict(
                    id=f"{key[0]}:{key[1]}:identical",
                    prompt=expected[key]["prompt"],
                    a=indexes["base"][key],
                    b=indexes["base"][key],
                    arms=["base", "base"],
                    unit=list(key),
                    expected="tie",
                    repeat=False,
                )
            )
    return cases


if __name__ == "__main__":
    print(json.dumps(verify()[1], indent=2))
