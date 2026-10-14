#!/usr/bin/env python3
"""Post-hoc, stdlib-only accounting of completed V18 toy case artifacts.

No model imports, tensor loading, forwards, fitting, or gate changes occur.
Receipt consistency is checked here; source/import and weight/population audits
remain the responsibility of the separate frozen-artifact verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path

PLAN_DIGEST = "27648d5189850f1efc844c37e4c77524fef876499fad4b8191d6e58cccb91471"
FACTORS = ("centered_final", "centered_ordered", "centered_symmetric", "raw_ordered")
SEEDS = (17, 29, 43)
DTYPES = ("torch.float32", "torch.bfloat16")
FRAMES = {"dev": 8, "held_out": 32}
ORDERS = tuple(itertools.permutations(range(3)))
QUESTIONS = tuple(itertools.permutations(range(3), 2))
ROW_KEYS = {
    "seed",
    "factor",
    "split",
    "native_dtype",
    "case",
    "frame",
    "order",
    "subject",
    "object",
    "question",
    "renamed_question",
    "ranks",
    "twin_ranks",
    "label",
    "twin_label",
    "logits",
    "twin_logits",
    "delta_norm",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), "Nonfinite JSON float")
        return result

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_float
    )


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def bound_inputs(directory, seal_path):
    directory, seal_path = Path(directory), Path(seal_path)
    plan, source, started, result, terminal = (
        load(directory / name)
        for name in ("PLAN.json", "SOURCE.json", "STARTED.json", "RESULTS.json", "FINISHED.json")
    )
    seal = load(seal_path)
    require(
        terminal["status"] == "COMPLETED" and not (directory / "FAILED.json").exists(),
        "A successful terminal receipt is required",
    )
    require(digest(plan) == PLAN_DIGEST, "Frozen plan mismatch")
    for filename, field in (("RESULTS.json", "results_sha256"), ("CASES.jsonl", "cases_sha256")):
        require(sha(directory / filename) == terminal[field], f"Terminal hash mismatch: {filename}")
    require(re.fullmatch(r"[0-9a-f]{40}", source["commit"]) is not None, "Invalid source commit")
    require(source["commit"] == seal["source_commit"], "Source commit/seal mismatch")
    require(
        source["files"] and digest(source["files"]) == source["aggregate_sha256"],
        "Source map digest mismatch",
    )
    require(
        all(seal["source_hashes"].get(k) == v for k, v in source["files"].items()),
        "Source map escapes seal",
    )
    require(started["external_seal_sha256"] == sha(seal_path), "External seal hash mismatch")
    for receipt in (started, result):
        require(
            receipt["plan_sha256"] == PLAN_DIGEST
            and receipt["source_sha256"] == source["aggregate_sha256"],
            "Source/plan receipt mismatch",
        )
    require(
        result["schema"] == "v18-controlled-operand-selection-result-v1", "Unknown result schema"
    )
    require(
        result["device"] == started["device"] and result["device"] in ("cpu", "cuda"),
        "Runtime mismatch",
    )
    files = (
        "PLAN.json",
        "SOURCE.json",
        "STARTED.json",
        "RESULTS.json",
        "FINISHED.json",
        "CASES.jsonl",
    )
    binding = {
        "directory": directory.name,
        "source_commit": source["commit"],
        "source_sha256": source["aggregate_sha256"],
        "plan_sha256": PLAN_DIGEST,
        "source_seal_sha256": sha(seal_path),
        "artifact_sha256": {name: sha(directory / name) for name in files},
    }
    audit_path = seal_path.parent / f"ASSAY_{result['device'].upper()}_AUDIT.json"
    audit = load(audit_path)
    require(
        audit["schema"] == "v18-operand-selection-supplemental-terminal-audit-v1"
        and audit["status"] == "OFFLINE_TERMINAL_AUDIT_PASS"
        and audit["device"] == result["device"]
        and audit["source_commit"] == source["commit"]
        and audit["source_seal_sha256"] == sha(seal_path)
        and audit["gates"] == result["gates"],
        "Prior terminal audit binding mismatch",
    )
    replay = audit["raw_replay"]
    require(
        replay["status"] == "OFFLINE_RAW_METRICS_AND_GATES_PASS"
        and replay["device"] == result["device"]
        and replay["source_commit"] == source["commit"]
        and replay["gates"] == result["gates"]
        and replay["raw_groups"] == 50
        and replay["raw_rows"] == 36864
        and all(
            type(x[k]) is int and x[k] == 0
            for x in (audit, replay)
            for k in ("forward_calls", "training_updates")
        ),
        "Prior raw replay binding mismatch",
    )
    binding["prior_terminal_audit"] = {"file": audit_path.name, "sha256": sha(audit_path)}
    return result, terminal, binding


def expected_groups():
    return {
        (seed, factor, split, dtype)
        for seed in SEEDS
        for factor in FACTORS
        for split in FRAMES
        for dtype in DTYPES
    } | {(None, "common_only", "held_out", dtype) for dtype in DTYPES}


def validate_row(row):
    require(type(row) is dict and set(row) == ROW_KEYS, "Case schema mismatch")
    for field in ("case", "frame", "order", "subject", "object", "label", "twin_label"):
        require(type(row[field]) is int, f"Non-integer case field: {field}")
    require(row["seed"] is None or type(row["seed"]) is int, "Non-integer seed")
    key = tuple(row[k] for k in ("seed", "factor", "split", "native_dtype"))
    require(key in expected_groups(), "Unexpected case group")
    count = FRAMES[row["split"]] * 36
    require(0 <= row["case"] < count, "Case index out of bounds")
    frame, within = divmod(row["case"], 36)
    order, question = divmod(within, 6)
    subject, obj = QUESTIONS[question]
    ranks = list(ORDERS[order])
    twin = [1 - rank if rank < 2 else rank for rank in ranks]
    expected = {
        "frame": frame,
        "order": order,
        "subject": subject,
        "object": obj,
        "ranks": ranks,
        "twin_ranks": twin,
        "label": int(ranks[subject] <= ranks[obj]),
        "twin_label": int(twin[subject] <= twin[obj]),
        "question": f"Is E{subject} ranked above E{obj}? Answer:",
        "renamed_question": f"Is Alias{subject + 7} ranked above Alias{obj + 7}? Answer:",
    }
    require(all(row[k] == v for k, v in expected.items()), "Case world/question binding mismatch")
    require(
        all(type(v) is int for name in ("ranks", "twin_ranks") for v in row[name]),
        "Rank values must be integers",
    )
    for name in ("logits", "twin_logits"):
        values = row[name]
        require(
            type(values) is list and len(values) == 7, "Expected seven native vocabulary logits"
        )
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in values),
            "Nonfinite or nonnumeric logit",
        )
        require(
            values[0] == -values[1] and all(v == values[2] for v in values[2:]),
            "Toy native-head identities changed",
        )
    norm = row["delta_norm"]
    require(
        type(norm) in (int, float) and math.isfinite(norm) and 0 <= norm <= 0.250001,
        "Invalid recorded residual norm",
    )
    if row["seed"] is None:
        require(
            norm == 0 and row["logits"] == row["twin_logits"] == [0, 0, -4, -4, -4, -4, -4],
            "Frozen-zero reference changed",
        )
    return key


def read_groups(path):
    groups = defaultdict(dict)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = strict_json(line)
        key = validate_row(row)
        require(row["case"] not in groups[key], "Duplicate case index")
        groups[key][row["case"]] = row
    require(set(groups) == expected_groups(), "Incomplete or extra case groups")
    for key, values in groups.items():
        require(set(values) == set(range(FRAMES[key[2]] * 36)), "Incomplete case population")
    return {key: [values[i] for i in range(len(values))] for key, values in groups.items()}


def prediction(logits):
    return max(range(len(logits)), key=logits.__getitem__)


def correct(logits, label):
    return prediction(logits) == label and logits.count(max(logits)) == 1


def integer_metrics(rows):
    good = [correct(r["logits"], r["label"]) for r in rows]
    twin_good = [correct(r["twin_logits"], r["twin_label"]) for r in rows]
    affected = [r["label"] != r["twin_label"] for r in rows]
    agree = [prediction(r["logits"]) == prediction(r["twin_logits"]) for r in rows]
    return {
        "unique_intact_queries": len(rows),
        "paired_queries": len(rows),
        "unique_worlds": len(rows) // 6,
        "reciprocal_pairs": len(rows) // 2,
        "affected_pairs": sum(affected),
        "unaffected_pairs": len(rows) - sum(affected),
        "strict_native_correct": sum(good),
        "ordinary_native_correct": sum(prediction(r["logits"]) == r["label"] for r in rows),
        "native_ties": sum(r["logits"].count(max(r["logits"])) > 1 for r in rows),
        "twin_native_ties": sum(r["twin_logits"].count(max(r["twin_logits"])) > 1 for r in rows),
        "reciprocal_both_correct": sum(
            good[i + a] and good[i + b]
            for i in range(0, len(rows), 6)
            for a, b in ((0, 2), (1, 4), (3, 5))
        ),
        "affected_donor_flips": sum(
            a and c and t and not same for a, c, t, same in zip(affected, good, twin_good, agree)
        ),
        "unaffected_strict_correct": sum(c and not a for c, a in zip(good, affected)),
        "unaffected_agreement_count": sum(same and not a for same, a in zip(agree, affected)),
    }


def check_metrics(actual, recorded):
    for key, value in actual.items():
        if key != "unaffected_agreement_count":
            require(
                type(recorded[key]) is int and recorded[key] == value,
                f"Recorded integer metric mismatch: {key}",
            )
    ratios = {
        "strict_native_accuracy": ("strict_native_correct", "unique_intact_queries"),
        "reciprocal_both_correct_rate": ("reciprocal_both_correct", "reciprocal_pairs"),
        "affected_donor_flip_rate": ("affected_donor_flips", "affected_pairs"),
        "unaffected_strict_accuracy": ("unaffected_strict_correct", "unaffected_pairs"),
        "unaffected_prediction_agreement": ("unaffected_agreement_count", "unaffected_pairs"),
    }
    for key, (numerator, denominator) in ratios.items():
        require(
            type(recorded[key]) in (int, float)
            and abs(recorded[key] - actual[numerator] / actual[denominator]) <= 1e-7,
            f"Recorded FP32 ratio mismatch: {key}",
        )


def head_axes(rows):
    """Recover the two toy-visible residual coordinates from FP32 intact logits."""
    require(
        rows and all(r["native_dtype"] == "torch.float32" for r in rows),
        "Axis accounting requires FP32 rows; BF16 inverse is quantized",
    )
    answer = [r["logits"][0] / 8 for r in rows]
    distractor = [-r["logits"][2] / 4 - 1 for r in rows]
    total = math.fsum(r["delta_norm"] ** 2 for r in rows)
    ae, de = math.fsum(x * x for x in answer), math.fsum(x * x for x in distractor)
    require(
        total > 0 and ae + de <= total + max(1e-10, total * 1e-5),
        "Recovered head-axis energy exceeds recorded residual energy",
    )
    return {
        "rows": len(rows),
        "residual_squared_norm_sum": total,
        "answer_coordinate_squared_sum": ae,
        "distractor_coordinate_squared_sum": de,
        "answer_energy_fraction": ae / total,
        "distractor_energy_fraction": de / total,
        "unaccounted_energy_fraction_with_rounding": (total - ae - de) / total,
        "mean_delta_norm": math.fsum(r["delta_norm"] for r in rows) / len(rows),
        "mean_absolute_answer_coordinate": math.fsum(map(abs, answer)) / len(rows),
        "mean_distractor_coordinate": math.fsum(distractor) / len(rows),
        "mean_nonanswer_logit": math.fsum(r["logits"][2] for r in rows) / len(rows),
    }


def compare_rows(left, right):
    require(len(left) == len(right), "Comparison population mismatch")
    changes = {
        "intact_predictions": 0,
        "twin_predictions": 0,
        "intact_correctness": 0,
        "twin_correctness": 0,
    }
    max_logit, margin_diffs = 0.0, []
    for a, b in zip(left, right):
        require(
            all(
                a[k] == b[k]
                for k in ROW_KEYS - {"native_dtype", "logits", "twin_logits", "delta_norm"}
            ),
            "Compared cases have different bindings",
        )
        for field, label, prefix in (
            ("logits", "label", "intact"),
            ("twin_logits", "twin_label", "twin"),
        ):
            x, y = a[field], b[field]
            changes[f"{prefix}_predictions"] += prediction(x) != prediction(y)
            changes[f"{prefix}_correctness"] += correct(x, a[label]) != correct(y, b[label])
            max_logit = max(max_logit, *(abs(u - v) for u, v in zip(x, y)))
            margin_diffs.append(abs((x[0] - x[1]) - (y[0] - y[1])))
    return {
        "paired_rows": len(left),
        "changed_counts": changes,
        "max_absolute_logit_difference": max_logit,
        "max_absolute_answer_margin_difference": max(margin_diffs),
        "mean_absolute_answer_margin_difference": math.fsum(margin_diffs) / len(margin_diffs),
    }


def analyze_runtime(directory, seal_path):
    result, terminal, binding = bound_inputs(directory, seal_path)
    groups = read_groups(Path(directory) / "CASES.jsonl")
    require(
        set(result["results"]) == {f"{seed}:{factor}" for seed in SEEDS for factor in FACTORS},
        "Result factor population mismatch",
    )
    table = []
    for (seed, factor, split, dtype), rows in groups.items():
        recorded = (
            result["common_only_reference"][dtype]
            if seed is None
            else result["results"][f"{seed}:{factor}"][f"{split}_{dtype.split('.')[-1]}"]
        )
        counts = integer_metrics(rows)
        check_metrics(counts, recorded)
        table.append({"seed": seed, "factor": factor, "split": split, "dtype": dtype, **counts})
    axes, bf16, controls = [], [], []
    for seed in SEEDS:
        for factor in FACTORS:
            axes.append(
                {
                    "seed": seed,
                    "factor": factor,
                    "split": "held_out",
                    **head_axes(groups[(seed, factor, "held_out", DTYPES[0])]),
                }
            )
            controls.append(
                {
                    "seed": seed,
                    "factor": factor,
                    "runtime_attested_not_recomputed": result["results"][f"{seed}:{factor}"][
                        "controls"
                    ],
                }
            )
            for split in FRAMES:
                bf16.append(
                    {
                        "seed": seed,
                        "factor": factor,
                        "split": split,
                        **compare_rows(
                            groups[(seed, factor, split, DTYPES[0])],
                            groups[(seed, factor, split, DTYPES[1])],
                        ),
                    }
                )
    bf16.append(
        {
            "seed": None,
            "factor": "common_only",
            "split": "held_out",
            **compare_rows(
                groups[(None, "common_only", "held_out", DTYPES[0])],
                groups[(None, "common_only", "held_out", DTYPES[1])],
            ),
        }
    )
    gates = result["gates"]
    require(
        gates["old_scientific_gate"] == "FAIL"
        and gates["winner"] == "none"
        and gates["non_regression"] == "NOT_ESTABLISHED",
        "Historical gate changed",
    )
    report = {
        "input_binding": binding,
        "case_rows": sum(map(len, groups.values())),
        "case_groups": len(groups),
        "integer_replay": "MATCH",
        "recorded_gates_not_requalified": gates,
        "terminal_resources": terminal["resources"],
        "counts": table,
        "held_out_fp32_head_axis_accounting": axes,
        "fp32_bf16_comparisons": bf16,
        "controls": controls,
    }
    return report, groups


def report_bundle(bundle):
    bundle = Path(bundle)
    runtimes, populations = {}, {}
    for device in ("cpu", "cuda"):
        runtimes[device], populations[device] = analyze_runtime(
            bundle / f"assay_{device}", bundle / "SOURCE_SEAL.json"
        )
    require(
        runtimes["cpu"]["input_binding"]["source_sha256"]
        == runtimes["cuda"]["input_binding"]["source_sha256"],
        "Cross-runtime source mismatch",
    )
    cpu, cuda = populations["cpu"], populations["cuda"]
    keys = sorted(cpu, key=lambda key: repr(key))
    comparison = compare_rows(
        [r for key in keys for r in cpu[key]], [r for key in keys for r in cuda[key]]
    )
    return {
        "schema": "v18-operand-cases-posthoc-analysis-v1",
        "report_script_sha256": sha(__file__),
        "runtimes": runtimes,
        "cpu_cuda_comparison": comparison,
        "limitations": [
            "Post-hoc description, not a new gate, causal intervention, or model forward.",
            "Receipt consistency does not replace source/import/weights/populations verification.",
            "Orders, reciprocals, twins, seeds and runtimes are not independent new samples.",
            "Head identities are specific to this synthetic head; no Mistral interpretation.",
            "FP32 delta30=logit0/8; delta31=-logit2/4-1, with baseline coordinates 0 and 1.",
            "Fractions use sum-of-squares ratios; not mean ratios or causal attribution.",
            "FP32 rounding may leave a small signed accounting remainder; it is not clamped.",
            "BF16 quantization prevents exact residual inversion; axis accounting excludes BF16.",
            "Controls are copied with original failures; raw control forwards were not rerun.",
            "No writer, full-update ownership, language quality, or non-regression qualification.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = report_bundle(args.bundle)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)


if __name__ == "__main__":
    main()
