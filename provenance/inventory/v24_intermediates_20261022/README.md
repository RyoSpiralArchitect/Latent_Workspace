# Two superseded intermediate checkpoints — 2026-10-22

Ryō explicitly requested retirement of no-longer-needed intermediate weights
after the V24 storage inventory. This is **not** a version-wide purge.

- V23 `canary_step1.pt`: exact positive-P fresh-process replay completed;
  scientific final P-off and P-on now supply the comparison weights.
- V22 `training_step16.pt`: exact restoration into the completed step32
  continuation is recorded in `raw/train_b/RESTORE.json`; the step32 final is
  retained. This intermediate is not used by current comparisons.

Allowlist total: **58,008,782,872 bytes (54.0249 GiB)**. Original Mistral,
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

## Completed retirement

The ledger and exact helper were pushed in commit
`a7943b107a2e437c82e8d8f56d3663f8b2830334` **before** deletion. The published
ledger SHA256 is `f2cd97d5d00194e799928809e35f9c6c8870ded19972ead7ca2bc88afec9dc1d`.
After rechecking both full hashes, unused-file status, source evidence and
protected identities, the helper removed exactly the two files at
**2026-10-22T04:38:22.739811+00:00**. The final protected identities still matched.

[DELETE_FINISHED.json](DELETE_FINISHED.json) records **58,008,782,872 bytes**
retired, with available space rising from **55,557,410,816** to
**113,566,195,712 bytes (105.7668 GiB)**. See also
[start receipt](DELETE_STARTED.json), [first unlink](DELETED_0.json) and
[second unlink](DELETED_1.json). The available-space delta need not equal the
file-size sum exactly on a shared filesystem.

This remains **0.2332 GiB below** the earlier conservative 106-GiB forecast for
two concurrent 28-GiB saves plus a 50-GiB floor. No Full-FT admission is claimed
and no additional file is deleted. A separately frozen sequential save/retire
lifecycle can avoid retaining a spent engineering canary beside the final save;
the 50-GiB floor must remain unchanged and be checked live.

**Git stores receipts and hashes, not a tensor backup. Deleted bodies cannot
be recovered from Git.** This operation does not waive the next run's disk
admission or alter historical receipts that refer to the retired bodies.
