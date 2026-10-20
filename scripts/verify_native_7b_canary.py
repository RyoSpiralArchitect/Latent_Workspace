#!/usr/bin/env python3
"""Offline source/receipt/replay verification. Never imports Torch or runs a model."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

PLAN = "configs/v1_0/NATIVE_7B_CANARY.json"
ENTRY = "scripts/run_native_7b_canary.py"
SCOPES = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")
TINY_PASS = "TINY_NATIVE_CANARY_HARNESS_PASS_NOT_7B"
CEILING = dict(
    new_sequences=0,
    judge_calls=0,
    weight_deletions=0,
    old_expression_gate="FAIL",
    winner="none",
    non_regression="NOT_ESTABLISHED",
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manifest(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        require(not path.is_symlink(), "Artifact symlink")
        if path.is_file() and path != folder / "FINISHED.json":
            result[path.relative_to(folder).as_posix()] = dict(
                bytes=path.stat().st_size, sha256=digest(path)
            )
    return result


def terminal(folder):
    start, end = read(folder / "STARTED.json"), read(folder / "FINISHED.json")
    require(end["files"] == manifest(folder), "Artifact manifest mismatch")
    require(all(end.get(key) == value for key, value in CEILING.items()), "Claim ceiling")
    return start, end


def verify_source(bundle, repo):
    seal = read(bundle / "SOURCE_SEAL.json")
    sha = seal["source_commit"]
    require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Source commit")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo)

    tracked = set(
        filter(
            None, git("ls-tree", "-r", "--name-only", "-z", sha, "--", *SCOPES).decode().split("\0")
        )
    )
    require(tracked == set(seal["source_hashes"]), "Complete source seal")
    blobs = {}
    for name, expected in seal["source_hashes"].items():
        require(
            not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts,
            "Source path",
        )
        data = git("show", f"{sha}:{name}")
        require(hashlib.sha256(data).hexdigest() == expected, f"Source hash: {name}")
        if name == ENTRY or name.startswith("configs/v1_0/NATIVE_7B_CANARY"):
            blobs[name] = data
    # Read the literal plan path from the sealed source without executing it.
    assignments = [
        node.value.value
        for node in ast.parse(blobs[ENTRY]).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "PLAN" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    require(len(assignments) == 1 and assignments[0] in blobs, "Sealed literal plan path")
    plan = json.loads(blobs[assignments[0]])
    plan_sha = hashlib.sha256(canonical(plan).encode()).hexdigest()
    require(f'PLAN_SHA256 = "{plan_sha}"'.encode() in blobs[ENTRY], "Frozen plan hash")
    require(
        plan["schema"]
        in (
            "ltws-native-memory-7b-canary-v1",
            "ltws-native-memory-7b-canary-identity-recovery-v1",
        )
        and plan["no_retry"],
        "Canary scope",
    )
    if "identity_reference" in plan:
        ref = plan["identity_reference"]
        raw = git("show", f"{sha}:{ref['path']}")
        require(hashlib.sha256(raw).hexdigest() == ref["sha256"], "Historical identity reference")
        contract = json.loads(raw)["contract"]
        require(
            plan["backbone"]["identity"]
            == dict(
                legacy_state_v1_sha256=contract["original_legacy_identity_sha256"],
                state_tree_v1_sha256=contract["original_base_sha256"],
            ),
            "Identity schemes bound to history",
        )
        old = plan["recovery_of"]
        raw = git("show", f"{sha}:{old['terminal']}")
        require(hashlib.sha256(raw).hexdigest() == old["terminal_sha256"], "Previous terminal")
    return seal, plan


def verify_identity(folder, plan, *, complete):
    path = folder / "ORIGINAL_IDENTITY.json"
    if not complete and not path.exists():
        return
    record = read(path)
    expected = plan["backbone"]["identity"]
    require(
        record["schema"] == "named-native-model-identity-v1"
        and record["expected"] == expected
        and set(record["observed"]) == set(expected),
        "Named identity receipt",
    )
    observed = record["observed"]
    require(
        all(
            isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
            for v in observed.values()
        ),
        "Observed identity digest",
    )
    matches = {key: observed[key] == expected[key] for key in expected}
    require(record["matches"] == matches, "Measured identity matches")
    if complete:
        require(all(matches.values()), "Original model identity")
        require(
            read(folder / "CONTEXT.json")["contract"]["original_base_sha256"]
            == observed["state_tree_v1_sha256"],
            "Identity bound to run contract",
        )


def verify_qualification(bundle, seal, plan):
    devices = {}
    require(plan["qualification_devices"] == ["cpu", "cuda"], "Both qualification devices")
    expected = dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
    for device in ("cpu", "cuda"):
        folder = bundle / "qualification" / device
        start, end = terminal(folder)
        require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification source/selection",
        )
        require(
            end["status"] == TINY_PASS
            and end["pytest_exit_code"] == 0
            and end["counts"] == expected
            and end["device"] == device,
            "Qualification outcome",
        )
        require(
            end["native_weight_updates"] == end["real_model_updates"] == 0,
            "Tiny is not pretrained updating",
        )
        require(
            0 <= end["elapsed_seconds"] <= plan["qualification_wall_seconds"],
            "Qualification wall limit",
        )
        require(end["cpu_mkldnn_enabled"] is False, "CPU backend policy")
        xml = ElementTree.parse(folder / "TESTS.xml").getroot()
        observed = {k: sum(int(s.get(k, 0)) for s in xml.iter("testsuite")) for k in expected}
        require(observed == expected, "Literal XML denominator")
        if device == "cuda":
            require(
                0 < end["peak_cuda_allocated_bytes"] <= plan["qualification_gpu_limit_gib"] * 2**30,
                "Tiny CUDA cap",
            )
        devices[device] = observed
    return devices


def verify_run(raw, seal, plan):
    start, end = terminal(raw)
    require(start["seal"] == seal and start["plan"] == plan, "Dispatch source/plan")
    if "identity" in plan["backbone"]:
        for role in ("primary", "replay"):
            if (raw / role).exists():
                terminal(raw / role)
                verify_identity(raw / role, plan, complete=end["status"] == plan["pass_status"])
    if end["status"] != plan["pass_status"]:
        require(end["status"] == "INCOMPLETE_NO_RETRY", "Unknown terminal status")
        return dict(
            status="VERIFIED_INCOMPLETE_NO_RETRY",
            completed_roles=end["completed_roles"],
            error=end.get("error"),
            native_weight_updates=end["native_weight_updates"],
        )
    require(end["completed_roles"] == ["primary", "replay"], "Two terminal roles")
    statuses = {"primary": "TWO_NATIVE_UPDATES_SAVED", "replay": "EXACT_NATIVE_STEP2_REPLAY"}
    for role, updates in (("primary", 2), ("replay", 1)):
        role_start, role_end = terminal(raw / role)
        require(
            role_start["seal"] == seal
            and role_start["plan"] == plan
            and role_start["role"] == role,
            "Role source/selection",
        )
        require(
            role_end["status"] == statuses[role] and role_end["native_weight_updates"] == updates,
            "Role completion/activity",
        )
        require(
            0 <= role_end["elapsed_seconds"] <= plan["resources"]["max_elapsed_seconds"],
            "Role wall limit",
        )
        require(
            0
            < role_end["outcome"]["peak_cuda_allocated_bytes"]
            <= plan["resources"]["allocator_cap_gib"] * 2**30,
            "Role CUDA cap",
        )
    primary, replay = raw / "primary", raw / "replay"
    inputs = read(primary / "INPUTS.json")
    require(inputs == read(replay / "INPUTS.json") and len(inputs) == 4, "Exact frozen inputs")
    for actual, selected in zip(inputs, plan["rows"], strict=True):
        require({k: actual[k] for k in selected} == selected, "Fixed input text/key")
        ids, labels, memory = actual["input_ids"], actual["labels"], actual["memory_ids"]
        require(
            len(ids) == len(labels) and labels[0] == -100 and labels[-1] == 2,
            "Causal answer labels/EOS",
        )
        count = sum(x != -100 for x in labels[1:])
        require(
            0
            < count
            == actual["supervised_tokens"]
            <= plan["bounds"]["answer_tokens_including_eos"],
            "Answer denominator",
        )
        require(
            len(memory) <= plan["bounds"]["memory_tokens"]
            and len(ids) <= plan["bounds"]["query_tokens_including_answer"],
            "Input bounds",
        )
    context = read(primary / "CONTEXT.json")
    require(context["contract"] == read(replay / "CONTEXT.json")["contract"], "Run contract")
    require(
        context["contract"]["source_commit"] == seal["source_commit"]
        and context["contract"]["data_sha256"]
        == hashlib.sha256(canonical(inputs).encode()).hexdigest(),
        "Frozen source/data binding",
    )
    require(
        context["parameter_elements"] == plan["backbone"]["parameters"]
        and context["runtime"] == plan["expected_runtime"],
        "Native ownership/runtime",
    )
    require(read(replay / "RESTORE.json")["exact_step1"] is True, "Step1 restore")
    a, b = read(primary / "step2.json"), read(replay / "step2.json")
    require(a == b, "Step2 row/update/state/RNG equality")
    for folder, steps in ((primary, (1, 2)), (replay, (2,))):
        for step in steps:
            record = read(folder / f"step{step}.json")
            require(
                [r["key"] for r in record["rows"]] == plan["windows"][step - 1],
                "Ordered window rows",
            )
            for index, row in enumerate(record["rows"]):
                require(row == read(folder / f"step{step}_row{index}.json"), "Row receipt")
            changes = record["update"]["changes"]
            require(
                len(changes) == context["physical_parameters"]
                and any(c["master_changed"] for c in changes)
                and sum(c["native_changed_elements"] for c in changes) > 0,
                "Visible updates",
            )
    checkpoint = read(primary / "CHECKPOINT_step2.json")
    repeated = read(replay / "REPLAY.json")
    require(
        repeated["exact"] is True
        and repeated["state_sha256"] == checkpoint["state_sha256"]
        and repeated["replay_weight_file_written"] is False,
        "Exact serialized state",
    )
    expected = dict(
        native_weight_updates=3,
        unique_updates=2,
        replay_updates=1,
        backward_rows=6,
        retained_checkpoints=2,
        exact_replay=True,
        old_expression_gate="FAIL",
        non_regression="NOT_ESTABLISHED",
    )
    require(end["summary"] == expected and end["native_weight_updates"] == 3, "Final denominators")
    return dict(status="OFFLINE_NATIVE_7B_CANARY_VERIFIED_NOT_QUALITY", **expected)


def verify(bundle, repo, qualification_only=False):
    seal, plan = verify_source(bundle, repo)
    result = dict(
        source_commit=seal["source_commit"],
        source_files=len(seal["source_hashes"]),
        qualification=verify_qualification(bundle, seal, plan),
        status="QUALIFICATION_VERIFIED_NOT_7B",
        model_calls=0,
    )
    if not qualification_only:
        result.update(verify_run(bundle / "raw", seal, plan))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--qualification-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle, args.repo, args.qualification_only), indent=2))
