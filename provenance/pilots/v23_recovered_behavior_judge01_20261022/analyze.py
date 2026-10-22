"""Offline study replay; invalidities/order/repeat failures remain in denominators."""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import v23_recovered_judge as recovered  # noqa: E402

ex, judge = recovered.ex, recovered.judge
STUDY = HERE / "study"


def pair_summary(rows):
    outcomes = Counter(r["outcome"] for r in rows)
    repeats = [r for r in rows if r["repeat_agrees"] is not None]
    stable = [r for r in rows if r["outcome"] not in ("order_conflict", "unjudged")]
    # Descriptive sensitivity, not a revised frozen gate or repaired preference.
    conservative = [r for r in stable if r["repeat_agrees"] is not False]
    return dict(
        planned_cases=len(rows),
        r0_outcomes=dict(outcomes),
        r0_order_stable_cases=len(stable),
        repeated_cases=len(repeats),
        repeat_agree=sum(r["repeat_agrees"] for r in repeats),
        repeat_disagree=sum(not r["repeat_agrees"] for r in repeats),
        repeat_disagreement_ids=[r["id"] for r in repeats if not r["repeat_agrees"]],
        sensitivity_excluding_observed_repeat_disagreements=dict(
            n=len(conservative),
            outcomes=dict(Counter(r["outcome"] for r in conservative)),
            caveat=(
                "Untested cases are not repeat-qualified; this does not change the frozen r0 view."
            ),
        ),
    )


def analyze():
    result = recovered.verify(
        STUDY,
        HERE.parent / "v23_comparison01_20261022/furnace",
        HERE.parent / "v23_comparison_recovery02_20261022/furnace",
        HERE.parent / "v23_behavior_judge01_20261022/calibration",
    )
    terminal = ex.read(STUDY / "run/FINISHED.json")
    assert terminal["analysis"] == result
    assert result["planned"] == 174 and sum(result["statuses"].values()) == 174
    assert result["statuses"] == dict(VALID=170, INVALID=4)
    cases = ex.read(STUDY / "CASES_OPERATOR.json")
    requests = ex.read(STUDY / "REQUESTS_OPERATOR.json")
    assert len(cases) == 75 and len({c["id"] for c in cases}) == 75
    assert len({(tuple(c["unit"])) for c in cases}) == 24
    groups = {}
    for arms in (["base", "off"], ["base", "on"], ["off", "on"]):
        rows = [p for p in result["pairs"] if p["arms"] == arms]
        assert len(rows) == 24
        groups[":".join(arms)] = dict(
            A=arms[0],
            B=arms[1],
            **pair_summary(rows),
            repeat_cases_planned=sum(c["repeat"] for c in cases if c["arms"] == arms),
        )
    invalid, records = [], []
    for request in requests:
        folder = STUDY / "run" / request["id"]
        out = ex.read(folder / "OUTCOME.json")
        raw = ex.read(folder / "RESPONSE.json")
        observation = out["observation"]
        final = judge.final_text(raw["choices"][0]["message"]["content"])
        checks = {}
        try:
            parsed = judge.strict_json(final)
            checks = {s: parsed.get(f"quote_{s}") in request["shown"][s]["text"] for s in "AB"}
        except (ValueError, TypeError, KeyError):
            parsed = None
        if observation["status"] != "VALID":
            # Observation status is authoritative. Diagnosis does not repair it.
            assert observation["status"] == "INVALID" and parsed is not None
            assert raw["choices"][0]["finish_reason"] == "stop"
            assert not all(checks.values())
            invalid.append(
                dict(
                    request_id=request["id"],
                    case_id=request["case_id"],
                    order=request["order"],
                    repeat=request["repeat"],
                    status=observation["status"],
                    literal_quote_present=checks,
                    diagnosis="Returned JSON failed the unchanged exact-substring quote contract.",
                    response_sha256=out["response_sha256"],
                )
            )
        records.append(
            dict(
                request_id=request["id"],
                case_id=request["case_id"],
                order=request["order"],
                repeat=request["repeat"],
                status=observation["status"],
                response_sha256=out["response_sha256"],
                final_text=final,
                normalized_preference=(
                    judge.normalized(observation["judgment"], request["order"])
                    if observation["status"] == "VALID"
                    else None
                ),
            )
        )
    controls = [p for p in result["pairs"] if p["arms"] == ["base", "base"]]
    assert len(controls) == 3 and all(p["outcome"] == "tie" for p in controls)
    assert result["expected_control_matches"] == 6
    return dict(
        schema="v23-recovered-judge-terminal-analysis-01",
        status="COMPLETE_DISPATCH_MIXED_VALIDITY_NOT_RELEASE",
        source=ex.read(STUDY / "SEAL.json")["source_commit"],
        study_seal_sha256=ex.digest(STUDY / "SEAL.json"),
        terminal_sha256=ex.digest(STUDY / "run/FINISHED.json"),
        terminal_at=terminal["at"],
        frozen_replay=result,
        pairs=groups,
        identical_controls=controls,
        denominators=dict(
            independent_prompts=12,
            prompt_seed_units=24,
            learner_answers=72,
            main_pairs=72,
            main_r0_requests=144,
            repeat_requests=24,
            identical_control_requests=6,
            planned_requests=174,
            returned_responses=174,
            valid=170,
            invalid=4,
            undispatched=0,
            unknown_remote_execution=0,
        ),
        invalid=invalid,
        usage_scope=(
            "All 174 returned responses, including four invalid ones; invoice cost UNKNOWN."
        ),
        qualification_limits=(
            "Calibration used eight analyst fixtures, not human gold. Study has order and repeat "
            "disagreements despite calibration PASS. Mistral-family bias and capped learner "
            "answers remain. No independent population preference, retention or causal "
            "workspace claim."
        ),
        analysis_model_calls=0,
        analysis_judge_calls=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    ), records


def literal_bank(result, records):
    lines = [
        "# V23 blind judge: every returned final judgment",
        "",
        "All 174 returned final texts, including INVALID results. No provider reasoning "
        "trace is substituted for the final judgment. AB/BA is the presented order; "
        "normalized A/B refers to the original case arms. Invalid responses have no "
        "normalized preference. Each response and receipt remains separately preserved.",
        "",
        "[All 72 literal learner answers](../../v23_comparison_recovery02_20261022/"
        "analysis/ANSWER_BANK.md)",
        "",
    ]
    for pair in result["frozen_replay"]["pairs"]:
        lines.extend(
            [
                f"## {pair['id']}",
                "",
                f"Arms: {pair['arms']}; r0 outcome: "
                f"{pair['outcome']}; repeat agrees: {pair['repeat_agrees']}.",
                "",
            ]
        )
        for r in records:
            if r["case_id"] != pair["id"]:
                continue
            fence = "`" * max(
                3, 1 + max((len(s) for s in re.findall(r"`+", r["final_text"])), default=0)
            )
            lines.extend(
                [
                    f"### {r['order']} r{r['repeat']} · {r['status']}",
                    "",
                    f"[Response](../study/run/{r['request_id']}/RESPONSE.json) · "
                    f"[Receipt](../study/run/{r['request_id']}/OUTCOME.json) · "
                    f"normalized={r['normalized_preference']}",
                    "",
                    fence + "text",
                    r["final_text"],
                    fence,
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify"))
    args = parser.parse_args()
    result, records = analyze()
    text = literal_bank(result, records)
    folder = HERE / "analysis"
    if args.command == "write":
        folder.mkdir(exist_ok=False)
        ex.write_new(folder / "ANALYSIS.json", result)
        ex.write_new(folder / "JUDGMENTS.json", records)
        with (folder / "JUDGMENT_BANK.md").open("x") as stream:
            stream.write(text)
        ex.write_new(folder / "MANIFEST.json", ex.manifest(folder))
    assert ex.read(folder / "ANALYSIS.json") == result
    assert ex.read(folder / "JUDGMENTS.json") == records
    assert (folder / "JUDGMENT_BANK.md").read_text() == text
    actual = ex.manifest(folder)
    actual.pop("MANIFEST.json")
    assert actual == ex.read(folder / "MANIFEST.json")
    print(
        json.dumps({k: result[k] for k in ("status", "denominators", "pairs", "invalid")}, indent=2)
    )


if __name__ == "__main__":
    main()
