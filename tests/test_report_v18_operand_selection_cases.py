"""The post-hoc report is cases-only and does not modify its frozen inputs."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "report_cases", ROOT / "scripts/report_v18_operand_selection_cases.py"
)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def row(case=0, *, factor="centered_ordered", seed=17, split="dev", dtype="torch.float32"):
    frame, within = divmod(case, 36)
    order, question = divmod(within, 6)
    subject, obj = report.QUESTIONS[question]
    ranks = list(report.ORDERS[order])
    twin = [1 - rank if rank < 2 else rank for rank in ranks]
    label, twin_label = int(ranks[subject] <= ranks[obj]), int(twin[subject] <= twin[obj])

    def logits(y):
        value = 0.8 if y == 0 else -0.8
        return [value, -value, -4.0, -4.0, -4.0, -4.0, -4.0]

    result = {
        "seed": seed,
        "factor": factor,
        "split": split,
        "native_dtype": dtype,
        "case": case,
        "frame": frame,
        "order": order,
        "subject": subject,
        "object": obj,
        "ranks": ranks,
        "twin_ranks": twin,
        "label": label,
        "twin_label": twin_label,
        "question": f"Is E{subject} ranked above E{obj}? Answer:",
        "renamed_question": f"Is Alias{subject + 7} ranked above Alias{obj + 7}? Answer:",
        "logits": logits(label),
        "twin_logits": logits(twin_label),
        "delta_norm": 0.1,
    }
    if seed is None:
        result.update(
            delta_norm=0, logits=[0, 0, -4, -4, -4, -4, -4], twin_logits=[0, 0, -4, -4, -4, -4, -4]
        )
    return result


@pytest.mark.parametrize(
    "text",
    [
        '{"x":1,"x":2}',
        '{"x":{"n":0,"n":1}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":1e999}',
    ],
)
def test_strict_json_rejects_ambiguous_nonfinite(text):
    with pytest.raises(ValueError):
        report.strict_json(text)


def test_valid_json_preserves_types():
    assert report.strict_json('{"x":1,"y":[false,0.125,null]}') == {
        "x": 1,
        "y": [False, 0.125, None],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("case", False),
        ("case", 288),
        ("frame", 7),
        ("subject", 2),
        ("label", 0),
        ("ranks", [0, 2, 1]),
        ("ranks", [False, 1, 2]),
        ("question", "Is E1 ranked above E0? Answer:"),
        ("delta_norm", float("inf")),
        ("delta_norm", 0.3),
        ("delta_norm", False),
        ("native_dtype", "torch.float64"),
        ("logits", [0.8, 0.8, -4, -4, -4, -4, -4]),
        ("logits", [-0.8, 0.8, -4, -3, -4, -4, -4]),
        ("logits", [False, 0, -4, -4, -4, -4, -4]),
    ],
)
def test_case_bindings_and_head_constants_fail_closed(field, value):
    value_row = row()
    value_row[field] = value
    with pytest.raises(ValueError):
        report.validate_row(value_row)


def test_valid_rows_and_strict_integer_replay():
    rows = [row(i) for i in range(288)]
    for value in rows:
        report.validate_row(value)
    counts = report.integer_metrics(rows)
    assert counts["strict_native_correct"] == 288
    assert counts["reciprocal_both_correct"] == 144
    assert counts["affected_donor_flips"] == 96
    assert counts["unaffected_strict_correct"] == counts["unaffected_agreement_count"] == 192
    assert counts["native_ties"] == 0


def test_common_only_ties_are_not_strict_correct():
    rows = [row(i, factor="common_only", seed=None, split="held_out") for i in range(1152)]
    report.validate_row(rows[0])
    metrics = report.integer_metrics(rows)
    assert metrics["strict_native_correct"] == metrics["affected_donor_flips"] == 0
    assert metrics["ordinary_native_correct"] == 576
    assert metrics["native_ties"] == 1152
    rows[0]["delta_norm"] = 0.01
    with pytest.raises(ValueError, match="Frozen-zero"):
        report.validate_row(rows[0])


def test_metrics_reject_tampered_count_and_preserve_fp32_ratio_rounding():
    counts = report.integer_metrics([row(i) for i in range(288)])
    recorded = {k: v for k, v in counts.items() if k != "unaffected_agreement_count"}
    recorded.update(
        strict_native_accuracy=1.0,
        reciprocal_both_correct_rate=1.0,
        affected_donor_flip_rate=1.0,
        unaffected_strict_accuracy=1.0,
        unaffected_prediction_agreement=1.0,
    )
    report.check_metrics(counts, recorded)
    wrong = dict(recorded, strict_native_correct=287)
    with pytest.raises(ValueError, match="integer metric"):
        report.check_metrics(counts, wrong)
    with pytest.raises(ValueError, match="FP32 ratio"):
        report.check_metrics(counts, dict(recorded, strict_native_accuracy=0.5))


def test_head_axis_algebra_and_no_bfloat_inverse():
    value = row()
    value["logits"] = [0.8, -0.8, -4.8, -4.8, -4.8, -4.8, -4.8]
    value["delta_norm"] = math.sqrt(0.1**2 + 0.2**2)
    axes = report.head_axes([value])
    assert axes["answer_energy_fraction"] == pytest.approx(0.2)
    assert axes["distractor_energy_fraction"] == pytest.approx(0.8)
    assert axes["unaccounted_energy_fraction_with_rounding"] == pytest.approx(0, abs=1e-14)
    with pytest.raises(ValueError, match="BF16"):
        report.head_axes([dict(value, native_dtype="torch.bfloat16")])
    with pytest.raises(ValueError, match="exceeds"):
        report.head_axes([dict(value, delta_norm=0.01)])


def test_comparison_distinguishes_logits_from_predictions():
    left = [row()]
    right = copy.deepcopy(left)
    right[0]["native_dtype"] = "torch.bfloat16"
    right[0]["logits"][0] -= 0.01
    right[0]["logits"][1] += 0.01
    result = report.compare_rows(left, right)
    assert all(value == 0 for value in result["changed_counts"].values())
    assert result["max_absolute_answer_margin_difference"] == pytest.approx(0.02)
    right[0]["frame"] = 1
    with pytest.raises(ValueError, match="bindings"):
        report.compare_rows(left, right)


def test_read_groups_rejects_duplicates_and_missing_population(tmp_path):
    path = tmp_path / "CASES.jsonl"
    path.write_text(json.dumps(row()) + "\n" + json.dumps(row()) + "\n")
    with pytest.raises(ValueError, match="Duplicate case"):
        report.read_groups(path)
    path.write_text(json.dumps(row()) + "\n")
    with pytest.raises(ValueError, match="case groups"):
        report.read_groups(path)


@pytest.fixture
def receipts(tmp_path):
    def write(name, value):
        (tmp_path / name).write_text(json.dumps(value))

    plan = json.loads((ROOT / "configs/v18/OPERAND_SELECTION_ASSAY_PLAN.json").read_text())
    files = {"scripts/frozen.py": "a" * 64}
    source = {"commit": "b" * 40, "files": files, "aggregate_sha256": report.digest(files)}
    write("SOURCE_SEAL.json", {"source_commit": source["commit"], "source_hashes": files})
    write("PLAN.json", plan)
    write("SOURCE.json", source)
    common = {
        "device": "cpu",
        "plan_sha256": report.digest(plan),
        "source_sha256": source["aggregate_sha256"],
    }
    write(
        "STARTED.json",
        {**common, "external_seal_sha256": report.sha(tmp_path / "SOURCE_SEAL.json")},
    )
    gates = {
        "old_scientific_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
        "toy_learnable_all_seeds": True,
        "selection_advantage_all_seeds": False,
    }
    write(
        "RESULTS.json",
        {**common, "schema": "v18-controlled-operand-selection-result-v1", "gates": gates},
    )
    audit_common = {
        "device": "cpu",
        "source_commit": source["commit"],
        "gates": gates,
        "forward_calls": 0,
        "training_updates": 0,
    }
    write(
        "ASSAY_CPU_AUDIT.json",
        {
            **audit_common,
            "schema": "v18-operand-selection-supplemental-terminal-audit-v1",
            "status": "OFFLINE_TERMINAL_AUDIT_PASS",
            "source_seal_sha256": report.sha(tmp_path / "SOURCE_SEAL.json"),
            "raw_replay": {
                **audit_common,
                "status": "OFFLINE_RAW_METRICS_AND_GATES_PASS",
                "raw_groups": 50,
                "raw_rows": 36864,
            },
        },
    )
    (tmp_path / "CASES.jsonl").write_text(json.dumps(row()) + "\n")

    def finish():
        write(
            "FINISHED.json",
            {
                "status": "COMPLETED",
                "results_sha256": report.sha(tmp_path / "RESULTS.json"),
                "cases_sha256": report.sha(tmp_path / "CASES.jsonl"),
            },
        )

    finish()
    return tmp_path, write, finish


def test_input_receipt_binding_is_read_only(receipts):
    directory, _, _ = receipts
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    _, _, binding = report.bound_inputs(directory, directory / "SOURCE_SEAL.json")
    assert binding["source_commit"] == "b" * 40
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


@pytest.mark.parametrize(
    "tamper", ["case_hash", "result_hash", "source", "seal", "plan", "runtime", "failed"]
)
def test_bad_receipts_rejected(receipts, tamper):
    directory, write, finish = receipts
    if tamper == "case_hash":
        (directory / "CASES.jsonl").write_text("{}\n")
    elif tamper == "result_hash":
        write("RESULTS.json", {})
    elif tamper == "source":
        value = report.load(directory / "SOURCE.json")
        value["aggregate_sha256"] = "0" * 64
        write("SOURCE.json", value)
    elif tamper == "seal":
        value = report.load(directory / "SOURCE_SEAL.json")
        value["source_commit"] = "c" * 40
        write("SOURCE_SEAL.json", value)
    elif tamper == "plan":
        value = report.load(directory / "PLAN.json")
        value["native_answer_head_scale"] = 9
        write("PLAN.json", value)
    elif tamper == "runtime":
        value = report.load(directory / "RESULTS.json")
        value["device"] = "cuda"
        write("RESULTS.json", value)
        finish()
    else:
        write("FAILED.json", {"message": "retained failure"})
    with pytest.raises(ValueError):
        report.bound_inputs(directory, directory / "SOURCE_SEAL.json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "FAILED"),
        ("source_commit", "c" * 40),
        ("source_seal_sha256", "0" * 64),
        ("gates", {}),
        ("forward_calls", True),
    ],
)
def test_prior_audit_must_match(receipts, field, value):
    directory, write, _ = receipts
    audit = report.load(directory / "ASSAY_CPU_AUDIT.json")
    audit[field] = value
    write("ASSAY_CPU_AUDIT.json", audit)
    with pytest.raises(ValueError, match="audit|replay"):
        report.bound_inputs(directory, directory / "SOURCE_SEAL.json")
