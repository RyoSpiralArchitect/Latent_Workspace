# V16 full-update comparison: launch evidence

**2026-10-15 terminal addendum:** the existing run completed. See
[RESULTS.md](RESULTS.md), [raw terminal receipts](raw/FINISHED.json) and
[offline replay](OFFLINE_VERIFY.json). The launch-era text below is retained
as chronology, not the current run status.

2026-10-14. **Launched on Furnace; no terminal comparison result in this
publication.** This is not a completed-run, semantic-success or non-regression
receipt. Follow the existing process; do not start another copy.

Execution source: `59f0c15965db7c22f6362825bb8873a7aede391a`.
[SOURCE_SEAL.json](SOURCE_SEAL.json) binds 535 source/config/test/data files.
All 526 files in the preceding slot-state qualification seal remain unchanged.
The [prospective contract](../../../docs/v16/FULL_COMPARISON.md) and
[fixed selection](../../../configs/v16/FULL_COMPARISON_PLAN.json) predate launch.

## Evidence that permits this bounded launch

| Check | Observed result | Evidence |
| --- | --- | --- |
| Selected local regression + new evaluator/offline tests | 279/279, no failures/errors/skips | [XML](PRELAUNCH_TESTS.xml) |
| Source-isolated Furnace CPU integration | 12/12; pytest 24.41 s, wrapper 29.136 s | [terminal receipt](qualification/cpu/FINISHED.json), [XML](qualification/cpu/TESTS.xml) |
| Source-isolated Furnace CUDA integration | 12/12; pytest 41.29 s, wrapper 45.955 s | [terminal receipt](qualification/cuda/FINISHED.json), [XML](qualification/cuda/TESTS.xml) |
| New code lint | passed | source publication checked with Ruff |

Each device suite covers three arms × FP32/BF16: evaluation nonmutation,
complete updates against the unchanged qualified window, independent snapshots
and exact serialized next-update replay. It also checks frozen-plan rejection,
identical common/raw/candidate initial tensors and non-promoting summaries.
The seven additional offline local tests replay evaluation arithmetic and reject
missing/duplicate rows, a labelled random/common control, donor-direction damage,
summary damage and changed original-reference order.

Pinned Furnace runtime: Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0,
CUDA 13.2. These are within-runtime tests; local CPU and CUDA are not claimed
bit-identical to one another. Tiny qualification does not establish 7B capacity.

## Existing launch, not a completion

[Dispatcher STARTED](launch/STARTED.json), [common dispatch](launch/DISPATCH_common.json)
and [common STARTED](launch/common/STARTED.json) are immutable copies from the
running attempt. Dispatcher PID 1714013, first arm PID 1714045; the outer isolated
launcher PID is 1713998. Resolve these against their command lines before relying
on a PID later. No recurring monitor was created or re-enabled.

At the initial common-arm admission, available host memory was
128,346,980,352 bytes (119.532 GiB), and persistent free space was
290,133,561,344 bytes (270.208 GiB). Reserving the entire remaining 192 GiB output
forecast left 78.208 GiB, above the unchanged 50-GiB floor. The native model
loaded successfully; this observation is not a completed backward/update or a
new-reader peak-memory measurement. Subsequent GPU/host/disk samples and progress
belong to the live receipts described in the handoff.

The common arm subsequently completed its [step-zero native evaluation](launch/common/evaluation_step0.json):
160/160 workspace rows match the direct base's full-vocabulary output, with
16 direct-base rows and 80 factor rows. The evaluator's owned-state fingerprint
is unchanged. Offline evaluation arithmetic was replayed successfully. These
are initialization/zero-identity checks, not learning gains. The first backward
window is now in progress; no complete window/replay is claimed in this launch
snapshot. [Initial state hashes](launch/common/INITIAL.json) and
[owned context/provenance](launch/common/CONTEXT.json) are retained beside it.

Three sequential fresh-process arms: common, raw matched control, slot contrast.
Planned totals: **6 unique update windows, 3 replay windows, 144 backward pairs**;
**1,440 workspace evaluation rows, 144 direct-base rows, 720 factor rows**.
These counts are planned, not completed, in this launch publication. All share
two exposed training worlds; no held-out quality claim is admitted.

No new generation, paid judge request or weight deletion is included. Two full
checkpoints per condition remain on Furnace, outside Git. The old gate remains
**FAIL / winner:none / non_regression NOT_ESTABLISHED**.

See [EXECUTION_HANDOFF.md](EXECUTION_HANDOFF.md) for exact source/output locations,
failure handling and terminal offline verification. The old negative runs and
all earlier provenance bundles have not been rewritten.
