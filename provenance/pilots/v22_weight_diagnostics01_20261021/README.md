# V22 weight diagnostics 01 — terminal results

**The remaining errors are not repaired by increasing head precision alone.**
On this exposed panel, the MMLU changes come predominantly from changed head
inputs, while world errors are concentrated at an early answer-identity decision.
This narrows the next investigation; it is not a new quality win or release gate.

Execution source: `35cbe95fa498d95c8f967b428758ddac0bd29966`, **734 sealed files**.
The [plan](../../../docs/v22/WEIGHT_DIAGNOSTICS_01.md) was frozen after observing
[comparison 01](../v22_base_comparison01_20261021/README.md), before this diagnosis.
The checkpoint, exact inputs, previous scores and generated texts are unchanged.
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains in force.

## What completed

- CPU and CUDA qualification: **158/158 each**, no failures, errors or skips.
  The 20 new tests include device-aware BF16 observation across four tiny host
  architectures and the actual diagnostic runner. Legacy fixtures still mix CPU
  and device-aware coverage; 158 is not a count of CUDA-kernel tests.
- **1,140/1,140 MMLU rows**, **384/384 world conditions**, **2,814/2,814 recorded
  next-token positions**, and **291/291 physical parameter tensors**.
- Every historical MMLU score and complete-target teacher loss reproduced
  exactly. Fixed-prefix next-token disagreement: **0/1,566 base; 0/1,248 V22**.
- **570/570 four-cell head factorials**; both same-shape self cells reproduce
  exactly. Complete V22 owner restore and before/after native weight identity pass.
- Zero new generated sequences, real-model updates, checkpoint saves, weight
  deletions, provider calls or retries. The checkpoint-write directory is empty.
  Both workers exited and Furnace has no remaining compute client from this run.

The world conditions represent **96 unique rows in 16 twin groups**, not 384
independent tasks. The MMLU panel was already exposed. There is one trained
checkpoint, not independent training replications. No new free-writing or code
quality judgement was made.

## 1. MMLU: final rounding is not the entire regression

All alternative arithmetic below uses the **same BF16-rounded hidden states and
head weights**. It is not an FP32 decoder and does not replace the benchmark.

| Readout | Base correct / 570 | V22 correct / 570 | Base-only losses | V22-only repairs | Ties, base / V22 |
|---|---:|---:|---:|---:|---:|
| Original native BF16 | 356 | 354 | 2 | 0 | 15 / 18 |
| FP32 head, same states/weights | 355 | 355 | 4 | 4 | 0 / 0 |
| That FP32 result cast back to BF16 | 356 | 354 | 2 | 0 | 15 / 18 |

Strict unique-maximum native scoring remains **351→349/570**, with five losses
and three repairs. Equal aggregate FP32 accuracy hides **four losses and four
repairs**; it does not establish the requested base floor. Casting back reproduces
these choice outcomes, not bitwise equality of every vocabulary logit: native
BF16 GEMM and FP32-then-cast are distinct arithmetic paths.

Both original argmax losses remain wrong under FP32 head projection. The gold
answer is D and the competitor B in both cases:

| Exposed question | Base FP32 D−B | V22 FP32 D−B | Hidden-only effect | Head-only effect | Interaction |
|---|---:|---:|---:|---:|---:|
| nutrition, `9596` | +0.139412 | −0.021511 | −0.158493 | −0.002441 | +0.000011 |
| world_religions, `13900` | +0.125656 | −0.038277 | −0.161421 | −0.002542 | +0.000027 |

The first two columns use full-vocabulary FP32 projection; the factorial effects
use a matched four-row FP32 GEMV shape, hence a few micro-units of numerical
difference. In the factorial, changing only the head changes **0/570 predictions**
at either fixed hidden-state arm. Changing hidden states with the base head
changes **11/570 predictions**, with four correctness losses and four repairs.
All four cells score 355/570, but they are not the same answers.

For these two D−B margins, the hidden-state term accounts for approximately
**98.5%** of the total change under this specific additive decomposition. This
is evidence against a head-only repair for these cases, **not** identification
of a particular layer, loss term, or universal source of FT regressions.

## 2. World failures: the decisive token is hidden by an average

The existing latent-route outcomes remain **64/72 test + 19/24 OOD = 83/96**.
Teacher forcing gets **611/623 gold tokens** as argmax, yet 13 complete answers
are wrong. Of those 13, seven first diverge at token index 0, five at index 1,
and one at index 5: **12/13 fail within the first two generated tokens**.

At each failed answer's first token fork, that token contributes
**94.806%–99.645% of the complete gold teacher-forced NLL**. Later easy tokens
and EOS dilute the average. This localizes a decision bottleneck; it does not
prove that merely reweighting the existing cross-entropy will solve it.
FP32 head projection selects the gold token at **0/13** of these failed forks.

Every failure, memory, query, base/inline control, token margin and probability
is retained in the [complete failure panel](FAILURE_PANEL.md), not a selected
success gallery. Two literal examples:

- **Missing evidence:** `wb01-event_order-test-0015/s0/absent` has no memory.
  Target: `Not specified.`; base: `Not specified`; V22: `Nfzyxfrnok.`.
  V22 chooses the first event named in the question. At the initial fork the
  gold probability is **0.42839**, native gold margin **−0.25**, and FP32-head
  margin **−0.27954**. This is an observed query-option fallback, not proof of
  a universal first-option heuristic. Both failed event-order abstentions remain.
- **Exact copy:** `wb01-linked_location-ood-0058/s1/affected` should answer
  `Nymszrcrff.`. Base latent: `Nymszrcrff`; V22 latent: `Nymszrcrk.`;
  V22 inline: `Nymszrcrff`. At index 5, gold `ff` has probability **0.15765**
  and margin **−1.625** versus the chosen `k`; FP32 margin is **−1.53716**.
  The same memory content succeeds inline. The error is route-dependent in
  this case, not resolved by changing the last projection precision.

### A separate instrument issue: full teacher sequence versus prefix-only

Even at identical preceding token histories, computing the whole teacher
sequence and computing only the prefix need not produce identical BF16 scores.
Across all comparable positions, gold-argmax correctness disagrees at **2/867
base** and **2/1,111 V22** positions. These are not failures to replay the old
generation: **the prefix-only replay matches that generation exactly**.

One V22 disagreement is substantive: `linked_location-ood-0023/s1/unaffected`
selects the gold `er` by tie-breaking in the full teacher forward (margin 0),
but the prefix-only forward prefers `k` (gold margin −0.25), producing
`Nkxfboiobj.` instead of `Neruhfebov.`. The other V22 disagreement is period
versus EOS on an answer already accepted by the unchanged normalization.

Existing tiny same-length future-token causality tests pass. This run does
**not** distinguish sequence-shape numerical sensitivity from any real-7B
causality/layout defect. A matched-extent future-content control must precede
that attribution; do not describe the observation as proven answer leakage.

## 3. Weight transport: full updates, partial BF16 visibility

All **7,248,023,552 parameters / 291 tensors** were examined against the pinned
original and the verified step-32 FP32 masters, with chunked CPU FP64 reductions.
Every native value equals its master cast exactly.

| Tensor group | Tensors with changed native values / total | Native elements changed | FP32 master elements changed |
|---|---:|---:|---:|
| Attention | 128 / 128 | 12.4192% | 99.9937% |
| MLP | 96 / 96 | 11.1025% | 99.9940% |
| Embedding | 1 / 1 | 1.5613% | 14.7853% |
| Head | 1 / 1 | 10.2464% | 99.9926% |
| Normalization | 13 / 65 | 0.9180% | 95.7516% |

Overall, **7,133,205,643 master elements (98.4159%)** changed, compared with
**808,400,857 native elements (11.1534%)**. There are **6,324,804,786** changed
master elements whose native values still equal the original. All 291 master
tensors changed; 239 native tensors changed; the **52 entirely unchanged native
tensors are normalization weights**. Their names and all raw per-tensor measures
are published, not inferred from a single norm statistic.

This is observable quantization of updates, not evidence that the optimizer
failed or that all invisible updates are useless. Norms need special caution:
large norm-weight energy dominates the global relative-L2 denominator. Inspect
the per-group measures in [SUMMARY.json](SUMMARY.json). Neither a larger learning
rate nor forcibly moving norm weights is justified by these counts alone.

## Verification, resources and next step

The original checkpoint remains 29,004,418,636 bytes, SHA-256
`cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`;
its full owner payload and training fingerprint match before the explicit
inference-policy transition. Original comparison input SHA-256 is
`3370e6e19c82065f1593f85865b89acb863178d92eb81400ee3bdd060475d4eb`.

Base / V22 role time: **218.67 / 405.66 seconds**. Peak CUDA allocated:
**17.455 / 17.955 GiB**; reserved **26.379 / 26.879 GiB**. Peak host RSS:
**5.542 / 55.761 GiB**. The managed-runtime check passed; the custom native
graph required the existing read-only PyTorch runtime. Nothing was installed.

Offline verification checks the old bundle and literal answer bank, both source
records, qualification XML and manifests, all terminal manifests, paired rows,
token denominators, unchanged weights and literal failure-panel regeneration:

```bash
python3 provenance/pilots/v22_weight_diagnostics01_20261021/summarize.py --verify
python3 provenance/pilots/v22_weight_diagnostics01_20261021/interpret.py --verify
```

The [interpretation audit](INTERPRETATION_AUDIT.json) is explicitly post-result;
[raw evidence](furnace/raw/) remains immutable. The next proposal is
[prefix-instrument qualification, then separable reader and preservation
factors](../../../docs/v22/POST_DIAGNOSTIC_NEXT_STEPS.md), **not immediate larger
FT, a head swap, or release**. No inspected test target is admitted to training.
