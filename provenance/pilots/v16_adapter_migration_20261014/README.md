# Real-Mistral adapter migration: frozen PASS, full not dispatched

2026-10-14. Terminal **INCOMPLETE_NO_RETRY**. The unchanged real-7B frozen
comparison and replay passed; full mode stopped at admission, before loading
its model or executing any pair. This is not an overall migration PASS.

Executed source: `7c3af3c70df31a69bbe624532dbcd516dbb195a0`, with
[510 sealed source files](SOURCE_SEAL.json), Python3.12.14, Torch2.13.0+cu132,
Transformers5.15.0, CUDA13.2. All raw evidence is retained in
[the terminal receipt](raw/FINISHED.json) and its 21 hashed companion files.

[The frozen design](../../../docs/v16/ADAPTER_MIGRATION.md) compares the unchanged
old learner with the repaired v2 adapter, in frozen/full modes, two complete
windows each plus two adapter replays. Planned total: **8 unique + 2 replay
windows, 160 backward pairs**, zero generated sequences/judge calls/deletions.

## Observed denominators and exactness

- Frozen: two complete windows per legacy/adapter-v2 arm, **4/4 unique windows**,
  plus **1/1 next-window replay**. All 16 ordered pairs per window were used.
- Across the original plan: **4/8 unique windows, 1/2 replay windows,
  80/160 backward pairs, 1/2 modes**. Full: **0/4 unique, 0/1 replay**, no full
  checkpoint and no full update. Missing work is not a negative numeric result.
- [Frozen equivalence](raw/frozen_EQUIVALENCE.json) binds exact initial state,
  six losses plus total, spill order, accumulated CPU-gradient hashes after
  every pair, each native/bridge/master tensor, complete optimizers and RNG.
- [Replay](raw/frozen_REPLAY.json) exactly reproduces window2 from the serialized
  step1 checkpoint, including complete checkpoint-state hash
  `aed9caf5f6d099e420812074bb74b99ae2fb39c0c273f56b744c241d60681234`.
  The two retained frozen checkpoints are 50,547,559 bytes each. Large binaries
  remain on Furnace; file and state hashes are published in the checkpoint receipts.
- [Offline verification](OFFLINE_VERIFY.json) passes receipt integrity and
  comparisons, **not** the incomplete run. It does not reload checkpoint binaries.

## Resource stop, not OOM or numerical mismatch

Elapsed: **281.496287 seconds**. Sampled frozen peak Torch allocated/reserved:
**14.141144 / 14.273438 GiB**. Minimum sampled device free: **16.341797 GiB**;
host available: **116.721195 GiB**. Process peak RSS: **6.885208 GiB**.
These frozen-only measurements do not bound the full path.

At `full:admission`, device free was **32,738,639,872 bytes (30.490234 GiB)**,
below the unchanged **31-GiB** cold-start floor. Only this process was present:
912,261,120 bytes reported for its CUDA context, including 64-MiB allocated and
128-MiB reserved Torch memory. Retained CUDA/library state in the warmed process
is the likely cause; the non-Torch portion was not separately instrumented.
After this process exited, Furnace returned to 10 MiB used with no compute client.
No other job was stopped. The error is preserved verbatim in FINISHED.json.

Ryō explicitly authorized **only the never-dispatched full mode in a new
process**. That additive continuation must preserve this entire bundle, the old
source, data/seed/math/runtime and all resource thresholds. Frozen work must not
be rerun. No retry, new reader training, generation or judge is implied.

## Prelaunch tests and claim ceiling

[PRELAUNCH_TESTS.xml](PRELAUNCH_TESTS.xml) records **157/157 local CPU tests**:
28 migration/comparator/contract tests, 16 V16 reader-prototype tests,
12 deletion-helper safety tests, 93 checkpoint-v2 tests and eight v2 publication
tests. The migration-specific cases include four two-window FP32/BF16 ×
frozen/full comparisons and two BF16 complete-window serialized replays on a
tiny model. The other test families overlap previous evidence; they are not
157 independent scientific experiments. This ordinary local test run is not
the separately sealed CUDA/7B execution.

The V16 slot-contrast prototype is not used by this migration. All historical
sources and old FAIL / winner:none / non-regression NOT_ESTABLISHED remain.
