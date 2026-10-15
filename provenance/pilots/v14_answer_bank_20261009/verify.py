#!/usr/bin/env python3
"""Offline publication closure; optional exclusive index/receipt, never API/GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
BUNDLE = Path(__file__).resolve().parent
REPO = BUNDLE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import render_v14_answer_bank as reader  # noqa: E402
import verify_v14_answer_bank as bank_verifier  # noqa: E402
import verify_v14_answer_bank_judge as judge_verifier  # noqa: E402

EXCLUDED = {"ARTIFACT_INDEX.json", "VALIDATION.json"}
EPHEMERA = ["**/__pycache__/*.pyc"]
PLAN = "configs/v14/ANSWER_BANK_RETRY_PLAN.json"
CASES = "data/v14_answer_bank/cases.json"


def require(value, message):
    if not value:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def safe_path(root, relative):
    name = Path(relative)
    require(not name.is_absolute() and ".." not in name.parts, "Noncanonical artifact path")
    path = root / name
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()), "Missing artifact")
    require(all(not parent.is_symlink() for parent in (path, *path.parents)
                if parent != root and parent.is_relative_to(root)), "Symlink artifact")
    require(path.relative_to(root).as_posix() == relative, "Noncanonical artifact spelling")
    return path


def inventory(root=REPO, bundle=BUNDLE):
    files = {path for path in bundle.rglob("*") if path.is_file()
             and not (path.parent == bundle and path.name in EXCLUDED)
             and not (path.parent.name == "__pycache__" and path.suffix == ".pyc")}
    require(not any(path.is_symlink() for path in bundle.rglob("*")), "Symlink in bundle")
    for pattern in ("scripts/*v14*answer_bank*.py", "tests/test*answer_bank*.py",
                    "configs/v14/ANSWER_BANK*PLAN.json", "data/v14_answer_bank/*.json"):
        files.update(root.glob(pattern))
    files.add(root / "src/latent_workspace_ft_v10/answer_bank_generation.py")
    require(all((root / name).is_file() for name in (PLAN, CASES)), "Missing frozen plan/cases")
    return {path.relative_to(root).as_posix(): path for path in files}


def index_document(files, root=REPO):
    return {"format": "latent-workspace-v14-answer-bank-artifact-index-v1",
            "excluded_top_level": sorted(EXCLUDED), "excluded_ephemera": EPHEMERA,
            "ephemera_reason": "Python bytecode caches are interpreter-generated, not evidence.",
            "artifacts": [
        {"path": name, "bytes": safe_path(root, name).stat().st_size, "sha256": sha(path)}
        for name, path in sorted(files.items())
    ]}


def check_index(index, files, root=REPO):
    require(index.get("format") == "latent-workspace-v14-answer-bank-artifact-index-v1",
            "Unknown artifact index format")
    require(index.get("excluded_top_level") == sorted(EXCLUDED)
            and index.get("excluded_ephemera") == EPHEMERA, "Artifact exclusion rule changed")
    names = [entry["path"] for entry in index["artifacts"]]
    require(len(names) == len(set(names)) and set(names) == set(files), "Artifact path closure")
    for entry in index["artifacts"]:
        path = safe_path(root, entry["path"])
        require(type(entry["bytes"]) is int and path.stat().st_size == entry["bytes"]
                and sha(path) == entry["sha256"], f"Artifact changed: {entry['path']}")


def evidence_checks(root=REPO, bundle=BUNDLE):
    raw, judge_dir, reader_dir = bundle / "raw", bundle / "judge", bundle / "reader"
    plan_path, cases_path, bank_path = root / PLAN, root / CASES, raw / "bank.json"
    started, report = load(raw / "STARTED.json"), load(raw / "report.json")
    for field in ("source_commit", "plan_sha256", "runtime", "checkpoint_inventory"):
        require(started[field] == report[field], f"STARTED/report mismatch: {field}")
    require(started["plan_sha256"] == sha(plan_path), "STARTED does not bind retry plan")
    require(started["expected_answers"] == report["denominators"]["answers"] == 336,
            "STARTED answer count mismatch")
    bank = bank_verifier.verify_run(raw, plan_path, root=root, verify_weights=False)
    require(bank["status"] == "PASS", "Answer bank verification failed")
    judge = judge_verifier.verify(bank_path, plan_path, cases_path, judge_dir)
    require(judge["mechanical_receipt_closure"], "Primary judge receipts are incomplete")
    require(judge["judge_model_contract_satisfied"]
            and judge["reported_usage_within_reserved_bounds"], "Judge contract/budget drift")
    with tempfile.TemporaryDirectory(prefix="v14-answer-bank-review-check-") as directory:
        regenerated = Path(directory) / "reader"
        reader.render(bank_path, cases_path, regenerated, judge_dir / "SUMMARY.json")
        expected = {path.name: path.read_bytes() for path in regenerated.iterdir()}
        require(reader_dir.is_dir() and not reader_dir.is_symlink(), "Reader directory missing")
        actual_files = list(reader_dir.iterdir())
        require(all(path.is_file() and not path.is_symlink() for path in actual_files),
                "Unexpected reader file type")
        require({path.name: path.read_bytes() for path in actual_files} == expected,
                "Reader regeneration differs; preserve any edited human annotations")
    supplement = bundle / "quote_wrapper_supplement"
    if supplement.exists():
        import recover_v14_answer_bank_quote_wrappers as recovery

        supplemental = load(supplement / "SUMMARY.json")
        require(supplemental["status"] == "POSTHOC_FORMAT_RECOVERY_NOT_PRIMARY_NOT_GOLD",
                "Supplement must remain posthoc and separate from primary")
        require(supplemental["primary_summary_sha256"] == sha(judge_dir / "SUMMARY.json"),
                "Supplement primary binding differs")
        require(supplemental == recovery.build_supplement(
            bank_path, plan_path, cases_path, judge_dir), "Supplement does not recompute")
        require((supplement / "REVIEW.md").read_text() == recovery.render_review(supplemental),
                "Supplement review does not reproduce")
    return {"generation_execution_commit": report["source_commit"], "bank_status": bank["status"],
            "primary_judge_status": judge["status"],
            "primary_valid_judgments": judge["valid_judgments"],
            "reader_bytes_reproduced": True, "human_labels": "PENDING_BLANK",
            "supplement_present": supplement.exists(),
            "supplement_recomputed_exactly": True if supplement.exists() else None,
            "supplement_claim": (
                "POSTHOC_FORMAT_RECOVERY_NOT_PRIMARY_NOT_GOLD" if supplement.exists() else None)}


def write_new(path, document):
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def verify(*, seal=False, write_receipt=False, root=REPO, bundle=BUNDLE):
    index_path, receipt_path = bundle / "ARTIFACT_INDEX.json", bundle / "VALIDATION.json"
    if seal and index_path.exists():
        raise FileExistsError("Artifact index already exists; sealing is exclusive")
    if write_receipt and receipt_path.exists():
        raise FileExistsError("Validation receipt already exists; writing is exclusive")
    files = inventory(root, bundle)
    index = index_document(files, root) if seal else load(index_path)
    check_index(index, files, root)
    evidence = evidence_checks(root, bundle)
    check_index(index, inventory(root, bundle), root)  # No input changed during validation.
    if seal:
        write_new(index_path, index)
    result = {"format": "latent-workspace-v14-answer-bank-publication-validation-v1",
              "status": "PASS", "artifact_index_sha256": sha(index_path),
              "indexed_files": len(files), "verifier_sha256": sha(Path(__file__)),
              "validation_checkout_commit": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              **evidence, "semantic_promotion": False, "non_regression": "NOT_ESTABLISHED",
              "claim_boundary": "Offline artifact/receipt closure only. No API, GPU, tokenizer, "
              "new generation, checkpoint-body recheck, human evaluation, CI or quality proof."}
    if receipt_path.exists():
        require(load(receipt_path)["artifact_index_sha256"] == result["artifact_index_sha256"],
                "Existing receipt binds a different index")
    if write_receipt:
        write_new(receipt_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(seal=args.seal, write_receipt=args.write_receipt),
                     ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
