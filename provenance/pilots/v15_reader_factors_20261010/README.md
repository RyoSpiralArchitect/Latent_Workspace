# Reader factor audit: stronger question response is not yet fact binding

2026-10-10 · **COMPLETED_READER_FACTOR_AUDIT_NO_UPDATE**.

The useful result is a more specific bottleneck, not a repaired learner. The
modulated reader makes a larger question × memory interaction, but comparable
interaction magnitude survives replacing each world's slots with its own mean.
The retained output projection strongly favors a common direction; the smooth
cap further changes interaction geometry. At the two affected reciprocal pairs,
the donor-directed interaction remains far below the question-independent
memory bias. Native correctness and donor flips do not improve.

This is a fixed-checkpoint mechanism diagnostic. The modulated reader has **not
been retrained**. Neither low effective rank nor a cap derivative proves that
removing a direction, raising the cap, or full-backbone training will repair it.

## Scope, execution and unchanged gates

The [prospective protocol](../../../docs/v15/READER_FACTOR_AUDIT.md) and
[plan](../../../configs/v15/READER_FACTOR_PLAN.json) were committed before the
single invocation. The execution source is
`1516d3be796332f70846e85f3191187bb9f6f200`; [SOURCE_SEAL.json](SOURCE_SEAL.json)
records **303 source/input files**. It includes the preceding reader comparison's
13 raw files, whose bytes and historical source seal remain unchanged.

- One retained answer-only step-8 checkpoint; two readers, legacy and modulated
  at strength 0.25; same pinned Mistral-7B-Instruct-v0.3, FP32 bridge, cap one,
  final query and full-sequence native BF16 head geometry.
- Two already-exposed training worlds × four reciprocal question pairs × four
  memory-pair variants × two readers = **64 blocks**. Four corners per block
  give **256 observations**, not 256 independent tasks.
- Only actual original/twin memory has factual labels: **32 rows per reader /
  64 total**. Each reader has four affected individual questions, forming **two
  affected reciprocal blocks**, plus 12 unaffected questions. These overlapping
  denominators must not be interchanged.
- Other memory pairs are own-mean slots, identical original memory on both sides,
  and independent norm-matched random memories with fixed seed 470016. They are
  structural controls, not additional accuracy cases or new held-out worlds.
- No autograd, optimizer construction/step, new learner generation, judge call,
  cap/strength sweep or weight deletion. Base and both bridge tensor hashes are
  unchanged; all parameter `.grad` fields remain `None`.

Each reader remains **16/32 correct**, zero ties, **0/4 correct donor flips**;
all four affected native donor-margin changes are exactly zero. All **64/64**
actual-memory native score vectors exactly match the prior reader comparison.
All **48/48** ordinary/shared full-head prefix checks and **32/32** written-zero
checks pass. Across readers, every matched memory and pre-modulation query/read
hash matches on all **128/128** observations. Identical-memory controls give
exactly zero M and I in all **16/16** blocks across both readers.

Old **FAIL**, `winner: none`, and `non_regression: NOT_ESTABLISHED` remain.
The judge collection remains closed and `INCOMPLETE_OR_CALIBRATION_BLOCKED`;
the original 1,042-file bundle, its unknown/invalid outcomes and blocked OpenAI
study remain untouched. The heartbeat was not restarted.

## 1. Separate common, question, memory and interaction factors

For corners `[even/original, even/twin, odd/original, odd/twin]`, use ±1 coding
to form C, Q, M and I. Reconstruct each corner as `C ± Q ± M ± I`. I is one
quarter of the mixed finite difference. This new audit promotes captured FP32
corners to FP64 **before** subtraction; the previous mixed-difference panel
subtracted in FP32. Tiny results need not be bitwise identical across those
diagnostic arithmetic paths. All actual native scores still match exactly.

Mean factor L2 below uses **eight actual-memory blocks per reader**. `r` is the
attention output, `z` its optionally modulated input to `up`, `x` the projected
raw correction, and `d` the capped correction. Rows are not independent
subpopulations, causal percentages, or universal Jacobian gains.

| Reader / stage | C | Q | M | I |
|---|---:|---:|---:|---:|
| Legacy r = z | 1.320556e+01 | 2.529064e-04 | 1.577481e-01 | 4.786369e-05 |
| Legacy x | 4.808229e+00 | 6.893672e-06 | 5.845817e-03 | 3.444366e-06 |
| Legacy d | 9.790494e-01 | 6.514162e-07 | 1.014241e-03 | 9.684937e-08 |
| Modulated r | 1.320556e+01 | 2.529064e-04 | 1.577481e-01 | 4.786369e-05 |
| Modulated z | 1.344885e+01 | 1.569526e-01 | 1.629754e-01 | 1.773708e-03 |
| Modulated x | 4.822094e+00 | 3.030983e-03 | 5.622596e-03 | 5.571116e-05 |
| Modulated d | 9.791659e-01 | 2.616409e-04 | 1.021759e-03 | 3.530048e-06 |

Question sensitivity and interaction both increased, but the final interaction
is still small relative to memory main effect and common correction. The table
does not label those small vectors semantic: their donor direction matters.

## 2. The learned projection favors a common direction

The FP64 SVD of the **4096 × 256** retained `up` matrix has:

| Diagnostic | Observed |
|---|---:|
| Leading singular direction's squared-Frobenius energy share | 87.966884% |
| Leading four directions' energy share | 99.032837% |
| Energy participation rank | 1.282634 |
| Energy-entropy effective rank | 1.677128 |
| Legacy common d: mean leading-left-direction energy share | 98.676189% |
| Modulated common d: same measure | 98.661850% |

Effective ranks here use normalized **squared** singular values. This is energy
concentration, not a claim that the matrix's mathematical rank is one or that
an architectural rank constraint exists. The common correction aligns strongly
with the leading output direction, while input factors occupy different right
singular directions. The full spectrum and reconstruction residual are retained
in [SPECTRUM.json](raw/SPECTRUM.json). No singular component was removed.

## 3. Slot diversity is not necessary for the new interaction's magnitude

Mean capped I norm over eight blocks per condition:

| Memory-pair variant | Legacy | Modulated |
|---|---:|---:|
| Actual original/twin | 9.684937e-08 | 3.530048e-06 |
| Each side's own mean slots | 0 | 3.524366e-06 |
| Identical memory on both sides | 0 | 0 |
| Independent norm-matched random pair | 2.581599e-03 | 3.053255e-03 |

The modulated mean-slot/actual **ratio of mean I norms is 99.839031%**. This is
not vector equality, retained semantic information percentage, or proof that
mean slots are content-free: their values still depend on the original world.
It shows that almost the same *magnitude* does not require differentiated slot
selection. Random memory produces much larger interactions without factual
labels; interaction norm alone cannot choose a winner. Global norm matching
does not match post-normalization distributions/covariance.

With `g(q)=0.25*tanh(projected_query)`, the latent interaction decomposes as:

`I_z = I_r*(1+mean(g)) + M_r*(g_odd-g_even)/2`.

For actual slots, mean norms of these two source vectors are **4.883740e-05**
and **1.772960e-03**; after fixed FP64 output projection they are **3.415030e-06**
and **5.384401e-05**, respectively. The new branch is predominantly supplied by
memory-main × question-gate in this norm comparison. The vectors need not be
orthogonal; their norms must not be summed into contribution percentages.
Own-mean slots make the first source exactly zero but leave the second.

The maximum production-vs-decomposition error is **8.680058e-08**, within the
prospective two-operation FP32 bound for all **32/32** modulated blocks; the
largest error/bound ratio is **0.142963**. This is arithmetic reconstruction,
not evidence that the interaction learned the correct relation.

## 4. Memory bias overwhelms donor-directed interaction; the cap matters too

For the fixed FP64 yes-minus-no head axis, the two memory changes are
`2(M_axis-I_axis)` and `2(M_axis+I_axis)`. Their donor signs reverse. Thus both
donor margins are positive iff `s_odd*I_axis > abs(M_axis)`; equality is not a
pass. This identity is not a relaxed native success threshold.

Here the odd donor sign is +1. All **four reader/world blocks** below fail this
algebraic condition, as well as the unchanged native evaluation.

| Reader / world | Capped M axis | Capped I axis | Signed I / abs(M) |
|---|---:|---:|---:|
| Legacy 0 | 9.989012e-05 | 2.994740e-09 | 2.998035e-05 |
| Legacy 1 | -3.124448e-04 | 5.889908e-09 | 1.885104e-05 |
| Modulated 0 | 9.204041e-05 | -7.822565e-08 | -8.499056e-04 |
| Modulated 1 | -3.133470e-04 | 6.067201e-07 | 1.936256e-03 |

The modulated raw pre-cap I/abs(M) ratios are **2.799980e-03 / 9.279751e-03**
for worlds 0/1, already below one. The cap cannot be the only missing step.
It nevertheless changes geometry: world 0's raw positive interaction axis
becomes negative after the cap. An offline Cauchy-Schwarz bound using saved
production-minus-FP64 endpoint errors places its ideal-FP64 capped interaction
axis in **[-8.515015e-08, -7.130116e-08]**. This is an arithmetic interval, not
a confidence interval; the local sign reversal is not explained merely by
final FP32 cap rounding. The much smaller legacy I intervals include zero,
so their tiny positive signs are not robust to this arithmetic comparison.

At actual-memory midpoints, mean cap tangential/radial gains over 16 endpoint
pairs per reader are **0.203620 / 0.008442** (legacy) and **0.203059 / 0.008373**
(modulated). These are local directional derivatives, not attenuation of every
factor by one scalar. FP64 cap finite-difference versus linearization mean L2
errors are **2.287302e-09 / 2.025930e-09**; production-FP32 versus ideal-FP64
memory-difference errors are **6.475340e-08 / 5.446480e-08**. Large random
interventions have larger nonlinear remainders, also retained in the receipts.

### Literal native examples, not generated answers

The head candidates are token 1476 (`" no"`) and 5849 (`" yes"`), in that order.
Both readers and both memory sides give each listed score vector unchanged:

| World / query text | Original label → twin label | Native [no, yes] logits |
|---|---|---|
| 0: Is Galen ranked above Kestrel? | yes → no | [19.25, 18.875] |
| 0: Is Kestrel ranked above Galen? | no → yes | [20.875, 21.625] |
| 1: Is Kestrel ranked above Doran? | yes → no | [18.625, 20.25] |
| 1: Is Doran ranked above Kestrel? | no → yes | [19.5, 18.5] |

These are exact stored outputs. No new free generation or LLM judge ran.

## 5. Code-level implication: the desired loss signal already exists

The existing [pair objective](../../../scripts/run_v15_5_native_answer.py)
already contains a donor hinge, plus unaffected/unrelated controls. When both
reciprocal hinges are active, their sum in four-corner *score* notation is
`2*margin - 4*s_odd*I_score` before the existing batch reduction and weight:
the memory main effect cancels. With native scores unchanged, both hinges are
active. Adding a second nominal "make the twin matter" loss can duplicate an
existing objective instead of fixing signal transmission. This scalar algebra
does not assert exact independently accumulated BF16 gradient equivalence.

The fixed checkpoint shows weak useful interaction, a common-mode-favoring
projection and cap anisotropy. It does **not** determine whether fresh matched
training can learn to orient the new modulation route. Nor does it establish
that the common correction is useless: prior qualitative improvements have
not been causally attributed to C, M or I here.

### Next bounded decision, proposed and not executed

1. Preserve the stronger question route as a candidate and run the already
   proposed short, matched **fresh-seed legacy versus modulated** bridge-only
   learning comparison. Same initial tensors, optimizer, full 16-pair windows,
   losses, cap, renderer, native head, data order and budget. Do not silently
   continue from these retained weights or change EOS/aliases simultaneously.
2. Add these C/Q/M/I, spectral and cap diagnostics at predeclared checkpoints.
   Track signed native reciprocal margins, both directions separately, common
   correction norm, per-loss gradient cancellation and mean/random controls.
   The question is whether existing donor supervision grows useful interaction,
   not merely larger Q or lower answer CE. A fixed-axis or ratio improvement
   cannot replace correct native donor direction and unaffected stability.
3. If matched learning fails, isolate one next factor: how common-task output
   and relational interaction share the output projection/cap or receive updates.
   First inspect per-loss actual parameter-update effects; only then separately
   freeze an architectural split or optimizer/objective change. Do not remove
   the leading singular vector, repeat old failed slot-centering, raise gain,
   or add redundant donor losses as an automatic repair. Diagnostic four-corner
   factors require paired worlds and are **not** a deployment-time oracle.
4. Only after that reader decision return to the complete-window/full-model
   update/resume audit. Retain fresh held-out original-base correctness and
   behavior checks before claiming FT-beta quality or useful generation.

## Evidence and replay

One Furnace invocation completed in **32.676897 seconds**, with **14.125497 GiB**
peak Torch allocation, **14.257812 GiB** peak reservation, and **16.419922 GiB**
minimum sampled free device memory over **78 samples**. The postflight GPU had
no compute process. These frozen-forward numbers do not estimate full-update
optimizer memory. The [raw inventory](ARTIFACT_INDEX.json) retains **8 files /
897,674 bytes**, including scalar factors and tensor hashes, not full activations.

[Prelaunch checks](PRELAUNCH_VALIDATION.json): **232 tests** passed locally and
on Furnace; local Ruff passed. **14 post-result tests** validate receipt replay,
matched memory/read hashes, and rejection of ten deliberate corruptions.
The maximum four-corner FP64 reconstruction error is zero in both arms.
Old native, cue, full-backward, modulation and closed judge receipts replayed.

The [frozen summary](SUMMARY.json), [derived mechanism contrasts](MECHANISM.json),
[validation receipt](VALIDATION.json) and [terminal handoff](EXECUTION_HANDOFF.md)
separate recorded measurements, arithmetic checks and design proposals.
`MECHANISM.json` is a post-result offline analysis, not a prospectively selected
statistical test or a new success gate. The following commands are offline:

```sh
.venv/bin/python scripts/summarize_v15_reader_factors.py --bundle provenance/pilots/v15_reader_factors_20261010
.venv/bin/python provenance/pilots/v15_reader_factors_20261010/analyze_mechanism.py
.venv/bin/python -m pytest -q provenance/pilots/v15_reader_factors_20261010/test_receipts.py
.venv/bin/python provenance/pilots/v15_reader_factors_20261010/check_publication.py
```

Offline replay checks recorded scalars, identity, arithmetic, inventory and
selected prose. It does not independently reproduce model tensors. Source and
results are local commits only: no GitHub push, PR, CI run or merge.
