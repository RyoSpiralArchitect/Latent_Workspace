# V18 next boundary: actual writer, controlled context

2026-10-15. **NOT_FROZEN_NOT_LAUNCHED — protocol sketch only.**
No experiment, source/math change, checkpoint-owner admission or 7B run is
authorized by this document itself.

Follow-up: [the new saved-state diagnosis](../../provenance/pilots/v18_selection_permutation_20261015/README.md)
completed, but historical forward reproduction is blocked in every cell.
Centering is not yet selected for repair. The fact-only writer helper is now
implemented with 42 local tests; this does not freeze or launch the comparative
fit below. Its frozen input container validates shape/mask policy, not the
factual identity or label independence of arbitrary caller-provided features.

## Why this boundary, not a larger model yet

The supplied-slot study passes ordered-reader toy learnability in all three
seeds on both runtimes, but **does not pass selection advantage**. The final-state
reader also learns nearly all answers; raw-ordered succeeds too. This is
controlled identity/rank-slot accessibility, not proof of a unique centered
mechanism or learned-writer accessibility. Exact metrics and control outcomes
are in the [CPU results](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/assay_cpu/RESULTS.json)
and [CUDA results](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/assay_cuda/RESULTS.json).
The [CPU](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/ASSAY_CPU_AUDIT.json)
and [CUDA](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/ASSAY_CUDA_AUDIT.json)
offline audits pass without new forwards. The old **FAIL / winner:none /
non_regression NOT_ESTABLISHED** remains.

## Gate A: explain the existing permutation-control failure first

All **6/6 centered-final fits** (three seeds × two runtimes) fail the fixed
`1e-6` maximum-logit permutation control. Recorded errors range from
`1.1883676052093506e-6` to `2.1457672119140625e-6`. They are not control-clean
baselines, even though their answer accuracy is high. Ordered/symmetric/raw
controls pass; this does not establish causal superiority of ordered selection.

Before a comparative writer fit, separately specify a bounded diagnostic on
the retained tiny states: archive full original/permuted control logits,
matching slot/mask permutations, query tensors and intermediate reductions.
Check repeatability and identify the earliest changed reduction or attention
operation. Distinguish writer-output slot permutation from permuting input facts.
Optional higher-precision arithmetic is diagnostic only, not a replacement for
the original primary computation. Keep the old failures and threshold unchanged.
If a changed implementation is needed, freeze it as a separate version and
requalify every matched arm before fitting; do not silently repair the baseline
or declare the original comparison control-clean.

## Gate B: change the source of slots only

Replace supplied final memory with the existing query-independent
[`write_memory(context, mask)`](../../src/latent_workspace_ft_v10/precision_bridge.py)
path. Supply controlled factual context features: entity identity and world rank
at each fact position, with explicit masks. This exercises the actual
`FunctionalMemoryWriter`, not an LLM encoder or natural-language fact extraction.
No direct supplied-slot bypass is allowed in the writer-study primary arms.

Keep question identity features, CPU-FP32 operand pooling, split-query reader,
full-sequence/full-vocabulary synthetic head, initialization policy, normalization,
centering, interaction fraction and cap unchanged. The common readout stays
frozen at exact zero. Explicitly enable only its writer submodule plus the same
interaction parameters; record this new trainable-parameter denominator.
The writer gets facts and masks only: no question, answer label, donor identity,
or twin flag. Labels remain loss-only; twin facts change only the world ranks.

Primary matched arms are **centered-final versus centered-ordered**. Retain
centered-symmetric and raw-ordered as diagnostics with the same writer and
parameter budget, plus the untrained common-only reference. Use matched writer
and reader initial states and minibatch indices within each seed. Do not claim
that a gain from this new writer-plus-reader fit isolates reader training alone.

Retain full-vocabulary CE plus residual-squared penalty, with no reference-bank,
preservation, donor-auxiliary, temperature or gain intervention at the same time.
The prior 256-update / batch-64 / AdamW-0.001 recipe is a proposed fixed-budget
starting point, not a launched or automatically extended run. Freeze exact
seeds, budgets, resources, optimizer groups and stopping rules before results.

## Gate C: fresh populations and pre-result tests

Use new identity frames and seeds disjoint from the now-observed prior train,
dev and held-out sets and the analytic witness. Bind family splits before fitting;
all reciprocal queries, world permutations and twins of a frame stay together.
Keep last-step evaluation and no dev-driven selection. Alias strings that reuse
features are binding controls, not new independent data or language robustness.

Before launch, test fact-only writer inputs, query-independent memory, exact
common zero, writer/reader gradient ownership and matching initial states.
Test masks, paired labels, finite/cap behavior and raw-artifact offline replay.
Apply zero/equal-slot controls **after writing**: zero context need not produce
zero slots because the writer has learned slot seeds and biases. Archive raw
control outputs this time. Freeze the primary reciprocal, donor-flip, unaffected
and accuracy gates prospectively; do not loosen them after inspecting scores.

Report per-seed denominators and all failures, not only aggregate accuracy.
Writer collapse, lost factual information and failed query selection are distinct
diagnoses; track slot variation and query-dependent attention as diagnostics,
never as substitutes for donor-directed native decisions.

## Separate gates after this sketch

A positive controlled-writer result still leaves real contextual hidden states,
inference-text bindings and learned LLM representations untested. The new reader
also remains outside the qualified V18 checkpoint owner: explicit parameter and
optimizer ownership, save/restore and uninterrupted-versus-resumed agreement
must be qualified separately before 7B full update. A frozen 7B resource estimate,
base-preservation protocol and behavioral evaluation are later requirements.
No 7B training, new generation, paid judge, weight deletion or HF release follows
automatically from this controlled result.
