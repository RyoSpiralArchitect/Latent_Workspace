# Read-only storage candidate inspection

2026-10-14 JST. This is the historical **candidate-list-only** inspection,
performed before separate authorization to delete V12 weights. These raw
receipts are not retroactively changed by the later cleanup.

[WEIGHT_SIZE_INVENTORY.json](WEIGHT_SIZE_INVENTORY.json) records 228 weight-like
files / 365.786965 GiB across this repository's scoped Furnace experiment
directories. Original model/cache directories were excluded. Weight content was
not read or hashed here; names alone do not establish role or redundancy.
[WEIGHT_METADATA_INVENTORY.json](WEIGHT_METADATA_INVENTORY.json) separately reads
small manifests/configs/coverage receipts. Neither snapshot authorizes deletion.

| Group | Files | Logical GiB | Interpretation at inspection |
| --- | ---: | ---: | --- |
| V12 calibrated route | 90 | 206.805452 | 15 final states; no implicit retention selection |
| V14 semantic chat | 44 | 82.837845 | Includes step4, step8 and final exports |
| V15 native learner | 8 | 54.400840 | Protected update/replay and reader states |
| Other scoped experiments | 86 | 21.742829 | Includes diagnostic tensors, not all checkpoints |

V14 step8/final metadata suggests duplicate exports (about 27.578 GiB across two
conditions), but weight equality was not verified. V12 stage4/step1 base exports
have no released base-update coverage; that does not prove byte equality with
the original model. Step1 and stage4 also have different release schedules and
must not be silently collapsed into one retention condition.

**Subsequent authorized action:** Ryō selected all V12 experiment weights.
The [separate hash-backed cleanup receipt](../v12_weight_prune_20261014/README.md)
records their removal and 249.571 GiB post-cleanup available space. No V14/V15
or other candidates were removed. The original inspection reported 42.831 GiB
available at its own timestamp, not the later cleanup's before measurement.
