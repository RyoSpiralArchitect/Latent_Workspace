# V18 reconstruction: parameter-flag intervention

2026-10-15. A new bounded intervention follows the completed
[saved-state diagnostic](../../provenance/pilots/v18_selection_permutation_20261015/README.md).
The latter is not rerun or repaired. All24 of its cells retain their failed
historical-forward reproduction status. This follow-up tests one explicit
execution-policy difference before selecting any arithmetic change.

## Fixed factor and limits

For each original saved state, load the same reader once and keep its parameter
objects and storage unchanged. Visit policies in the fixed order **A, B, B, A**:

- A: the historical partition, six interaction parameter tensors trainable and
  26 common/writer tensors frozen.
- B: all32 parameter tensors frozen, as in the completed diagnostic.

Every visit remains eval + no-grad, with the same FP32 arithmetic, saved
1,152-row population, original 256-row batching and slot permutation `[2,0,1]`.
Perform original and permuted forward passes at each visit, yielding two
repeats per policy/order. Run the original six-pass controls once per policy.
Archive all raw logits/residuals, parameter flags/layout/storage identity,
execution settings, and comparisons against both original and prior-diagnostic
outputs. The original saved states, input bundle, prior diagnostic and all
three source seals are bound and kept unchanged.

This is 12 saved fits × two flag policies = 24 policy cells per runtime, not new
training replications. It uses 1,200 batched forwards per runtime, zero
optimizers/backward/writer calls/updates. Separate CPU/CUDA processes each have
a 900-second wall limit, 4-GiB observed peak memory bound and two CPU threads;
GPU contention fails admission. Outputs are exclusive and outside source.
Do not retry a failed or ambiguous process automatically.

Freshly reconstructed `.grad` buffers are absent in both arms. Historical
post-update gradient buffers and allocator/kernel-cache state were not saved.
ABBA holds current storage fixed; it does not recreate every aspect of the
historical process or prove a kernel-level mechanism. Keep these limits visible.

## Interpretation fixed before results

Flag-dependent output changes, exact historical agreement, agreement with the
prior diagnostic, and within-policy repeatability are separate observations.
If both arms agree but neither reproduces historical logits, the tested flag
change does not explain the gap in this execution; do not label centering the
cause by elimination. If flags change the output, report direction and exact
arrays, not merely a changed pass count. A hypothetical historical match must
also reproduce the full controls before it is called a reconstructed baseline.

The original tolerance remains `1e-6`; no fit, new data, precision repair,
native Mistral update, paid evaluation or HF publication is part of this test.
The historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
