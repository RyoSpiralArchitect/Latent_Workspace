# V16 prerequisite: owned preparation and missing full adapter recovery 02

2026-10-14. **TERMINAL engineering PASS: full updates and serialized replay are exact.**
The additive repair has passed tiny CPU/CUDA and the selected real-7B comparison.
This is unchanged-learner engineering,
not V16 semantic FT, improved answers or a base non-regression result.

Execution source: `5736cd7d93f71bd48a567f33163adacb02f3d339`, 519 files in
[SOURCE_SEAL.json](SOURCE_SEAL.json). The [execution contract](../../../docs/v16/ADAPTER_FULL_RECOVERY_02.md)
and [handoff](EXECUTION_HANDOFF.md) define scope and the one-attempt stop rule.

## What was repaired

The installed native HF checkpointing method already registers an embedding
input-gradient hook. The historical helper registered a second one and replaced
the handle list, leaving the first registration unowned. The strict readout
adapter correctly refused it. Direct-HF component tests missed this composition.

The new native preparation boundary registers exactly once, admits repeated
identical preparation without mutation, and rejects duplicate/unowned hooks or
changed policies. It pins the installed method sources and retains the strict
adapter guard. No historical engine, math, source seal or old outcome was edited.
The preparation receipt is explicitly owned by the new checkpoint contract.

## Tiny gates (not 7B quality evidence)

- [Ordinary local CPU regression](PRELAUNCH_TESTS.xml): **295/295**, 35.73 seconds.
  [Final rerun](FINAL_TESTS.xml): **295/295**, 38.09 seconds, not additional cases.
- [Source-isolated CUDA qualification](tiny_cuda/FINISHED.json): **22/22**, zero
  failures/errors/skips, 12.50 seconds for tests; 17.399429 seconds total.
  Peak allocated CUDA memory: **67,511,296 bytes (64.383789 MiB)**.
- Those 22 cases comprise eight four-family × two-dtype preparation/forward/
  all-gradient cells, two negative historical-duplicate controls, ten rejection
  cases, and two FP32/BF16 complete-window update plus serialized-replay cases.
  Families: Mistral, GPT-2, OLMo2, Gemma2. The full training context binding remains
  separately Mistral-qualified; four readout layouts do not imply four 7B runs.
- Runtime: Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0, CUDA 13.2;
  RTX 5090, two CPU threads, TF32 disabled. Tiny cap: 4 GiB; wall limit: 300 s.

## Three separate provenance sets

| Evidence | Work actually selected | Terminal interpretation |
| --- | --- | --- |
| [Original migration](../v16_adapter_migration_20261014/README.md), source `7c3af3c` | Frozen old/new updates and replay: 80 pairs | Original remains INCOMPLETE_NO_RETRY; full never admitted |
| [Continuation 01](../v16_adapter_full_continuation_01_20261014/README.md), source `6bf8398` | Legacy full two windows: 32 pairs | Remains INCOMPLETE_NO_RETRY; adapter hook admission failed before its first pair |
| This recovery, source `5736cd7` | Only full adapter two windows plus serialized replay: 48/48 pairs | Full exact updates/replay PASS; not semantic qualification |

The complete original 26-file and previous 20-file bundles remain immutable,
including their historical READMEs and terminal/handoff records. Previous
manifest SHA256: `49c2b861805a1208e433011fa1dac9ed4c9e109161891bfb295a37acb1efbd2a`.
No completed frozen or full-legacy arm is recomputed. Combined planned budget
remains **160 pairs, eight unique windows and two replay windows**.

The retained-reference comparison permits only explicitly recorded source-commit
and preparation-provenance differences. It does not strip arbitrary metadata or
normalize tensor, gradient, loss, optimizer or RNG hashes. Checkpoint restoration
is within the new source contract, not cross-source. Full model binary snapshots
stay on Furnace; offline receipt verification does not reload those binaries.

## Terminal 7B result and resource observations

[FINISHED](raw/FINISHED.json) records
`EXACT_7B_FULL_PREPARATION_REPAIR_PASS_NOT_SEMANTIC_QUALIFICATION`.
[Offline replay](OFFLINE_VERIFY.json) verifies all 16 raw files and all three
source/evidence sets. The combined engineering view has **160/160 pairs,
8/8 unique windows and 2/2 replay windows**, with frozen and full now qualified
under this pinned Mistral/seed/runtime contract. Historical terminal failures
are not relabelled. No planned recovery cell is missing or retried.

The two [full-update comparisons](raw/full_EQUIVALENCE.json) match initial state,
all 32 ordered per-pair losses/spills/accumulated-gradient hashes and both
updated native/bridge/FP32-master/optimizer/RNG states. The
[serialized replay](raw/full_REPLAY.json) matches all 16 next-window pairs, its
complete update state and the entire v2 checkpoint-payload hash. No tolerance
was introduced. This is two updates at seed47, not a general numerical theorem.

Both updates changed **291/291 FP32 masters**, including **65/65 RMSNorm
masters**. Native BF16 changes occur in **237/291 tensors** per update, with
123,205,237 then 174,891,214 changed elements; bridge changes are 18/26 then
26/26 tensors. These are identical to the retained legacy reference. Master
updates are not a claim that every native BF16 tensor changed, nor evidence of
semantic improvement. See [step 1](raw/full_adapter_v2_step1.json) and
[step 2](raw/full_adapter_v2_step2.json).

| Observation | Value |
| --- | ---: |
| Recovery wall time | 1,164.569855 s (19 min 24.57 s) |
| Peak Torch CUDA allocation | 29,797,499,392 bytes / 27.751084 GiB |
| Peak Torch CUDA reservation | 30,461,132,800 bytes / 28.369141 GiB |
| Minimum sampled device free | 2,348,810,240 bytes / 2.187500 GiB |
| Minimum sampled host available | 61,800,992,768 bytes / 57.556660 GiB |
| Peak process RSS | 94,320,824,320 bytes / 87.843113 GiB |

Free-memory minima are phase samples, not continuous worst-case guarantees.
All original admission/stop/forecast thresholds were retained. These observations
qualify this adapter update/snapshot/restore path only; the new V16 reader or
longer sequences still need their own forecast. Both checkpoints remain on
Furnace: **29,054,823,004 bytes each**, 54.118825 GiB total. Their hashes are in
[step 1 receipt](raw/full_adapter_v2_step1_CHECKPOINT.json) and
[step 2 receipt](raw/full_adapter_v2_step2_CHECKPOINT.json). No weight was deleted.

The local launch exited 0; the identified process is absent and Furnace has no
compute client. The post-run persistent filesystem had 208,740,114,432 bytes
(194.404381 GiB) available. Only small receipts were copied to this repository.

## Lessons and next boundary

Preparation is an owned execution state, not incidental setup. Qualification must
exercise the production composition through complete updates and serialized
resume, not only the direct-HF components. Preserve model-native arithmetic in
qualified bindings while keeping reader/loss/optimizer mechanisms separate.

With this bounded full migration qualified, the next V16 gate is explicit ownership for
the slot-contrast reader's writer/common/interaction tensors and descriptor.
The old owner must not be bypassed by disguising the new reader as the old one.
Only after matched updates and snapshot/rejected/valid restore tests should a
bounded legacy-common / uncentered-control / slot-contrast FT comparison be frozen.
Reliable donor direction, original-base preservation and literal generations
remain distinct later gates. Bigger gradients or unchanged update math alone do
not demonstrate better use of memory.

Old **FAIL / winner:none / non_regression NOT_ESTABLISHED** and historical judge
missingness remain unchanged. No new generation, paid judge, V16 mechanism FT,
weight deletion, heartbeat or merge is included.
