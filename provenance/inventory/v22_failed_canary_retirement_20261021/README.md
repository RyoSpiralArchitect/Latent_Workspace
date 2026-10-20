# Conditional retirement of the failed V22 canary body

**Terminal: one approved old body retired at 2026-10-20 21:07:58 UTC.**
[Deletion receipt](DELETE_FINISHED.json) confirms exactly 29,004,378,380 bytes,
with free disk 97,154,629,632 → 126,158,893,056 bytes. The pre-delete ledger and
gate evidence were published in Git commit `b6fdfc7ce7d10c7798a81f5426b2765dc9b3652b`
before removal. No retained backup of the old body exists; metadata is not a
weight backup. Ryō explicitly authorized this one file, only after the new
exact replay passed. That gate was satisfied: [new checks](../../pilots/v22_full_ft_recovery01_20261021/furnace/checks/FINISHED.json)
and [exact payload replay](../../pilots/v22_full_ft_recovery01_20261021/furnace/raw/replay/REPLAY.json).
CPU and CUDA qualification each passed 318/318. The old 42-file failure bundle
and both parent banks remain unchanged.

The [inventory](INVENTORY.json) binds exactly one old body, its original execution
source, byte count, SHA-256, inode and timestamp, and the separately retained
new body. Both complete weight files were independently checked with Furnace
`sha256sum`, matching their save receipts. The new canary's two update receipts
also exactly match the original trial's corresponding numerical receipts.

Target only: old `latent-v22-full-ft01-20261021/checkpoints/canary_step1.pt`,
**29,004,378,380 bytes / 27.0124 GiB**. Original Mistral, the newly verified
canary body, all other checkpoints, every directory, and all data/receipt files
are excluded. No backup of the old body is claimed; Git metadata cannot
reconstruct deleted bytes.

Pre-ledger observed free disk: 97,154,666,496 bytes, about 90.5 GiB. The two future training
saves have a 56-GiB allowance and must leave the unchanged 50-GiB floor.
This single retirement is expected to make that admission possible; actual
free space is checked again afterward and by each training process.

The bounded [one-file operation](retire_one.py) requires the pinned inventory,
successful unchanged new checks/replay, unchanged replacement metadata and a
fresh full hash of the exact old regular file. It refuses symlinks, hard links,
inode/timestamp/size drift, or a repeated attempt. Publish this inventory,
operation and gate evidence before invoking it. It writes exclusive
`DELETE_STARTED.json` and `DELETE_FINISHED.json`; only the latter establishes
completed removal. No training process performs this deletion.
