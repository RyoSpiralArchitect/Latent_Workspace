# V18 operand selection: controlled learning continuation 01

2026-10-15 JST. **COMPLETED AND REPLAYED; CONTROLLED LEARNABILITY PASS;
SELECTION ADVANTAGE NOT ESTABLISHED.**

The selected centered-ordered reader learned the supplied identity/rank-slot
task in all three seeds on both CPU and CUDA. This is not a Mistral run, a
learned-writer result, checkpoint-owner admission, or original-base preservation.
The historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.

## Provenance and dispatch

- The [original attempt](../v18_operand_selection_20261015/README.md) and all its
  bytes remain unchanged: CPU passed 200/200 tests; CUDA rejected another GPU
  client before test dispatch; neither controlled learning study ran there.
- Ryō reported free Furnace capacity and authorized continuing. Live preflight
  found no GPU compute clients. This continuation ran only the previously
  unexecuted CUDA qualification, then each frozen controlled study once.
- Execution source: `dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`, bound by the
  unchanged [572-file source seal](SOURCE_SEAL.json). Math, plan, thresholds,
  split seeds, runtime limits and model seeds did not change.
- The additive offline auditor was frozen **before fitting** in
  `d2752de88b1f908ed5ee52496196853fe9d5cbca`; it is not the execution source.
  It passed 97/97 local tests and Ruff. Its cross-runtime QR recipe bound is
  only `atol=1e-6, rtol=0` for identity coordinates, not an experimental gate.
- [Execution handoff](EXECUTION_HANDOFF.md) records paths and limits.
  CPU qualification receipts are literal copies, not rerun tests. New
  [CUDA qualification](cuda/FINISHED.json) passed **200/200**, with no skips.
  The [combined qualification verifier](QUALIFICATION_VERIFY.json) passed.

Both fits used Python 3.12.14 / PyTorch 2.13.0+cu132 on Furnace. CPU and CUDA
were separate processes, with exclusive outputs, an offline environment,
isolated Python/fresh bytecode, pre-import verification and import closure.
No 7B update, real writer fit, API judge, new learner generation, weight
deletion, HF upload, PR/merge or recurring monitor occurred.

## Population and fitting denominators

The [frozen plan](../../../configs/v18/OPERAND_SELECTION_ASSAY_PLAN.json)
uses seeds **17, 29, 43** and four factors: centered-final, centered-ordered,
centered-symmetric and raw-ordered. Common-only is an **untrained frozen-zero
reference**, not a fifth trained factor. The writer is frozen and bypassed;
no backbone is present. Only interaction parameters train, with the common
route frozen at zero.

Each runtime completed **12/12 fits × 256 updates = 3,072 updates**, batch 64:
196,608 sampled training presentations, not that many independent examples.
CPU and CUDA together are 24 fits / 6,144 updates, but repeat the same three
initialization seeds and populations; they are not six independent seeds.
The fixed last step is evaluated; no dev selection or post-result tuning.

| Split | Identity frames | World orders | Directed questions | Rows |
| --- | ---: | ---: | ---: | ---: |
| Train | 32 | 6 per frame | 6 per world | 1,152 |
| Dev | 8 | 6 per frame | 6 per world | 288 |
| Held-out | 32 | 6 per frame | 6 per world | 1,152 |

Each held-out evaluation has 192 worlds, **384 affected / 768 unaffected paired
rows**, and **576 reciprocal pairs**. Twins swap ranks 0 and 1. All six orders
are already present: twin forwards duplicate unique worlds, not independent
samples. Frames, reciprocal rows, repeated seeds and dtypes are not pooled
into an inflated statistical sample. Alias renaming preserves synthetic identity
features by construction; it is not real tokenizer alias generalization.

Each runtime archives **36,864 raw rows in 50 groups**: 48 fitted dev/held-out
FP32/BF16 groups and two common-only held-out groups. Each raw row contains both
intact and twin logits. Final tiny state dictionaries and realized populations
are retained for reproducibility, not exported as language-model weights.

## Primary held-out results

These integer counts are identical for CPU FP32, CPU BF16, CUDA FP32 and CUDA
BF16. The primary gate uses FP32; BF16 cannot rescue a primary failure.

| Seed / factor | Strict correct /1,152 | Reciprocal both correct /576 | Donor flips /384 | Unaffected correct /768 | Unaffected agreement /768 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 17 final | 1,138 | 564 | 372 | 760 | 752 |
| 17 ordered | 1,150 | 574 | 382 | 767 | 766 |
| 17 symmetric | 576 | 0 | 0 | 384 | 768 |
| 17 raw ordered | 1,152 | 576 | 384 | 768 | 768 |
| 29 final | 1,145 | 569 | 374 | 766 | 764 |
| 29 ordered | 1,152 | 576 | 384 | 768 | 768 |
| 29 symmetric | 576 | 0 | 0 | 384 | 768 |
| 29 raw ordered | 1,152 | 576 | 384 | 768 | 768 |
| 43 final | 1,152 | 576 | 384 | 768 | 768 |
| 43 ordered | 1,152 | 576 | 384 | 768 | 768 |
| 43 symmetric | 576 | 0 | 0 | 384 | 768 |
| 43 raw ordered | 1,152 | 576 | 384 | 768 | 768 |

Ordered strict accuracy is **99.8264%, 100%, 100%**. Every selected ordered seed
passes the unchanged accuracy, reciprocal, donor-flip, unaffected and control
criteria. Ordered-minus-final is **+1.041667, +0.607639, +0 percentage points**:
none meets the required +5 pp. This is controlled learnability, not a selection
advantage or proof that centering beats raw slots. Final already contains both
operands in separate blocks and is not an order-deprived control.
Final is already above 98.7% in every seed, so this particular task/budget leaves
less than five points of accuracy headroom. That ceiling does not justify
lowering the predeclared advantage requirement after the result.

Dev ordered/raw are perfect in every seed (288 correct, 144 reciprocal pairs,
96 flips, 192 unaffected correct/agreement). Dev final is perfect in seeds 17
and 43; seed 29 has 287 correct, 143 reciprocal pairs, 96 flips, 191 unaffected
correct and 190 agreement. Dev symmetric has 144 correct, zero reciprocal
success/flips, 96 unaffected correct and 192 agreement in every seed.

All fitted outputs have zero native ties. Frozen common-only instead has
**0/1,152 strict**, **576/1,152 ordinary**, **1,152 ties**, and zero donor flips.
Its ordinary 50% reflects tie breaking, not learned behavior.

## Retained numerical control failures

**Only 9/12 control bundles pass per runtime.** All three centered-final fits
fail the frozen `1e-6` slot-permutation maximum-logit-error threshold:

| Final seed | CPU maximum error | CUDA maximum error |
| --- | ---: | ---: |
| 17 | 1.3113021850585938e-6 | 2.1457672119140625e-6 |
| 29 | 1.1883676052093506e-6 | 1.8477439880371094e-6 |
| 43 | 1.3113021850585938e-6 | 1.9073486328125e-6 |

All ordered, symmetric and raw-ordered controls pass. Equal-slot zero is
explicitly inapplicable to raw-ordered. Ordered permutation errors range from
7.152557373046875e-7 to 8.344650268554688e-7. No tolerance was relaxed and no
failed control was relabeled. Raw control logits were not archived; these are
verified saved control observations, **not control-forward replay**, and their
prediction-level impact is not established. A fully qualified comparative
advantage cannot be claimed from this failed final-control panel.

## Dtypes, resources and offline replay

FP32-to-BF16 changes no intact/twin predictions or correctness outcomes in
18,432 dtype-paired rows per runtime. CPU-to-CUDA likewise changes none across
36,864 matched rows; logits are not bitwise equal (maximum absolute difference
8.821487426757812e-6). This BF16 factor rounds the supplied hidden states and
full-vocabulary toy head, **not an end-to-end BF16 LLM**.

| Runtime | Terminal elapsed | Peak RSS | Peak CUDA allocated |
| --- | ---: | ---: | ---: |
| CPU | 8.628830 s | 901,046,272 bytes (859.30 MiB) | 0 |
| CUDA | 14.123122 s | 2,166,779,904 bytes (2,066.40 MiB) | 69,646,848 bytes (66.42 MiB) |

Both meet the 900-second / 4-GiB limits. These are toy resource measurements,
not a 7B memory estimate. They exclude prior qualification and later auditing.

The first [Mac replay attempts](LOCAL_REPLAY_ATTEMPTS.md) rejected exact equality
of descriptive FP32 means. Integer counts and all threshold-bearing rates
matched; see [the retained diagnosis](LOCAL_REPLAY_DIAGNOSIS.md). Replaying with
the original Furnace interpreter then passed **without changing any tolerance,
source, result or gate**: [CPU audit](ASSAY_CPU_AUDIT.json),
[CUDA audit](ASSAY_CUDA_AUDIT.json). Each validates the source/import/plan
identities, population schemas and geometry, saved controls, all 36,864 raw rows,
12 final states and recomputed gates. Zero forwards or training updates were
performed by these auditors.

Publication validation also passed **714/714 local regression tests**, including
the 97 supplemental-auditor tests, and **42/42 separate cases-report tests**.
Ruff passed for both additive scripts and their tests. Retained local JUnit:
[regression](LOCAL_REGRESSION.xml), [report](LOCAL_REPORT_TESTS.xml). These local
tests are distinct from the source-isolated engineering receipts and the fitted
study. The 572-file selection, 557-file window/reference and 546-file V16
population seals still match current bytes; their historical bundles are
unchanged. No CI result or merge is implied by local validation.

Primary machine-readable results: [CPU](assay_cpu/RESULTS.json),
[CUDA](assay_cuda/RESULTS.json); terminal receipts:
[CPU](assay_cpu/FINISHED.json), [CUDA](assay_cuda/FINISHED.json).

## Post-hoc: residual magnitude versus answer use

The separate [cases-only report](CASES_ANALYSIS.json) and its
[reproducer](../../../scripts/report_v18_operand_selection_cases.py) use saved
logits and residual norms only, with no model imports, forwards or fitting.
This is explicitly post-hoc description, not a new pass criterion or intervention.

For this fixed toy head only, FP32 intact logits expose two residual coordinates:
`delta[30] = logit[0] / 8` (yes/no axis) and
`delta[31] = -logit[2] / 4 - 1` (shared non-answer suppression). In held-out CPU
cases, symmetric fits allocate approximately **99.9850–99.9989%** of aggregate
residual squared norm to the latter axis while remaining at 50% accuracy. The
five non-answer logits fall from -4 to means around -4.982 to -4.986. Ordered
fits allocate approximately **99.9101–99.9902%** to the answer axis instead;
CUDA reproduces this pattern.

These are ratios of squared sums, not causal attribution or per-example mean
fractions. Rounding can leave a small signed accounting remainder; the report
does not clamp it. BF16 is excluded from inversion because quantization obscures
the exact residual. Large residuals and lower full-vocabulary CE therefore need
not mean successful relational use even in this toy. No equivalent Mistral-head
decomposition is claimed.

## Interpretation and next boundary

The access path is not intrinsically unable to learn a relation when useful
identity/rank slots are supplied. This removes one uncertainty; it does not show
that the real writer produces such slots or that contextual Mistral states
expose the same query geometry. Symmetric failure is expected for these
deliberately order-invariant synthetic inputs, not a finding about an LLM.

The next [actual-writer transition](../../../docs/v18/ACTUAL_WRITER_TRANSITION.md)
is a separate, not-yet-frozen study: insert the query-independent writer while
keeping the existing toy common route, head, cap and losses fixed. Preserve the
final numerical failures and examine them independently. Then qualify actual
contextual/native-model behavior and explicit selection state ownership before
7B full updates. Do not add preservation supervision, gain changes or another
loss at the same time and attribute any improvement solely to selection.
