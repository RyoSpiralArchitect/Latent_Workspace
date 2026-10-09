#!/usr/bin/env python3
"""Verify sealed completion-path scalar receipts, not model logits or tokenization.

The earlier generated answers and expression gate are immutable. Fixed-alias
mass is a posthoc diagnostic over those already-exposed prompt cases.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
from v15_completion_mass import ALIASES, METADATA, summarize  # noqa: E402
from verify_ft_beta_query_pool import (  # noqa: E402
    BASE_HASH,
    digest,
    load,
    require,
    sha,
    verify_resources,
    write_new,
)
from verify_v15_elicitation import (  # noqa: E402
    number,
)
from verify_v15_elicitation import (  # noqa: E402
    verify_bundle as verify_predecessor,
)

PLAN_PATH = "configs/v15/COMPLETION_MASS_PLAN.json"
PREDECESSOR = "provenance/pilots/v15_base_elicitation_20261010"
RAW_NAMES = {"STARTED.json", "SCORES.json", "REPORT.json", "RESOURCES.jsonl"}
SOURCE_ADDITIONS = {
    PLAN_PATH,
    "docs/v15/COMPLETION_MASS_PLAN.md",
    "scripts/run_v15_completion_mass.py",
    "scripts/v15_completion_mass.py",
    "scripts/verify_v15_completion_mass.py",
    "tests/test_v15_completion_mass.py",
    "tests/test_verify_v15_completion_mass.py",
    "tests/test_run_v15_completion_mass.py",
    f"{PREDECESSOR}/ARTIFACT_INDEX.json",
}
PLAN_HASH = "492dbfbaf9f1d6082132d9c322a622a53d3eee118f344b4604c54b827f680abf"
CLAIMS = {
    "training_performed": False,
    "semantic_promotion": False,
    "non_regression": "NOT_ESTABLISHED",
    "quality_judging": "NOT_RUN",
    "instrument_qualified": False,
    "posthoc_scoring_diagnostic": True,
    "historical_generation_gate_changed": False,
}


def verify_plan(plan):
    require(
        plan["format"] == "v15-base-completion-mass-v1"
        and plan["predecessor_bundle"] == PREDECESSOR
        and plan["predecessor_source_commit"] == "9983e42d082a9452feedc60bb0b72d0b810795b8"
        and plan["predecessor_artifact_index_sha256"]
        == "45563fddd8edcc3cf1ce150cdc777b0d1012848632b8bab830aaa597ed6b1d7b"
        and plan["predecessor_primary_expression_gate"] == "FAIL",
        "Frozen predecessor contract",
    )
    require(
        plan["model_parent"] == "configs/v14/PRECISION_BRIDGE_PLAN.json"
        and plan["model_revision"] == "c170c708c41dac9275d15a8fff4eca08d52bab71"
        and plan["base_state_sha256"] == BASE_HASH,
        "Frozen model contract",
    )
    require(
        plan["cases"] == 36
        and plan["prefixes"] == 144
        and plan["all_cases_exposed"] is True
        and plan["alias_suffixes"] == [a[1] for a in ALIASES]
        and plan["alias_classes"] == [a[0] for a in ALIASES]
        and plan["alias_string_bindings"] == 576
        and plan["eos_token_ids"] == [2],
        "Frozen panel/alias/EOS contract",
    )
    require(
        plan["optimizer_steps"] == 0
        and plan["workspace_loaded"] is False
        and plan["new_generation_sequences"] == 0
        and plan["nice"] == 10
        and plan["claims"] == CLAIMS,
        "No-update/no-promotion contract",
    )
    require(
        plan["prefix_policy"]
        == "reuse all exact predecessor prompt IDs; no rerendering or new cases"
        and plan["alias_binding"]
        == (
            "entire prefix unchanged; exactly one appended token; deduplicate by token ID "
            "within class; reject cross-class collisions"
        )
        and plan["path_definition"]
        == "one fixed alias token followed immediately by the pinned model EOS token",
        "Fixed path contract",
    )
    require(
        plan["history"] == "teacher-forced complete-prefix recomputation; no KV cache"
        and plan["probability_arithmetic"]
        == "FP64 log_softmax over the entire native vocabulary; no temperature scaling"
        and plan["prediction"]
        == "class with strictly greater log mass; exact ties are unknown and not correct",
        "Scoring arithmetic contract",
    )


def _verify_source_manifests(started, report, old_started, repo):
    before = started["source_manifest_before"]
    require(
        report["source_manifest_before"] == report["source_manifest_after"] == before,
        "Source manifest changed",
    )
    require(set(before) == set(old_started["source_hashes"]) | SOURCE_ADDITIONS, "Source coverage")
    for name, expected in before.items():
        require(sha(expected) and digest(repo / name) == expected, f"Source hash mismatch: {name}")
    require(
        all(before[k] == v for k, v in old_started["source_hashes"].items()),
        "Sealed predecessor source changed",
    )
    return len(before)


def verify_contracts(bundle, repo=REPO):
    raw = bundle / "raw"
    require(
        raw.is_dir() and not raw.is_symlink() and {p.name for p in raw.iterdir()} == RAW_NAMES,
        "Raw inventory",
    )
    values = {name: load(raw / name) for name in RAW_NAMES}
    started, report, rows = values["STARTED.json"], values["REPORT.json"], values["SCORES.json"]
    plan = load(repo / PLAN_PATH)
    require(digest(repo / PLAN_PATH) == PLAN_HASH, "Frozen plan bytes changed")
    verify_plan(plan)
    require(
        started["plan"] == plan
        and started["plan_sha256"] == report["plan_sha256"] == digest(repo / PLAN_PATH),
        "Plan identity",
    )
    predecessor = repo / plan["predecessor_bundle"]
    old = verify_predecessor(predecessor, repo)
    require(
        old["status"] == "VERIFIED_RECEIPTS"
        and old["summary"]["primary_expression_gate"]
        == plan["predecessor_primary_expression_gate"]
        == "FAIL",
        "Predecessor gate is immutable",
    )
    require(
        started["predecessor_artifact_index_sha256"]
        == report["predecessor_artifact_index_sha256"]
        == plan["predecessor_artifact_index_sha256"]
        == digest(predecessor / "ARTIFACT_INDEX.json"),
        "Predecessor artifact identity",
    )
    old_started = load(predecessor / "raw/STARTED.json")
    require(
        old_started["source_commit"] == plan["predecessor_source_commit"]
        and started["runtime"] == old_started["runtime"]
        and re.fullmatch(r"[0-9a-f]{40}", started["source_commit"]) is not None,
        "Runtime/commit identity",
    )
    source_count = _verify_source_manifests(started, report, old_started, repo)
    require(
        started["tokenizer_identity_before"]
        == report["tokenizer_identity_before"]
        == report["tokenizer_identity_after"]
        == old_started["tokenizer_identity"],
        "Pinned tokenizer before/after receipt",
    )
    require(
        report["base_sha256_before"] == report["base_sha256_after"] == BASE_HASH,
        "Frozen base receipt",
    )
    summary, counters = verify_scores(
        rows,
        load(predecessor / "raw/RENDERINGS.json"),
        load(predecessor / "raw/CASES.json"),
        load(predecessor / "raw/CHOICES.json"),
    )
    require(
        report["status"] == "COMPLETED_COMPLETION_MASS_ASSAY"
        and report["optimizer_steps"] == 0
        and report["workspace_loaded"] is False
        and report["generation_sequences"] == 0
        and report["eos_token_ids"] == [2],
        "Completion execution scope",
    )
    require(all(report[k] == v for k, v in counters.items()), "Forward/parity accounting")
    require(report["summary"] == summary, "Completion summary mismatch")
    require(all(report[k] == v for k, v in CLAIMS.items()), "Report claim ceiling")
    require(plan["resources"] == old_started["plan"]["resources"], "Resource contract")
    number(report["elapsed_seconds"], "Elapsed seconds", 0)
    resources = verify_resources(values["RESOURCES.jsonl"], started, report, plan["resources"])
    return {
        "status": "VERIFIED_RECEIPTS",
        "raw_files": len(RAW_NAMES),
        "summary": summary,
        "accounting": counters,
        "resources": resources,
        "source_files_verified": source_count,
        "predecessor_primary_expression_gate": "FAIL",
        "prior_generation_sequences_unchanged": 288,
        "full_logits_recomputed": False,
        "model_state_recomputed": False,
        "tokenizer_files_rehashed_locally": False,
        "alias_tokenization_recomputed": False,
        "scalar_path_arithmetic_recomputed": True,
        "notes": [
            (
                "Four fixed textual aliases are deduplicated by within-class token identity; "
                "this is not exhaustive valid-answer mass."
            ),
            (
                "Full logits, model state, cached tokenizer files and alias tokenization "
                "remain execution receipts."
            ),
            (
                "All cases were exposed before this posthoc scoring diagnostic; historical "
                "generation answers and FAIL gate are unchanged."
            ),
            (
                "Resource process peaks are sampled observations; "
                "the Torch allocator cap is not a whole-process cap."
            ),
        ],
        **CLAIMS,
    }


def prefix_hash(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def verify_scores(rows, renderings, cases, choices):
    """Replay metadata, native lowercase identities and scalar path arithmetic."""
    summary = summarize(rows)
    key_names = ("case_id", "renderer", "information")
    render_index = {tuple(r[k] for k in key_names): r for r in renderings}
    choice_index = {tuple(r[k] for k in key_names): r for r in choices}
    case_index = {c["case_id"]: c for c in cases}
    expected = set(itertools.product(case_index, ("raw", "native_chat"), ("query_only", "inline")))
    require(
        set(render_index) == set(choice_index) == expected and len(rows) == 144,
        "Predecessor prompt grid",
    )
    seen, alias_forwards = set(), 0
    for row in rows:
        key = tuple(row[k] for k in key_names)
        require(key in expected and key not in seen, "Duplicate/unknown completion row")
        seen.add(key)
        case, rendered, old = case_index[key[0]], render_index[key], choice_index[key]
        require(
            all(row[k] == case[k] for k in METADATA if k not in key_names),
            "Completion case metadata",
        )
        ids = row["prefix_ids"]
        require(
            ids == rendered["prompt_ids"] and row["prefix_sha256"] == prefix_hash(ids),
            "Exact predecessor prefix identity",
        )
        require(
            row["old_lowercase_native"] == old["native"]
            and row["initial_choice_replay_exact"] is True
            and row["ordinary_shared_full_logits_exact"] is True,
            "Initial native replay/parity receipt",
        )
        aliases = row["aliases"]
        # analyze_row/summarize already checks the complete four-spelling union,
        # class ownership, within-class deduplication, log sums and probabilities.
        lower = {}
        for label, suffix in ((0, " no"), (1, " yes")):
            matches = [a for a in aliases if suffix in a["suffixes"]]
            require(len(matches) == 1, "Lowercase binding coverage")
            alias = matches[0]
            require(
                alias["token_id"]
                == old["candidate_ids"][label]
                == rendered["candidate_ids"][label],
                "Historical lowercase token identity",
            )
            require(
                math.isclose(
                    alias["first_probability"],
                    old["candidate_probabilities"][label],
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                ),
                "Initial lowercase full-vocabulary probability replay",
            )
            lower[label] = alias
        require(
            math.isclose(
                lower[1]["first_log_probability"] - lower[0]["first_log_probability"],
                old["native"]["gap"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ),
            "Lowercase log probability/native logit-gap identity",
        )
        alias_forwards += len(aliases)
    require(seen == expected, "Missing completion rows")
    return summary, {
        "rows": len(rows),
        "alias_forwards": alias_forwards,
        "initial_choice_replay_matches": len(rows),
        "readout_parity_checks": len(rows) + alias_forwards,
    }


def index_for(bundle):
    return {
        "format": "v15-completion-mass-artifact-index-v1",
        "files": {
            name: {
                "sha256": digest(bundle / "raw" / name),
                "bytes": (bundle / "raw" / name).stat().st_size,
            }
            for name in sorted(RAW_NAMES)
        },
    }


def verify_bundle(bundle, check_index=True, *, repo=REPO):
    bundle = Path(bundle)
    if check_index:
        require(
            load(bundle / "ARTIFACT_INDEX.json") == index_for(bundle),
            "Artifact hash/index mismatch",
        )
    return verify_contracts(bundle, repo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", type=Path, default=REPO / "provenance/pilots/v15_completion_mass_20261010"
    )
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.write_index:
        require(not (args.bundle / "ARTIFACT_INDEX.json").exists(), "Artifact index collision")
    result = verify_bundle(args.bundle.resolve(), check_index=not args.write_index)
    if args.write_index:
        write_new(args.bundle / "ARTIFACT_INDEX.json", index_for(args.bundle))
    if args.output:
        write_new(args.output, result)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
