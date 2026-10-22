# Two superseded intermediate checkpoints — 2026-10-22

Ryō explicitly requested retirement of no-longer-needed intermediate weights
after the V24 storage inventory. This is **not** a version-wide purge.

- V23 `canary_step1.pt`: exact positive-P fresh-process replay completed;
  scientific final P-off and P-on now supply the comparison weights.
- V22 `training_step16.pt`: exact restoration into the completed step32
  continuation is recorded in `raw/train_b/RESTORE.json`; the step32 final is
  retained. This intermediate is not used by current comparisons.

Allowlist total: **58,008,782,872 bytes (54.0245 GiB)**. Original Mistral,
V22 step32, V23 P-off/P-on step32, all other scientific branches, activations,
datasets, source seals, raw trial records and other projects are protected.

The [helper](retire.py) inventories complete body SHA256, filesystem identity,
original checkpoint/state receipts, successful replay/continuation gates and
retained final files. It rejects symlinks, hardlinks, changed bodies/evidence,
open files, a changed script/ledger and repeat attempts. All preconditions are
checked before any unlink. Only the two exact regular files can be removed;
no directory is removed. Publish the inventory before execution.

The first metadata-only inventory stopped before deletion: PSmisc 23.7
interprets `fuser --` as an empty process specification. Its original script
and empty destination remain on Furnace; [the failure record](INVENTORY_ATTEMPT01.json)
is retained. The corrected invocation accepts only absolute operands, retains
strict exit-code/stderr checking, and passed **11/11** local regression tests.
The new attempt is `latent-v24-intermediate-retirement02-20261022`, with tools
in `tmp/latent-v24-retirement-tools02-20261022` under the Furnace project root.

[INVENTORY.json](INVENTORY.json) is the completed pre-deletion inventory.
It records both full-body hashes, original receipts, protected final-file
identities and evidence hashes. This publication alone does **not** establish
that deletion completed; a separate `DELETE_FINISHED.json` must record that.

**Git stores receipts and hashes, not a tensor backup. Deleted bodies cannot
be recovered from Git.** This operation does not waive the next run's disk
admission or alter historical receipts that refer to the retired bodies.
