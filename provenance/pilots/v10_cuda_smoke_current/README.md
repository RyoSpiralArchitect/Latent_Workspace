# Current CUDA smoke evidence

This directory contains compact, receipt-bound evidence imported from the
Furnace run surface after the four-condition seed-42 smoke cut.

- `smoke/` contains each formal run's compact export plus its prune intent and
  receipt. No trained model shards are present.
- `resume_equivalence/` contains the four top-level zero-tolerance step-4 resume
  receipts.
- `oracles/` contains the current-source F0 spill-versus-native receipt and the
  historical d5 base-only receipt.
- `parity/` retains compact F0 native runtime evidence used for the bounded
  throughput measurement.
- `negative_evidence/` records why B native multi-microbatch parity is not
  claimed.

The compact exports, hashes, and index files are evidence, not loadable trained
weight backups. See
[`docs/CUDA_SMOKE_STATUS.md`](../../../docs/CUDA_SMOKE_STATUS.md) for the result,
failed hypotheses, and claim boundaries. The later removal of duplicate/oracle/
resume weight bodies is recorded in
[`PRUNE_RECEIPT.json`](../../pruning/current_cuda_oracle_and_resume_raw_weights/PRUNE_RECEIPT.json).
