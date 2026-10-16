# Retirement of two V20 A2 development feature folders

2026-10-16. **TERMINAL: exactly these two folders retired, by Ryō, at 09:08:23Z.** All six files matched the inventory before removal; 17,359,974,877 bytes freed, available space 61,993,750,528 → 79,353,753,600 bytes ([receipt](DELETE_FINISHED.json), [postflight](POSTFLIGHT.json)). Ryō's request:
"容量が逼迫していたら、途中のものでもう使わないのは台帳に記録して消してゆこう".
The bounded interpretation: retire the two folders below and nothing else. It
is not a retention policy and does not cover any other file.

## Why the space is needed

The sealed A2 depth ladder writes about 22 GiB of features. The resource guard
of every run keeps 50 GiB free on Furnace's filesystem. Before this
retirement, 59.8 GiB were available (64,201,588,736 bytes), which is not
enough. Retiring these folders frees 16.2 GiB.

## Exact scope

Under `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a2-dev-20261016/`:

| Folder | Files | Bytes | What it was |
| --- | ---: | ---: | --- |
| `big_features/` | 4 | 12,499,028,958 | Cut-16 features of 2,045 generated training worlds, for check 6 (more data) |
| `shallow_cut4/` | 2 | 4,860,945,919 | Final states with memory at cut 4, for checks 10 and the position comparison |

Total: **17,359,974,877 bytes / 16.168 GiB**. Every file's size and SHA-256
are in [INVENTORY.json](INVENTORY.json).

## Why they are no longer needed

Both served development checks before freezing A2, recorded with their
scripts and results in
[DEV_POWER_CHECKS.md](../../pilots/v20_a2_flip_20261016/DEV_POWER_CHECKS.md).
They are not evidence; no sealed run, verifier or claim reads them. Both
can be rebuilt with the recorded scripts:

- The generated worlds come from the engine's generator, seed 20261016, with
  the canonical train settings.
- The cut-4 states come from the pinned base.

The small train-split features (`train_features/`, 1.6 GB), the generated
data file and every script stay.

## Procedure

[`retire_v20_a2_dev.sh`](retire_v20_a2_dev.sh) is to be run once on Furnace,
by Ryō. It checks every file's size and SHA-256 against the inventory and
removes nothing if any differs. It then removes the six files and the two
empty folders, and writes `DELETE_FINISHED.json` (bytes, available space
before and after) into the task root.
