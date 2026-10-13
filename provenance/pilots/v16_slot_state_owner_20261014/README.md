# V16 slot-contrast state owner: tiny CPU/CUDA qualification

2026-10-14. **145/145 PASS independently on CPU and CUDA.** This integrates the
reader into explicit ownership, complete-window updates, snapshot and resume.
It is not a 7B semantic experiment, a response-quality result or a base-floor claim.

## Source and boundaries

Execution commit: `e6866c0a173d23bc8b4a0c59b8b74bca4abc7877`;
[526-file seal](SOURCE_SEAL.json). CPU and CUDA each used a fresh process in the
same detached, source-isolated Furnace checkout, with a pre-import cleanliness
check and fresh bytecode path. The [contract](../../../docs/v16/SLOT_STATE_OWNER.md)
and [fixed selection](../../../configs/v16/SLOT_STATE_QUALIFICATION_PLAN.json)
describe the allowed work. The [handoff](EXECUTION_HANDOFF.md) records exact paths.

All 519 previously sealed source files remain byte-identical. The original
migration, failed continuation and successful unchanged-reader recovery bundles
also remain unchanged. This extends that work; it does not rerun or relabel any
of its 160 real-7B backward pairs.

## Terminal evidence

| Runtime | Cases | Failures / errors / skips | Test time | Total qualification time | Peak CUDA allocated |
| --- | ---: | --- | ---: | ---: | ---: |
| Furnace CPU | 145/145 | 0 / 0 / 0 | 143.471 s | 145.961211 s | Not applicable |
| Furnace CUDA | 145/145 | 0 / 0 / 0 | 247.295 s | 249.918512 s | 67,596,288 bytes / 64.464844 MiB |

Sources: CPU [STARTED](cpu/STARTED.json), [JUnit](cpu/TESTS.xml),
[FINISHED](cpu/FINISHED.json); CUDA [STARTED](cuda/STARTED.json),
[JUnit](cuda/TESTS.xml), [FINISHED](cuda/FINISHED.json).
Both exited 0 with `TINY_SLOT_STATE_PASS_NOT_7B_OR_SEMANTIC`.
[Offline replay](OFFLINE_VERIFY.json) checks selected test identities, counts,
artifact bytes, current source hashes and unchanged claim ceilings. No checkpoint
or model is loaded by the offline verifier; live tests did serialize and reload.

Runtime: Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0, pytest 9.1.1,
CUDA 13.2, Linux x86_64, RTX 5090. CPU and CUDA tests ran concurrently in distinct
processes; timings are engineering receipts, not a CPU/GPU speed comparison.
CUDA's fixed allocator ceiling was 4 GiB and each suite's deadline 900 seconds.
The tiny peak is **not** a forecast for Mistral-7B, longer contexts or a new pilot.

Prelaunch ordinary local CPU regression passed **440/440** in 170.33 seconds:
145 new ownership cases plus 295 retained cases; see
[PRELAUNCH_TESTS.xml](PRELAUNCH_TESTS.xml). The separate offline verifier tests
pass **14/14** ([VERIFIER_TESTS.xml](VERIFIER_TESTS.xml)); those use synthetic
receipts, not model evidence. Ruff passes on all six new Python files.

## What the comparisons establish

- **16/16 replay cells per runtime:** candidate/raw × FP32/BF16 × full/frozen ×
  checkpointing on/off. Each completes two ordered 16-pair windows, then restores
  serialized step 1 into a fresh pinned target and exactly replays step 2. Every
  pair's loss/spill/accumulated-gradient receipt, update, whole owned-state hash
  and RNG continuation matches. This is within-runtime equality, not CPU/CUDA
  numerical equality and not equality between different reader mechanisms.
- **8/8 independent update references per runtime:** native-dtype CPU gradient
  accumulation, clipping, AdamW and FP32-master Adafactor agree exactly for both
  modes, dtypes and update scopes. Production native checkpoint preparation is
  included, not replaced with a simpler setup path.
- **66/66 bad-payload cases**, **19/19 incompatible fresh-target cases** and
  **5/5 late base-optimizer cases** reject without changing
  target contents, versions, pointers or process RNG. Two additional fresh-target
  replacement cases are correctly accepted. **21/21 live-policy cases** are also
  rejected before a window begins, without changing RNG. These are compatibility guards under
  exclusive ownership, not a concurrent-mutation or device-failure transaction.
- Both modes own all 32 tiny-reader tensors exactly once: writer 20, common
  reader 6, interaction 6. Initial interaction-query gradients are zero by design;
  the new output projection receives a gradient, and after one update the query
  route has a finite nonzero gradient. This is liveness, not useful gradient size
  or factual selectivity.
- Independent retained snapshots, bidirectional metadata/tensor isolation,
  step-zero replay, complete-window requirements, candidate/control separation,
  identical initial tensors and the unchanged legacy whitelist also pass.

## Carry forward, without promoting the claim

V16 now has its own explicit checkpoint format and reader contract. It owns mode,
norm budget, common policy, canonical module graph and parameter partitions;
same-shaped candidate/control checkpoints cannot be interchanged. Historical
v15/v2 files, their strict reader guard, optimizer math, paired objective and
model-native readout remain unchanged. Reader buffers and hooks are rejected,
not silently omitted from state.

The next gate is a **separately budgeted three-arm Mistral comparison**: common
reference, raw matched-capacity control and slot-contrast candidate. Freeze its
source, seeds, original base, complete-window schedule, losses, eval controls and
CPU/GPU/checkpoint forecast first. Treat frozen/full backbone as another axis.
Then ask about reciprocal donor direction, unaffected regressions and original
versus updated direct-base behavior; larger query gradients alone are insufficient.

Old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. Historical
judge coverage remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`. No 7B update, new
sequence, paid judge request, experiment-weight deletion, heartbeat or merge
occurred in this qualification. Both jobs are terminal; post-run Furnace had no
compute client. PR #13 remains Draft, stacked on PR #12; no CI pass is implied.
