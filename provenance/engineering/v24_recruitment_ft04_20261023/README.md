# V24 R1 FT04: exact real-model replay after storage-accounting repair

**Checks complete; scientific Full FT not yet dispatched.**
Execution source: `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`, **856 sealed files**.
This is the explicitly authorized new attempt after the immutable
[FT03 storage stop](../v24_recruitment_ft03_20261023/README.md), not a retry or
rewrite of that run. [Execution and protocol handoff](EXECUTION_HANDOFF.md).

## Closed results and denominators

- CPU qualification **643/643**, CUDA qualification **643/643**; zero failures,
  errors or skips. Elapsed 74.029 / 80.163 seconds respectively, under the
  unchanged 900-second / 4-GiB tiny-test limits.
- Independent CPU observer: **140 successful samples, zero errors**, normal
  requested-stop exit; child CUDA initialization rejected, final visible
  device count zero. Sampled visibility/PID evidence, not an OS sandbox.
- Real 7B canary: **2 updates / 8 backward rows / 2,220 target tokens**, exactly
  one step-1 checkpoint (29,004,378,444 bytes). Elapsed **489.139 seconds**.
- Fresh process: restore the saved state exactly, then **1 replay update /
  4 rows / 1,049 target tokens**. Elapsed **343.692 seconds**. Whole step-2
  records and the complete payload hash match the uninterrupted canary.
- Total executed real-model updates: **3 engineering/replay**, **0 scientific**.
  The checks dispatcher closed successfully in **843.772 seconds**. Neither
  32-update scientific arm was started; no training or overall training terminal
  is invented from this checks-only success.

The two completed canary update records also **exactly match FT03**:
ordered rows, losses, gradients, native weights, CPU masters, optimizer state,
RNG, buffers, execution state, history and cursor. This bounds the numerical
equivalence claim to these matched two windows; it is not general model quality
or future-training evidence. Source-bound checkpoint payload hashes are not
expected to match across FT03 and FT04 source identities.

[Offline checks verification](OFFLINE_CHECKS_VERIFICATION.json) replays the
complete frozen source archive, closed terminal manifests, qualification XML,
bound observer journal, operation-specific resource records, exact replay and
both historical numerical records. [Qualification-only result](OFFLINE_QUALIFICATION_VERIFICATION.json).
The final offline verification/retirement/historical regression selection passes
**87/87**, plus Ruff. This post-run publication suite is separate from the frozen
643-per-device execution selection; it does not alter the old or new run.
Run locally without GPU/model calls:

```sh
python3 -B scripts/verify_v24_recruitment_ft04.py provenance/engineering/v24_recruitment_ft04_20261023/furnace --phase checks
```

## What changed, and what did not

The inherited `snapshot_admission` coupled independent host-memory reserve to
a **32-GiB disk write**, even for memory-only payload hashing and reading an
existing checkpoint. FT03 stopped at that nonexistent second write; the actual
free-space floor had not been crossed. The pre-admission plan had missed this
post-save condition. The old source and failed receipts remain unchanged.

The new operation-specific adapter retains the **32-GiB real-write reserve**
and **32-GiB independent host snapshot reserve above the 24-GiB host floor**.
Only operations that produce no tensor file use zero new-file bytes. Every
operation still calls the original GPU/host/disk/time guard. Actual receipts:

| Operation | New tensor-file forecast | Observed in |
| --- | ---: | --- |
| Checkpoint write | 32 GiB | Canary step-1 save |
| Existing-checkpoint read | 0 | Fresh-process restore |
| In-memory payload hash | 0 | Canary and replay step-2 verification |

Canary admission forecasts 32 GiB; replay admission forecasts zero. Lowest
recorded free disk was **70.2270 GiB**, above the unchanged **50-GiB floor**.
All observed forecasts and host snapshot reserves passed offline replay.
GPU allocated/reserved peaks: canary **27.7510 / 29.9980 GiB**, replay
**27.7496 / 30.2188 GiB** (allocator cap remains 30.5 GiB).
Peak host RSS: **86.9264 / 85.7739 GiB**. The GPU was idle after completion.
These are this engineering assay's measurements, not training throughput estimates.

No native engine arithmetic, seeds, optimizer, ordered data, targets, precision,
parameter ownership or scientific threshold changed. Same original Mistral,
native BF16 with CPU FP32 masters, Adafactor 2e-7, seed 47, P=0. The scientific
recipe remains 32 updates / 538 matched rows / 21,112 targets per route, with
both arms initialized independently from original base, never these canaries.

## Storage at checks completion (historical)

Only the explicitly authorized [old FT01 canary](../../inventory/v24_ft01_superseded_20261023/README.md)
was retired: **one file / 27.0124 GiB**, after published ledger and complete
target/protected-body rehash. Original FT01/FT03 failures and their missing
historical replay remain visible. Git stores records, **not a recoverable copy
of deleted tensor bytes**. No further body was deleted during the checks phase.

Retained on Furnace at the checks terminal:

| Checkpoint | Size | Whole-file SHA-256 |
| --- | ---: | --- |
| FT03 `canary_step1.pt` | 27.0124 GiB | `471776810c42359141b59e7bb7f1dc607668a63114b69d4c9af8d7351b413418` |
| FT04 `canary_step1.pt` | 27.0124 GiB | `c18804e64d48c94f8046dffba7907bacb6863fddc3434223bbd03438c3682699` |

Each path is under
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft0N-20261023/checkpoints/`.
Original Mistral, V22 step32 and both V23 final comparison weights remain protected.
[Independent post-check full-body rehash](POST_CHECK_BODY_REHASH.json) confirms
both retained canary hashes above. V22/V23 final sizes, inodes and link counts
also still match the pre-deletion protected identities; their bodies were not
rehash-read again or copied locally.

Post-check free space: **75,405,676,544 bytes / 70.2270 GiB**. Paired scientific
admission conservatively requires **28 GiB prior final + 32 GiB next write +
50 GiB floor = 110 GiB**. Retiring only the now-replayed FT04 canary would yield
about **97.24 GiB**, still insufficient. Retiring both engineering canaries
would yield about **124.25 GiB**, before shared-disk changes. This is a
**proposal requiring new explicit authorization**, not an executed cleanup;
FT03 was expressly retained in the current authorization. A different qualified
storage destination is another option. The separate successful-replay and
published spent-canary retirement gates remain mandatory before training.

## Authorized retirement and scientific training dispatch

Ryō subsequently approved only the two engineering canaries above. The
[exclusive inventory and terminal](../../inventory/v24_ft04_canaries_20261023/README.md)
record whole-file rehash before publication and again before deletion. Exactly
two files / **58,008,756,888 bytes (54.0249 GiB)** were removed at
2026-10-23 07:49:33 UTC. The ledger was already pushed at
`62f2d78afb626db0809c7bfab4c7df14e2dc9f77`. No scientific final or base weight
was deleted; all prior non-tensor evidence and protected final identities stayed
unchanged. FT03 remains historically failed without replay. The
[FT04-only retirement receipt](furnace/CANARY_RETIREMENT.json) binds its actual
successful replay and exact checkpoint identity to the two-file terminal.

Available disk reached **133,414,617,088 bytes / 124.2520 GiB** after retirement.
At about **16:52 JST**, the one-shot training launcher entered the same clean
execution checkout at `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`, verified all
856 sealed files, and passed the unchanged 110-GiB admission. Inline runs first;
workspace starts only after its successful terminal, in a fresh process from
original base. No checks are rerun and no canary state is inherited. Planned
scientific denominator: **64 updates**, **538 rows / 21,112 target tokens per
arm**, two final saves, with 76 descriptive development NLL rows per arm.

Status is **RUNNING**, not a successful training/quality terminal. At the
[16:57:16 JST observation](TRAINING_PROGRESS_20261023T075716Z.json), inline had
completed **1/32 updates / 2 backward rows / 545 target tokens**, with all
291 master tensors changed and the frozen row order exact. Update 2 was in
progress; workspace had not started. Startup and first-update metadata are
published, not a fabricated full-run manifest. See the
[handoff](EXECUTION_HANDOFF.md). No automatic retry or recurring monitor was
created. Local post-retirement offline/tiny-file selection: **103/103 PASS**
and Ruff PASS, distinct from the unchanged 643-per-device qualification.

## Claim ceiling

This resolves the bounded save/restore accounting and exact-update gate. It
does **not** establish better workspace use, retention, benchmark improvement
or general capability improvement. No new generation, judge, benchmark,
confirmation/OOD exposure, PR or HF release occurred. Old expression gate:
**FAIL**. Winner: **none**. Non-regression: **NOT_ESTABLISHED**.
