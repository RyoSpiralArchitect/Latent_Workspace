# V15: connect the learner's readout to native generation

Client date: 2026-10-10. **DIAGNOSTIC / NO NEW TRAINING / NOT RELEASE QUALIFIED**.
This is a prospective protocol and staged design, not an execution receipt.
Execution results belong in a separately sealed provenance bundle.

The objective remains: preserve useful behavior, strengthen it, add missing
capabilities, and do not fall below the pinned base on correctness. V15 starts
by making the path from a learned workspace residual to native logits and
tokens explicit and testable. It does not assume that larger perturbations,
changed text, or repeated judge preferences are improvements.

## 1. Evidence carried forward

The [three-judge synthesis](../v14/FT_BETA_JUDGE_SYNTHESIS.md) and
[FT-beta improvement plan](../v14/FT_BETA_IMPROVEMENT_PLAN.md) remain in force.
Their useful development sentinel is concise, calibrated, measurement-aware
verification behavior. Only one selected case/regime had stable workspace
preference across all three judge settings; that answer still omitted an
explicit contemporaneous untreated group and randomization. These are not
gold training labels or evidence of content causality. Mechanical constraint
checks, blind human review, and a fresh correctness battery remain necessary.

The [learner audit](../../provenance/pilots/ft_beta_learner_audit_20261009/README.md)
identified reciprocal donor-gradient cancellation and a distinction between
the query representation and the original final prediction state. The
[matched question-pooling micro-fit](../../provenance/pilots/ft_beta_query_pool_20261010/README.md)
then exposed two different limitations:

- Both readers reached 25/32 FP32 intact rows; the other seven are unreachable
  under the present residual-norm cap and selected head rows. The old 32/32
  feasibility gate remains failed and is not retrospectively relaxed.
- Reversing the same facts reduced FP32 accuracy to 20/32 or 19/32 and reversed
  all four donor-signed changes. Content and serialization are not yet robustly
  separated. Increasing readout capacity first could amplify this shortcut.

The old generator already adds the residual before the native full head.
The missing integration is not an absent output connection: training used a
two-choice FP32 path, while generation used native postnorm composition and
full-vocabulary logits. Question-span pooling was not wired into free
generation. V15 makes a shared native path available to training code,
evaluation, and generation without rewriting sealed historical implementations.

## 2. Fixed scope of the first V15 assay

- Independently loaded, frozen `mistralai/Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`; original native BF16 CUDA head.
- Retained step-256 `final` and `mean_span` checkpoints from the matched
  micro-fit. No optimizer, additional FT step, cap/gain change, or base update.
  The 4,200,192 bridge/writer parameters and residual-norm cap 1.0 stay fixed.
- First two already exposed training worlds, all eight questions and both
  factual sides. These are development diagnostics, not an unseen holdout.
- Historical symmetric functional rendering is unchanged (`use_chat_template:
  false`). Results concern this functional probe, not general Instruct/chat
  quality. A prompt/template change would be a separate experiment.
- Same original final normalized state anchors base readout for both readers.
  Pooling affects only the reader query. During continuation, mean pooling
  remains bound to the original question-token positions; the final reader
  queries the current final state. No labels or entity-role oracle enter either
  forward path.
- Mean reduction remains CPU FP32, matching retained checkpoint training. During
  generation the bound original-prefix states are transferred for that reduction;
  moving the mean to CUDA would be a separate numerical intervention. No cached
  continuous question state is substituted across generation steps.
- No new paid judges, preference training, broad search, weight deletion, or
  other-job intervention. Retained weights and sealed evidence remain intact.

### Resource contract

On Furnace, recheck current clients and require at least 20 GiB free before
model allocation. Cap this process's Torch allocator at 18 GiB and abort its
own work if sampled device free memory falls below 4 GiB. CUDA context and
other non-Torch allocations are outside the allocator cap. Record allocated,
reserved, and sampled process/device memory separately. Admission is not a
reservation: another job can grow between observations. Never stop, change,
or reprioritize that job to make this assay fit.

## 3. Shared native readout and transport receipts

The shared interface owns the architecture-dependent operation:

`original normalized sequence + final-position FP32 residual -> native cast -> full-sequence/full-vocabulary head`.

Do not substitute a last-row-only matrix multiply for the native full-sequence
geometry. Retain the separate two-choice FP32 readout as a diagnostic, not as
the claimed native training/generation path. Avoid an unnecessary broad
architecture rewrite; each future model binding requires its own parity test.

Before interpreting any candidate result, require:

1. Pinned source, model, tokenizer, runtime, renderer, checkpoint, and data
   identities. Base and bridge state hashes are unchanged after the assay.
2. Ordinary base versus split/native adapter parity on declared original
   prefixes. Shared readout versus historical native implementation parity
   uses identical sequence geometry, not a relaxed tolerance after failure.
3. Memory is written and then zeroed; zero is not an empty-text shortcut.
   Written-zero native logits equal the corresponding base logits exactly.
4. On a loaded nonzero bridge, a loss constructed from the shared native
   scores has finite, nonzero bridge gradients, with no optimizer update and
   no backbone gradients. Record the loss, selected rows, group norms, and
   unchanged-state evidence. This demonstrates a connected differentiable
   path only: BF16 cast backward is a surrogate for the discontinuous rounded
   forward map. It does not show that a finite optimizer step changes native
   logits or improves generation.

For identical prefixes, record full-vocabulary logit change, base-to-candidate
KL, total variation, base/candidate top tokens and their probabilities, native
ties, and donor-signed two-choice margins. Compute probability diagnostics in
a declared stable higher precision and do not confuse a top-1 probability
change with semantic direction. Preserve exact-zero cases and denominators.
Native versus FP32 changes composition and head arithmetic together; it is
not a whole-model precision experiment.

## 4. No-training content × serialization crossover

For every world/query and both factual sides, encode three orders:

- Original historical fact serialization.
- Label-independent canonical lexicographic fact-sentence order.
- Reversal of that canonical order.

The fact multiset must be identical within a factual side. No sorting key may
use the answer, affected flag, rank label, or a model score. Preserve text and
token receipts so sentence preservation and ordering can be checked.

Compute the donor content contrast separately within each matched order:
`margin(twin, order) - margin(intact, order)`, signed toward the donor answer.
Compute serialization effects separately within each fixed factual side.
Do not call an original-versus-twin contrast with unmatched order a pure
content effect. Report reciprocal questions individually; averaging an
opposite-sign pair can hide the failure that motivated the assay.

Keep written-zero, fixed carrier, seeded global-raw-memory-L2-matched random,
different-fact/same-schema, and different-fact/different-schema controls.
Memory norm matching is not residual/logit amplitude matching, and schema
controls are not a perfectly orthogonal factorial design. Measure remaining
amplitude confounding rather than describing these controls as equivalent.

Report the four unique affected world/query pairs and twelve unaffected pairs
separately; the 32 side/query rows are correlated observations from two worlds.
Native candidate-score ties remain ties, not correct predictions. Retain the
cap-reachability diagnostic and the impossible rows. There is no new 32/32
pass gate, pooling winner, or semantic-promotion decision from this assay.

## 5. Bounded functional generation tracing

This stage is a narrow amendment to the earlier ordering in which free
generation followed a safety/base-floor gate: it traces transport on exposed
functional prompts before qualification. It is **not** the fresh qualitative
quality comparison, judge replication, or correctness-floor test.

Use the first two worlds' two reciprocal affected queries, factual side 0:
four prompts × two regimes (greedy and sample211) × eight conditions =
**64 planned sequences**, each capped at 64 new tokens.

Conditions are direct query-only base, base with the same facts inline,
final-intact, final-twin, final-written-zero, mean-intact, mean-twin, and
mean-written-zero. The inline base is an information-access reference with a
different token path, not native-logit parity's identical-prefix reference.
In these query-only workspace lanes, memory is authoritative. Future cases
with visible authoritative facts must not count conflicting-memory obedience
as a correct donor flip.

Reuse counter-based common uniform numbers for matched sampling. Record all
generated IDs, seed/uniform coordinates, first divergence, termination cause,
and budget truncation. On each identical prefix, compare logits before token
choice; all written-zero lanes must also match base tokens under the same
decoding rule. Identical sampled output alone is not a logit-parity test.
After text diverges, distinguish comparisons at a shared prefix from those
at different histories. Invalid/unparseable answers and truncation are
outcomes, not silently excluded observations.

Recompute the full prefix at every step. There is no continuous hidden/KV
state transport. Final-norm residuals can change selected tokens and hence
later textual history; equal selected tokens do not carry a residual hidden
state forward. A token bifurcation does not establish KV-mediated semantic
amplification. This generation subset also does not replace the pending
48-case legacy free-text control bank.

## 6. Decision boundary after the assay

If identity, parity, zero, or forward invariants fail, stop interpretation and
repair the measurement path first. If gradients are absent/nonfinite, report
that reachability failure without claiming the bridge cannot learn. Passing
these engineering gates only establishes an auditable shared path.

If content effects remain order-dependent, the next single learner change is
serialization robustness: train-only alternative orders of equivalent worlds,
with consistency across orders **within the same factual side**. Do not force
intact and counterfactual worlds to share an answer or representation. Reserve
unseen orders/worlds for evaluation. Hold initialization, residual budget,
reader, optimization, and readout policy fixed; do not bundle pooling, a new
gate, larger capacity, and several losses into one cell.

Only after that diagnosis should a separate experiment test native-readout
training or a capacity budget. These are not already validated fixes. Native
gradient connectivity is not quantization-aware optimization, and a larger
cap is not justified by unreachable examples alone. Prespecify an independent
safety budget and unchanged-learner/task-only controls before new training.

## 7. Still-open FT-beta qualification work

The [existing correctness-floor contract](../v14/FT_BETA_IMPROVEMENT_PLAN.md#4-the-pinned-base-correctness-floor)
is unchanged: zero allowed score loss on each primary fixed benchmark and
protected slice, plus a separately preregistered cluster-aware uncertainty
contract before any population noninferiority claim. Use equal task information,
paired regression/improvement ledgers, and independent task/world/paraphrase
families. Query-only base versus fact-bearing workspace is not that test.

Before a qualification run, freeze benchmark versions/hashes/splits, locked
candidate, sample size, protected slices, aggregation, scorer and tie/invalid
rules, decoding budget, confidence method/level, clustering, multiplicity,
and infrastructure-missingness handling. The independent manifest and its
statistical implementation are still **PENDING**, not inferred from this assay.

Also pending: all 48 legacy case-regime memory controls; new general-quality
tasks that are not selected for changed output; deterministic constraints;
grounded evidence spans; blind human review; and a new preregistered judge
method if additional judging is used. Never train on the selected preferred
answers or repair old judge votes retrospectively. Preserve useful calibrated
behavior as a sentinel without preserving its known mistakes.

Until those gates pass, retain `winner: none`, `semantic_promotion: false`,
`non_regression: NOT_ESTABLISHED`, and human evaluation `PENDING`.
V15 here names an engineering/diagnostic iteration, not a qualified FT-beta
release or a claim that latent intelligence has been extracted.
