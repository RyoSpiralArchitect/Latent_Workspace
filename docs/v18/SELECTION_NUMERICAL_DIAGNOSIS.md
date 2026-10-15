# V18 saved-state permutation diagnosis

2026-10-15. This is a separately frozen, bounded observation of the completed
[supplied-slot study](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/README.md).
It does not refit any state, change arithmetic, relax a tolerance, or replace a
historical receipt. Ryō requested further diagnosis before precise implementation
and V18 full updates. The [full-update roadmap](FULL_UPDATE_ROADMAP.md) keeps the
later benchmark and conditional-release boundaries explicit.

## Fixed question and population

Why do the three centered-final fits on each runtime exceed the existing
`1e-6` maximum-logit slot-permutation control? Observe the same final states,
1,152 held-out rows, seeds 17/29/43, all four original factors, permutation
`[2,0,1]`, eval mode and batch size 256. CPU and CUDA use their own saved states
and original Python/Torch environment. Twelve saved states per runtime are
diagnosed, not twelve new fits. No new population or train/dev selection occurs.

The input execution source remains `dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`.
The original 572-file seal and both earlier bundles remain byte-for-byte
unchanged. A distinct source seal owns this additive diagnostic and its tests.
The qualified interpreter is Furnace's existing Aether Python 3.12.14 / Torch
2.13.0+cu132 environment, not the different local Mac runtime.

## Observations, not interventions

For each state, collect two ordinary original-order and two permuted-order
passes, then one instrumented pass per order. Observe actual module outputs
and the actual SDPA call without changing its arguments or returned value.
Require bit-exact instrumented/uninstrumented logits and residuals. Reconstruct
centering and radial caps only for observation, and require exact agreement
with the actual attention input and residual. Re-run the original six-pass
control procedure once and retain its results, including failures.

Archive original/permuted full-vocabulary logits, residuals, common/interaction
queries, normalized slots, centered slots, projected Q/K/V, attention outputs
and cap stages. Align permuted slot axes before comparison. Anchor, offsets,
sum and mean in the anchor-based centering are gauge-dependent: archive them
but do not call their expected change a numerical defect. Identify the earliest
changed invariant stage separately for the common and interaction branches.
This is numerical localization, not a causal intervention or proof of mediation.

Original-order logits must reproduce the original archived FP32 case rows
exactly. Original permuted logits were not archived; historical comparison for
that side is limited to the recorded maximum-error scalar and control fields.
Report any reproduction discrepancy explicitly. An offline replay validates
artifacts and provenance; its success does not turn a failed control into PASS.

There are 12 complete held-out passes / 60 batched forwards per saved state,
720 batched forwards per runtime. Each runtime has a separate exclusive output,
900-second wall limit, 4-GiB host/CUDA peak bound and two CPU threads. GPU
contention fails admission. Do not retry a failed or ambiguous cell implicitly.
No optimizer, backward, writer invocation, fitting, FP64 shadow, 7B forward,
new learner generation, judge call, deletion or upload is part of this diagnosis.

## Decision after observation

Keep the historical **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
If a new arithmetic policy is justified, implement and freeze it separately,
apply it across matched arms, and qualify its gradients and invariants before
fitting. Do not choose a repair merely because it makes the old reported scalar
smaller. The parallel actual-writer helper is engineering preparation only:
it chooses neither a numerical repair nor a new fitting population or budget.
