# V16 prerequisite: unchanged real-Mistral adapter migration

2026-10-14. This is **engineering equivalence**, not V16 slot-contrast training
or a new model-quality experiment. The old scientific FAIL remains unchanged.

The [fixed contract](../../configs/v16/ADAPTER_MIGRATION_PLAN.json) and
[entry](../../scripts/run_v16_adapter_migration.py) implement the
[migration gate](../v15/ADAPTER_7B_MIGRATION_GATE.md). The old runner, graph
equations, six-term loss, optimizer and all old receipts remain unchanged.

## Comparison

- Pinned original Mistral-7B-Instruct-v0.3, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`, native BF16/SDPA, seed47,
  query-modulated common reader, zero EOS weight, boundary16.
- Frozen/full are separate modes. In each, sequential old-reference and v2
  adapter arms begin from freshly loaded original state and matched RNG.
- Two complete 16-pair windows per arm: two exposed worlds × eight queries in
  frozen order. **8 unique windows / 128 paired objectives planned.**
- Each v2 arm saves step1 and step2. Reload original native parts, restore step1
  through the v2 boundary, and replay window2: **2 replay windows / 32 paired
  objectives planned**, **160 backward pairs total**. No partial-window update.
- Exact comparisons include all six losses and total, ordered spill receipts,
  actual native-dtype CPU accumulated-gradient hash after every pair, update
  receipts, each native/bridge/master tensor, complete optimizer state and RNG.
  A scalar-loss match alone cannot pass. No tolerance widening.
- Checkpoint byte/state hashes and complete next-update payload hash are checked
  during replay. Original identity and updated-state identity remain separate.

No new reader mechanism, loss, dtype, generation or judge is introduced. Extra
forwards and per-pair CPU hashing are intentional diagnostic costs; a passing
result would not be a throughput or cross-runtime equivalence claim.

## Admission and provenance

Use an isolated committed checkout and `run_source_sealed.py` before importing
project code. The new seal binds source, tests, configs and the V10 data. Actual
project import paths are checked against that seal, including editable-install
redirection. Outputs/checkpoints are exclusive and outside the source tree.
The old historical Python3.14.4 run is not replayed under a new name: this fresh
comparison pins Python3.12.14, Torch2.13.0+cu132, Transformers5.15.0, CUDA13.2
from the separately qualified tiny CUDA environment. Both arms use this runtime.

The [V12 cleanup](../../provenance/inventory/v12_weight_prune_20261014/README.md)
left 249.571 GiB persistent space. New admission forecasts **64 GiB retained
artifacts plus 50 GiB remaining**, without deleting V14/V15 or old negatives.
Only four new v2 checkpoints are retained (latest/previous per frozen/full
condition); the reference arms preserve complete per-tensor hashes and receipts,
not extra 7B checkpoint copies. This does not omit the adapter replay check.

Before dispatch: GPU free ≥31 GiB, host available ≥100 GiB, one CUDA device and
no competing compute client. Torch allocation is capped at30.5 GiB; stop below
0.75 GiB device-free or24 GiB host-available. Reserve32 GiB extra host space
before a full independent snapshot/restore and32 GiB disk forecast before a full
checkpoint write. Total wall budget is7200s, checked at resource boundaries.
The initial64-GiB forecast assumes both output directories share one filesystem.
Actual host/device samples, process peak RSS and Torch peaks are retained; old
resource observations are not treated as bounds for the new graph policy.

An exception, resource abort or exact mismatch is a terminal
`INCOMPLETE_NO_RETRY`; keep partial pair journals, checkpoints and missingness.
Do not retry or relax criteria automatically. A later recovery needs its own
explicit decision and provenance. No other workload may be stopped.

The [offline verifier](../../scripts/verify_v16_adapter_migration.py) checks
literal artifacts, current source hashes, all reported exact comparisons and
denominators. It never loads a model or redispatches a cell. Offline verification
does not reload the large remote checkpoint files; that is the run's replay duty.

Only after a complete migration PASS should the explicit new-reader ownership
and matched slot-contrast/control training stages in [the V16 plan](PLAN.md)
be admitted. A failed migration is an implementation diagnostic, not a semantic
defeat or victory for the as-yet-untrained V16 prototype.
