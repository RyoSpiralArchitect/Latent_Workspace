"""Replay all raw diagnoses; keep machine truth, model disagreement and missingness."""

from __future__ import annotations

import argparse
import itertools
import json
import re
from collections import Counter
from pathlib import Path

import run_v15_5_diagnostic_judge as run
import v15_5_diagnostics as d

io = d.io


def bucket(record, observation):
    """A descriptive model-dependent classification, never an old-score rewrite."""
    if observation is None:
        return "unavailable_judgment"
    if record["mechanical"]["finish_reason"] == "length":
        return "incomplete_observed_text"
    j = observation["judgment"]
    if j["contradiction"] == "present" or j["commitment"] == "conflicting":
        return "internal_contradiction"
    if j["commitment"] in ("yes", "no") and j["commitment"] != record["oracle"]["answer"]:
        return "unambiguous_wrong_commitment"
    if record["mechanical"]["strict_correct"]:
        return "strict_success"
    if j["commitment"] == "abstain":
        return "abstention"
    if j["commitment"] == "no_answer":
        return "no_answer"
    if (
        j["commitment"] == record["oracle"]["answer"]
        and j["contradiction"] == "absent"
        and j["reasoning"] in ("supported", "none")
        and j["added_facts"] in ("entailed", "none")
    ):
        return "format_only_candidate_not_rescued"
    if j["reasoning"] == "faulty" or j["added_facts"] == "unsupported":
        return "explanation_or_grounding_failure"
    return "unresolved"


def analyze(root):
    plan, data, seal = run.load_frozen()
    root = Path(root)
    cells, gates, provider_summary = {}, {}, {}
    for provider in run.PROVIDERS:
        calibration = run.replay_cell(root, provider, "calibration", plan, data)
        gates[provider] = run.calibration_gate(calibration, data, plan)
        study = run.replay_cell(root, provider, "study", plan, data)
        if any(r["status"] != "not_dispatched" for r in study):
            d.require(gates[provider]["status"] == "PASS", "Study dispatched without qualification")
        cells[provider] = {(r["item_id"], r["replicate"]): r for r in study}
        stability = Counter()
        stability_dimensions = {k: Counter() for k in d.ENUMS}
        for item_id in data["repeat_item_ids"]:
            a, b = (cells[provider][item_id, rep] for rep in (0, 1))
            if a["status"] != "valid_diagnosis" or b["status"] != "valid_diagnosis":
                stability["invalid_or_missing"] += 1
                continue
            ja, jb = (r["observation"]["judgment"] for r in (a, b))
            matches = {k: ja[k] == jb[k] for k in d.ENUMS}
            stability["all_four_equal" if all(matches.values()) else "differs"] += 1
            for k, same in matches.items():
                stability_dimensions[k]["equal" if same else "differs"] += 1
        receipts = []
        for phase, rows in (("calibration", calibration), ("study", study)):
            request_map = {r["request_id"]: r for r in d.requests_for(data, plan, provider, phase)}
            for row in rows:
                if row["status"] != "not_dispatched":
                    receipts.append(
                        {
                            **request_map[row["request_id"]],
                            "usage_receipt": row.get("usage_receipt", {}),
                        }
                    )
        provider_summary[provider] = {
            "model": plan["providers"][provider]["model"],
            "planned": 560,
            "calibration": gates[provider],
            "study_and_repeat_statuses": dict(Counter(r["status"] for r in study)),
            "primary_measurement_statuses": dict(
                Counter(r["status"] for r in study if r["replicate"] == 0)
            ),
            "repeat_statuses": dict(Counter(r["status"] for r in study if r["replicate"] == 1)),
            "repeat_stability": {
                "planned": 32,
                **dict(stability),
                "dimensions": {k: dict(v) for k, v in stability_dimensions.items()},
            },
            "usage": io.usage_summary(receipts),
        }
    ledger = []
    for record in data["records"]:
        diagnoses = {}
        for provider in run.PROVIDERS:
            value = cells[provider][record["item_id"], 0]
            observation = value.get("observation") if value["status"] == "valid_diagnosis" else None
            commitment = observation["judgment"]["commitment"] if observation else None
            diagnoses[provider] = {
                "status": value["status"],
                "request_id": value["request_id"],
                "observation": observation,
                "bucket": bucket(record, observation),
                "truth_relative_commitment_match": commitment == record["oracle"]["answer"]
                if commitment in ("yes", "no")
                else None,
            }
        available = all(v["status"] == "valid_diagnosis" for v in diagnoses.values())
        differences = None
        if available:
            a, b = (v["observation"]["judgment"] for v in diagnoses.values())
            differences = [k for k in d.ENUMS if a[k] != b[k]]
        ledger.append(
            {
                **record,
                "diagnoses": diagnoses,
                "agreement": "unavailable"
                if not available
                else "all_four_equal"
                if not differences
                else "disagreement",
                "disagreement_dimensions": differences,
            }
        )
    strata = []
    for renderer, cue, info, view, label in itertools.product(
        ("raw", "native_chat"),
        ("present", "absent"),
        ("inline", "query_only"),
        ("atomic", "full_chain"),
        (0, 1),
    ):
        rows = [
            r
            for r in ledger
            if (
                r["coordinate"]["renderer"],
                r["coordinate"]["cue"],
                r["coordinate"]["information"],
                r["view"],
                r["oracle"]["label"],
            )
            == (renderer, cue, info, view, label)
        ]
        strata.append(
            {
                "renderer": renderer,
                "cue": cue,
                "information": info,
                "view": view,
                "label": label,
                **summarize_rows(rows),
            }
        )
    complete = all(
        sum(
            v["study_and_repeat_statuses"].get(k, 0)
            for k in (
                "valid_diagnosis",
                "invalid_judgment",
                "incomplete_response",
                "refused",
                "unexpected_model_identity",
            )
        )
        == 544
        for v in provider_summary.values()
    )
    summary = {
        "status": "ALL_RESPONSES_RECORDED" if complete else "INCOMPLETE_OR_CALIBRATION_BLOCKED",
        "providers": provider_summary,
        "planned_paid_requests": 1120,
        "machine": d.machine_summary(data),
        "primary_inline": summarize_rows(
            [r for r in ledger if r["coordinate"]["information"] == "inline"]
        ),
        "secondary_query_only": summarize_rows(
            [r for r in ledger if r["coordinate"]["information"] == "query_only"]
        ),
        "strata": strata,
        "source_files_verified": len(seal["source_hashes"]),
        "old_expression_gate": "FAIL",
        "judge_consensus_is_gold": False,
        "rows_are_independent_tasks": False,
        "world_clusters": 16,
        **plan["claims"],
    }
    return summary, ledger


def summarize_rows(rows):
    return {
        "total": len(rows),
        "strict_correct": sum(r["mechanical"]["strict_correct"] for r in rows),
        "valid_eos": sum(r["mechanical"]["valid_eos"] for r in rows),
        "length": sum(r["mechanical"]["finish_reason"] == "length" for r in rows),
        "agreement": dict(Counter(r["agreement"] for r in rows)),
        "judges": {
            p: {
                "statuses": dict(Counter(r["diagnoses"][p]["status"] for r in rows)),
                "buckets": dict(Counter(r["diagnoses"][p]["bucket"] for r in rows)),
                "dimensions": {
                    k: dict(
                        Counter(
                            r["diagnoses"][p]["observation"]["judgment"][k]
                            for r in rows
                            if r["diagnoses"][p]["status"] == "valid_diagnosis"
                        )
                    )
                    for k in d.ENUMS
                },
                "truth_relative_matches": sum(
                    r["diagnoses"][p]["truth_relative_commitment_match"] is True for r in rows
                ),
                "truth_relative_mismatches": sum(
                    r["diagnoses"][p]["truth_relative_commitment_match"] is False for r in rows
                ),
                "truth_relative_unresolved": sum(
                    r["diagnoses"][p]["truth_relative_commitment_match"] is None for r in rows
                ),
            }
            for p in run.PROVIDERS
        },
    }


def panel_text(summary, ledger):
    def fence(text):
        ticks = "`" * max(3, 1 + max((len(v) for v in re.findall(r"`+", text)), default=0))
        return f"{ticks}text\n{text}\n{ticks}"

    lines = [
        "# V15.5 complete diagnostic panel",
        "",
        "All 512 original outputs, unmodified. Old strict gate: **FAIL**.",
        "",
        "Model diagnoses are not human gold, hidden-state evidence, or rescued strict success.",
        "Query-only truth matches are not evidence of grounded capability.",
        "",
        f"Execution: `{summary['status']}`. All repeats/calibration are in the raw call records.",
        "",
    ]
    for row in ledger:
        coord = row["coordinate"]
        lines.extend(
            [
                f"## {coord['case_id']} / {coord['renderer']} / cue {coord['cue']} / "
                f"{coord['information']}",
                "",
                f"Record: `{row['item_id']}`",
                "",
                fence(
                    "\n".join(row["payload"]["visible_facts"]) + "\n" + row["payload"]["question"]
                ),
                "",
                f"Symbolic truth: {row['oracle']['answer']}; strict correct: "
                f"{row['mechanical']['strict_correct']}; finish: "
                f"{row['mechanical']['finish_reason']}.",
                "",
                fence(row["payload"]["response_text"]),
                "",
                f"Judge agreement: {row['agreement']}; differing dimensions: "
                f"{row['disagreement_dimensions']}.",
                "",
            ]
        )
        for provider, diagnosis in row["diagnoses"].items():
            lines.extend(
                [
                    f"### {provider}: {diagnosis['status']}",
                    "",
                    f"Descriptive bucket: `{diagnosis['bucket']}`.",
                    "",
                ]
            )
            if diagnosis["observation"]:
                value = diagnosis["observation"]["judgment"]
                lines.extend(
                    [
                        "; ".join(f"{k}: **{value[k]}**" for k in d.ENUMS) + ".",
                        "",
                        value["assessment_en"],
                        "",
                    ]
                )
                for k in d.ENUMS:
                    for evidence in diagnosis["observation"]["verified_evidence"][k]:
                        lines.extend(
                            [
                                f"{k} evidence, code-point spans {evidence['codepoint_spans']}:",
                                "",
                                fence(evidence["quote"]),
                                "",
                            ]
                        )
    return "\n".join(lines)


def raw_index(root):
    root = Path(root)
    files = {}
    for p in sorted(root.rglob("*")):
        relative = p.relative_to(root)
        if p.is_file() and relative.parts[0] in ("openai", "mistral", "metadata"):
            files[str(relative)] = {"bytes": p.stat().st_size, "sha256": io.file_sha(p)}
    return {"format": "v15.5-diagnostic-raw-index-v1", "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = run.confined(args.bundle)
    summary, ledger = analyze(root)
    path = root / "analysis"
    if args.write:
        path.mkdir(parents=True, exist_ok=False)
        io.write_json(path / "SUMMARY.json", summary, exclusive=True)
        io.write_json(path / "LEDGER.json", ledger, exclusive=True)
        io.write_json(path / "ARTIFACT_INDEX.json", raw_index(root), exclusive=True)
        with (path / "DIAGNOSTIC_PANEL.md").open("x", encoding="utf-8") as stream:
            stream.write(panel_text(summary, ledger))
    if args.verify:
        d.require(io.load_json(path / "SUMMARY.json") == summary, "Summary replay")
        d.require(io.load_json(path / "LEDGER.json") == ledger, "Ledger replay")
        d.require(io.load_json(path / "ARTIFACT_INDEX.json") == raw_index(root), "Raw hash index")
        d.require(
            (path / "DIAGNOSTIC_PANEL.md").read_text() == panel_text(summary, ledger),
            "Verbatim panel replay",
        )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "source_files": summary["source_files_verified"],
                "providers": {
                    p: {k: v[k] for k in ("calibration", "study_and_repeat_statuses")}
                    for p, v in summary["providers"].items()
                },
                "old_expression_gate": "FAIL",
            }
        )
    )


if __name__ == "__main__":
    main()
