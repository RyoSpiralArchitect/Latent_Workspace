# V16: explicit slot-contrast state ownership

2026-10-14. Engineering integration only; no new 7B learner experiment.
[Terminal qualification](../../provenance/pilots/v16_slot_state_owner_20261014/README.md):
145/145 cases independently on source-isolated CPU and CUDA, plus 440/440 local
regression and 14/14 offline-verifier cases. All 16 replay cells pass per runtime.

`SlotContrastNativeLearner` admits the sealed `SlotContrastWorkspaceBridge`
through a separate `SlotContrastStateBinding`. The historical v15/v2 whitelist
still rejects it. The new checkpoint format is
`v16-slot-contrast-native-resume-v1`; old checkpoints are not silently converted.

## What is owned

The reader contract partitions every parameter exactly once:

| Partition | Parameter prefix | Tiny fixture tensors |
| --- | --- | ---: |
| Query-independent writer | `common.writer.` | 20 |
| Common reader | remaining `common.` | 6 |
| Question/slot interaction | remaining reader parameters | 6 |

The candidate and raw matched-capacity control have identical tensor schemas
and initial values, but different contracts. A checkpoint cannot cross that
mode boundary merely because its tensors fit. Mode, interaction fraction, cap,
common modulation strength, normalization epsilon, attention settings, writer
mode/steps, train/eval modes and ordered partitions are bound in the descriptor.
Only the canonical module graph is admitted. Module/parameter/storage
replacement, aliases, cross-base storage, instance method overrides, hooks,
unregistered attributes/tensors and added persistent/nonpersistent reader
buffers are rejected. This first format intentionally owns **no reader buffers**;
supporting such state needs a new qualified contract, not ignored keys.

Meta-device canonical construction validates shape/policy without allocating a
second reader or changing CPU/CUDA RNG. Reader tensors stay trainable FP32 on
the one native-model device. The reader knows no transformer layer layout,
normalization/head formula, answer label or donor ID. Context/readout ownership
still belongs to the model binding. Only the Mistral training binding has been
qualified here; model-independent interfaces do not establish all-model parity.

## What does not change

The complete ordered CPU-gradient window, native-dtype accumulation, family
clipping, FP32 CPU base masters, Adafactor, bridge AdamW, native cast/copy and
paired six-term objective are unchanged. `step`, `begin_window`, `save` and the
post-preflight restore publication routine are inherited, not rewritten.
The new constructor and restore preflight are additive specializations of the
sealed v1/v2 sources: the descriptor boundary changes, not the update math.

Native gradient-checkpoint preparation uses the separately qualified, idempotent
owned-hook helper. Preparation, model binding, reader binding, complete update,
serialization and replay are tested together. No new loss, precision intervention,
original-base imitation bank, seed search or extra generation is introduced.

## Snapshot and resume boundary

Snapshots are independent detached CPU tensors and independently copied metadata.
They include both optimizers, FP32 masters, native aliases/buffers, base identity,
native execution policy, original-base provenance and all RNG state. Saving is
exclusive and requires a complete-window boundary with no live gradients.

Restore requires an independently supplied content hash, metadata and run
contract, plus a fresh pinned original base and canonical reader target. All
reader, native, optimizer-moment/step and private-generator checks finish before
copying any target tensor or restoring global RNG. Rejected restores must preserve
target contents, versions, pointers, trainability and RNG. A fresh same-shaped
canonical module is a valid target; replacing a module inside a live owner is not.

These are compatibility/error-path guarantees under exclusive ownership, not a
security sandbox or a transaction against device failure, process death or
concurrent mutation. Cross-runtime/device migration is deliberately not promised.

## Fixed tiny qualification

The [selection](../../configs/v16/SLOT_STATE_QUALIFICATION_PLAN.json) contains
145 cases; the source-isolated runner requires an immutable commit and source
seal before importing project code. CUDA has a 4-GiB allocator ceiling and
900-second test deadline, refuses another compute client, and writes exclusive
STARTED/FINISHED receipts. It does not load the 7B checkpoint or call a provider.

- 16 serialized replay cells: candidate/raw × FP32/BF16 × full/frozen × native
  checkpointing on/off. Each runs two complete 16-pair windows, saves step 1,
  restores it into a fresh target and exactly replays all step-2 pair receipts,
  gradients, updates, owned state and RNG. Comparisons are within a runtime.
- Eight independent CPU-accumulation/optimizer reference cells (both modes,
  dtypes and update scopes, production checkpointing enabled).
- 66 corrupted-payload rejection cases, including rehashed invalid payloads;
  21 live-policy rejection cases; 19 incompatible-target rejection cases and
  two valid fresh-target replacements; five late base-optimizer rejection cases.
- Two partition/gradient-warmup cases, two step-zero/window-boundary cases,
  two bidirectional snapshot-isolation cases, one matched-initialization/old
  whitelist check and one inherited-update/publication-method check.

Zero interaction output projection is intentional: the initial upstream
interaction-query gradient is zero, but the output projection receives a live
gradient. After an update, question-route gradients must exist and be finite.
This does not impose a minimum useful gradient, establish semantic selectivity,
or prove that later training will use factual memory well.

The separate 14-case offline receipt-verifier suite checks source/artifact
hashes, selected test identities, counts, resource bounds and unchanged claim
ceilings. These verifier fixtures are explicitly synthetic, not run evidence.

## Boundary after qualification

The results are published in the separate provenance bundle after terminal replay.
Old bundles, their failure states and all sealed source files remain unchanged.
The scientific gate stays **FAIL / winner:none / non_regression NOT_ESTABLISHED**.

Next, freeze a bounded three-arm real-Mistral comparison: common reference,
raw matched-capacity control and slot-contrast candidate. Account separately for
the extra interaction tensors, FP32 gradient/master/optimizer state, native
attention graph and two retained checkpoints; the old common-reader 27.751-GiB
peak is not a new-reader forecast. Admit CPU/GPU/disk budgets before launch.
Preserve full-window data order and unchanged losses/readout; full versus frozen
is a separate axis. Judge calls, new answer banks and preservation supervision
remain later, independently scoped work.
