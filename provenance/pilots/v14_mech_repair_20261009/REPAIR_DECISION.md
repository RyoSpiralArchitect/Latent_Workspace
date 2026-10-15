# Frozen repair decision — before fresh holdout scoring

2026-10-09. Design input: fixed original/task128/task256/semantic128/semantic256,
first16 **training** worlds, both sides and all8 questions. No new evaluation
scores were used. Source of the MI run: cfd9218. All existing weights stayed fixed.

## What the MI supports

The reader's decomposition is `A(q)V = mean(V) + A(q)(V - mean(V))`.
There were1,280 production traces and640 reverse-query pairs. Separately
reconstructed interventions reproduce production bounded residuals to maximum
absolute error1.86265e-8, below the frozen1e-5 tolerance. Reversing K/V slot order
together is an exact negative control on these runs.

For semantic256, input query relative difference is0.110294, projected query
0.017702, attention-weight difference0.000535, attention-output difference
2.356e-5, raw residual3.583e-6, capped residual2.509e-6 (means of per-pair ratios).
Query differences are present but strongly attenuated before the cap; removing
the cap alone is not established as the appropriate fix.

Normalized slot diversity increases from0.069994 to0.125415 (centered L2 fraction).
Therefore semantic-slot collapse is **not** supported by this panel. Nor does
the experiment establish native RMSNorm/LayerNorm as the cause of training failure.

The mean-value path dominates the current bias. For semantic256:

- Mean raw residual norm11.5441; mean-only norm11.5215; centered-only norm0.155737.
- Uniform attention changes the answer-axis gap by mean absolute0.000208207.
- Removing mean values changes mean absolute gap from0.313439 to0.011096,
  approximately96.46% lower. Mean absolute *intervention change* is0.308736;
  this last quantity must not be mislabeled the original or remaining effect.
- Swapping the projected query with the reversed question changes answer-axis
  gap by mean absolute8.973e-8.

These are bounded causal interventions on the **existing reader outputs**, not
proof that the mean-value path caused optimization failure or that its removal
will produce semantic learning. Slot centering can still permit a fixed,
nonuniform attention pattern and query-insensitive bias.

## One change to test

Create a parameter-identical `CenteredValueWorkspaceBridge`, changing only V
input after memory normalization to its masked-slot-centered value. Keep Q and
K unchanged. Preserve up projection, cap1.0, initialization47, optimizer,
paired losses, training data/order and256-step budget. No extra normalization,
loss term, gain, or learning-rate search is introduced.

Centering before the bias-free V projection is mathematically equivalent to
centering projected V. K and V now use separate input tensors, which may change
projection GEMM geometry, so numerical equivalence is checked with bounded
FP32 tolerance, not asserted bit-exact.

Train task and semantic variants from the original initialization, **not** by
continuing old failed checkpoints. Evaluate old task/semantic and both new
conditions on the same fresh64 worlds (seed901009); these have zero ID, individual
order, unordered twin or context overlap with all320 old worlds. Shared entities
and question templates remain in scope. The4-turn repeated no/yes assay uses
fresh worlds0/1 with both sides; no KV cache is used.

Success must be judged by donor-directed affected comparisons with unaffected,
unrelated and carrier controls—not merely a smaller residual or higher accuracy.
No fresh-score-driven retry is authorized by this frozen plan. This pilot does
not promote a winner automatically, and will retain a negative result.

The new branch preserves failed artifacts and saves only its latest two small
bridge checkpoints per condition. Mistral's original weights remain untouched.
