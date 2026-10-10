# V15.5: return to the learner, with native answer and completion separated

2026-10-10. **Prospective engineering pilot; not instrument or release qualification.**

Ryō chose to stop diagnostic collection and resume the FT line using the valid
evidence already available. The heartbeat remains paused. Neither the remaining
161 never-dispatched Mistral requests nor the eight ambiguous calls are retried;
OpenAI remains calibration-blocked. The original bundles and FAIL remain intact.

## Evidence used, without turning diagnoses into gold

The [terminal report](../../provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010/README.md)
has 343/512 valid main diagnoses, not 343 independent tasks or human-verified
answers. Repeats and unavailable observations are not added to the training set.
Among 87 diagnosed native-chat inline outputs, the observed strict failures
include 13 contradictions and 13 wrong commitments. The 82 diagnosed inline
length stops belong to raw rendering. This motivates separating answer content
from stopping, not selecting a preferred clause or an EOS-only cure.

The [earlier judge-derived plan](../v14/FT_BETA_IMPROVEMENT_PLAN.md) remains the
behavioral direction: preserve useful calibrated responses, strengthen grounded
fact use, add reliable checks, and eventually meet the independent base floor.
No selected preference, rationale, or generated answer becomes a training target.

## Explicit scope amendment and single-factor comparison

The earlier output instrument has **not** passed. This newly authorized small
learner-path test proceeds as engineering diagnosis on two already-exposed train
worlds, not as the previously gated generalization study or a way around its
failure. Larger FT, independent correctness qualification and fresh qualitative
banks remain separate stages. No prompt search or further judge collection is
required to implement and inspect this bounded update path.

The [frozen plan](../../configs/v15_5/NATIVE_ANSWER_PLAN.json) fixes two arms:

1. Native full-vocabulary answer-token CE.
2. The **same** answer CE, plus coefficient-one EOS CE after the graph-verified
   correct answer. The answer coefficient remains one, not one half.

Both retain the legacy donor-hinge, unaffected-gap, unrelated-gap and residual
penalties, now measured on the shared native head. These are not full-vocabulary
preservation losses. Every nuisance setting is shared: fresh seed-47 bridge,
4,200,192 FP32 trainable parameters, frozen pinned Mistral-7B-Instruct-v0.3,
final-position reader, cap 1.0, native chat with the Answer cue retained, fixed
canonical fact order, full reciprocal batch and eight AdamW updates. Reader,
renderer and readout differ from historical training; neither new arm is a
one-factor reproduction of V14. Only the EOS coefficient differs between them.

Training uses all eight queries in each of two worlds, both factual sides:
32 answer rows per update, four unique affected and twelve unaffected pairs.
Both arms capture and evaluate both possible answer-extension prefixes, even
when EOS has zero loss weight. Answer targets come only from an independently
verified ranking graph and exact tokenizer extensions. No label enters the
writer or answer reader. Teacher-forced answer tokens enter only the explicitly
named completion-training prefix; greedy inference never receives oracle tokens.

Each microbatch is one world/query with both factual sides; reciprocal queries
remain in the full batch, accumulated in fixed world/query order. Reductions
retain their 32/4/12/16/48 denominators; no shorter last window or label-dependent
loss scaling is allowed.
Only the shared pipeline/readout is used. Native full-sequence GEMM geometry is
kept; selected two-token FP32 logits cannot silently substitute for native CE.

## Measurements and safeguards

- Ordinary/native and written-zero full-logit equality, exact query anchoring,
  verified optimizer membership, finite gradients and updated parameters,
  frozen-base identity, source/runtime/tokenizer/data hashes.
- Checkpoints 0/1/8: all 16 world/query prefixes and six memory conditions,
  giving 96 rows per checkpoint and 576 rows across both arms. Record native
  choices/ties, full-vocabulary disturbance, donor direction and reverse-order
  sensitivity. The selected-row FP32 cap bound is diagnostic, not a native bound.
- Checkpoints 0/8: four exposed reciprocal queries, five conditions, two arms:
  **80 greedy sequences**, at most 16 new tokens each. Base inline has facts and
  query-only base does not; this is not an equal-information correctness battery.
  Keep all wrong, extra-text and length-limited outcomes. This new bounded budget
  does not repair the older 64-token gate.
- Compare actual native logits before/after finite updates. Cast-surrogate
  gradients alone are insufficient. Save bridge checkpoints 4 and 8 per arm;
  do not delete historical weights or copy the backbone.
- Require 20 GiB free before allocation, cap the Torch allocator at 18 GiB,
  and stop only this run below 4 GiB free. Record sampled process memory and
  Torch peaks separately; do not interfere with another client.

Prospective scalar receipt replay uses `atol=1e-5, rtol=1e-6` only for the
FP32-microbatch-loss versus FP64 scalar reconstruction. The FP32 norm guard
allows at most 1.000001 for the cap-one residual. Native/zero logit parity and
source hashes remain exact; neither tolerance is a correctness or promotion gate.

The pilot does not test all random/schema controls, unseen worlds, full-backbone
updates, natural multi-turn dialogue or preservation of the earlier qualitative
sentinel. Canonical/reversed literal orders are a bounded check, not universal
proof of content/order disentanglement. No automatic longer run, model selection,
weight pruning, API judge, PR or merge follows from a favorable pilot.

The old gate remains FAIL; `winner: none`, `semantic_promotion: false`, and
`non_regression: NOT_ESTABLISHED` remain the publication ceiling.
