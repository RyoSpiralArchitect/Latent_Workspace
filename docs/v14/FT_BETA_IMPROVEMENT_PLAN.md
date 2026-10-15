# FT-beta for Mistral-7B-Instruct: preserve, strengthen, add

2026-10-09 · **PROPOSED / NOT_TRAINED / NOT_RELEASE_QUALIFIED**.

The goal is to retain useful behavior, extend it to new tasks, fill missing
capabilities, and **not fall below the pinned base on correctness benchmarks**.
This is a proposed exit contract, not an assertion that V14 has met it. The
[three-judge synthesis](FT_BETA_JUDGE_SYNTHESIS.md) identifies a development
target; it does not select a winning learner. Publication/review of this plan
does not authorize or record a new training run.

## 1. Scope and present gap

The target is `mistralai/Mistral-7B-Instruct-v0.3`, revision
`c170c708c41dac9275d15a8fff4eca08d52bab71`, with a functional workspace and its
native Mistral readout. Mistral Large 4 is a **judge**, not this target model.
Current precision/centering experiments freeze the base and train a compact
4,200,192-parameter bridge/writer; they are not full-backbone fine-tuning.
Keep that bounded scope for the next diagnostic. A later full-base update needs
its own preservation, optimizer, resource, and retention contract.

The [precision pilot](../../provenance/pilots/v14_precision_bridge_20261009/README.md)
reported native semantic accuracy 487/1,024 versus original query-only
516/1,024, with 0/128 correct affected flips. These are correlated rows from
64 worlds, and the information paths differ; this is not a fair equal-information
capability comparison. It nevertheless supplies no base-floor qualification.
The [centering comparison](../../provenance/pilots/v14_mech_repair_20261009/README.md)
reduced one unrelated-gap disturbance but retained almost query-insensitive bias;
its 1/128 correct flip was the same legacy example, not a new improvement.

The positive development target is narrower: preserve cautious causal language,
make useful verification proposals more concrete, and meet explicit constraints.
In the selected causal/sample211 pair, 80→54 words crossed the 60-word bound and
all three judge settings stably preferred workspace. It still omitted an explicit
contemporaneous no-checklist group and randomization. Do not equate a more useful
proposal with demonstrated causal identification, or preserve its omissions.

## 2. What to keep, strengthen, and add

| Track | Evidence motivating it | Decision | Evidence required before promotion |
|---|---|---|---|
| **Keep: intervention substrate** | Audited original-base identity; native/zero parity; checkpoint provenance | Preserve the independently loaded base, query-independent writer, bounded residual, architecture-owned arithmetic, and raw negative results | Rerun identity and parity for each new candidate/runtime; an old receipt is not a new qualification |
| **Keep: useful behavior as a sentinel** | Shared causal/sample211 preference and mechanically verified brevity | Keep concise, calibrated, measurement-aware verification behavior as a development sentinel, not a training target copied from the bank | Replication on fresh tasks, blind human review, and grounded/constraint checks |
| **Strengthen: content selectivity** | Near query-insensitive reader bias and weak donor direction | Learn when and how authoritative memory should change an answer, not simply a larger residual | Reciprocal-query direction, affected/unaffected separation, and matched negative controls |
| **Strengthen: explanation quality** | OpenAI rewards concrete proposals; Gemini/Mistral often emphasize shared failures or constraints | Separate correctness, grounding, usefulness, calibration, and instruction compliance | Check each dimension directly where possible; do not turn a preferred but incomplete design into gold |
| **Strengthen: preservation without freezing errors** | Selected preferences are not a correctness battery; current benchmark qualification is absent | Protect correct base behavior while allowing verified improvements to wrong answers | Paired regression/improvement ledger and the zero-tolerance base-floor contract below |
| **Add: reliable evaluation primitives** | All three judges can miscount; Mistral quotes and scores also vary | Deterministic constraints, verifiable evidence spans, score/rationale/order diagnostics, and independent human sheets | New preregistered evaluator method; current votes stay unchanged |
| **Add: causal and generalization controls** | Old unrelated examples share task schema; twins may also change serialization | Fresh task/world holdouts, same/different-schema negatives, and same-world reserialization | Distinguish fact use, schema transfer, and generic perturbation; leave unresolved confounding explicit |

Judge-specific observations guide which failure modes to test, not three
statistically independent votes for an architecture. No all-closed gate that
copies base is a usefulness success; no always-on bias is a content-use success.

## 3. Smallest implementation sequence

### G0 — re-establish identity and native execution

Freeze model/tokenizer/source/bridge hashes, renderer, attention backend, dtype,
head geometry, mask/position policy, random-number coupling, and scoring.
Compare an independently loaded ordinary base with the native adapter; then
write memory and zero its **written slots**, rather than replacing source text
with an empty string. Require the declared native logit/token parity checks.
Stop on missing identity or parity receipts. Do not tune gain or relax tolerances
to get through this gate.

Use the existing [ordinary-base gate](../../scripts/run_v14_answer_bank.py),
[native full readout](../../src/latent_workspace_ft_v10/answer_bank_generation.py),
and [model boundary contract](../V14_PORTABLE_BOUNDARIES.md). For Mistral-only
FT-beta, preserve the verified binding first; do not make a broad multi-model
abstraction rewrite a prerequisite. A descriptor alone is not numerical parity.

The [CPU portability addendum](../../provenance/pilots/v14_mech_repair_20261009/NUMERICAL_ADDENDUM.md)
also remains open: the old manual projected-V toy diagnostic had 74 passes/1
failure on Furnace versus 75 local passes. Its exact-zero expectation is distinct
from production-reader reconstruction. A future operation-derived numerical
contract must address that distinction and both assertions, retaining the old
failure. This document neither changes that test nor claims the remote suite passed.

### G1 — no-training legacy memory controls

Use all 48 legacy case-regimes as an explicitly exposed development bank: all
10 changed pairs and the 38 unchanged pairs. Do not select only the causal wins.
Separately freeze new tasks/worlds and paraphrase families before generation;
do not select their inclusion according to whether output changes.

Compare direct base, legacy intact, written-zero, authoritative twin with
affected/unaffected queries, different-fact/same-schema memory,
different-fact/different-schema memory, seeded norm-matched random slots, and
same-world reserialization. Preserve prompt facts when they are authoritative;
following a conflicting memory is then a failure, not a successful donor flip.

The [existing random control](../../scripts/v14_precision_bridge_eval.py) matches
global memory L2. Per-active-slot post-write norm matching is a **proposal**, not
already implemented. Neither matches residual/logit amplitude or covariance by
construction. Observe these separately; unresolved amplitude confounding stays
`UNRESOLVED`. Freeze any additional amplitude control before observing its result.

Measure identical-prefix/full-vocabulary changes and content direction before
interpreting free-generation divergence. The current history harness recomputes
prefixes; do not relabel it as a KV-cache intervention.

Exit: useful changes beyond the selected example, preserved protected behavior,
and distinguishable fact/schema effects. If unrelated/random perturbations explain
the same changes, retain that alternative and return to reader diagnostics.
Missing controls or ambiguous effects do not qualify the learner.

### G2 — diagnose the existing objective before adding another loss

The [current objective](../../scripts/run_v14_precision_bridge.py) already has
paired CE, donor hinge, unaffected stability, unrelated two-candidate gap, and
residual regularization. Its supervision uses two FP32 candidate-head rows;
it is not full-vocabulary native preservation. Merely renaming another term
"contrastive" or "control" does not resolve the observed failure.

On train-only worlds, batch reciprocal queries and original/twin together.
Record each loss term's writer/Q/K/V/up gradient norm, inner product/cosine,
upstream reachability, and resulting donor-margin changes. Use the production
[reader panel](../../src/latent_workspace_ft_v10/bridge_reader_panel.py), not an
old projected-V assumption. Cancellation is a diagnostic, not proof of causation.

Then compare exactly one query representation: the existing answer-position
query versus fixed pooling of an inference-available user-query token span.
No gold entity-role annotation or answer may enter forward inputs. Match
initialization, data, optimization budget and parameterization where possible;
declare any unmatched factor. Require both reciprocal directions and
affected/unaffected separation on a tiny train-only overfit task before scaling.
Overfit success establishes feasibility, not generalization.

### G3 — one conditional learner change, then locked evaluation

Only after the diagnostics, select one hypothesis and freeze a matched experiment:

- Selective intervention gate if relevance is the missing distinction. Test both
  no-op and always-open degeneracies and step-zero upstream gradients.
- Full-vocabulary preservation on prespecified unnecessary-intervention contexts
  if two-choice preservation is inadequate. Use the same prefix and a frozen base
  distribution; do not globally penalize useful fact/schema-dependent changes.
- Grounded-response supervision if content direction exists but explanation or
  constraint realization fails. Use independently constructed, checked train
  targets, not the selected answer-bank or judge-preferred text.

Keep unchanged-learner and task-only controls. Do not bundle query pooling, a gate,
and a new loss into one first cell. Preserve the latest two checkpoints per
condition with behavior/metric/hash records before any separately authorized pruning.
Neither a gain sweep nor a longer run is the default remedy for almost cap-sized,
poorly directed residuals.

## 4. The pinned-base correctness floor

Two different claims must pass separately. The default tolerance is **delta = 0**;
an allowed loss is not silently introduced under the name "noninferiority".

### A. Exact statement about a fixed benchmark

For every preregistered primary benchmark and protected slice, require
`candidate_score - pinned_base_score >= 0`. Declare aggregation/weights before
scoring; gains elsewhere cannot hide a primary-slice failure. Keep any predeclared
must-preserve sentinels as a separate hard gate.

For binary correctness, publish both-correct, both-wrong,
base-correct→candidate-wrong regressions, and base-wrong→candidate-correct
improvements. Net score alone can conceal harmful substitutions. Do not freeze
known base mistakes in order to maximize response identity.

Match task information, prompt/template, decoding and token budget, scorer, and
runtime policy. A query-only base versus a fact-bearing workspace measures added
information access, not equal-information capability. Include the pinned base
with the same authoritative facts inline as an information-access baseline,
while acknowledging its different token path. Ordinary correctness benchmarks
must give both systems the same task information.

### B. Evidence beyond that fixed corpus

For a population noninferiority claim, require a preregistered one-sided paired,
cluster-aware lower confidence bound for `candidate - base` at least `-delta`.
Here **delta = 0** unless the user separately agrees to a positive allowance.
A positive margin must never be chosen from the exposed V14 scores.
An underpowered result is `INCONCLUSIVE`, not a pass. "No significant difference"
and identical outputs on a small finite bank do not prove noninferiority.

Before execution, freeze benchmark versions/splits, protected slices, sample size,
confidence level, interval method, clustering, multiplicity, missingness treatment,
and the locked final candidate or sequential-testing rule. Choose sample size
using a separate pilot's paired discordance/cluster variability and planned
power/precision, not the count of decoding seeds, reverse queries, AB/BA orders,
or judge calls. Do not use a degenerate small-sample bootstrap as proof of equality.

Report all planned denominators. A model refusal/truncation/invalid answer remains
an outcome under the frozen scorer; infrastructure missingness blocks the claim
or receives prespecified conservative sensitivity bounds, never silent exclusion.
Train, development, and final holdout split by task/world/paraphrase family.
Already inspected 48-case and 64-world panels cannot become unseen again.

The historical [V11 helper](../../scripts/finalize_v11_f1_o0_refinement.py)
`paired_noninferiority()` compares point metrics with frozen margins. It does not
compute this uncertainty contract and must not be reused as proof of the FT-beta floor.
The new benchmark manifest and statistical implementation are **not yet fixed or
implemented**; this plan is not an executable qualification receipt.

## 5. FT-beta exit and review boundary

FT-beta qualification requires all of the following, not a compensating average:

1. Pinned identity, native arithmetic, zero-path, runtime, and retention receipts.
2. Both the declared fixed-corpus correctness floor and the preregistered
   generalization/noninferiority gate, with no protected-slice failure hidden.
3. Useful, grounded changes on fresh tasks with content/schema controls; neither
   copying base everywhere nor a generic perturbation is sufficient.
4. Deterministic constraint checks plus blind qualitative human evaluation,
   separated from judge preferences and their invalid/order-conflicting cases.
5. Reproducible source, complete planned denominators, failures, and bounded claims.

The next implementation unit is **G0/G1 plus the correctness-battery contract**,
not new preference training. Evaluator improvements (constraint facts, span IDs,
separate calibration/compliance rubrics) require a new method with symmetric inputs
for all judges; never repair current votes retrospectively. Human evaluation is
still `PENDING`; it is not replaced by three model settings.

This PR may close the reporting/design chapter after review. It does not close
the FT-beta qualification gap. Current status remains `winner: none`,
`semantic_promotion: false`, and `non_regression: NOT_ESTABLISHED`.
