"""Read-only, post-hoc decomposition of already-frozen V24 development receipts.

No model/tokenizer/provider imports, new prompts, checkpoint loads, or raw private
data. Stdout is the complete reproducible JSON analysis; this script writes nothing.
"""

import hashlib
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BUNDLE = ROOT / "provenance/engineering/v24_recruitment_ft04_20261023"
PREP = ROOT / "provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank"
SOURCES = {}


def identify(path):
    raw = path.read_bytes()
    SOURCES[str(path.relative_to(ROOT))] = dict(
        bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
    )
    return raw


def read(path):
    return json.loads(identify(path))


def aggregate(rows):
    assert rows
    tokens = sum(r["tokens"] for r in rows)
    sums = {
        name: math.fsum(r["loss_sums"][name] for r in rows)
        for name in ("inline_base", "inline_step32", "workspace_base", "workspace_step32")
    }
    nll = {name: value / tokens for name, value in sums.items()}
    return dict(
        rows=len(rows),
        source_groups=len({r["group"] for r in rows}),
        tokens=tokens,
        loss_sums=sums,
        token_weighted_nll=nll,
        row_macro_nll={
            name: statistics.mean(r["loss_sums"][name] / r["tokens"] for r in rows) for name in sums
        },
        final_workspace_minus_inline_nll=nll["workspace_step32"] - nll["inline_step32"],
        final_workspace_minus_inline_loss_sum=sums["workspace_step32"] - sums["inline_step32"],
        inline_improved_rows=sum(
            r["loss_sums"]["inline_step32"] < r["loss_sums"]["inline_base"] for r in rows
        ),
        workspace_improved_rows=sum(
            r["loss_sums"]["workspace_step32"] < r["loss_sums"]["workspace_base"] for r in rows
        ),
        final_workspace_lower_rows=sum(
            r["loss_sums"]["workspace_step32"] < r["loss_sums"]["inline_step32"] for r in rows
        ),
        final_inline_lower_rows=sum(
            r["loss_sums"]["workspace_step32"] > r["loss_sums"]["inline_step32"] for r in rows
        ),
        final_tied_rows=sum(
            r["loss_sums"]["workspace_step32"] == r["loss_sums"]["inline_step32"] for r in rows
        ),
    )


def by(rows, key):
    return {
        value: aggregate([r for r in rows if r[key] == value])
        for value in sorted({r[key] for r in rows})
    }


def main():
    observations = {
        f"{role}_{phase.lower()}": read(BUNDLE / "furnace/raw" / role / f"DEV_{phase}.json")
        for role in ("inline", "workspace")
        for phase in ("BASE", "STEP32")
    }
    schedule = read(PREP / "SCHEDULE.json")
    preparation = read(PREP / "SUMMARY.json")
    recipe = read(ROOT / "configs/v24/RECRUITMENT_BANK_01.json")
    plan = read(ROOT / "configs/v24/RECRUITMENT_FT_04.json")
    seal = read(BUNDLE / "furnace/SOURCE_SEAL.json")
    for code_path in (
        "src/latent_workspace/recruitment_bank.py",
        "src/latent_workspace/execution.py",
        "scripts/prepare_v24_recruitment.py",
        "scripts/run_v22_full_ft.py",
    ):
        identify(ROOT / code_path)
        assert SOURCES[code_path]["sha256"] == seal["source_hashes"][code_path]
    assert plan["old_expression_gate"] == "FAIL" and plan["winner"] == "none"
    assert plan["non_regression"] == "NOT_ESTABLISHED"
    reference = observations["inline_base"]["rows"]
    signature = [(r["key"], r["bucket"], r["supervised_tokens"]) for r in reference]
    assert len(reference) == 76 and len({r[0] for r in signature}) == 76
    assert [r[0] for r in signature] == schedule["development"]
    for observation in observations.values():
        assert observation["new_sequences"] == 0
        assert signature == [
            (r["key"], r["bucket"], r["supervised_tokens"]) for r in observation["rows"]
        ]
    rows = []
    for i, (key, bucket, tokens) in enumerate(signature):
        synthetic = key.startswith(("wb02-", "recruit-"))
        group = key.split("/")[0] if synthetic else key
        family = (
            re.sub(r"^(?:wb02|recruit)-\d+-", "", group).rsplit("-dev-", 1)[0]
            if synthetic
            else bucket
        )
        sums = {name: value["rows"][i]["loss_sum"] for name, value in observations.items()}
        assert tokens > 0 and all(math.isfinite(v) and v >= 0 for v in sums.values())
        rows.append(
            dict(
                key=key,
                bucket=bucket,
                group=group,
                family=family,
                mode=key.rsplit("/", 1)[-1] if synthetic else "no_memory",
                synthetic=synthetic,
                tokens=tokens,
                loss_sums=sums,
                final_workspace_minus_inline_nll=(sums["workspace_step32"] - sums["inline_step32"])
                / tokens,
            )
        )
    buckets = by(rows, "bucket")
    for bucket, result in buckets.items():
        for name, observation in observations.items():
            assert result["tokens"] == observation["tokens_by_bucket"][bucket]
            assert math.isclose(
                result["token_weighted_nll"][name],
                observation["mean_nll_by_bucket"][bucket],
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
    training = [key for window in schedule["training"] for key in window]
    assert len(training) == len(set(training)) == 538
    assert set(training).isdisjoint(schedule["development"])
    train_groups = {key.split("/")[0] for key in training if key.startswith(("wb02-", "recruit-"))}
    assert train_groups.isdisjoint(r["group"] for r in rows if r["synthetic"])
    all_rows = aggregate(rows)
    assert all_rows["tokens"] == 5002
    retention = [r for r in rows if not r["synthetic"]]
    synthetic = [r for r in rows if r["synthetic"]]
    reasoning = [r for r in rows if r["bucket"] == "reasoning"]
    world = [r for r in rows if r["bucket"].startswith("world/")]
    affected = [r for r in world if r["mode"] == "affected"]
    families = by(affected, "family")
    overall_gap = all_rows["final_workspace_minus_inline_loss_sum"]
    assert math.isclose(
        sum(b["final_workspace_minus_inline_loss_sum"] for b in buckets.values()),
        overall_gap,
        abs_tol=1e-10,
    )
    leave_out = {
        family: aggregate([r for r in affected if r["family"] != family]) for family in families
    }
    reasoning_gap = aggregate(reasoning)["final_workspace_minus_inline_loss_sum"]
    world_gap = aggregate(affected)["final_workspace_minus_inline_loss_sum"]
    output = dict(
        schema="ltws-v24-ft04-offline-dev-decomposition-v1",
        analysis_kind="POST_HOC_DESCRIPTIVE_FIXED_DEVELOPMENT_ONLY",
        analysis_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_commit=seal.get("git_commit", seal.get("source_commit", seal.get("commit"))),
        inputs=SOURCES,
        no_model_or_tokenizer_load=True,
        new_model_forwards=0,
        new_sequences=0,
        judge_calls=0,
        checkpoint_loads=0,
        confirmation_or_ood_inputs_read=0,
        assertions=dict(
            four_ordered_dev_denominators_match=True,
            original_bucket_recomputation_matches=True,
            training_keys_unique=True,
            training_dev_keys_disjoint=True,
            synthetic_train_dev_groups_disjoint=True,
            additive_gap_decomposition_matches=True,
        ),
        overall=all_rows,
        buckets=buckets,
        no_memory_retention=aggregate(retention),
        synthetic=aggregate(synthetic),
        retention_token_share=sum(r["tokens"] for r in retention) / all_rows["tokens"],
        reasoning_by_family=by(reasoning, "family"),
        reasoning_by_mode=by(reasoning, "mode"),
        world_by_family=by(world, "family"),
        affected_world_by_family=families,
        affected_world_leave_one_family_out=leave_out,
        descriptive_concentration=dict(
            register_trace_fraction_of_net_reasoning_gap=by(reasoning, "family")["register_trace"][
                "final_workspace_minus_inline_loss_sum"
            ]
            / reasoning_gap,
            revision_fraction_of_net_affected_world_gap=families["revision"][
                "final_workspace_minus_inline_loss_sum"
            ]
            / world_gap,
            warning=(
                "Ratios of signed net gaps include cancellation; "
                "not causal attribution or statistical importance."
            ),
        ),
        reasoning_target_format=dict(
            source_based_observation=(
                "Canonical JSON sorts keys, so present-reference fields are answer then steps."
            ),
            teacher_forcing=(
                "Later step tokens are conditioned on earlier gold answer tokens; "
                "whole-output NLL does not measure steps-before-answer generation."
            ),
            per_token_value_vs_syntax_attribution="NOT_RECORDED_IN_THESE_RECEIPTS",
            retrospective_generation_accuracy="NOT_IDENTIFIABLE_FROM_NLL",
        ),
        training=dict(
            updates_per_arm=32,
            rows=len(training),
            unique_rows=len(set(training)),
            source_groups=preparation["training_source_groups"],
            tokens=21112,
            rows_by_role=preparation["training_rows_by_role"],
            tokens_by_role=preparation["training_tokens_by_role"],
            token_shares_by_role={
                k: v / 21112 for k, v in preparation["training_tokens_by_role"].items()
            },
            requested_token_shares=recipe["target_supervised_token_shares"],
            both_scientific_arms_start_from_original_base=True,
        ),
        final_row_differences_sorted_by_absolute_nll=sorted(
            rows, key=lambda r: (-abs(r["final_workspace_minus_inline_nll"]), r["key"])
        ),
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
        limits=[
            "One fixed development source group per synthetic family; "
            "twins and controls are not independent replicates.",
            "Route inputs already differ at base; "
            "training route and inference route are confounded.",
            "Whole-answer teacher-forced NLL includes format/EOS; "
            "no numeric-value/step/answer token attribution is available.",
            "No exact-match, output-length, free-generation, benchmark, judge, "
            "held-out confirmation or causal intervention result.",
            "Post-hoc strata and leave-one-group-out descriptions do not select a winner, "
            "change a threshold, or justify significance.",
        ],
    )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
