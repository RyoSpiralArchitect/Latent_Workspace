# Adapter-owned V15 updates: graph sharing is part of the arithmetic contract

Client date: 2026-10-13. Additive successor to the reviewed readout component;
the old Mistral learner, audit source and result seals remain unchanged.

Post-execution qualification: [CPU and CUDA tiny update/replay checks passed](../../provenance/pilots/v15_adapter_owner_cuda_02_20261013/README.md),
but [PR #12 review found two checkpoint API ownership gaps](ADAPTER_OWNER_REVIEW_20261014.md).
The v1 API below does **not** provide snapshot independence or failure-atomic
restore. The additive [v2 successor](ADAPTER_CHECKPOINT_V2.md) repairs both and
passes [164/164 CPU and CUDA cases](../../provenance/pilots/v15_adapter_owner_v2_20261014/README.md).
Do not interpret v1's intended rejection contract as the repaired guarantee.
Use v2 for new checkpoint work. The PR remains draft for follow-up review and
does not replace the sealed 7B runner.

## Why the migration is more than replacing one forward call

An initial local negative control found identical scalar losses but different
base gradients when every intact/twin/unrelated read recomputed its own question
graph. On one synthetic affected pair, FP32 and BF16 both differed in 20 of 21
base parameter tensors; all 26 bridge gradients remained exact. The frozen
control had no gradient differences. These are tiny CPU diagnostics, not 7B
measurements or a semantic result.

The historical pair objective builds one question-prefix graph, then sums its
branches before backward through the backbone. Independent forwards change
where native-dtype addition/rounding occurs. Equal forward values and equal
single-answer gradients therefore do not prove pair/update equivalence.

## Separate backend, neutral owner

`HFTrainingReadoutAdapter` adds an exclusive one-objective graph scope. It
prepares the question once, prepares each teacher-forced completion separately
in historical construction order, and reuses the exact live normalized tensor
at the real head boundary. Every read still invokes the native outer model and
checks its recomputed input before sharing. Native normalization, full head
geometry and post-head transforms are not reimplemented. No graph survives into
another pair or update; no KV cache or selected-row head is introduced.

This deliberately conservative first implementation repeats some native forward
work. It is a parity reference, **not a speed optimization or a demonstrated 7B
memory envelope**. Any later elision of redundant work needs another matched
forward/backward/update qualification.

`AdapterNativeLearner` accepts an explicit training binding and reuses the
historical complete-window accumulation, CPU FP32-master Adafactor and bridge
AdamW update methods verbatim. The core has no model-family switch or norm/head
formula. `MistralTrainingBinding` is the **only qualified context binding in this
unit**; four-family readout tests do not imply four-family end-to-end training.

The separate six-term paired objective retains the old reductions, donor hinge,
unaffected/unrelated controls and residual penalty. Its denominators still refer
to the fixed two-world/eight-query protocol. A two-pair synthetic unit-test
window is not a balanced real training window or a new loss design.

## New, explicit checkpoint format

`v15-adapter-native-resume-v1` binds the original-base content identity, objective
metadata, reader semantics, adapter and context descriptions, native schemas,
all native buffers (including nonpersistent ones), module modes, checkpointing
policy, execution runtime/arithmetic, optimizer policy, masters and RNG. Restore
requires the expected content hash, metadata and run contract, and starts from
the pinned original before restoring current masters. Loaded optimizer/master
state is copied, so a resumed update cannot mutate the input checkpoint payload.

The original reference is an **identity**, not a new teacher bank or preservation
loss. Current-base zero identity still does not establish original-base quality.
Mode/buffer changes, active objective/window saves, changed optimizer settings,
unrecognized hooks and incompatible resumes fail closed. The installed HF input
gradient hook used by non-reentrant checkpointing is explicitly recognized;
arbitrary hooks are not accepted as equivalent. Out-of-band `.data` mutation and
untrusted concurrent owners remain outside the contract.

## Qualification scope and next gate

Local regressions compare full/frozen × FP32/BF16 × checkpointing off/on:
two declared synthetic windows, and saved window 1 → exact next window 2 replay.
They compare native weights, bridge, FP32 masters, both optimizer states and RNG,
not only loss or logits. A separate four-layout test compares all gradients to
an independent native head-hook reference. Malformed policy/resume and deliberate
independent-forward controls are retained.

The [fixed CPU/CUDA qualification plan](../../configs/v15/ADAPTER_OWNER_QUALIFICATION_PLAN.json)
uses 71 tiny synthetic test cases and the reviewed pre-import source launcher.
It permits **zero real-model updates, new sequences, judge calls or weight
deletions**. CUDA admission requires no competing GPU workload and a 6 GiB Torch
allocation ceiling. Each execution has its own source-bound terminal receipt;
failures are preserved, never relabelled as a pass or automatically retried.

After the review's snapshot/restore gaps are repaired and requalified, a
**separately frozen real-Mistral complete-window budget and
memory/resource admission** is needed before replacing the sealed 7B runner.
Keep numerical transport, useful semantic interaction and original-reference
preservation as later independent factors. Old **FAIL / winner:none /
non-regression NOT_ESTABLISHED** remain unchanged.
