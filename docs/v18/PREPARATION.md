# V18 preparation: preserve useful behavior, make memory selectively usable

2026-10-15. **DESIGN / ENGINEERING PREREQUISITES IN PROGRESS / NO 7B LAUNCH**.
Ryō requested completion of the existing V16 population diagnostic, then
preparation for improved full updates if the results do not show marked
degradation. This document prepares that decision; it does not authorize an
automatic new run or redefine a passed gate. V18 is the requested prospective
name. No intermediate V17 experiment or qualification is implied.

The additive [window/reference ownership implementation](WINDOW_REFERENCE.md)
now addresses unit 1 and the immutable supplied-bank portion of unit 2. Real
reference capture, preservation loss, selection mechanism and full-update
training remain unimplemented or unlaunched. See its separate qualification
record; implementation is not a semantic or non-regression result.

## Evidence boundary

The [V16 population contract](../v16/POPULATION_DIAGNOSTICS.md) evaluates
existing two-update checkpoints: 128 new world pairs, 1,024 queries, 256
affected queries, and a fixed 570-question MMLU subset with no workspace.
Four evaluation-data seeds do not replace independent training seeds: there
is still one model seed, two trained worlds and two updates per arm.

Read its terminal results and offline replay before selecting a learner factor.
The [completed small pilot](../../provenance/pilots/v16_full_comparison_20261014/RESULTS.md)
already distinguishes live question gradients from useful native answer
direction: all three arms retained 0/4 affected native-margin changes and
0/4 donor-directed flips. A changed residual or vocabulary logit is not yet
selective use of memory, and FP64 direction was not consistently correct.

The [historical proposed correctness floor](../v14/FT_BETA_IMPROVEMENT_PLAN.md#4-the-pinned-base-correctness-floor)
has tolerance delta = 0. Its prospective benchmark/slice/statistical protocol
was not fully implemented. Do not invent a positive tolerance after seeing
these results. "No marked decline" can justify engineering preparation, not
formal noninferiority, a winning branch, or FT-beta release. Retain ordinary
and strict-tie scores, original-correct regressions and repairs, uncertainty,
and protected-slice failures separately. The current 570-question subset is
descriptive and is now exposed development evidence, not a new untouched gate.

**Old FAIL / winner:none / non_regression NOT_ESTABLISHED remains unchanged.**

The [population result is now complete](../../provenance/pilots/v16_population_diagnostics_20261015/RESULTS.md)
with a successful offline replay. Slot contrast scores 354/570 ordinary and
348/570 strict MMLU, versus original 356/570 and 355/570; it retains 0/256 donor
flips. Preparation can continue, but no non-regression or training promotion is
declared. Its centered-slot norm fraction is 0.06227 and remaining budget
0.27243, so exact slot identity and exhausted cap are not sufficient explanations.
Near-uniform selection of centered values is the leading **observational**
bottleneck; intended FP64 direction is positive in 127/256 affected queries,
negative in 129/256. A selection-only relational-query/read factor is therefore
the narrow next hypothesis, initially preserving writer/common/output map/cap
and native arithmetic. It still needs a tiny reciprocal-binding learning test
and matched controls, not a formula chosen from trace magnitudes alone.

Ryō's conditional destination is a Hugging Face beta named
**mistral-7b-instruct-ver0.3-LTWspaced β**. The
[release checklist](HF_RELEASE.md) separates a prospective beta risk allowance
from the unchanged historical gate and requires inference-export parity,
full evidence disclosure and resolved publication identity. No upload is made.

## Preserve / strengthen / add

| Track | Preserve or change | Evidence and boundary |
| --- | --- | --- |
| Preserve | Query-independent writer; native architecture-owned readout; bounded common route; explicit optimizer/RNG/state ownership | The [V16 owner](../v16/SLOT_STATE_OWNER.md) qualified these engineering boundaries, not all-model or language-quality equivalence |
| Preserve as a hypothesis | Concise, calibrated, verification-oriented responses | The [V14 synthesis](../v14/FT_BETA_JUDGE_SYNTHESIS.md) has one shared stable favorable causal pair; it is an exposed sentinel, not training gold or a general quality result |
| Strengthen | Inference-text-conditioned selection of differentiated memory, followed by donor-directed native readout | Choose one bottleneck from slot variation, attention selection, output mapping and cap measurements; do not assume stronger gradients imply useful direction |
| Add | Immutable original-base preservation on independent, unnecessary-intervention contexts | The current unrelated-memory baseline follows the updated model and cannot itself anchor the original model |
| Add | General complete-window data reductions and full-update-compatible behavior evaluation | Fixed diagnostic denominators and frozen-backbone generation sharing cannot be carried into larger full updates unchanged |

## Engineering unit 1: generalize the window contract without changing old math

[`adapted_pair_objective`](../../src/latent_workspace_ft_v10/adapted_pair_objective.py)
explicitly implements a fixed two-world/eight-query diagnostic. Its reductions
use 32 answer terms, 4 affected pairs, 12 unaffected pairs, 16 unrelated pairs
and 48 residual terms. Passing more data through these constants changes the
effective loss weights. Keep this sealed implementation intact.

Add a new immutable reduction contract, derived before any backward call from
the complete ordered training window. Own counts per loss family, window ID,
pair/data order, reduction policy, update boundary, and any preservation-bank
identity. Reject inconsistent counts, duplicate coordinates and incomplete
windows. Specify explicitly what happens when a loss family has zero examples;
never silently divide by a clamp or infer a count from successful rows only.
Labels may choose losses but must never enter writer/reader forward inputs.

Qualification must first reproduce the historical 16-pair window's loss
components, gradients, updates and serialized next update exactly under the
same runtime/order. For new window sizes, use an independent reduction/update
reference with the declared order. Floating-point accumulation need not be
invariant to arbitrary reordering: do not promise that stronger property.
Test full/frozen scopes, native FP32/BF16 tiny models, checkpointing on/off,
partial-window rejection, corruption, aliases and restore rejection without
target mutation. Qualify on isolated CPU and CUDA before a 7B admission probe.

This is an engineering prerequisite, not an additional semantic loss or
evidence that a longer run will solve content binding.

## Engineering unit 2: an original-base anchor, kept as a separate factor

The current objective's no-gradient baseline is read from the **current**
adapter. It constrains an unrelated-memory effect relative to current theta,
not accumulated drift from the pinned original model.

Prepare an independently frozen reference bank from the pinned original model
on train-only preservation contexts, disjoint by task/world/paraphrase family
from final evaluation. Record prompt tokens, native scoring policy, original
identity, content hashes and provenance. Public MMLU test answers and the old
judge-preferred answer text are not preservation-training targets. Protect
verified-correct behavior without treating all original errors as gold.

Before adding a loss, specify whether the reference is full-vocabulary logits
or a restricted projection, its storage/CPU-transfer costs and exactly which
capability it can preserve. A two-choice anchor is not full-vocabulary
preservation. Include task-only and preservation-enabled controls; keep this
axis separate from a reader change. Bind its version and schedule into the new
state descriptor and require exact replay. Do not silently admit old payloads
because tensor shapes happen to fit.

The current owner requires a physical gradient for every owned parameter in
each backward slot. A direct-backbone-only preservation row would leave reader
gradients absent. Do not weaken that invariant silently: a combined scalar or
typed gradient scope needs a separately qualified contract. The first
engineering unit can qualify a reduction specification and synthetic frozen
bank ownership without adding this loss. The current checkpoint admits the
original model only in an identity role; preservation supervision needs a new
format, not ignored metadata or unowned reader buffers.

## Engineering unit 3: choose one interaction factor from the measured chain

Current status: the [text-bound operand prototype](OPERAND_SELECTION.md) is
implemented and has 200/200 source-isolated CPU engineering passes. CUDA was
blocked by another GPU client before test dispatch, so the fixed controlled-slot
learning comparison is still entirely undispatched. See the retained
[attempt and next decision](../../provenance/pilots/v18_operand_selection_20261015/README.md).
This does not admit the new reader into the qualified owner or establish a gain.

The [read-only observer](../../src/latent_workspace_ft_v10/v16_population_probe.py)
separates these hypotheses; none is established by interaction magnitude alone.

| Observed bottleneck | Narrow next factor | Do not infer |
| --- | --- | --- |
| Little variation survives normalization/centering | Writer representation / differentiated slot construction | Slot diversity automatically represents useful facts |
| Variation remains but query selection cancels it | Inference-text-only relational query/selection mechanism | A new auxiliary loss alone repairs the access path |
| Selected read is substantial but output mapping erases it | Output-map/update-allocation factor | Global gain or FP64 readout is the remedy |
| Remaining common-route norm budget is near zero | Separately allocated, bounded interaction budget | Cap starvation if the measured remaining budget is substantial |

Keep common, parameter-matched raw and centered-slot references; match initial
values, data/order, optimizer and update budget where applicable. Report any
capacity/compute mismatch explicitly. Preserve intact/twin, zero, unrelated,
common-slot, random and reciprocal-query controls. Measure donor direction,
unaffected drift, original-base regressions and native visibility together.
The observer's shadow attention weights are not production activations or a
causal patch. One-factor intervention is required before a mechanistic claim.

The next [selection-factor proposal](SELECTION_FACTOR_PROPOSAL.md) makes this
concrete: keep the common query unchanged and compare final-state, ordered
operand-difference and symmetric-operand interaction queries. It is not yet an
implemented reader or an admitted experiment; begin with reciprocal binding on
controlled slots, then the actual writer, before selecting a 7B cell.

## Behavior and judge preparation

Use the [paired behavior protocol](BEHAVIOR_EVALUATION.md) and
[manual Claude review sheet](CLAUDE_REVIEW_SHEET.md). Original base, updated
backbone without workspace, and updated model with workspace are distinct
conditions. Identical seed alone is insufficient: use frozen token-level
common random numbers and model-identity-aware prefix ownership.

Keep correctness, logical validity, grounding, instruction compliance,
termination and writing preference separate. Strong preference cannot rescue
an incorrect answer or the old gate. Preserve unchanged outputs as well as
changed outputs; repeats/orders are not independent tasks.

Environment-held API keys are authorized for an eventual scoped evaluator;
never print or publish their values. `luna6` is a user-suggested candidate label,
not a verified API model ID. Resolve the actual execution surface/model and
freeze its settings before new-rubric calibration. Claude can be reviewed by
manual file transfer without any Claude API key. No new generation, judge or
training is launched by these documents.

## Admission checklist before V18 full updates

1. Terminal V16 population receipts and offline replay; retain all negative and
   missing outcomes. No automatic retry or retrospective threshold adjustment.
2. Choose one reader hypothesis; freeze a separate preservation axis and
   unchanged controls. Do not change several mechanisms in the first cell.
3. Implement and qualify the general window/state contract, old-window parity,
   new independent update references and exact save/resume on CPU/CUDA.
4. Freeze train/dev/final family splits, independent model seeds, complete-window
   schedule and resource ceilings. Current evaluation seeds do not count as
   model-seed replication. Determine size from a separate pilot and required
   precision, not from the number of judge requests.
5. Reforecast VRAM, host RAM, CPU transfers and storage for the actual sequence
   lengths, reference bank, optimizer and latest-two checkpoints **per
   condition**. Do not delete existing weights as a side effect of preparation.
6. Qualify full-update-aware generation identity and controls; freeze untouched
   evaluator calibration/rubric before paid or manually collected judgments.
7. Make an explicit launch decision from these receipts. Engineering readiness,
   exploratory continuation and correctness qualification are separate states.
