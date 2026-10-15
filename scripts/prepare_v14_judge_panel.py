#!/usr/bin/env python3
"""Freeze a text-difference-selected judge panel; no prior verdicts, API or model."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "data/v14_judge_panel/selection.json"
SOURCES = {
    "source_bank": {
        "path": "provenance/pilots/v14_answer_bank_20261009/raw/bank.json",
        "sha256": "916b344c1e94725cccd0b9b7657e982fc809a57b54b057b31eae04185c6936ad",
    },
    "source_cases": {
        "path": "data/v14_answer_bank/cases.json",
        "sha256": "177c9242583aa54d20a5f502c52ca63264d44482c8fe886072e89d4d657965a9",
    },
    "source_pairs": {
        "path": "provenance/pilots/v14_answer_bank_20261009/judge/PAIRS.json",
        "sha256": "96089d67d5e517e7c17eb8df854c43c8b346cf43b84bef9db0abee6639b24727",
    },
}
CONDITIONS = (
    "base",
    "base_inline",
    "legacy_semantic",
    "centered_semantic",
    "centered_zero",
    "centered_unrelated",
    "centered_twin",
)
COMPARISONS = ("legacy_semantic", "centered_semantic")
REGIMES = ("greedy", "sample211", "sample212")
CONTROL_CASES = (
    "general-02-json",
    "general-04-code",
    "relation-02-reverse",
    "relation-03-reverse",
)
CASE_FIELDS = ("id", "lane", "user_prompt", "reference", "rubric")


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identifier(case_id, regime, comparison):
    data = json.dumps(
        [case_id, regime, comparison], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(data).hexdigest()[:20]


def cluster(case):
    return (
        ("relation", case["reference"]["world_id"])
        if case["lane"] == "relation"
        else (
            "general",
            case["id"],
        )
    )


def select(bank, case_document, pair_document):
    require(bank["format"] == "latent-workspace-v14-answer-bank-v1", "Unknown bank format")
    require(
        case_document["format"] == "latent-workspace-v14-answer-bank-cases-v1",
        "Unknown cases format",
    )
    case_rows = case_document["cases"]
    cases = {row["id"]: row for row in case_rows}
    require(len(case_rows) == len(cases) == 16, "Cases must close to 16 unique IDs")
    require(
        Counter(row["lane"] for row in case_rows) == {"general": 8, "relation": 8},
        "Expected eight cases per lane",
    )
    coordinates = [(row["case_id"], row["regime"], row["condition"]) for row in bank["rows"]]
    indexed = dict(zip(coordinates, bank["rows"]))
    expected = {
        (case_id, regime, condition)
        for case_id in cases
        for regime in REGIMES
        for condition in CONDITIONS
    }
    require(
        len(coordinates) == len(indexed) == 336 and set(indexed) == expected,
        "Generation bank must close to 16 x 3 x 7 unique coordinates",
    )
    for key, row in indexed.items():
        require(
            row["id"] == "__".join(key) and row["lane"] == cases[key[0]]["lane"],
            "Bank identity/lane mismatch",
        )
        require(
            isinstance(row["answer"], str) and row["finish_reason"] in ("eos", "length"),
            "Unknown answer type or finish reason",
        )
        if key[2] != "base_inline":
            base = indexed[key[0], key[1], "base"]
            require(
                row["prompt_ids"] == base["prompt_ids"] and row["messages"] == base["messages"],
                "Unequal primary prompt",
            )
    rebuilt = []
    for case_id in sorted(cases):
        for regime in REGIMES:
            base = indexed[case_id, regime, "base"]
            for comparison in COMPARISONS:
                workspace = indexed[case_id, regime, comparison]
                rebuilt.append(
                    {
                        "pair_id": identifier(case_id, regime, comparison),
                        "case_id": case_id,
                        "lane": cases[case_id]["lane"],
                        "regime": regime,
                        "comparison": comparison,
                        "base_answer": base["answer"],
                        "workspace_answer": workspace["answer"],
                        "base_finish_reason": base["finish_reason"],
                        "workspace_finish_reason": workspace["finish_reason"],
                        "exact_identical": base["answer"] == workspace["answer"],
                        "selected_for_identical_calibration": False,
                    }
                )
    # This reconstructs the earlier pair receipt, not the earlier judge results.
    for pair in [pair for pair in rebuilt if pair["exact_identical"]][:4]:
        pair["selected_for_identical_calibration"] = True
    require(pair_document == {"pairs": rebuilt}, "Prior 96-pair receipt does not reconstruct")
    changed = [pair for pair in rebuilt if not pair["exact_identical"]]
    require(len(changed) == 10, "Frozen bank no longer has exactly ten changed primary pairs")
    controls = [
        pair
        for pair in rebuilt
        if pair["case_id"] in CONTROL_CASES
        and pair["regime"] == "greedy"
        and pair["comparison"] == "centered_semantic"
    ]
    require(
        len(controls) == 4 and all(pair["exact_identical"] for pair in controls),
        "The four fixed controls must be actual identical pairs",
    )
    for pair in controls:
        base = indexed[pair["case_id"], pair["regime"], "base"]
        workspace = indexed[pair["case_id"], pair["regime"], pair["comparison"]]
        require(
            base["generated_ids"] == workspace["generated_ids"]
            and base["finish_reason"] == workspace["finish_reason"],
            "Calibration token/termination identity is not exact",
        )
    selected = []
    for pair in changed + controls:
        row = {
            key: value for key, value in pair.items() if key != "selected_for_identical_calibration"
        }
        selected.append({**row, "calibration_only": row["exact_identical"]})
    selected.sort(key=lambda pair: (pair["case_id"], pair["regime"], pair["comparison"]))
    counts = {
        "source_cases": 16,
        "source_answers": 336,
        "source_primary_pairs": 96,
        "selected_pairs": len(selected),
        "changed_pairs": len(changed),
        "calibration_pairs": len(controls),
        "changed_pairs_by_lane": dict(sorted(Counter(pair["lane"] for pair in changed).items())),
        "changed_pairs_by_comparison": {
            name: sum(pair["comparison"] == name for pair in changed) for name in COMPARISONS
        },
        "changed_unique_cases": len({pair["case_id"] for pair in changed}),
        "changed_world_task_clusters": len({cluster(cases[pair["case_id"]]) for pair in changed}),
        "calibration_unique_cases": len({pair["case_id"] for pair in controls}),
        "selected_unique_cases": len({pair["case_id"] for pair in selected}),
        "selected_world_task_clusters": len({cluster(cases[pair["case_id"]]) for pair in selected}),
    }
    require(
        counts["changed_unique_cases"] == 7 and counts["changed_world_task_clusters"] == 6,
        "Changed case/cluster denominator drift",
    )
    return {
        "format": "latent-workspace-v14-judge-panel-selection-v1",
        **copy.deepcopy(SOURCES),
        "selection_rule": {
            "changed": "Select ALL primary pairs whose decoded base/workspace "
            "answers differ exactly.",
            "calibration": "Select the four prespecified case IDs, greedy, base versus "
            "centered_semantic; require actual text/token/finish identity.",
            "calibration_case_ids": list(CONTROL_CASES),
            "prior_judge_verdicts_read_or_used": False,
            "primary_comparisons": list(COMPARISONS),
            "all_original_generation_regimes_preserved": True,
            "case_metadata": "All 16 original cases embedded for complete source binding.",
        },
        "counts": counts,
        "cases": [
            {field: copy.deepcopy(cases[case_id][field]) for field in CASE_FIELDS}
            for case_id in sorted(cases)
        ],
        "pairs": selected,
        "claim_boundary": [
            "Selection is conditioned on observed text change, "
            "not a representative quality sample.",
            "Ten changed pairs are seven case prompts and six world/task clusters, "
            "not ten independent problems.",
            "Four identical controls calibrate judges and are not examples "
            "of workspace quality improvement.",
            "Repeated orders and judge models assess judgment variability; "
            "majority agreement is not gold.",
            "This reuses existing development responses; "
            "it is neither new model generation nor a fresh holdout.",
            "No prior model verdict, score, human label, API credential "
            "or new inference is used in selection.",
        ],
    }


def build(root=REPO):
    loaded = {}
    for name, spec in SOURCES.items():
        path = root / spec["path"]
        require(
            path.is_file() and not path.is_symlink() and sha(path) == spec["sha256"],
            f"Frozen source changed: {name}",
        )
        loaded[name] = json.loads(path.read_text())
    return select(loaded["source_bank"], loaded["source_cases"], loaded["source_pairs"])


def prepare(output=OUTPUT, root=REPO, check=False):
    document = build(root)
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if check:
        require(
            output.is_file() and output.read_text() == serialized,
            "Frozen selection does not reproduce byte-for-byte",
        )
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    return {"selection_sha256": sha(output), "counts": document["counts"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, check=args.check), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
