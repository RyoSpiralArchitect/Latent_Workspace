# V18 native selection pilot 01 — first real 7B full update: results

2026-10-15. **COMPLETE AND VERIFIED.** On the real pinned Mistral-7B, the V18
owner reproduced the V16 slot-contrast step-1 receipt bit for bit; the
centered-ordered condition then completed two full-parameter update windows;
a fresh interpreter replayed window 2 exactly from the step-1 checkpoint. This
establishes engineering integration, exact resume and resource use on the real
model. It does **not** establish memory-dependent answers, held-out benefit,
selection advantage or base non-regression: every intact/twin memory contrast
left the native answer gap exactly unchanged. The old **FAIL / winner:none /
non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

Execution commit `fb409ed2ba6ff3b2be209f7a97894b02637f5b2f`, bound by the
[599-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `0f0bd799…a1d1b`), written on
the clean Furnace checkout and byte-identical to an independent local seal. The
[execution handoff](EXECUTION_HANDOFF.md) records paths, pre-dispatch checks
and the one detached [dispatch script](furnace/launch_native_pilot.sh). Its
[timeline](furnace/launch-timeline.log): tiny CPU qualification 21:26:10Z →
CUDA → pilot 21:27:12Z → all stages exited 0 at 21:59:02Z (UTC). No retry.

Tiny runner qualification passed on both devices: CPU 18/18 (25.8 s) and CUDA
18/18 (34.35 s, peak 67,544,064 bytes). The three roles then ran as separate
fresh processes through the pre-import source launcher (PIDs 1871827,
1873051, 1876062), each checking the 594 Furnace-qualified owner sources, the
pinned V16 comparator receipts and the training data before importing them.

| Role | Status | Elapsed | Peak CUDA allocated / reserved | Peak RSS | Min free GPU / host |
| --- | --- | ---: | ---: | ---: | ---: |
| Probe | `V18_FINAL_QUERY_EXACT_V16_PARITY` | 391.7 s | 29,782,776,320 / 30,452,744,192 | 93,575,364,608 | 2,357,198,848 / 63,267,188,736 |
| Primary | `V18_CENTERED_ORDERED_FULL_UPDATE_TWO_WINDOWS_COMPLETE` | 996.2 s | 29,835,256,320 / 30,454,841,344 | 94,785,789,952 | 2,355,101,696 / 62,117,011,456 |
| Replay | `V18_FRESH_PROCESS_EXACT_NEXT_WINDOW_REPLAY` | 512.7 s | 29,835,256,320 / 30,463,229,952 | 94,194,565,120 | 2,346,713,088 / 63,245,479,936 |

Bytes throughout. These match V16's measured envelope (29.84 GB allocated,
95.8 GB RSS); the split query and complete-window owner add no measurable GPU
cost at this sequence length. All roles stayed inside the 30.5-GiB allocator cap
and the host/disk floors. The dispatch receipt is
`BOUNDED_V18_NATIVE_PILOT_COMPLETE_NOT_SEMANTIC_QUALIFICATION`: 3 unique
windows, 1 replay window, 64 backward pairs.

## Probe: the V18 owner reproduces V16 exactly on 7B

With the `final` interaction query, every frozen comparison matched the V16
slot-contrast arm exactly: original-model hash, preparation, native binding
descriptor, all prompt/context features, initial state; then for all 16 pairs
the loss components, spill receipt, accumulated-gradient hash and bridge-gradient
norms; then the update receipt and the full state fingerprint (all 291 native
tensors, FP32 masters, bridge, both optimizers and RNG). See
[PROBE.json](furnace/raw/probe/PROBE.json). Real-text operand binding, the 7B
layout/ownership guards and contextual backward therefore run the qualified
historical arithmetic, not an approximation of it.

## Primary: centered-ordered, two full-update windows

All 7,248,023,552 native parameters and the 32 bridge tensors were trainable
(base Adafactor 2e-7 on FP32 CPU masters; bridge AdamW 1e-4), on the two exposed
V16 training worlds × 8 questions per window. Checkpoints, retained on Furnace
under `tmp/latent-v18-native-pilot-20261015/checkpoints/primary/`:

| Checkpoint | Bytes | File SHA-256 | State SHA-256 |
| --- | ---: | --- | --- |
| `step1.pt` | 29,083,263,908 | `ed0bac21…6115c4` | `09fa3d18…fd9aa10` |
| `step2.pt` | 29,083,263,908 | `8293eb6d…52facb8` | `8f4780f6…7ed2ed17` |

Each is 103,104 bytes larger than the matched V16 checkpoint (the selection and
window envelope). The step-0 evaluation matched V16's step-0 evaluation in every
shared field ([record](furnace/raw/primary/STEP0_V16_EVALUATION_PARITY.json)).

| Step | Arm | Intact correct / ties | Twin correct / ties | Intact-vs-twin gap change (affected +/0/−) | Donor-directed flips | Mean interaction L2 | Mean common L2 |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| 0 | both | 8/16, 0 | 8/16, 0 | 0/4/0 | 0/4 | 0 | 0 |
| 1 | V18 centered-ordered | 11/16, 1 | 9/16, 1 | 0/4/0 | 0/4 | 4.642e-5 | 0.443956 |
| 1 | V16 centered-final | 11/16, 1 | 9/16, 1 | 0/4/0 | 0/4 | 8.042e-5 | 0.443956 |
| 2 | V18 centered-ordered | 11/16, 1 | 9/16, 1 | 0/4/0 | 0/4 | 5.388e-5 | 0.729892 |
| 2 | V16 centered-final | 9/16, 2 | 8/16, 2 | 0/4/0 | 0/4 | 1.322e-4 | 0.729962 |

Mean L2 is over the 32 intact/twin rows per step. Counts are on the two
training-exposed worlds: correlated observations, not a held-out sample.

**Step 1 is identical to V16 by construction.** The interaction output projection
starts at zero, so native gradients cannot depend on the interaction query in
the first window. All 291 native tensors and FP32 masters after step 1 equal
V16's; only the interaction `up.weight` differs.

**Step 2 diverges through the backbone, not through memory.** With a now-nonzero
interaction contribution, 229 of 291 native tensors differ from V16 after the
second update (174,893,129 versus 174,887,171 changed native elements). The
current no-workspace backbone itself then answers 11/16 intact and 9/16 twin
labels (V16's: 9/16 and 8/16), and the workspace choices follow it. The higher
step-2 counts are a backbone-trajectory difference near bf16 ties, not a
selection advantage.

**Memory content does not reach the native answer.** In both arms, every
intact-versus-twin, reversed, equal-slot and random-pair contrast leaves the
native candidate gap exactly unchanged (affected 0/4 changed, unaffected 0
changed). Gaps move only in bf16 quanta of 0.125: at step 2, on 7/16 questions,
all real-memory conditions (intact, twin, reversed, unrelated, equal-slot)
shift the gap by the same −0.125 relative to zero memory, while norm-matched
random memory matches zero memory. In V18 that uniform shift turns one
unaffected question into an exact tie (7 rows). Only one question (world 1,
query 7) separates the canonical facts and their equal-slot versions from
reversed or unrelated facts; intact still equals twin there. The workspace therefore adds a content-independent
real-memory shift; content differences stay below the native readout's bf16
resolution at this budget. The interaction route stays near 5e-5 against a
common route of about 0.73.

## Replay

A fresh interpreter rebuilt the contract, schedule, metadata and operand
bindings independently, restored `step1.pt` with `weights_only=True` and
replayed window 2: all 16 pair receipts, the update and the state fingerprint
equal the primary's, and the serialized state equals `step2.pt`'s state hash
`8f4780f6…7ed2ed17` ([REPLAY.json](furnace/raw/replay/REPLAY.json)).

## Offline verification

[Local receipt verification](OFFLINE_VERIFY_LOCAL.json) rehashed all 599
sealed sources from a clean clone of the execution commit, both qualification
bundles and every role manifest; it recomputed the V16 probe comparison, the
replay equality and all evaluation summaries from saved records. The
[Furnace verification](OFFLINE_VERIFY_FURNACE.json) repeated this from a
separate clean checkout of the same commit and also rehashed both checkpoint
bodies. Both report `OFFLINE_V18_NATIVE_PILOT_RECEIPT_PASS` with zero forwards.

Local file names: macOS paths are case-insensitive, so the Furnace task-root
`DISPATCH.log` (SHA-256 `2c2abc44…6d493402`) is stored as
[launch-timeline.log](furnace/launch-timeline.log) and its `dispatch.log`
(`4f68c48f…4b748ac7ad`) as [dispatch-runner-stdout.log](furnace/dispatch-runner-stdout.log).
Neither is inside a verified manifest.

## What this enables, and what it does not

The V18 selection window owner is now qualified end to end on the real model:
exact historical parity, a full-parameter update path, exact checkpoint resume
in a fresh process, and a measured envelope: about 29.8 GB GPU and 95 GB RSS;
about 10 s per backward pair; per 16-pair window cycle roughly 4.5 min update,
1 min evaluation and 1.2 min checkpoint save; 29.1 GB per checkpoint. No new sequences, judge calls, weight deletions or retries occurred.

It does not show that the workspace can carry facts into answers. Two updates
at these learning rates leave memory content below bf16 visibility, as in V16.
A larger run needs a separately frozen hypothesis, population (train/dev/final
families), size and decision rule. With these two checkpoints retained, the task
filesystem has about 99 GiB free, so a further full condition that also retains
two checkpoints would go below the 50-GiB floor unless storage is freed by an
explicit decision.
