# V23 matched preservation full-FT experiment 01

**Frozen design; [472/472 CPU and CUDA qualifications pass](../../provenance/engineering/v23_preservation_ft01_20261022/README.md).
Real-model teacher/canary/replay/training is a separate in-progress pipeline.**
The [completed gradient audit](../../provenance/engineering/v23_gradient_audit01_20261022/TERMINAL.md)
is immutable. This is a new experiment, not its continuation or a V22 resume.
See the [execution handoff](../../provenance/engineering/v23_preservation_ft01_20261022/EXECUTION_HANDOFF.md).

## Question and matched conditions

Does ordinary-host preservation improve retention during native full FT
without sacrificing useful workspace computation? The audit's small negative
world/KL cosine motivates measurement, not a prediction of Adafactor updates.
The 99.018% identity share is residual training CE, not generation errors;
median Q/M state-gradient ratio 1.235 does not justify universal Q scaling.

The [plan](../../configs/v23/PRESERVATION_FT_01.json) varies **P only**:

| Condition | CE | Ordinary-host forward KL |
| --- | --- | --- |
| off | unchanged whole-window target mean | disabled: exact legacy path |
| on | same | coefficient 1.0, whole-window preservation-target mean |

Both start from the same pinned original Mistral-7B-Instruct-v0.3, seed 47,
cut 4, BF16/eager, non-reentrant checkpointing, all 7,248,023,552 native
parameters, CPU FP32 Adafactor, LR 2e-7, weight decay zero and clip norm one.
Both reuse **V22's** 32 windows / 723 rows / 20,860 supervised targets (16,763
preservation targets). Neither starts from V22 or canary-updated weights.
Coefficient one is a predeclared equal-mean contrast, not fitted to gradient
ratios or outcomes and not claimed optimal. New world data, B, I, recurrence
and Q scaling remain separate factors; the 512 new groups are not used here.

```text
J = sum CE(all targets) / N
  + lambda * sum KL(original teacher || student)(preservation targets) / Np
```

One combined scalar backward per eligible row retains the existing ordered
native-dtype accumulation, CPU masters, clipping and native casts. Diagnostic
FP32 across-row gradient spills do not replace the training arithmetic.

## Owned targets and checkpoint semantics

The same owner now admits a versioned objective and engine-owned
[`PreservationTargets`](../../src/latent_workspace/preservation_objective.py).
Its registry covers all 728 distinct training/canary rows. Exactly 89 ordinary
rows (38 instruction, 41 prose, 10 code) supply 18,727 target positions.
Every training window has at least 309 preservation targets; each canary has
1,109. Empty-memory world controls are **not** preservation rows. Unknown keys
or uncovered rows fail closed.

The original host in eval mode supplies FP32 log probabilities for every
active causal position, all 32,768 vocabulary entries, T=1, on complete
identical English training contexts. Tensor payload is 2,454,585,344 bytes
(2.286 GiB). These are teacher-forced distributions, not generated text.
Same-weight eval/train forward differences are recorded for all 89 rows;
zero KL is not assumed or forced. Private tokens/targets remain on Furnace.

The source-verified completed teacher-role manifest admits the receipt. Its
`input_sha256` is canonical JSON over the complete ordered registry, distinct
from target-file byte SHA256. Body hashes, exact keys/shapes, FP32/finiteness/
log normalization, causal shift, complete row content and actual forwarded
IDs/labels/masks/memory are checked. Each selected tensor is rehashed before
use, lifecycle boundaries recheck the body, and only one row moves to GPU.
There is no second live teacher during FT.

Off retains literal CE and v1 payload. On uses
`ltws-native-owner-preservation-v2`, binding coefficient, both normalizations,
source/base/teacher/registry, CE/KL token cursors, ordered histories, execution,
moments, masters and RNG. Invalid targets/provenance fail before restore
publishes native tensors or RNG. These objectives are not interchangeable
resume formats. The earlier metadata-only binding remains historically
metadata-only; body validation is a new layer.

## Gates and resources

1. **472 selected cases on CPU then CUDA**, 4 GiB / 900 seconds per device,
   no skips. CPU oneDNN is explicitly off; BF16 stays BF16. Four host families,
   tied leaves, recomputation, independent CE/KL reference updates, exact
   disabled-path parity, corruption guards and fresh-process replay are tested.
   Local development subsets do not replace full Furnace qualification.
2. Build and validate the 89-row original-host reference bank.
3. Positive-P longest-context two-update canary, save step 1, then separate-
   process step-2 replay: row losses, spilled gradients, native/master/moments,
   RNG and **entire v2 payload**, including KL history/cursors, must match.
4. Only then off/on each run 32 updates in fresh processes. Each saves only
   step 32; no best-checkpoint selection. Legacy v1 restart stays in the tiny
   suite; the additional real-7B canary qualifies the new positive-P objective.
5. Same exposed 40-row V22 dev NLL before/after each arm, diagnostic only.
   Unseen retention, new confirmation/OOD and generation remain separate gates.

The differentiable native PyTorch lane is necessary for owned W/Q/R backward
and restart; this is not a serving workload. Managed-runtime doctor is checked
without changing that environment. Each real role retains 31-GiB GPU admission,
30.5-GiB allocator cap, 0.75-GiB GPU floor, 100-GiB host admission / 24-GiB host
floor, 50-GiB disk floor and four-hour wall limit. The audit's 17.7802-GiB peak
is not a training-memory estimate.

Storage forecast is 3 x 28-GiB checkpoint maxima + 2.5-GiB targets + 50-GiB free
floor = **136.5 GiB**, before small evidence overhead. The observed 145.4-GiB
free disk fits, subject to live admission. No additional weights are deleted;
base and V22 step16/32 stay. Every stage is source-sealed, fresh and no-retry.
No source edits inside a running trial, provider/judge calls, new generations,
exports, PR/merge or Hub release occur.

**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. Completing
64 training updates or exact restart is not a quality/release result. Preserve
missingness on failure; never reduce the plan or retry under the same identity.
