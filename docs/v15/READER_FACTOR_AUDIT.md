# Reader factor audit: where question sensitivity becomes content-independent

2026-10-10 · prospective no-update diagnostic, not another reader modification.

Ryō asked to investigate the mechanism further. Keep the legacy and modulated
reader fixed at the same retained answer-only step-8 state. Do not train, tune
strength/cap, generate text, call judges, change thresholds or delete weights.
The preceding modulation bundle and historical source seals stay unchanged.

## Four-corner decomposition

For each reciprocal question pair and original/twin memory, capture the actual
attention output `r`, pre-output-projection value `z`, raw projected correction
`x`, and capped correction `d`. For corners `(even,original)`, `(even,twin)`,
`(odd,original)`, `(odd,twin)`, define FP64 factors:

- C = `(v00 + v01 + v10 + v11)/4` (common).
- Q = `(-v00 - v01 + v10 + v11)/4` (question).
- M = `(-v00 + v01 - v10 + v11)/4` (memory).
- I = `(v00 - v01 - v10 + v11)/4` (question × memory).

The corners reconstruct as `C ± Q ± M ± I`; four times I is the previous mixed
difference. Large Q does not imply large I. These are finite descriptive factors,
not orthogonal causal percentages, independent observations or learned features.

For actual affected reciprocal questions, the fixed yes-minus-no head axis
gives memory differences `2(M-I)` and `2(M+I)`. Because the donor signs reverse,
both donor margins can be positive only when `s_odd * I_axis > abs(M_axis)`.
This is algebra for this contrast, not a new success gate. Native margins remain
authoritative; FP64 fixed-axis projections do not replace the full native head.

For the modulated reader, let `g = 0.25*tanh(projected_question)`. Its latent
interaction splits exactly in real arithmetic into
`I_z = I_r*(1+mean(g)) + M_r*(g_odd-g_even)/2`.
The first term propagates old interaction; the second creates interaction from
memory main effect and question modulation. Capture gates on the execution
device and check reconstruction against a predeclared FP32 two-operation
rounding bound, rather than adjusting tolerance after results.

## Operator and cap diagnostics

Compute the retained `up` operator's FP64 SVD, full singular spectrum, fixed
top-k Frobenius-energy fractions and effective ranks. Record factor alignment
with the leading singular directions and fixed head axis. High spectral
concentration, if observed, is not itself a causal failure proof or permission
to remove a singular direction.

At each memory-pair midpoint, compare the cap's analytic directional derivative
with its FP64 finite difference, separately recording production-FP32 rounding.
Radial and tangential gains differ. Factor ratios across the nonlinear cap are
not universal Jacobian gains. No cap bypass or alternate head is used as a
replacement evaluation condition.

## Frozen scope and controls

The [plan](../../configs/v15/READER_FACTOR_PLAN.json) fixes two readers × two
exposed worlds × four reciprocal pairs × four memory-pair variants: **64 blocks**.
Each has four observed corners: **256 native-scored observations**. Only the
actual-memory variant carries factual labels (**64 rows total**, 32 per reader).
All other variants are interventions, not additional accuracy cases.

Memory pairs: actual original/twin; each side replaced by its own masked mean
slots; identical original memory on both sides (M=I=0 null); seeded independent
random memory with each side's original global norm. Random controls do not
match post-normalization covariance. Same-memory/mean-slot success does not
establish semantic binding. No new held-out world or entity is introduced.

Use pinned original Mistral, the exact retained checkpoint, final query and
unchanged native geometry. Recheck all 64 actual-memory native vectors against
the prior modulation bundle. Preserve original/shared prefix parity and perform
written-zero native checks. All state hashes and parameter `.grad` fields must
remain unchanged; no autograd or optimizer is required for this probe.

There are 32 written-zero full-head checks (16 queries per reader) in addition
to 48 ordinary/shared prefix checks. Scalar replay requires FP64 four-corner
reconstruction error at most 1e-12; projection/cap residuals are reported, not
thresholded into semantic success. Algebraic scalar replay uses 1e-12 relative
and 1e-15 absolute tolerance. These are arithmetic checks, not task gates.

Seal source and all inputs before one exclusive-output Furnace invocation in
an isolated worktree. No competing GPU process; admission free memory 20 GiB,
allocator cap 18 GiB, sampled free floor 4 GiB, disk floor 20 GiB, two CPU threads,
phase-checked 600-second limit. Preserve partial receipts and stop without retry
if any contract fails. Retain scalar measurements plus tensor hashes; these are
not an archived complete activation bank. Offline replay validates receipts,
not an independent model recomputation.

Source/results may be committed locally only. No GitHub push, PR or merge.
Full-update and short reader learning remain proposed, not launched by this
diagnostic. Old FAIL, winner none, non-regression unestablished and closed judge
missingness remain unchanged; the heartbeat stays paused.
