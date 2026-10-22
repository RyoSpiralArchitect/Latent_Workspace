# After V22 weight diagnostics: retain grounding, stabilize decisions

**Follow-up completed:** the [memory-causality assay](../../provenance/pilots/v22_memory_causality01_20261021/README.md)
now qualifies the fixed-extent future controls and executes memory ablations
and a writer/reader factorial. Preserve the proposal below as its rationale;
the evidence-updated next investigation is the [V23 roadmap](../v23/ROADMAP_TO_1_0.md).
No V23 training or release has been dispatched.

This is a **proposal**, not a training or generation dispatch. Its evidence is
the [completed V22 diagnostic](../../provenance/pilots/v22_weight_diagnostics01_20261021/README.md).
Keep the original native scores and all negative outcomes. The goal remains
useful latent-memory behavior without breaking the original host's protected
capabilities; the present evidence does not establish that floor.

## 0. Qualify the prefix instrument before changing the objective

Full-teacher and prefix-only computations disagree on gold-argmax correctness
at two shared-prefix positions per arm. One V22 case is an actual entity error;
one is punctuation/EOS. Existing tiny same-length future-token invariance tests
pass, but they do not establish exact 7B BF16 prefix-cropping equivalence.

Freeze a separate, finite read-only assay with identical preceding tokens,
positions, masks, memory and head. Separate **sequence extent** from **future
content**: compare prefix-only, padded/masked equal-extent, full-gold continuation,
and equal-length changed-future controls at the same prediction position.
Include original/V22, latent/inline, affected/unaffected/absent controls, and
non-boundary examples, not only the one exposed disagreement. Test the harness
on device-aware BF16 and higher-precision tiny graphs before allocating 7B.
Do not relax tolerance after results; retain both exact and numerical differences.

A future-content effect at fixed layout demands a causal-mask/layout diagnosis
before training. An extent effect with invariant future-content controls supports
a numerical-path explanation, but still requires prefix-realistic decision
measurements. No full-FP32 7B conversion is assumed to fit the existing envelope.

## 1. Improve answer identity and abstention without abandoning native output

Keep the differentiable native-memory graph, oracle-checked grouped worlds,
full-vocabulary output and actual token-weighted mixture. Preserve the observed
latent grounding gains and exact empty-memory native bypass.

The current 13 latent failures are dominated by the first answer-identity fork:
12 occur in the first two tokens, and 94.8–99.6% of each failed target's teacher
loss is at its first fork. A higher average target likelihood is therefore not
sufficient. Before choosing a new loss, use the model-independent host/cut
interface for matched state-patching or routing probes that distinguish memory
writing, question-conditioned fact selection, and later symbol copying.
The MMLU head factorial does not localize those world mechanisms.

Candidate single-factor learner experiment: contrast the **first differing
answer-identity span** of oracle-derived, train-only counterfactual/query pairs,
using native full-vocabulary logits. Derive decisions from the oracle/answer
pair before scoring, not from the exposed test mistakes or a universal fixed
token index. Couple this with explicit abstention checks on empty/unrelated
memory and unaffected-query preservation. This is a candidate to test, not an
assumption that another broadly similar cross-entropy term solves the problem.

Keep token/update budgets and group exposure matched to the original objective.
Do not force a two-choice generation head, train on MMLU/test targets, select
easy nonce tokenizations, or replace failures with explanations. Exact-symbol
copying is a separate outcome; the index-5 `ff`→`k` case should not be hidden
inside an early-decision average.

## 2. Protect the body, not only the last head

On all 570 exposed MMLU questions, swapping only the FP32-projected head changes
zero predictions at either fixed hidden arm; changing hidden states changes 11.
For the two original losses, approximately 98.5% of the measured margin change
is the hidden-state term. A frozen head is therefore not a sufficient protection
strategy for these cases. This is not proof that any one decoder layer is at fault.

Candidate independent factor: original-host native-logit anchoring on the
existing **train-only** preservation bank, measured separately from answer NLL.
First audit conflicting gradients and decision-margin movement; then compare
anchoring on/off with the same reader objective, initialization, mixture,
updates and total token budget. The protected tests cannot supply teacher labels,
optimization targets or checkpoint selection. Preserve instruction, prose and
code coverage and the already requested paired reasoning/writing inspection.

## 3. Keep normalization visibility as a separate precision factor

All 65 normalization master tensors changed, while 52 native tensors stayed
bitwise equal to the original. This is a measured transport limitation, but not
a demonstrated cause of current errors or permission to increase their LR.
Only after the preceding controls should a separately matched normalization
precision/parameter-group experiment be considered. Do not bundle a norm change,
stronger readout, larger LR and a new objective into one uninterpretable run.

## Exit conditions before another full-FT claim

Freeze the new source, data admission, resource envelope, primary checkpoint,
loss factors and gates before dispatch. Require update/save/restart equivalence
for any learner change; evaluate native choices and prefix-realistic generation,
absent/unrelated/unaffected controls, exact copy, and a fresh protected benchmark
with paired loss/repair counts. Retain uncertainty and complete denominators.
Judge/human review of matched free answers remains separate from correctness.

The existing ceiling is still **FAIL / winner:none / non_regression
NOT_ESTABLISHED**. Equal aggregate FP32 MMLU counts (355/570 each, four losses
and four repairs) are not a release pass. No further training, provider call,
weight deletion, beta replacement or Hub upload is executed by this document.
