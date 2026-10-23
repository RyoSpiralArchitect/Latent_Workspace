#!/usr/bin/env python3
"""Offline public-subset replay; private preservation arrays remain on Furnace."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from qualification_isolation import validate_audit  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import recruitment_bank as bank  # noqa: E402
from latent_workspace import world_expansion as worlds  # noqa: E402

SOURCE = "92d078880176d1a3f6fd1aa16adc9d2c19050b85"
PRIVATE = {"PRIVATE_CANARY.json.gz", "PRIVATE_inline.json.gz", "PRIVATE_workspace.json.gz"}


def manifest_subset(folder, expected, omitted=()):
    observed = ex.manifest(folder)
    observed.pop("FINISHED.json", None)
    ex.require(
        observed == {k: v for k, v in expected.items() if k not in omitted}, "Exact public subset"
    )
    ex.require(set(omitted) <= set(expected), "Explicit private omissions only")


def verify(folder):
    folder = Path(folder)
    seal = ex.read(folder / "SOURCE_SEAL.json")
    ex.require(seal["source_commit"] == SOURCE, "Pinned preparation source")
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            SOURCE,
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
        bodies = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in bodies.items()}
    ex.require(hashes == seal["source_hashes"], "Entire committed source seal")
    plan = json.loads(bodies["configs/v24/RECRUITMENT_PREPARATION_01.json"])
    recipe = json.loads(bodies[plan["recipe"]])
    path = folder / "qualification/cpu"
    start, end = ex.read(path / "STARTED.json"), ex.read(path / "FINISHED.json")
    manifest_subset(path, end["files"])
    counts = dict(tests=60, failures=0, errors=0, skipped=0)
    xml = ElementTree.parse(path / "TESTS.xml")
    observed = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in counts}
    ex.require(
        start["seal"] == seal
        and start["plan"] == plan
        and end["counts"] == observed == counts
        and end["status"] == "V24_RECRUITMENT_DATA_TESTS_PASS",
        "CPU qualification",
    )
    validate_audit(
        ex.read(folder / "qualification/CPU_ISOLATION.json"),
        ex.digest(path / "FINISHED.json"),
        start["pid"],
    )
    for role, omitted in (
        ("raw", {"data/bank/" + p for p in PRIVATE}),
        ("raw/data", {"bank/" + p for p in PRIVATE}),
    ):
        path = folder / role
        start, end = ex.read(path / "STARTED.json"), ex.read(path / "FINISHED.json")
        manifest_subset(path, end["files"], omitted)
        ex.require(
            start["seal"] == seal
            and start["plan"] == plan
            and end["status"] == plan["pass_status"],
            "Completed same-source preparation",
        )
        ex.require(
            all(end[k] == v for k, v in ex.CEILING.items()), "No model activity or promotion"
        )
    data = folder / "raw/data/bank"
    manifest = ex.read(data / "MANIFEST.json")
    observed = ex.manifest(data)
    observed.pop("MANIFEST.json")
    ex.require(
        observed == {k: v for k, v in manifest["files"].items() if k not in PRIVATE},
        "Data public subset",
    )
    ex.require(manifest["source_commit"] == SOURCE, "Data source")
    for name, sha in manifest["source"].items():
        ex.require(
            sha == hashes[name] == ex.digest(ROOT / name), "Exact generator replay implementation"
        )
    world_plan = ex.read(ROOT / recipe["world_plan"])
    expected = [dict(r, role="world") for r in worlds.build(world_plan)] + bank.build(recipe)
    ex.require(
        ex.read_gz(data / "PUBLIC_SYNTHETIC.json.gz") == expected, "Full synthetic regeneration"
    )
    schedule, summary = ex.read(data / "SCHEDULE.json"), ex.read(data / "SUMMARY.json")
    ex.require(
        summary
        == {
            k: v
            for k, v in ex.read(folder / "raw/data/FINISHED.json")["outcome"].items()
            if k != "bank_manifest_sha256"
        },
        "Outcome-summary equality",
    )
    ex.require(
        len(schedule["training"]) == 32 and sum(map(len, schedule["training"])) == 538,
        "Complete ordered windows",
    )
    raw_lookup = {r["row_id"]: r for r in expected}
    for key in (k for w in schedule["training"] for k in w):
        if key in raw_lookup:
            ex.require(raw_lookup[key]["split"] == "train", "No heldout synthetic update")
    ex.require(
        sum(summary["training_tokens_by_role"].values())
        == summary["training_tokens_per_arm"]
        == 21112,
        "Target census",
    )
    return dict(
        status="PUBLIC_SUBSET_AND_SYNTHETIC_REPLAY_VERIFIED",
        source_commit=SOURCE,
        source_files=len(hashes),
        private_files_omitted=sorted(PRIVATE),
        private_token_arrays_recomputed_locally=False,
        model_calls=0,
        bank_manifest_sha256=ex.digest(data / "MANIFEST.json"),
        summary=summary,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(ex.canonical(verify(args.bundle)))
