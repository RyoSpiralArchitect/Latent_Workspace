# V18 operand selection: additive prototype and bounded controlled assay

2026-10-15. **CPU/CUDA ENGINEERING PASS; CONTROLLED LEARNABILITY PASS;
SELECTION ADVANTAGE NOT ESTABLISHED.**
This follows the [selection proposal](SELECTION_FACTOR_PROPOSAL.md) and the
[qualified window/reference foundation](WINDOW_REFERENCE.md). It does not
change or enter the existing checkpoint owner.

The [first isolated attempt](../../provenance/pilots/v18_operand_selection_20261015/README.md)
passed 200/200 CPU tests. CUDA stopped before dispatch because another GPU client
had appeared; its failure remains. Neither fitting study ran in that attempt.
The [authorized continuation](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/README.md)
then passed 200/200 CUDA tests and completed 12/12 fits on each runtime, with
unchanged source and exact same-runtime offline replay. Ordered selection passes
all seeds' toy learnability gates, but not the +5 pp advantage gate. The final
factor fails the frozen permutation tolerance in all three seeds on both
runtimes; only 9/12 control bundles pass per runtime. These failures remain.
The protocol below is the unchanged pre-result design.

## Three independent boundaries

1. [`v18_operand_query.py`](../../src/latent_workspace_ft_v10/v18_operand_query.py)
   binds exact, inference-visible subject/object spans. Supported questions are
   `Is X ranked above Y?` and `Does X outrank Y?`, followed by the existing
   `Answer:` cue. Distinct case-sensitive ASCII identifiers and verified fast
   tokenizer offsets are required. Ambiguity, truncation and punctuation-crossing
   tokens reject; this is not general-language entity recognition.
2. [`v18_selection_reader.py`](../../src/latent_workspace_ft_v10/v18_selection_reader.py)
   keeps the common query separate from the interaction query. Same-query
   arithmetic, parameters, initialization, writer and cap match V16. A changed
   interaction query cannot replace the common query or its budget calculation.
3. [`v18_selection_pipeline.py`](../../src/latent_workspace_ft_v10/v18_selection_pipeline.py)
   sends current final-position normalized state to the common route and keeps
   the architecture-owned full-sequence/full-vocabulary head untouched. The
   interaction uses final state, ordered operand difference or symmetric mean.
   Completion tokens cannot redefine the original operand positions.

Operand pooling is explicitly **CPU FP32**, in ascending token order; each
mean and the subsequent difference/half-sum run there before returning to the
native device. Autograd is retained. This currently transfers the original
prefix states, unlike the final-state control; it is not a speed/transfer
optimization. Actual contextual hidden states may change with question order.
No algebraic negation or symmetric invariance is claimed for an LLM's reversed
question. Manually forged, structurally consistent metadata is not authenticated;
production callers must use the checked binder.

The new reader is deliberately `NOT_ADMITTED_BY_V18_OWNER`. No changes to old
source seals, checkpoint whitelists, optimizer ownership or restore contracts
are needed for this prototype. State-owner admission will be a separate gate.

## Frozen controlled-slot study, before a real writer

The machine-readable [assay plan](../../configs/v18/OPERAND_SELECTION_ASSAY_PLAN.json)
is committed before execution. Its controlled adapter supplies independent
identity vectors and rank features for three entities. Queries contain identity
only; ranks/labels/twin flags cannot enter query construction. The final-state
control retains both operands in separate blocks, so it is not deprived of
order. A separately constructed two-head witness tests representational capacity
without initializing the fitted models from that solution.

This is **reader-only toy learning**: the common route is frozen at exact zero,
the writer is bypassed, and only interaction parameters train. Four matched
fits use centered-final, centered-ordered, centered-symmetric and raw-ordered;
common-only is an untrained reference. Seeds are 17, 29 and 43; each fit uses
256 updates, batches of 64, AdamW learning rate 0.001, zero weight decay,
gradient clipping 1, full-vocabulary CE and residual-squared penalty 0.001.
Preservation and donor auxiliary losses are off. This is a new toy budget, not
the qualified full-update optimizer or continuation of a trained checkpoint.

Independent identity frames define 32 train / 8 dev / 32 held-out frames.
All six world orders and six directed questions give 1,152 / 288 / 1,152 rows.
Held-out adjacent-rank twins yield 384 affected and 768 unaffected paired rows.
Reciprocal queries and twins share frames and are not independent samples.
Renaming the same identities is a binding-invariance control, not extra held-out
data. In this toy it preserves the feature codebook **by construction**; it does
not run a tokenizer or measure actual alias robustness. That binding mechanism
is tested separately. Fixed last-step evaluation is used: no dev selection or
result-driven tuning.

During pre-freeze review, the analytic construction test was found to use the
first two frames of the initially proposed held-out seed 3301. Before any fitting
study, its witness seed was separated to 9109 and the held-out seed changed to
4307. This is a documented pre-freeze correction, not a response to fitted scores.

Before seeing results, toy learnability requires **every seed** to attain:

- At least 95% held-out accuracy and 90% jointly correct reciprocal pairs.
- At least 90% donor-directed flips on affected pairs.
- At least 95% unaffected accuracy and intact/twin prediction agreement.
- Same-memory, zero/equal-slot, finite/cap and consistent slot/mask-permutation
  controls. Margin drift is reported, not required to be zero when rank distance
  legitimately changes.

A selection-advantage claim additionally needs ordered minus final accuracy of
at least five percentage points in every seed without lower reciprocal or
unaffected correctness. Passing capacity while tying final is not an advantage.
Symmetric failure in synthetic order-invariant operand states is not evidence
about contextual LLM states. Unrelated memory with absent queried entities has
no defined truth label, so its response is reported but not graded as an error.
BF16 readout evaluation is separate from FP32 fitting.

Each runtime has a fixed 900-second / 4-GiB CUDA allocation ceiling and at most
two CPU threads. CPU and CUDA are fresh source-isolated processes; numerical
equality between devices is not required. Outputs are exclusive, source-bound
and outside the execution checkout. An interrupted/failed study remains partial,
not permission to extend its budget or retry silently.

## Claim ceiling and next decision

Even a positive controlled result establishes only supplied identity/rank-slot
learnability in this synthetic hidden/head geometry. It does not establish
learned-writer accessibility, native Mistral behavior, full-update ownership,
general-language capability, original-base preservation or a 7B memory envelope.
If the selected factor misses its gate, retain the failure and diagnose it before
moving to actual-writer learning. If it passes, actual writer and real contextual
states are the next gate, followed by explicit owner/replay qualification.
The completed selected factor passed; the next
[actual-writer protocol sketch](ACTUAL_WRITER_TRANSITION.md) is not yet frozen or
launched. The final factor's control failures still prohibit a clean comparative
advantage claim and are not waived by ordered learnability.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. No 7B
training, real reference capture, free generation, paid judge, weight deletion,
HF upload or PR/merge is included in this study.
