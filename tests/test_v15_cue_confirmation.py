"""No-download CPU tests for prospective cue confirmation and closed gates."""

import copy
import hashlib
import inspect
import itertools
import json
from collections import Counter, defaultdict

import pytest
import run_v15_cue_confirmation as runner
import v15_cue_contract as contract
import verify_v15_cue_confirmation as verifier
from test_run_v15_elicitation import TinyBase
from test_v15_completion_mass import alias
from test_v15_elicitation_inputs import CONTEXT, QUERY, ToyTokenizer
from v13_task_fixture import _parse_context, _parse_query, symbolic_oracle

from latent_workspace_ft_v10.answer_bank_generation import matched_uniform
from latent_workspace_ft_v10.v15_readout import NativeWorkspaceReadout


class Tokenizer(ToyTokenizer):
    markers = {**ToyTokenizer.markers, " No": 10003, " Yes": 10004}


@pytest.fixture(scope="module")
def corpus():
    return contract.make_cases()


def test_frozen_plan_corpus_and_predecessor():
    plan, _, actual = runner.validate()
    assert plan["generation_sequences"] == 512
    assert plan["primary"] == {"renderer": "native_chat", "cue": "absent", "information": "inline"}
    assert actual == contract.make_cases()


@pytest.mark.parametrize(
    "key,value", [("max_new_tokens", 128), ("optimizer_steps", 1), ("families", 8), ("claims", {})]
)
def test_plan_mutation_fails_closed(tmp_path, monkeypatch, key, value):
    plan = json.loads(runner.PLAN.read_text())
    plan[key] = value
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(runner, "PLAN", path)
    with pytest.raises(ValueError, match="plan changed"):
        runner.validate()


def test_fresh_corpus_is_balanced_graph_derived_and_disjoint(corpus):
    cases = corpus["cases"]
    assert len(cases) == len({c["case_id"] for c in cases}) == 64
    assert set(Counter((c["view"], c["wording"], c["target_label"]) for c in cases).values()) == {8}
    old = contract.old.make_cases()
    excluded = contract.old.known_orders() | {
        tuple(_parse_context(c["context"])[0]) for c in old if c["view"] == "full_chain"
    }
    old_pairs = {
        frozenset(_parse_query(c["query"])) for c in old if c["view"] in ("atomic", "historical")
    }
    groups, pairs = defaultdict(list), set()
    for case in cases:
        assert case["target_label"] == symbolic_oracle(case["context"], case["query"])
        groups[case["family_id"], case["view"]].append(case)
    for (_, view), pair in groups.items():
        a, b = pair
        assert a["context"] == b["context"] and a["target_label"] + b["target_label"] == 1
        assert _parse_query(a["query"]) == _parse_query(b["query"])[::-1]
        order, edges = _parse_context(a["context"])
        assert len(edges) == (1 if view == "atomic" else 5)
        if view == "full_chain":
            assert tuple(order) not in excluded
        else:
            atom = frozenset(order)
            assert atom not in old_pairs and atom not in pairs
            pairs.add(atom)
    assert len(pairs) == 16


@pytest.mark.parametrize(
    "renderer,cue,info",
    list(itertools.product(contract.RENDERERS, contract.CUES, contract.INFORMATION)),
)
def test_render_changes_only_declared_cue_and_preserves_question(renderer, cue, info):
    row = contract.render_case(
        Tokenizer(), query=QUERY, context=CONTEXT, renderer=renderer, cue=cue, information=info
    )
    assert row["user_content"].endswith(QUERY if cue == "present" else QUERY[:-8])
    assert row["span"]["question"] == QUERY[:-8]
    assert row["span"]["prefix_ids"] == row["prompt_ids"]
    assert len(row["aliases"]) == 4
    assert ("Answer:" in row["user_content"]) == (cue == "present")
    other = contract.user_content(QUERY, CONTEXT, "present", info)
    assert row["user_content"] == (other if cue == "present" else other[:-8])


def test_renderer_does_not_receive_labels_or_family_metadata():
    assert set(inspect.signature(contract.render_case).parameters) == {
        "tokenizer",
        "query",
        "context",
        "renderer",
        "cue",
        "information",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("renderer", "auto"),
        ("cue", "best"),
        ("information", "target"),
        ("query", "bad query"),
        ("context", "bad facts"),
    ],
)
def test_invalid_rendering_fails(key, value):
    kwargs = dict(query=QUERY, context=CONTEXT, renderer="raw", cue="absent", information="inline")
    kwargs[key] = value
    with pytest.raises(ValueError):
        contract.render_case(Tokenizer(), **kwargs)


@pytest.fixture(scope="module")
def panel(corpus):
    plan = json.loads(runner.PLAN.read_text())
    rendered, scores, generations, receipts = [], [], [], []
    for case, renderer, cue, information in itertools.product(
        corpus["cases"], contract.RENDERERS, contract.CUES, contract.INFORMATION
    ):
        row = {
            "case_id": case["case_id"],
            **contract.render_case(
                Tokenizer(),
                query=case["query"],
                context=case["context"],
                renderer=renderer,
                cue=cue,
                information=information,
            ),
        }
        rendered.append(row)
        target = case["target_label"]
        aliases = [
            alias(
                a["target_label"],
                a["token_id"],
                a["suffixes"],
                0.3 if a["target_label"] == target else 0.15,
                0.8,
            )
            for a in row["aliases"]
        ]
        lower = [next(a for a in aliases if suffix in a["suffixes"]) for suffix in (" no", " yes")]
        native = [a["first_log_probability"] for a in lower]
        scores.append(
            {
                **{k: case[k] for k in contract.META},
                "renderer": renderer,
                "cue": cue,
                "information": information,
                "old_lowercase_native": {
                    "scores": native,
                    "gap": native[1] - native[0],
                    "prediction": target,
                },
                "aliases": aliases,
                "candidate_ids": row["candidate_ids"],
                "candidate_probabilities": [a["first_probability"] for a in lower],
                "top1_token_id": row["candidate_ids"][target],
                "top1_probability": lower[target]["first_probability"],
                "ordinary_shared_full_logits_exact": True,
                "prefix_ids": row["prompt_ids"],
                "prefix_sha256": runner.completion.prefix_digest(row["prompt_ids"]),
            }
        )
        condition = "base_inline" if information == "inline" else "base"
        ids = [row["candidate_ids"][target], 2]
        trace = [
            {
                "step": step,
                "token_id": token,
                "uniform": matched_uniform(case["case_id"], 0, step),
                "sampling_probability": 1.0,
                "chosen_token_native_probability": 0.3,
                "same_prefix_base_chosen_token_native_probability": 0.3,
                "chosen_native_logit": 1.0,
                "same_prefix_base_native_logit": 1.0,
                "native_top1_token_id": token,
                "same_prefix_base_native_top1_token_id": token,
                "native_top1_changed": False,
                **{
                    k: 0.0
                    for k in (
                        "delta_l2",
                        "native_applied_delta_l2",
                        "native_applied_fraction",
                        "native_logit_change_max_abs",
                        "native_logit_change_l2",
                    )
                },
            }
            for step, token in enumerate(ids)
        ]
        generations.append(
            {
                **{k: case[k] for k in contract.META},
                "id": f"{case['case_id']}__greedy__{condition}__{renderer}__{cue}",
                "renderer": renderer,
                "cue": cue,
                "information": information,
                "condition": condition,
                "regime": "greedy",
                "regime_parameters": contract.REGIME,
                "prompt_ids": row["prompt_ids"],
                "generated_ids": ids,
                "token_trace": trace,
                "token_count": 2,
                "answer": ("no", "yes")[target],
                "finish_reason": "eos",
                "parsed_answer": target,
                "valid_eos": True,
                "strict_correct": True,
                "lowercase_compliant": True,
            }
        )
    for case, renderer, cue in itertools.product(
        corpus["cases"], contract.RENDERERS, contract.CUES
    ):
        receipts.append(
            {
                "case_id": case["case_id"],
                "renderer": renderer,
                "cue": cue,
                "decoder_calls": 4,
                "shared_historical_native_checks": 4,
                "maximum_concurrent_prefixes": 2,
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
    return plan, rendered, scores, {"rows": generations, "receipts": receipts, "eos_token_ids": [2]}


def test_full_grid_summary_and_scalar_token_verification(corpus, panel):
    plan, rendered, scores, generated = panel
    actual = contract.summarize(corpus["cases"], scores, generated["rows"], plan)
    assert actual["primary_expression_gate"] == "PASS"
    assert all(g["total"] == g["valid_eos"] == g["correct"] == 64 for g in actual["gates"])
    index = verifier.verify_renderings(
        rendered, corpus["cases"], hashlib.sha256(Tokenizer.chat_template.encode()).hexdigest()
    )
    assert verifier.verify_scores(scores, index, plan["numerics"])["alias_forwards"] == 2048
    assert verifier.verify_generation(generated, corpus["cases"], index) == 1024

    def check_integer_tree(value):
        if isinstance(value, dict):
            for v in value.values():
                check_integer_tree(v)
        elif isinstance(value, list):
            for v in value:
                check_integer_tree(v)
        else:
            assert not isinstance(value, float)

    check_integer_tree(actual)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "metadata",
        "parser",
        "valid",
        "correct",
        "lowercase",
        "cue",
        "probability",
    ],
)
def test_summary_rejects_corrupt_records(corpus, panel, mutation):
    plan, _, scores, generated = copy.deepcopy(panel)
    rows = generated["rows"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = rows[0]
    elif mutation == "metadata":
        rows[0]["target_label"] ^= 1
    elif mutation == "parser":
        rows[0]["answer"] += " explanation"
    elif mutation == "valid":
        rows[0]["valid_eos"] = False
    elif mutation == "correct":
        rows[0]["strict_correct"] = False
    elif mutation == "lowercase":
        rows[0]["lowercase_compliant"] = False
    elif mutation == "cue":
        rows[0]["cue"] = "chosen_after_result"
    else:
        scores[0]["aliases"][0]["complete_probability"] = 0.999
    with pytest.raises(ValueError):
        contract.summarize(corpus["cases"], scores, rows, plan)


def test_failed_primary_is_not_replaced_by_passing_comparator(corpus, panel):
    plan, _, scores, generated = copy.deepcopy(panel)
    for row in generated["rows"]:
        if (row["renderer"], row["cue"], row["information"]) == (
            "native_chat",
            "absent",
            "inline",
        ) and row["target_label"] == 0:
            row.update(answer="yes", parsed_answer=1, strict_correct=False)
    result = contract.summarize(corpus["cases"], scores, generated["rows"], plan)
    assert (
        result["primary_expression_gate"] == "FAIL" and not result["method_selected_after_results"]
    )
    assert sum(g["status"] == "PASS" for g in result["gates"]) == 3


@pytest.mark.parametrize(
    "mutation", ["prefix", "eos", "top1", "uniform", "delta", "receipt", "cache", "id"]
)
def test_generation_corruption_is_rejected(corpus, panel, mutation):
    _, rendered, _, generated = copy.deepcopy(panel)
    row = generated["rows"][0]
    if mutation == "prefix":
        row["prompt_ids"] = list(row["prompt_ids"])
        row["prompt_ids"][0] += 100
    elif mutation == "eos":
        row["generated_ids"][0] = 2
    elif mutation == "top1":
        row["token_trace"][0]["native_top1_token_id"] += 1
    elif mutation == "uniform":
        row["token_trace"][0]["uniform"]["value"] = 0.5
    elif mutation == "delta":
        row["token_trace"][0]["delta_l2"] = 1e-20
    elif mutation == "receipt":
        generated["receipts"][0]["decoder_calls"] += 1
    elif mutation == "cache":
        generated["receipts"][0]["kv_cache_used"] = True
    else:
        row["id"] += "changed"
    with pytest.raises(ValueError):
        verifier.verify_generation(
            generated, corpus["cases"], {tuple(r[k] for k in contract.KEYS): r for r in rendered}
        )


def test_native_scorer_uses_full_alias_prefix_and_never_label():
    base = TinyBase()
    case = {
        "case_id": "toy",
        "family_id": "family",
        "view": "atomic",
        "wording": "ranked_above",
        "split": "confirmation",
        "target_label": 1,
    }
    row = {
        "case_id": "toy",
        "renderer": "raw",
        "cue": "absent",
        "information": "inline",
        "prompt_ids": [0, 1],
        "candidate_ids": [1, 2],
        "aliases": [
            {"target_label": label, "token_id": token, "suffixes": suffixes}
            for label, token, suffixes in ((0, 1, [" no", " No"]), (1, 2, [" yes", " Yes"]))
        ],
    }
    result, checks = runner.score(
        base, NativeWorkspaceReadout(base.lm_head), [row], [case], lambda _: None
    )
    assert checks == 3 and result[0]["old_lowercase_native"] == {
        "scores": [1.0, 2.0],
        "gap": 1.0,
        "prediction": 1,
    }
    assert [call[0].tolist() for call in base.calls] == [
        [[0, 1]],
        [[0, 1]],
        [[0, 1, 1]],
        [[0, 1, 2]],
    ]
    case["target_label"] = 0
    second, _ = runner.score(
        base, NativeWorkspaceReadout(base.lm_head), [row], [case], lambda _: None
    )
    assert result[0]["aliases"] == second[0]["aliases"]
    assert all(p.grad is None for p in base.parameters())


def test_answer_bank_preserves_every_answer_and_fences(corpus, panel):
    plan, _, scores, generated = copy.deepcopy(panel)
    summary = contract.summarize(corpus["cases"], scores, generated["rows"], plan)
    generated["rows"][0]["answer"] = "```example```  "
    text = verifier.answer_bank(corpus, generated["rows"], summary)
    assert text.count("### ") == 512
    assert "````text\n```example```  \n````" in text


@pytest.fixture
def bundle(tmp_path, corpus, panel):
    """Synthetic scalar bundle, not a claim of model or tokenizer execution."""
    plan, rendered, scores, generated = copy.deepcopy(panel)
    _, parent, _ = runner.validate()
    old = runner.REPO / plan["predecessor_bundle"] / "raw"
    old_started = verifier.load(old / "STARTED.json")
    old_report = verifier.load(old / "REPORT.json")
    identity = old_started["tokenizer_identity"]
    for row in rendered:
        row["chat_template"]["sha256"] = identity["chat_template_sha256"]
    started = {
        "source_commit": "a" * 40,
        "source_hashes": runner.sources(parent),
        "runtime": parent["expected_runtime"],
        "plan": plan,
        "plan_sha256": runner.PLAN_SHA256,
        "admission": old_started["admission"],
        "tokenizer_identity": identity,
    }
    report = {
        "status": "COMPLETED_CUE_CONFIRMATION",
        "optimizer_steps": 0,
        "workspace_loaded": False,
        "base_sha256_before": verifier.BASE_HASH,
        "base_sha256_after": verifier.BASE_HASH,
        "source_unchanged": True,
        "tokenizer_identity_unchanged": True,
        "prefixes": 512,
        "generation_sequences": 512,
        "initial_native_parity_checks": 512,
        "scoring_readout_parity_checks": 2560,
        "generation_readout_parity_checks": 1024,
        "summary": contract.summarize(corpus["cases"], scores, generated["rows"], plan),
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
        "REPORT.json": report,
        "CORPUS.json": corpus,
        "RENDERINGS.json": rendered,
        "SCORES.json": scores,
        "GENERATION.json": generated,
    }.items():
        verifier.write_new(raw / name, value)
    (raw / "RESOURCES.jsonl").write_bytes((old / "RESOURCES.jsonl").read_bytes())
    return tmp_path


def test_full_bundle_index_roundtrip(bundle):
    actual = verifier.verify_bundle(bundle, check_index=False)
    verifier.write_new(bundle / "ARTIFACT_INDEX.json", verifier.index_for(bundle))
    assert verifier.verify_bundle(bundle) == actual
    assert actual["status"] == "VERIFIED_RECEIPTS"
    assert actual["summary"]["primary_expression_gate"] == "PASS"
    assert actual["accounting"]["alias_forwards"] == 2048
    assert actual["full_logits_recomputed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("optimizer_steps", 1),
        ("workspace_loaded", True),
        ("base_sha256_after", "0" * 64),
        ("generation_sequences", 511),
        ("source_unchanged", False),
        ("generation_readout_parity_checks", 1),
    ],
)
def test_bundle_report_mutations_fail(bundle, field, value):
    path = bundle / "raw/REPORT.json"
    report = verifier.load(path)
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        verifier.verify_bundle(bundle, check_index=False)


def test_bundle_index_detects_changed_raw_bytes(bundle):
    verifier.write_new(bundle / "ARTIFACT_INDEX.json", verifier.index_for(bundle))
    path = bundle / "raw/REPORT.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="Raw index"):
        verifier.verify_bundle(bundle)
