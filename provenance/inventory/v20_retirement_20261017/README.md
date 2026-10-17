# Retirement of the feature files of finished V19.5/V20 runs

2026-10-17. **PROPOSED: not yet run.** Ryō's standing request (2026-10-16):
"容量が逼迫していたら、途中のものでもう使わないのは台帳に記録して消してゆこう".
Ryō approved these files on 2026-10-17 ("うん、これでやろう"). The bounded
interpretation: retire the 16 files below and nothing else. It is not a
retention policy and does not cover any other file.

## Why the space is needed

The sealed A4 run (the content-gated cut-4 route) reuses the depth ladder's
cut-4 features and extracts new rows. The resource guard of every run keeps
50 GiB free on Furnace's filesystem. Before this retirement, 45.2 GiB were
available (48,568,233,984 bytes), which is below the guard's floor. Retiring
these files frees 25.2 GiB, which leaves about 70.4 GiB.

## Exact scope

Under `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/`:

| Run | Files | Bytes | Verdict on record |
| --- | --- | ---: | --- |
| A2 depth ladder (`latent-v20-a2-depth-ladder-20261016/raw/`) | `extract_cut{0,8,16}/FEATURES_{train,final}.safetensors` (6) | 16,696,247,808 | [verified](../../pilots/v20_a2_depth_ladder_20261016/README.md) |
| V19.5 D1 (`latent-v20-deliberation-pilot-20261016/raw/extract/`) | `FEATURES_{train,dev,final}.safetensors` (3) | 6,920,406,144 | [verified](../../pilots/v20_deliberation_pilot_20261016/README.md) |
| V19.5 A1 (`latent-v20-a1-ladder-20261016/raw/`) | `extract_{initial,step256,step512}/FEATURES_{train,final}.safetensors` (6) | 1,835,719,704 | [verified](../../pilots/v20_a1_ladder_20261016/README.md) |
| A2 development (`latent-v20-a2-dev-20261016/train_features/`) | `FEATURES_train.safetensors` (1) | 1,563,519,416 | development, not evidence |

Total: **27,015,893,072 bytes / 25.161 GiB**. Every file's size and SHA-256
are in [INVENTORY.json](INVENTORY.json). For the 15 files of the three sealed
runs, both were checked against the run's own committed record
(`recorded_in`, each extract role's `FINISHED.json`) and match.

## Why they are no longer needed

- **Sealed runs (15 files):** each run's verdicts were computed inside its
  roles from these features. They were then verified offline, locally and on
  Furnace. On Furnace the verifier read the features: it rehashed them for D1
  and the depth ladder, and refitted A1's probes from them
  (`OFFLINE_VERIFY_FURNACE.json` of each run). Their receipts, scores and
  checkpoints stay. Each run's offline verifier still runs without them: it accepts a
  missing `FEATURES_*.safetensors` and checks every other file. What is lost
  is the option to rerun a feature-level check on Furnace (such as A1's
  exact probe refit) without re-extracting. Re-extraction from the run's seal
  would be a new run, checked against the recorded hashes.
- **The depth ladder's cut 4 stays:** A4 reuses those two files (5.57 GB),
  pinned by the hashes in `kept`.
- **The development file:** the cut-16 train-split features from A2's
  first power checks
  ([DEV_POWER_CHECKS.md](../../pilots/v20_a2_flip_20261016/DEV_POWER_CHECKS.md)).
  No current script reads it. The A3 and A4 development scripts compute
  their states from the pinned base. It can be rebuilt with
  [dev_extract_train.py](../../pilots/v20_a2_flip_20261016/dev/dev_extract_train.py).

Only the large feature files go. Every `FINISHED.json`, `STARTED.json`, row
file, score file and resource log in these folders stays, and so do all
checkpoints, weights and scripts.

## Procedure

[`retire_v20_finished_features.sh`](retire_v20_finished_features.sh) is to be
run once on Furnace, by Ryō. It first checks that the kept cut-4 files are
present, and every listed file's size and SHA-256 against the inventory. If
anything differs it removes nothing. It then removes the 16 files and writes
`DELETE_FINISHED.json` (bytes, available space before and after) next to
itself.
