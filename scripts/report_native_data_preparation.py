#!/usr/bin/env python3
"""Offline replay and literal review panels for the bounded data-preparation stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import run_native_teacher_inspection as teacher  # noqa: E402

from latent_workspace import execution as ex  # noqa: E402
from latent_workspace import world_bank as wb  # noqa: E402


def verify_seal(seal):
    """Read committed blobs, not mutable working files or model code."""
    names = sorted(seal["source_hashes"])
    refs = "".join(f"{seal['source_commit']}:{name}\n" for name in names)
    raw = subprocess.check_output(["git", "cat-file", "--batch"], input=refs.encode(), cwd=ROOT)
    cursor = 0
    for name in names:
        end = raw.index(b"\n", cursor)
        header = raw[cursor:end].split()
        ex.require(len(header) == 3 and header[1] == b"blob", "Sealed blob absent")
        size = int(header[2])
        payload = raw[end + 1 : end + 1 + size]
        ex.require(
            hashlib.sha256(payload).hexdigest() == seal["source_hashes"][name],
            f"Source seal mismatch: {name}",
        )
        cursor = end + size + 2
    ex.require(cursor == len(raw), "Extra source bytes")
    return dict(source_commit=seal["source_commit"], source_files=len(names))


def verify_terminal(directory):
    terminal = ex.read(directory / "FINISHED.json")
    actual = ex.manifest(directory)
    actual.pop("FINISHED.json")
    ex.require(actual == terminal["files"], f"Terminal bytes changed: {directory}")
    return terminal


def resource_report(root):
    sealed = verify_seal(ex.read(root / "SOURCE.json"))
    counts = {}
    for device in ("cpu", "cuda"):
        folder = root / "qualification" / device
        result = verify_terminal(folder)
        suites = ElementTree.parse(folder / "TESTS.xml").getroot()
        actual = {
            key: sum(int(s.get(key, "0")) for s in suites.iter("testsuite"))
            for key in ("tests", "failures", "errors", "skipped")
        }
        ex.require(actual == result["counts"], "Qualification XML disagrees")
        ex.require(
            actual == dict(tests=254, failures=0, errors=0, skipped=0), "Qualification incomplete"
        )
        counts[device] = actual
    dispatch = verify_terminal(root / "raw")
    role = verify_terminal(root / "raw" / "probe")
    ex.require(dispatch["completed_roles"] == ["probe"], "Resource dispatch incomplete")
    ex.require(role["status"] == "THREE_BACKWARDS_NO_NATIVE_UPDATE", "Resource role failed")
    result = ex.read(root / "raw" / "probe" / "RESOURCE_RESULT.json")
    ex.require(role["outcome"] == dispatch["summary"] == result, "Resource summary differs")
    identity = ex.read(root / "raw" / "probe" / "ORIGINAL_IDENTITY.json")
    ex.require(identity["observed"] == identity["expected"], "Original model identity differs")
    rows = ex.read(root / "raw" / "probe" / "RESOURCE_INPUTS.json")
    ex.require(
        [(len(r["memory_ids"]), len(r["input_ids"]), r["supervised_tokens"]) for r in rows]
        == [(0, 128, 16), (64, 128, 16), (128, 128, 16)],
        "Resource axes differ",
    )
    ex.require(
        result["backward_rows"] == 3
        and result["supervised_tokens"] == 48
        and result["masters_unchanged"]
        and result["native_unchanged"]
        and result["native_weight_updates"] == result["checkpoint_writes"] == 0,
        "Resource scope changed",
    )
    return {
        **sealed,
        "status": "OFFLINE_RESOURCE_REPLAY_PASS_NOT_TRAINING_QUALITY",
        "qualification": counts,
        "terminal_sha256": ex.digest(root / "raw" / "probe" / "FINISHED.json"),
        "resource_inputs_sha256": ex.plan_hash(rows),
        "peak_gib": {
            key: result[key] / ex.GIB
            for key in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "peak_host_rss_bytes",
            )
        },
        "native_weight_updates": 0,
        "checkpoint_writes": 0,
        "non_regression": "NOT_ESTABLISHED",
    }


def fence(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    marker = "`" * max(4, max((len(s) for s in text.split() if set(s) == {"`"}), default=0) + 1)
    return f"{marker}text\n{text}\n{marker}\n"


def teacher_report(root, bank, tokens):
    summary = teacher.verify(root, ex.read(ROOT / teacher.PLAN))
    sealed = verify_seal(ex.read(root / "SOURCE.json"))
    audit = wb.audit(
        ex.read_gz(bank / "world_rows.json.gz"), ex.read(bank / "instruction_seeds.json")
    )
    ex.require(audit == ex.read(bank / "AUDIT.json"), "Bank audit changed")
    manifest = ex.read(bank / "MANIFEST.json")
    actual = ex.manifest(bank)
    actual.pop("MANIFEST.json")
    ex.require(actual == manifest["files"], "Bank bytes changed")
    ex.require(
        ex.read(root / "FROZEN.json")["bank_manifest_sha256"] == ex.digest(bank / "MANIFEST.json"),
        "Teacher bank differs",
    )
    token_summary = ex.read(tokens / "SUMMARY.json")
    ex.require(
        token_summary["bank_manifest_sha256"] == ex.digest(bank / "MANIFEST.json"),
        "Token bank differs",
    )
    items = ex.read(root / "INPUTS.json")
    groups, elapsed = Counter(), 0.0
    panel = [
        "# Literal teacher inspection panel — all 64 planned items\n",
        "Source-backed review aid, not a blind judge. The teacher was shown canonical "
        "world answers and evidence. Structural PASS is not semantic approval. "
        "Every candidate remains quarantined; no training admission.\n",
    ]
    for i, item in enumerate(items):
        row = item["row"]
        path = root / "run" / f"outcome_{i:03d}.json"
        outcome = ex.read(path) if path.exists() else {"status": "NOT_ATTEMPTED"}
        groups[f"{item['kind']}/{row['family']}/{outcome['status']}"] += 1
        elapsed += outcome.get("elapsed_seconds", 0)
        panel.extend(
            [
                f"## {i + 1:02d} — {row['row_id']}\n",
                f"Kind: {item['kind']}; status: {outcome['status']}.\n",
                "Original memory:\n",
                fence(row["memory"]),
                "Original instruction/query:\n",
                fence(row["query"]),
                "Canonical/reference answer (not shown to the instruction teacher):\n",
                fence(row["answer"]),
            ]
        )
        if item["kind"] == "world":
            panel.extend(["Canonical evidence IDs:\n", fence(row["evidence_ids"])])
        response_path = root / "run" / f"response_{i:03d}.json"
        if response_path.exists():
            response = ex.read(response_path)
            panel.extend(
                [
                    "Literal assistant content:\n",
                    fence(response.get("choices", [{}])[0].get("message", {}).get("content", "")),
                ]
            )
        else:
            panel.append("No response body received. Missingness is retained.\n")
    summary.update(
        **sealed,
        by_kind_family_status=dict(groups),
        request_elapsed_seconds=elapsed,
        bank_audit=audit,
        student_token_summary=token_summary,
        old_expression_gate="FAIL",
        winner="none",
    )
    return summary, "\n".join(panel)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("resource", "teacher"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bank", type=Path)
    parser.add_argument("--tokens", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.kind == "resource":
        result, panel = resource_report(args.input), None
    else:
        result, panel = teacher_report(args.input, args.bank, args.tokens)
    if args.verify:
        ex.require(ex.read(args.output / "REPLAY.json") == result, "Published replay differs")
        if panel is not None:
            ex.require((args.output / "REVIEW_PANEL.md").read_text() == panel, "Panel differs")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        ex.write_new(args.output / "REPLAY.json", result)
        if panel is not None:
            with (args.output / "REVIEW_PANEL.md").open("x") as stream:
                stream.write(panel)
    print(ex.canonical(result))


if __name__ == "__main__":
    main()
