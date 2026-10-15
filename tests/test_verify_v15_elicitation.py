from __future__ import annotations

import copy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v15_elicitation_verify_test", ROOT / "scripts/verify_v15_elicitation.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
from v15_elicitation_inputs import make_cases  # noqa: E402


@pytest.fixture
def panel():
    cases = make_cases(ROOT)
    plan = verify.load(ROOT / verify.PLAN_PATH)
    choices, generated = [], []
    for case, renderer, info in itertools.product(cases, verify.RENDERERS, verify.INFORMATION):
        target = case["target_label"]
        gap = 1.0 if target else -1.0
        identity = {"case_id": case["case_id"], "renderer": renderer, "information": info}
        choices.append(
            {**identity, "native": {"scores": [0.0, gap], "gap": gap, "prediction": target}}
        )
        for regime in verify.REGIMES:
            generated.append(
                {
                    **identity,
                    "regime": regime["id"],
                    "answer": "yes" if target else "no",
                    "target_label": target,
                    "parsed_answer": target,
                    "valid_eos": True,
                    "strict_correct": True,
                    "lowercase_compliant": True,
                    "finish_reason": "eos",
                }
            )
    return cases, choices, generated, plan


def test_complete_summary_has_fixed_panel_denominators_and_no_selection(panel):
    result = verify.summarize(*panel)
    assert result["denominators"] == {"cases": 36, "choices": 144, "generation_sequences": 288}
    assert result["primary_expression_gate"] == "PASS"
    assert result["method_selected"] is False
    assert result["primary_renderer"] == "native_chat"
    assert all(cell["status"] == "PASS" for cell in result["expression_gates"].values())
    assert len(result["generation"]["cells"]) == 40


@pytest.mark.parametrize("index", [0, 1, 2])
def test_missing_denominator_is_rejected(panel, index):
    panel[index].pop()
    with pytest.raises(ValueError):
        verify.summarize(*panel)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_duplicate_cells_are_rejected(panel, index):
    panel[index][-1] = copy.deepcopy(panel[index][0])
    with pytest.raises(ValueError):
        verify.summarize(*panel)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gap", 0.0),
        ("prediction", None),
        ("prediction", True),
        ("scores", [float("nan"), 1.0]),
    ],
)
def test_initial_choice_cannot_repair_or_hide_ties(panel, field, value):
    panel[1][0]["native"][field] = value
    with pytest.raises(ValueError):
        verify.summarize(*panel)


@pytest.mark.parametrize(
    "field,value",
    [
        ("parsed_answer", None),
        ("valid_eos", False),
        ("strict_correct", False),
        ("lowercase_compliant", False),
        ("target_label", 9),
        ("finish_reason", "stopped"),
        ("answer", "yes, because of the facts"),
    ],
)
def test_parser_and_termination_receipts_are_recomputed(panel, field, value):
    panel[2][0][field] = value
    with pytest.raises(ValueError):
        verify.summarize(*panel)


def _update_answer(row, answer, reason="eos"):
    parsed = verify.parse_functional_answer(answer)
    valid = parsed is not None and reason == "eos"
    row.update(
        answer=answer,
        parsed_answer=parsed,
        valid_eos=valid,
        strict_correct=valid and parsed == row["target_label"],
        lowercase_compliant=answer.strip() in ("yes", "no"),
        finish_reason=reason,
    )


def test_length_truncated_correct_word_is_invalid_and_not_repaired_from_choice(panel):
    case_ids = {c["case_id"] for c in panel[0] if c["split"] == "confirmation"}
    row = next(
        r
        for r in panel[2]
        if r["case_id"] in case_ids
        and r["renderer"] == "native_chat"
        and r["information"] == "inline"
        and r["regime"] == "greedy"
    )
    _update_answer(row, row["answer"], "length")
    result = verify.summarize(*panel)
    assert result["primary_expression_gate"] == "FAIL"
    assert result["expression_gates"]["native_chat"]["valid_eos"] == 31
    assert result["expression_gates"]["raw"]["status"] == "PASS"
    assert result["primary_renderer"] == "native_chat"


def test_exposed_or_sample_failures_do_not_gate_confirmation_greedy(panel):
    exposed = {c["case_id"] for c in panel[0] if c["split"] == "exposed"}
    for row in panel[2]:
        if row["case_id"] in exposed or row["regime"] == "sample211":
            _update_answer(row, "not a valid answer")
    assert verify.summarize(*panel)["primary_expression_gate"] == "PASS"


def test_uppercase_valid_but_not_lowercase_compliant(panel):
    for row in panel[2]:
        _update_answer(row, row["answer"].upper())
    result = verify.summarize(*panel)
    assert result["primary_expression_gate"] == "PASS"
    assert all(r["lowercase_compliant"] == 0 for r in result["generation"]["cells"])


def test_wording_floor_cannot_be_hidden_by_view_average(panel):
    cases = {c["case_id"]: c for c in panel[0]}
    matching = [
        r
        for r in panel[2]
        if r["renderer"] == "native_chat"
        and r["information"] == "inline"
        and r["regime"] == "greedy"
        and cases[r["case_id"]]["view"] == "atomic"
        and cases[r["case_id"]]["wording"] == "ranked_above"
    ]
    for row in matching[:3]:
        _update_answer(row, "no" if row["target_label"] else "yes")
    result = verify.summarize(*panel)
    assert result["primary_expression_gate"] == "FAIL"
    atomic = next(
        r for r in result["expression_gates"]["native_chat"]["by_view"] if r["view"] == "atomic"
    )
    assert atomic["strict_correct"] == 13


def test_paired_lifts_report_rescues_and_regressions_separately(panel):
    rows = [r for r in panel[2] if r["renderer"] == "raw" and r["regime"] == "greedy"]
    first = next(r for r in rows if r["information"] == "query_only")
    second = next(
        r for r in rows if r["information"] == "inline" and r["case_id"] != first["case_id"]
    )
    _update_answer(first, "no" if first["target_label"] else "yes")
    _update_answer(second, "no" if second["target_label"] else "yes")
    paired = verify.summarize(*panel)["generation"]["paired_inline_minus_query"]
    assert sum(r["rescued_by_inline"] for r in paired) == 1
    assert sum(r["regressed_with_inline"] for r in paired) == 1
    assert sum(r["net_correct_change"] for r in paired) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("primary_renderer", "raw"),
        ("max_new_tokens", 128),
        ("regimes", []),
        ("information", ["inline"]),
        ("renderers", ["native_chat"]),
    ],
)
def test_prospective_contract_cannot_be_changed(panel, field, value):
    panel[3][field] = value
    with pytest.raises(ValueError):
        verify.summarize(*panel)


def test_gate_threshold_cannot_be_relaxed(panel):
    panel[3]["gate"]["valid_eos_required"] = 31
    with pytest.raises(ValueError):
        verify.summarize(*panel)


def test_label_and_reciprocal_pair_diagnostics_are_not_accuracy_duplicates(panel):
    cases = {c["case_id"]: c for c in panel[0]}
    for row in panel[2]:
        if row["renderer"] == "native_chat" and cases[row["case_id"]]["split"] == "confirmation":
            _update_answer(row, "yes")
    cells = verify.summarize(*panel)["generation"]["cells"]
    selected = [r for r in cells if r["renderer"] == "native_chat" and r["split"] == "confirmation"]
    assert all(r["label_correct"]["no"]["recall"] == 0 for r in selected)
    assert all(r["label_correct"]["yes"]["recall"] == 1 for r in selected)
    assert all(r["reciprocal_pairs"] == {"total": 4, "both_correct": 0} for r in selected)


@pytest.fixture
def bundle(tmp_path, panel):
    from v15_elicitation_inputs import SYMMETRIC_INSTRUCTION

    cases, choices, generated, plan = panel
    old = ROOT / plan["predecessor_bundle"] / "raw"
    old_start, old_report = (verify.load(old / name) for name in ("STARTED.json", "REPORT.json"))
    old_rows = verify.load(old / "GENERATION.json")["rows"]
    old_index = {(r["case_id"], r["condition"], r["regime"]): r for r in old_rows}
    renderings, lookup = [], {}
    for index, (case, renderer, info) in enumerate(
        itertools.product(cases, verify.RENDERERS, verify.INFORMATION)
    ):
        user = SYMMETRIC_INSTRUCTION + "\n\n" + case["query"].strip()
        if info == "inline":
            user = case["context"] + "\n\n" + user
        text = user if renderer == "raw" else "<s>[INST] " + user + " [/INST]"
        ids = [100 + index, 300 + index]
        if case["split"] == "exposed" and renderer == "raw":
            ids = old_index[case["case_id"], verify.CONDITIONS[info], "greedy"]["prompt_ids"]
        question = case["query"].strip().removesuffix("Answer:").strip()
        start = text.index(question)
        applied = renderer == "native_chat"
        row = {
            "case_id": case["case_id"],
            "renderer": renderer,
            "information": info,
            "text": text,
            "user_content": user,
            "prompt_ids": ids,
            "candidate_ids": [1476, 5849],
            "candidate_suffixes": [" no", " yes"],
            "span": {
                "question": question,
                "character_start": start,
                "character_end": start + len(question),
                "token_indices": [0],
                "prefix_ids": ids,
                "rendered_prefix_sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
            "chat_template": {
                "sha256": "a" * 64,
                "applied": applied,
                "add_generation_prompt": applied,
                "messages": "single_user_no_system" if applied else None,
                "native_tokenization_exact": True if applied else None,
            },
        }
        renderings.append(row)
        lookup[case["case_id"], renderer, info] = row
    for row in choices:
        row.update(
            candidate_ids=[1476, 5849],
            candidate_probabilities=[0.1, 0.2],
            top1_token_id=2,
            top1_probability=0.5,
            ordinary_shared_full_logits_exact=True,
            shared_historical_full_logits_exact=True,
            zero_delta_exact=True,
        )
    case_lookup = {c["case_id"]: c for c in cases}
    for row in generated:
        case = case_lookup[row["case_id"]]
        condition = verify.CONDITIONS[row["information"]]
        regime = next(r for r in verify.REGIMES if r["id"] == row["regime"])
        row.update({k: case[k] for k in ("split", "family_id", "view", "wording")})
        row.update(
            condition=condition,
            id=f"{row['case_id']}__{row['regime']}__{condition}__{row['renderer']}",
            regime_parameters=regime,
            prompt_ids=lookup[row["case_id"], row["renderer"], row["information"]]["prompt_ids"],
            generated_ids=[2],
            token_count=1,
            token_trace=[
                {
                    "step": 0,
                    "token_id": 2,
                    "uniform": verify.matched_uniform(row["case_id"], regime["seed"], 0),
                    "sampling_probability": 1.0 if regime["temperature"] == 0 else 0.5,
                    "chosen_token_native_probability": 0.5,
                    "same_prefix_base_chosen_token_native_probability": 0.5,
                    "chosen_native_logit": 1.0,
                    "same_prefix_base_native_logit": 1.0,
                    "native_top1_token_id": 2,
                    "same_prefix_base_native_top1_token_id": 2,
                    "native_top1_changed": False,
                    **dict.fromkeys(
                        (
                            "delta_l2",
                            "native_applied_delta_l2",
                            "native_applied_fraction",
                            "native_logit_change_max_abs",
                            "native_logit_change_l2",
                        ),
                        0.0,
                    ),
                }
            ],
        )
        if case["split"] == "exposed" and row["renderer"] == "raw":
            previous = old_index[row["case_id"], condition, row["regime"]]
            row.update(
                {
                    k: previous[k]
                    for k in (
                        "prompt_ids",
                        "generated_ids",
                        "answer",
                        "finish_reason",
                        "token_trace",
                        "token_count",
                    )
                }
            )
            _update_answer(row, row["answer"], row["finish_reason"])
    generation_lookup = {
        (r["case_id"], r["renderer"], r["information"], r["regime"]): r for r in generated
    }
    receipts = []
    for case, renderer, regime in itertools.product(cases, verify.RENDERERS, verify.REGIMES):
        group = [
            generation_lookup[case["case_id"], renderer, info, regime["id"]]
            for info in verify.INFORMATION
        ]
        counts = [
            len(
                {
                    tuple(r["prompt_ids"] + r["generated_ids"][:step])
                    for r in group
                    if r["token_count"] > step
                }
            )
            for step in range(max(r["token_count"] for r in group))
        ]
        receipts.append(
            {
                "case_id": case["case_id"],
                "renderer": renderer,
                "regime": regime["id"],
                "decoder_calls": sum(counts),
                "shared_historical_native_checks": sum(counts),
                "maximum_concurrent_prefixes": max(counts),
                "zero_full_logit_exact_checks": 0,
                "zero_full_logit_exact_checks_by_condition": {},
                "zero_pairs": [],
                "base_zero_token_ids_exact": True,
                "persistent_prefix_cache_entries": 0,
                "kv_cache_used": False,
                "readout_contract": "shared_native_full_sequence_full_vocabulary",
                "logit_reference": "base_at_same_current_prefix",
                "reader_span_owner": "backend_bound_original_prompt",
            }
        )
    summary = verify.summarize(cases, choices, generated, plan)
    anchor = verify.load(ROOT / "configs/v14/MISTRAL_PROMPT_GATE_PLAN.json")["model"]
    tokenizer_names = {
        "config.json",
        "generation_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer.model.v3",
        "tokenizer_config.json",
    }
    started = {
        "source_commit": "a" * 40,
        "plan": plan,
        "runtime": old_start["runtime"],
        "admission": old_start["admission"],
        "source_hashes": {
            name: verify.digest(ROOT / name)
            for name in set(old_start["source_hashes"]) | verify.SOURCE_ADDITIONS
        },
        "tokenizer_identity": {
            "snapshot": anchor["snapshot"],
            "chat_template_sha256": "a" * 64,
            "files": [r for r in anchor["snapshot_content_anchor"] if r["path"] in tokenizer_names],
        },
    }
    report = {
        "status": "COMPLETED_BASE_ELICITATION_ASSAY",
        "optimizer_steps": 0,
        "workspace_loaded": False,
        "base_state_sha256_before": verify.BASE_HASH,
        "base_state_sha256_after": verify.BASE_HASH,
        "base_unchanged": True,
        "source_unchanged": True,
        "tokenizer_identity_unchanged": True,
        "unique_prefixes": 144,
        "generation_sequences": 288,
        "raw_replay_exact_sequences": 16,
        "eos_token_ids": [2],
        "summary": summary,
        "elapsed_seconds": 1.0,
        **{
            k: old_report[k]
            for k in (
                "peak_cuda_allocated_bytes",
                "peak_cuda_reserved_bytes",
                "sampled_own_process_peak_bytes",
                "minimum_sampled_device_free_bytes",
            )
        },
        **plan["claims"],
    }
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, value in {
        "STARTED.json": started,
        "CASES.json": cases,
        "RENDERINGS.json": renderings,
        "CHOICES.json": choices,
        "REPORT.json": report,
        "GENERATION.json": {
            "rows": generated,
            "receipts": receipts,
            "summary": summary,
            "eos_token_ids": [2],
        },
    }.items():
        verify.write_new(raw / name, value)
    (raw / "RESOURCES.jsonl").write_bytes((old / "RESOURCES.jsonl").read_bytes())
    return tmp_path


def test_complete_portable_bundle_roundtrip_and_exclusive_index(bundle):
    result = verify.verify_bundle(bundle, write_index=True)
    assert result["status"] == "VERIFIED_RECEIPTS"
    assert result["generation_accounting"]["raw_replay_exact_sequences"] == 16
    assert result["summary"]["primary_expression_gate"] == "PASS"
    assert result["full_logits_recomputed"] is False
    assert verify.verify_bundle(bundle) == result
    with pytest.raises(ValueError, match="index collision"):
        verify.verify_bundle(bundle, write_index=True)


@pytest.mark.parametrize(
    "name,mutate",
    [
        ("STARTED.json", lambda v: v["source_hashes"].pop(verify.PLAN_PATH)),
        ("STARTED.json", lambda v: v["tokenizer_identity"].update(chat_template_sha256="b" * 64)),
        ("CASES.json", lambda v: v[4].update(target_label=0)),
        ("RENDERINGS.json", lambda v: v[0].update(user_content="label leaked")),
        ("RENDERINGS.json", lambda v: v[0]["span"].update(token_indices=[])),
        ("CHOICES.json", lambda v: v[0].update(ordinary_shared_full_logits_exact=False)),
        ("CHOICES.json", lambda v: v[0].update(candidate_probabilities=[0.6, 0.7])),
        (
            "GENERATION.json",
            lambda v: v["rows"][-1]["token_trace"][0]["uniform"].update(value=0.999),
        ),
        ("GENERATION.json", lambda v: v["rows"][-1]["token_trace"][0].update(delta_l2=0.1)),
        ("GENERATION.json", lambda v: v["rows"][-1].update(finish_reason="length")),
        ("GENERATION.json", lambda v: v["receipts"][-1].update(decoder_calls=999)),
        ("GENERATION.json", lambda v: v["receipts"][-1].update(kv_cache_used=True)),
        ("GENERATION.json", lambda v: v["rows"][0].update(answer="changed historical output")),
        ("REPORT.json", lambda v: v.update(workspace_loaded=True)),
        ("REPORT.json", lambda v: v.update(training_performed=True)),
        ("REPORT.json", lambda v: v.update(raw_replay_exact_sequences=15)),
        ("REPORT.json", lambda v: v.update(peak_cuda_allocated_bytes=1)),
    ],
)
def test_complete_bundle_mutations_fail_closed(bundle, name, mutate):
    path = bundle / "raw" / name
    data = verify.load(path)
    mutate(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify.verify_contracts(bundle)


def test_answer_bank_contains_all_records_without_activating_model_markdown(bundle):
    rows = verify.load(bundle / "raw/GENERATION.json")["rows"]
    rows[0]["answer"] = "# malicious heading\n<script>bad()</script>"
    text = verify.answer_bank(verify.load(bundle / "raw/CASES.json"), rows)
    assert sum(line.startswith("### ") and " / " in line for line in text.splitlines()) == 288
    assert "```\n# malicious heading\n<script>bad()</script>\n```" in text
