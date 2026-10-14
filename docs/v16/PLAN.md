# V16: useful workspace interaction, without sacrificing the original base

2026-10-14. **Reader prototype with tiny-qualified state ownership, not a trained winner.**
V15 remains the native full-update/state-ownership milestone. V16 names the next
learner improvement, not a relabelling of the historical unsuccessful models.

Current [prototype evidence](../../provenance/pilots/v16_slot_contrast_prototype_20261014/README.md):
16/16 ordinary local CPU tests pass, including tiny Mistral FP32/BF16 zero-path
and live-backward checks. This is not a source-isolated CUDA/7B qualification.
The subsequent [state-owner integration](SLOT_STATE_OWNER.md) separately passes
[145/145 source-isolated CPU and CUDA cases per runtime](../../provenance/pilots/v16_slot_state_owner_20261014/README.md),
including 16/16 exact serialized replay cells. This qualifies tiny state mechanics,
not 7B new-reader memory use, factual binding, response quality or preservation.

## What the evidence actually motivates

The [native readout audit](../../provenance/pilots/v15_readout_adapters_20261010/README.md)
found surviving hidden differences on 16/16 affected pairs and changed vocabulary
logits on 64/64 pairs, but no affected no/yes-logit changes. Intended donor
direction was only 2/4 per state. Thus neither “wire the head” nor “increase the
precision/gain” alone is an established remedy.

The [factor audit](../../provenance/pilots/v15_reader_factors_20261010/README.md)
found 87.966884% output-projection energy in one leading direction and a
99.839031% mean-slot/actual interaction-norm ratio for the modulated reader.
The mean still carries world content; it is not a content-free control. The
[short training pilot](../../provenance/pilots/v15_native_learner_20261010/README.md)
did not turn increased query sensitivity into donor-directed changes. Full
workspace accuracy reached 18/32 with three repairs and one new error; its
updated backbone alone was 15/32. Neither aggregate count establishes a base floor.

The [three-judge synthesis](../v14/FT_BETA_JUDGE_SYNTHESIS.md) also matters:
one changed causal answer was stably preferred across settings, but judgments
were selected, sometimes inconsistent and sometimes mechanically wrong.
Preserve the possibility of useful common-response changes. Do not train on
judge explanations as gold or remove the dominant direction automatically.

## First isolated mechanism: common response plus slot contrast

`SlotContrastWorkspaceBridge` is an additive, model-independent **prototype**.
The existing query-independent writer and modulated common reader are retained.
An additional bias-free reader receives question features and written slots.
Its candidate branch centers normalized slots before attention; its matched
control uses the same uncentered normalized slots. The two have exactly the
same trainable tensors, initialization and update-count budget. Centering adds
operations: this is parameter-matched, not a proved FLOP/runtime match.

Crucial executable properties:

- Initially the new output projection is zero, so both routes exactly reproduce
  the common reader's output. No pretrained common component is removed.
- Written-zero memory gives zero total correction even with nonzero projections.
- Identical valid slots give **exactly zero candidate interaction**, including
  non-power-of-two slot counts and masked padding. An uncentered carrier can
  still drive the control. Anchor-before-mean centering avoids a rounding-only
  violation of this null.
- The interaction uses at most 25% of the common route's remaining norm budget:
  `||delta_I|| <= 0.25 * (cap - ||delta_C||)`. The common output is not rescaled;
  triangle inequality keeps the total within the original cap, modulo floating
  point rounding. The budget is identical in candidate and control.
- Inputs are question features, written memory and mask only. Labels, answer
  rows, donor-side IDs and four-corner diagnostic factors do not enter inference.
- The existing native readout adapter executes normalization, casting and the
  complete vocabulary head. No FP32-head intervention is bundled into this factor.

This removes **one pathway's identical-slot carrier shortcut**, not all shortcuts
in the total reader. Common output can still be query-dependent; diverse random
slots can still produce interaction. Zero interaction on mean slots is now
partly architectural and cannot itself count as semantic success.

The initial zero output still gives zero upstream interaction gradients until
an output update occurs. Centered attention can also become weak when slots
collapse, and a saturated common residual leaves little interaction budget.
Record slot diversity, common/interaction norms, available budget, cap saturation,
per-loss gradient alignment and native quantization—not just query gradient size.
Preserving a common forward component does **not** preserve its weights during
training or guarantee useful behavior survives.

## Staged execution and stop rules

1. **Checkpoint repair, unchanged learner math.** Use the
   [v2 owner](../v15/ADAPTER_CHECKPOINT_V2.md), not the known-defective v1 checkpoint
   boundary. Retain historical sources and failures. Tiny repair tests are not
   real-Mistral migration evidence.
2. **Real-Mistral migration before changing the learner.** Fulfil the
   [16-pair-window migration gate](../v15/ADAPTER_7B_MIGRATION_GATE.md): pinned
   original Mistral-7B-Instruct-v0.3, BF16, unchanged six-term objective, complete
   ordered windows, old/new sequential arms, exact full/frozen update and replay
   comparisons. Freeze source, runtime and host/GPU/checkpoint forecast first.
   The [new execution contract](ADAPTER_MIGRATION.md) plans eight unique and two
   replay windows (160 backward pairs), with no generation or semantic factor.
3. **Integrate the candidate's explicit reader descriptor/state ownership.**
   The prototype intentionally is **not admitted by the v15/v2 owner's reader
   whitelist**. Qualify its writer/common/interaction ownership, gradients,
   matched updates and snapshot/rejected/valid resume in a new format before FT.
   Do not bypass the guard by disguising the new class as the old reader.
   **Now complete at tiny CPU/CUDA scale:** the dedicated state binding and
   `v16-slot-contrast-native-resume-v1` format retain the old guard unchanged.
   The source-sealed 145-case suite passes independently on both devices.
4. **One semantic factor at a time.** The first prospective pilot compares
   legacy-common reference, raw matched-capacity control and slot-contrast
   candidate. Candidate versus raw control is the mechanism comparison;
   candidate versus legacy alone confounds added capacity. Use the same fresh
   base/bridge seeds, native arithmetic, losses, data order, full-window/update
   counts and evaluation schedule. Full versus frozen base is a separate axis.
   Exact 7B run budgets/seeds and tensor/parameter manifests are not yet frozen;
   this document does not launch training or choose a winning checkpoint.
5. **Measure correct use, then preservation and generation.** Require native
   reciprocal donor-direction and stability controls, not just a larger hidden
   norm, lower CE or more visible logits. Report affected/unaffected/unrelated,
   mean-slot, random/diverse, zero-memory and original/updated direct-base results
   with denominators and paired repairs/new errors. Do not promote exposed-set
   diagnostics into generalization evidence.

The independent next factor is a fixed original-base preservation bank: capture
from the pinned original once, hash/own it in resume state, and separate it from
current-theta zero identity. Do not blindly imitate original errors. Freeze a
fresh correctness battery and uncertainty/noninferiority contract as specified
in [the FT-beta plan](../v14/FT_BETA_IMPROVEMENT_PLAN.md) before a base-floor claim.
After that, a same-seed literal answer bank and human-readable differences test
the useful behavior. Paid judges remain closed unless separately authorized.

## Storage history and current capacity boundary

The live 2026-10-14 Furnace check found an idle RTX 5090, about 119 GiB available
host RAM and **46,326,988,800 bytes (43.145 GiB) available on the persistent
filesystem**. `/tmp` and `/dev/shm` are RAM-backed, not alternative durable
checkpoint storage. The historical contract requires 50 GiB *remaining after*
forecast writes. Two approximately 27-GiB full checkpoints already imply about
104 GiB before writes; the full V16 multi-arm forecast may need more.

That initial check blocked dispatch. No gate was loosened and no checkpoint or
replay was dropped to fit the disk. Prototype integration cannot be reported as
7B qualification or improved response quality.

Ryō requested a **candidate list only**. The subsequent
[read-only inspection](../../provenance/inventory/v16_storage_inspection_20261014/README.md)
found 228 weight-like files (365.787 GiB) in scoped experiment directories,
excluding the pinned base/cache. It distinguishes likely duplicate step-8
exports from retention-protected states and unverified warmup base exports.
No cleanup was authorized by that inventory alone.

Ryō then explicitly selected **all V12 experiment weights**. The
[separate cleanup](../../provenance/inventory/v12_weight_prune_20261014/README.md)
recorded all 90 hashes and copied/verified 315 metadata files before removing
222,055,662,879 logical bytes (206.805452 GiB). Post-cleanup available space is
267,974,426,624 bytes (249.570633 GiB). V14/V15, other experiment weights and
model caches remain unchanged. This overrides two-state retention for V12
only. Hashes are not reconstructible weight backups.

The storage obstacle is resolved. The separately sealed
[migration](../../provenance/pilots/v16_adapter_migration_20261014/README.md)
passed frozen exact updates/replay: 80/160 planned pairs, 4/8 unique windows
and 1/2 replays. Full never started because the warmed process missed the
unchanged 31-GiB start floor; original status remains INCOMPLETE_NO_RETRY.
Ryō authorized [only full in a fresh process](ADAPTER_FULL_CONTINUATION_01.md).
This retains all existing math and thresholds; it is not new V16-reader FT.

Continuation 01 completed the legacy full reference but failed adapter hook
admission before its first pair. The separate
[owned-preparation recovery](../../provenance/pilots/v16_adapter_full_recovery_02_20261014/README.md)
now completes the missing 48 pairs with exact full updates and serialized
replay. Combined: 160/160 pairs, eight unique and two replay windows; both old
terminal failures and their entire bundles remain unchanged. Peak Torch CUDA
allocation/reservation in the recovery: 27.751/28.369 GiB; this is the unchanged
common reader's envelope, not a forecast for a new reader or longer inputs.

Staged gate 2 is therefore met for the pinned two-update/seed47 Mistral contract.
Gate 3's reader ownership subsequently passed the separate tiny CPU/CUDA
qualification linked above. Next freeze the three-arm semantic pilot and admit
its own resource envelope. The production setup must remain explicitly
owned/idempotent, with composition tests covering the actual preparation path
through complete updates, snapshots and restore.
No loss, tolerance or hook rejection was relaxed to obtain this engineering PASS.

The [historical continuation result](../../provenance/pilots/v16_adapter_full_continuation_01_20261014/README.md)
localized the preparation-composition gap at 112/160 pairs and motivated the
separately authorized recovery above. It is retained as a failed terminal,
not rewritten into a success. The slot-contrast reader is now state-integrated
and tiny-qualified, but remains untrained on 7B; unchanged-reader migration
does not qualify the new reader's real-model capacity or behavior.

### Three-arm storage screen after V14 cleanup

After retaining the migration checkpoints, the next live screen found only
about 188 GiB available. Keeping two states per condition across three arms has
a conservative planning envelope of **3 × 64 GiB outputs + 50 GiB remaining =
242 GiB**. No new training was dispatched with that storage deficit.

Ryō explicitly authorized [V14 experiment weight cleanup](../../provenance/inventory/v14_weight_prune_20261014/README.md).
All 44 weight hashes and 502 literal metadata copies were committed and pushed
before deletion. The terminal records **44/44 files / 82.837845 GiB removed**,
**270.661411 GiB available**, preserved metadata hashes and unchanged stats for
98 out-of-scope weights (including the four V16 migration checkpoints).
The original model/cache and all V15/V16 checkpoint payloads are outside the
deletion scope. Hashes cannot reconstruct the deleted V14 weights.

The storage screen now passes with **28.661411 GiB beyond the forecast and
floor**. The 50-GiB floor and each new condition's two-state retention stay intact.
This is capacity recovery only: the precise three-arm execution contract, new
reader GPU/host envelope, full-update/evaluation evidence and base preservation
remain unestablished. No model calls ran during cleanup.

Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** remains unchanged.
The closed diagnostic-judge status remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`;
invalid, unknown and undispatched outcomes are not repaired by V16 planning.
