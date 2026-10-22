#!/usr/bin/env python3
"""Offline V22 source/receipt verifier, including honest partial/failure states.

Reads committed source with Git, never imports the training entry or Torch.
Weight-file verification is optional and explicit; receipts alone are not a
backup or an independent measurement of retained checkpoint bodies.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
from pathlib import Path
from xml.etree import ElementTree

SCOPES = ("src", "scripts", "tests", "configs", "data/v10", "pyproject.toml")
ROLES = ("canary", "replay", "train_a", "train_b")
STATUSES = (
    "V22_TWO_LENGTH_UPDATES_ONE_SAVE",
    "V22_EXACT_LENGTH_STEP2_REPLAY",
    "V22_TRAINING_STEP16_SAVED",
    "V22_TRAINING_STEP32_SAVED",
)
TINY = "TINY_V22_MIXED_TRAINING_HARNESS_PASS_NOT_7B"


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
    end = read(folder / "FINISHED.json")
    require(end["files"] == manifest(folder), "Terminal manifest differs")
    for key, value in dict(
        new_sequences=0,
        judge_calls=0,
        weight_deletions=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    ).items():
        require(end.get(key) == value, f"Claim ceiling: {key}")
    return read(folder / "STARTED.json"), end


def source(repo, seal, *, recovery=False):
    sha = seal["source_commit"]
    require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Commit ID")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo)

    names = set(
        filter(
            None, git("ls-tree", "-r", "--name-only", "-z", sha, "--", *SCOPES).decode().split("\0")
        )
    )
    require(names == set(seal["source_hashes"]), "Complete committed source set")
    for name, expected in seal["source_hashes"].items():
        require(
            hashlib.sha256(git("show", f"{sha}:{name}")).hexdigest() == expected,
            f"Source hash: {name}",
        )
    plan_path = (
        "configs/v22/FULL_FT_RECOVERY_01.json" if recovery else "configs/v22/FULL_FT_01.json"
    )
    entry_path = (
        "scripts/run_v22_full_ft_recovery01.py" if recovery else "scripts/run_v22_full_ft.py"
    )
    plan = json.loads(git("show", f"{sha}:{plan_path}"))
    frozen = hashlib.sha256(canonical(plan).encode()).hexdigest()
    entry = git("show", f"{sha}:{entry_path}").decode()
    require(f'PLAN_SHA256 = "{frozen}"' in entry, "Frozen execution plan")
    require(plan["no_retry"] and plan["planned_training_updates"] == 32, "Bounded V22")
    return plan


def data_index(folder, plan):
    require(
        digest(folder / "MANIFEST.json") == plan["data_manifest_sha256"], "Frozen data manifest"
    )
    for name, item in read(folder / "MANIFEST.json")["files"].items():
        if name == "rows.json.gz" and not (folder / name).exists():
            continue
        require(
            (folder / name).stat().st_size == item["bytes"]
            and digest(folder / name) == item["sha256"],
            "Data projection bytes",
        )
    rows = json.loads(gzip.decompress((folder / "index.json.gz").read_bytes()))
    lookup = {r["key"]: r for r in rows}
    require(len(lookup) == len(rows), "Index keys")
    schedule = read(folder / "SCHEDULE.json")
    keys = [k for w in schedule["training"] for k in w]
    require(
        len(keys) == plan["planned_training_rows"]
        and all(lookup[k]["split"] == "train" for k in keys),
        "Training rows/split",
    )
    require(
        sum(lookup[k]["supervised_tokens"] for k in keys) == plan["planned_training_tokens"],
        "Training tokens",
    )
    return lookup, schedule


def check_steps(folder, windows, first, last, index):
    for step in range(first, last + 1):
        record = read(folder / f"step{step}.json")
        keys = windows[step - 1]
        require([r["key"] for r in record["rows"]] == keys, "Exact row order")
        total = sum(index[k]["supervised_tokens"] for k in keys)
        for i, (key, row) in enumerate(zip(keys, record["rows"], strict=True)):
            require(read(folder / f"step{step}_row{i}.json") == row, "Row receipt binding")
            require(
                row["tokens"] == index[key]["supervised_tokens"] and math.isfinite(row["loss_sum"]),
                "Loss denominator",
            )
            # Receipt float32 loss division can round, so not a Python-double equality gate.
            require(
                math.isclose(
                    row["scaled_loss"], row["loss_sum"] / total, rel_tol=2e-6, abs_tol=1e-8
                ),
                "Token-weighted loss",
            )
        updated, state = record["update"], record["state"]
        prefix = [[(k, index[k]["supervised_tokens"]) for k in w] for w in windows[:step]]
        require(canonical(state["history"]) == canonical(prefix), "Complete history")
        tokens = sum(n for w in prefix for _, n in w)
        require(
            state["tokens_seen"] == updated["tokens_seen"] == tokens
            and state["completed_steps"] == updated["completed_steps"] == step,
            "Step/token cursor",
        )
        require(any(r["master_changed"] for r in updated["changes"]), "Master update")
        require(
            sum(r["native_changed_elements"] for r in updated["changes"]) > 0,
            "Realized native update",
        )


def verify(bundle, repo, data, checkpoints=None):
    seal = read(bundle / "SOURCE_SEAL.json")
    probe = read(bundle / "qualification/cpu/STARTED.json")
    recovery = probe["plan"]["schema"] == "ltws-v22-native-full-ft-recovery-01"
    plan = source(repo, seal, recovery=recovery)
    index, schedule = data_index(data, plan)
    qualification = {}
    for device in ("cpu", "cuda"):
        folder = bundle / "qualification" / device
        if not (folder / "FINISHED.json").exists():
            qualification[device] = "NO_TERMINAL"
            continue
        start, end = terminal(folder)
        require(
            start["seal"] == seal and start["plan"] == plan and start["device"] == device,
            "Qualification source/plan",
        )
        suites = ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite")
        counts = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for k in counts:
                counts[k] += int(suite.attrib.get(k, 0))
        require(end["counts"] == counts, "Qualification XML")
        if end["status"] == TINY:
            require(
                counts == dict(tests=plan["qualification_cases"], failures=0, errors=0, skipped=0)
                and end["pytest_exit_code"] == 0,
                "Qualification pass",
            )
        qualification[device] = end["status"]
    outcomes = {}
    for role, expected, updates in zip(ROLES, STATUSES, (2, 1, 16, 16), strict=True):
        folder = bundle / "raw" / role
        if not (folder / "FINISHED.json").exists():
            outcomes[role] = "NO_TERMINAL"
            continue
        start, end = terminal(folder)
        require(start["seal"] == seal and start["plan"] == plan, "Role source/plan")
        require(
            all(v == TINY for v in qualification.values()), "No role before complete qualification"
        )
        position = ROLES.index(role)
        require(
            all(outcomes.get(ROLES[i]) == STATUSES[i] for i in range(position)),
            "No later role after missing/failed predecessor",
        )
        outcomes[role] = end["status"]
        if end["status"] != expected:
            continue
        require(end["native_weight_updates"] == updates, "Physical update count")
        identity = read(folder / "ORIGINAL_IDENTITY.json")
        require(
            identity["expected"] == plan["backbone"]["identity"] == identity["observed"]
            and all(identity["matches"].values()),
            "Original identity",
        )
        stream = "canary" if role in ("canary", "replay") else "training"
        contract = read(folder / "CONTEXT.json")["contract"]
        expected_data = hashlib.sha256(
            canonical(dict(manifest_sha256=plan["data_manifest_sha256"], stream=stream)).encode()
        ).hexdigest()
        require(
            contract
            == dict(
                source_commit=seal["source_commit"],
                original_base_sha256=plan["backbone"]["identity"]["state_tree_v1_sha256"],
                data_sha256=expected_data,
                objective=plan["objective"],
            ),
            "Source/base/data/stream objective binding",
        )
        if role == "replay":
            reference = bundle / "raw/canary"
            require(
                read(folder / "step2.json") == read(reference / "step2.json"), "Exact canary replay"
            )
            replay = read(folder / "REPLAY.json")
            require(
                replay["exact"] is True
                and replay["state_sha256"]
                == read(reference / "STEP2_PAYLOAD.json")["state_sha256"],
                "Exact replay payload",
            )
            check_steps(folder, schedule["canary"], 2, 2, index)
        else:
            windows = schedule["canary"] if role == "canary" else schedule["training"]
            first, last = {"canary": (1, 2), "train_a": (1, 16), "train_b": (17, 32)}[role]
            check_steps(folder, windows, first, last, index)
        for receipt_path in folder.glob("CHECKPOINT_*.json"):
            receipt = read(receipt_path)
            require(
                receipt["path"] in plan["checkpoint_names"]
                and receipt["bytes"] <= plan["checkpoint_max_bytes"],
                "Checkpoint scope/size",
            )
            state = read(folder / f"STATE_{receipt['path']}.json")
            require(
                state == read(folder / f"step{receipt['completed_steps']}.json")["state"],
                "Saved checkpoint state",
            )
            if checkpoints is not None:
                path = checkpoints / receipt["path"]
                require(
                    path.stat().st_size == receipt["bytes"] and digest(path) == receipt["sha256"],
                    "Checkpoint body bytes",
                )
        if role in ("replay", "train_b"):
            require(read(folder / "RESTORE.json")["exact"] is True, "Fresh-process restore")
        if role in ("train_a", "train_b"):
            expected_rows = sum(
                map(
                    len,
                    schedule["training"][0:16]
                    if role == "train_a"
                    else schedule["training"][16:32],
                )
            )
            require(end["outcome"]["backward_rows"] == expected_rows, "Training row denominator")
            development = read(
                folder / ("DEV_BASE.json" if role == "train_a" else "DEV_STEP32.json")
            )
            require(
                [r["key"] for r in development["rows"]] == schedule["development"],
                "Frozen development panel",
            )
            losses, counts = {}, {}
            for row in development["rows"]:
                require(
                    row["supervised_tokens"] == index[row["key"]]["supervised_tokens"]
                    and math.isfinite(row["loss_sum"]),
                    "Dev loss/denominator",
                )
                key = row["bucket"]
                losses[key] = losses.get(key, 0) + row["loss_sum"]
                counts[key] = counts.get(key, 0) + row["supervised_tokens"]
            require(
                development["tokens_by_bucket"] == counts
                and development["mean_nll_by_bucket"] == {k: losses[k] / counts[k] for k in counts},
                "Dev aggregate replay",
            )
        if recovery:
            row_files = list(folder.glob("step*_row*.json"))
            cache_files = list(folder.glob("CACHE_step*_row*.json"))
            require(len(cache_files) == len(row_files), "Cache/row denominator")
            for path in cache_files + list(folder.glob("CACHE_restore.json")):
                item = read(path)
                require(
                    item["action"] == "SYNCHRONIZE_EMPTY_CACHE"
                    and item["before"]["allocated_bytes"] == item["after"]["allocated_bytes"],
                    "Cache-only live allocation invariant",
                )
            require(
                (folder / "CACHE_restore.json").exists() == (role in ("replay", "train_b")),
                "Cache restore boundary count",
            )
    if recovery:
        for phase, roles, count in (("checks", ROLES[:2], 3), ("training", ROLES[2:], 32)):
            folder = bundle / phase
            if not (folder / "FINISHED.json").exists():
                continue
            start, end = terminal(folder)
            require(start["seal"] == seal and start["plan"] == plan, "Recovery phase source")
            if end["status"] != "INCOMPLETE_NO_RETRY":
                require(
                    end["native_weight_updates"] == count and end["completed_roles"] == list(roles),
                    "Phase activity denominator",
                )
                for role in roles:
                    actual = manifest(bundle / "raw" / role)
                    path = bundle / "raw" / role / "FINISHED.json"
                    actual["FINISHED.json"] = dict(bytes=path.stat().st_size, sha256=digest(path))
                    require(end["role_manifests"][role] == actual, "Phase role binding")
    complete = [outcomes[r] for r in ROLES] == list(STATUSES)
    if (bundle / "raw/FINISHED.json").exists():
        start, end = terminal(bundle / "raw")
        require(start["seal"] == seal and start["plan"] == plan, "Dispatch source")
        if end["status"] == plan["pass_status"]:
            require(complete and end["native_weight_updates"] == 35, "Complete training dispatch")
        else:
            complete = False
    else:
        complete = False
    return dict(
        status="OFFLINE_V22_COMPLETE_NOT_QUALITY" if complete else "OFFLINE_V22_PARTIAL_OR_FAILED",
        qualification=qualification,
        roles=outcomes,
        source_commit=seal["source_commit"],
        checkpoint_bodies_checked=checkpoints is not None,
        model_calls=0,
        old_expression_gate="FAIL",
        non_regression="NOT_ESTABLISHED",
        winner="none",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.bundle, args.repo, args.data, args.checkpoints), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
