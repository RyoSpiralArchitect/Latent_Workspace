"""Offline public-record replay; no model imports, dispatch, or private bodies.

The only optional write is exclusive creation of a derived analysis. Existing
trial records are never edited. Run without Python's assertion-disable flag.
"""

import argparse
import collections
import json
import math
from pathlib import Path

from verify_qualification import SOURCE, manifest, read, verify, verify_public_teacher

ROLES = ("teacher", "canary", "replay", "off", "on")
PRIVATE = "teacher/PRIVATE_TEACHER_TARGETS.safetensors"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ceiling(record):
    require(record["old_expression_gate"] == "FAIL", "Old gate changed")
    require(record["winner"] == "none", "Unexpected winner")
    require(record["non_regression"] == "NOT_ESTABLISHED", "Retention claim changed")
    for key in ("new_sequences", "judge_calls", "weight_deletions"):
        require(record[key] == 0, f"Unexpected activity: {key}")


def replay_manifest(folder, omitted=()):
    end = read(folder / "FINISHED.json")
    actual = manifest(folder)
    actual.pop("FINISHED.json")
    require(
        actual == {k: v for k, v in end["files"].items() if k not in omitted},
        f"Public manifest mismatch: {folder}",
    )
    require(set(omitted) <= set(end["files"]), "Omission not in manifest")
    return end


def dev_summary(value):
    rows = value["rows"]
    require(len(rows) == 40 and len({r["key"] for r in rows}) == 40, "Dev census")
    counts, tokens, losses = collections.Counter(), collections.Counter(), collections.Counter()
    for row in rows:
        n, loss, bucket = row["supervised_tokens"], row["loss_sum"], row["bucket"]
        require(n > 0 and math.isfinite(loss) and loss >= 0, "Invalid dev loss")
        counts[bucket] += 1
        tokens[bucket] += n
        losses[bucket] += loss
    means = {b: losses[b] / tokens[b] for b in tokens}
    require(dict(tokens) == value["tokens_by_bucket"], "Dev bucket denominator")
    require(means == value["mean_nll_by_bucket"], "Dev bucket means")
    return dict(
        rows=40,
        targets=sum(tokens.values()),
        mean_nll=sum(r["loss_sum"] for r in rows) / sum(tokens.values()),
        by_bucket={
            b: dict(rows=counts[b], targets=tokens[b], mean_nll=means[b]) for b in sorted(tokens)
        },
    )


def paired_dev(left, right):
    require(
        [(r["key"], r["bucket"], r["supervised_tokens"]) for r in left["rows"]]
        == [(r["key"], r["bucket"], r["supervised_tokens"]) for r in right["rows"]],
        "Paired dev identity/order mismatch",
    )
    deltas = [
        dict(
            key=a["key"],
            bucket=a["bucket"],
            targets=a["supervised_tokens"],
            left_nll=a["loss_sum"] / a["supervised_tokens"],
            right_nll=b["loss_sum"] / b["supervised_tokens"],
            delta=(b["loss_sum"] - a["loss_sum"]) / a["supervised_tokens"],
        )
        for a, b in zip(left["rows"], right["rows"], strict=True)
    ]
    return dict(
        right_lower=sum(r["delta"] < 0 for r in deltas),
        right_equal=sum(r["delta"] == 0 for r in deltas),
        right_higher=sum(r["delta"] > 0 for r in deltas),
        rows=deltas,
    )


def train_summary(folder, eligible, enabled):
    windows, history, preservation_history = [], [], []
    for step in range(1, 33):
        record = read(folder / f"step{step}.json")
        rows, update, state = (record[k] for k in ("rows", "update", "state"))
        n = sum(r["tokens"] for r in rows)
        np = sum(r["tokens"] for r in rows if r["key"] in eligible)
        require(n > 0 and np > 0, "Missing window denominator")
        for i, row in enumerate(rows):
            require(row == read(folder / f"step{step}_row{i}.json"), "Row receipt mismatch")
            require(math.isfinite(row["loss_sum"]), "Nonfinite training CE")
            if enabled:
                require(
                    row["ce_denominator"] == n and row["preservation_denominator"] == np,
                    "Incorrect CE/KL window denominators",
                )
                eligible_n = row["tokens"] if row["key"] in eligible else 0
                require(row["preservation_tokens"] == eligible_n, "KL eligibility")
                require((row["kl_sum"] is None) == (eligible_n == 0), "KL missingness")
                if eligible_n:
                    require(math.isfinite(row["kl_sum"]), "Nonfinite training KL")
                require(
                    math.isclose(row["scaled_ce"], row["loss_sum"] / n, rel_tol=2e-7, abs_tol=1e-9),
                    "Scaled CE",
                )
            else:
                require(
                    "kl_sum" not in row and "preservation_tokens" not in row,
                    "Off entered positive-P path",
                )
        history.append([[r["key"], r["tokens"]] for r in rows])
        preservation_history.append([r for r in history[-1] if r[0] in eligible])
        require(
            state["history"] == history and state["completed_steps"] == step,
            "Training state cursor/history",
        )
        require(
            update["completed_steps"] == step and len(update["changes"]) == 291,
            "Native update count",
        )
        windows.append(
            dict(
                step=step,
                rows=len(rows),
                targets=n,
                eligible_targets=np,
                ce_sum=sum(r["loss_sum"] for r in rows),
                ce_mean=sum(r["loss_sum"] for r in rows) / n,
                kl_sum=sum(r["kl_sum"] or 0 for r in rows) if enabled else None,
                kl_mean=sum(r["kl_sum"] or 0 for r in rows) / np if enabled else None,
                preclip_native_l2=update["preclip_native_l2"],
            )
        )
    flat = [r for w in history for r in w]
    require(len(flat) == len({r[0] for r in flat}) == 723, "Training row census")
    require(sum(r[1] for r in flat) == 20860, "Training target census")
    require(sum(w["eligible_targets"] for w in windows) == 16763, "Preservation census")
    require(state == read(folder / f"STATE_{folder.name}_step32.pt.json"), "Saved final state")
    if enabled:
        require(
            read(folder / "PRESERVATION_on_step32.pt.json")
            == dict(history=preservation_history, tokens_seen=16763),
            "Saved KL history",
        )
    return dict(
        updates=32,
        unique_rows=723,
        targets=20860,
        kl_targets=16763 if enabled else 0,
        windows=windows,
        online_ce_sum=sum(w["ce_sum"] for w in windows),
        online_ce_mean=sum(w["ce_sum"] for w in windows) / 20860,
        online_kl_mean=(sum(w["kl_sum"] for w in windows) / 16763 if enabled else None),
        checkpoint=read(folder / f"CHECKPOINT_{folder.name}_step32.pt.json"),
        native_sha256=state["native"],
    )


def analyze(root, repo):
    qualification = verify(root, repo)
    teacher = verify_public_teacher(root)
    seal = read(root / "SOURCE_SEAL.json")
    raw = root / "raw"
    end = replay_manifest(raw, (PRIVATE,))
    ceiling(end)
    require(
        end["status"] == "V23_MATCHED_P_OFF_ON_32_STEPS_COMPLETE_NOT_QUALITY"
        and end["completed_roles"] == list(ROLES)
        and end["native_weight_updates"] == 67,
        "Incomplete dispatch",
    )
    require(read(raw / "STARTED.json")["seal"] == seal, "Dispatcher source")
    roles = {}
    for role, updates in zip(ROLES, (0, 2, 1, 32, 32), strict=True):
        folder = raw / role
        terminal = replay_manifest(folder, (Path(PRIVATE).name,) if role == "teacher" else ())
        ceiling(terminal)
        require(
            terminal["status"] == f"V23_PRESERVATION_{role.upper()}_COMPLETE"
            and terminal["native_weight_updates"] == updates,
            "Incomplete role",
        )
        require(read(folder / "STARTED.json")["seal"] == seal, "Role source")
        require(0 < terminal["elapsed_seconds"] < 14400, "Role wall limit")
        host = [
            json.loads(line) for line in (folder / "HOST_RESOURCES.jsonl").read_text().splitlines()
        ]
        gpu = [json.loads(line) for line in (folder / "RESOURCES.jsonl").read_text().splitlines()]
        require(min(r["disk_free_bytes"] for r in host) >= 50 * 2**30, "Disk floor")
        require(min(r["available_bytes"] for r in host) >= 24 * 2**30, "Host floor")
        require(min(r["free_bytes"] for r in gpu) >= 0.75 * 2**30, "GPU floor")
        roles[role] = dict(
            elapsed_seconds=terminal["elapsed_seconds"],
            **terminal["outcome"],
            minimum_disk_free_gib=min(r["disk_free_bytes"] for r in host) / 2**30,
        )
    require(
        read(raw / "canary/step2.json") == read(raw / "replay/step2.json"),
        "Full row/gradient/state replay mismatch",
    )
    replay = read(raw / "replay/REPLAY.json")
    require(
        replay == dict(exact=True, **read(raw / "canary/STEP2_PAYLOAD.json")),
        "Full v2 payload replay mismatch",
    )
    require(read(raw / "off/INITIAL.json") == read(raw / "on/INITIAL.json"), "Initial mismatch")
    base = read(raw / "off/DEV_BASE.json")
    require(base == read(raw / "on/DEV_BASE.json"), "Base forward mismatch")
    eligible = {r["key"] for r in read(raw / "teacher/TEACHER_TARGETS.json")["rows"]}
    train = {arm: train_summary(raw / arm, eligible, arm == "on") for arm in ("off", "on")}
    require(
        read(raw / "off/STATE_off_step32.pt.json")["history"]
        == read(raw / "on/STATE_on_step32.pt.json")["history"],
        "Unmatched exposure",
    )
    dev = dict(base=base, **{a: read(raw / a / "DEV_STEP32.json") for a in ("off", "on")})
    older = repo / "provenance/pilots/v22_full_ft_recovery01_20261021/furnace/raw/train_b"
    v22 = dict(
        final_fingerprint_equal=read(older / "STATE_training_step32.pt.json")
        == read(raw / "off/STATE_off_step32.pt.json"),
        development_equal=read(older / "DEV_STEP32.json") == dev["off"],
        whole_payload_equal=False,
        note=(
            "Different source contracts and payload/file hashes; "
            "equal final fingerprints and dev are narrower."
        ),
    )
    return dict(
        schema="ltws-v23-preservation-ft-terminal-analysis-v1",
        source=SOURCE,
        status="PUBLIC_TERMINAL_REPLAY_PASS_NOT_QUALITY",
        public_raw_files=len(manifest(raw)),
        private_raw_omissions=[PRIVATE],
        checkpoint_bodies_verified_locally=False,
        qualifications=qualification,
        teacher=teacher,
        roles=roles,
        replay=replay,
        elapsed_seconds=end["elapsed_seconds"],
        native_weight_updates=67,
        training=train,
        dev={k: dev_summary(v) for k, v in dev.items()},
        pairs={
            f"{a}_to_{b}": paired_dev(dev[a], dev[b])
            for a, b in (("base", "off"), ("base", "on"), ("off", "on"))
        },
        off_vs_prior_v22=v22,
        limitations=[
            "Exposed fixed 40-row dev; not confirmation or accuracy",
            (
                "Online CE/KL measured on different rows along the training trajectory, "
                "not final-model drift"
            ),
            "Off KL was not measured; absent KL is not zero KL",
            "No new benchmark, generation, causal-use or quality evidence in this trial",
        ],
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write-analysis", type=Path)
    group.add_argument("--verify-analysis", type=Path)
    args = parser.parse_args()
    result = analyze(args.root, args.repo)
    if args.write_analysis:
        with args.write_analysis.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    if args.verify_analysis:
        require(read(args.verify_analysis) == result, "Derived analysis differs from replay")
    print(
        json.dumps(
            {k: result[k] for k in ("status", "public_raw_files", "dev", "off_vs_prior_v22")},
            indent=2,
        )
    )
