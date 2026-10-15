# Authorized Furnace V12 weight cleanup

2026-10-14 JST / 2026-10-13 16:31 UTC. **COMPLETE; permanent weight deletion.**

Ryō explicitly selected all V12 experiment weights after the
[read-only candidate inventory](../v16_storage_inspection_20261014/README.md).
This overrides latest/previous retention for **V12 only**, not other conditions
or generations. No model-quality or qualification claim follows from cleanup.

## Exact scope and result

- Source: Furnace worktree `latent-workspace-ft-v12-calibrated-route`, under
  `runs/v12/calibrated_route` only. The full absolute root is in [INVENTORY.json](INVENTORY.json).
- Deleted **90 files / 222,055,662,879 logical bytes (206.805452 GiB)**:
  60 trained/exported base shards, 15 workspace states and 15 trainer states,
  across six refinement16, six stage4 and three step1 final checkpoints.
- Available filesystem space: **45,918,445,568 → 267,974,426,624 bytes**
  (**42.764885 → 249.570633 GiB**). The observed filesystem delta includes
  allocation/metadata effects; logical file size is reported separately.
- All **315 source metadata files** retain their SHA-256 values. All **341
  remaining non-directory entries** in the scope, including model-cache entries
  and 15 chat-template files, retain their stat signatures.
- All **138 out-of-scope experiment-weight entries** in the earlier inventory
  retain their before/after stat signatures, including V14 and V15. This is a
  stat comparison, not a new full hash audit of those other weights.
- No source, config, metric, old failure, generation record or model cache was
  deleted. The original Mistral cache was not a deletion target.

The [terminal receipt](DELETE_FINISHED.json),
[per-file deletion log](DELETIONS.jsonl), and
[intent/protected-state record](DELETE_STARTED.json) preserve exact coordinates.
The read-only inventory's historical `deletion_performed:false` remains
unchanged; the later deletion is evidenced by these separate records.

## Records and recoverability

Before deletion, all 90 weights were statically hashed, and all 315 small metadata
files were copied and hash-verified on Furnace and after transfer to the local
machine. Every weight was rehashed during an all-target validation before
deletion. Exact regular-file/single-link/stat checks precede each individual
unlink. There is no recursive directory deletion and no automatic retry.

Inventory SHA-256: `543743d61d97599d182db2c7d0af6a9d38d4473b7e96b0f664a8d457e80fefe3`.
The metadata-only archive SHA-256 is
`41c65df4b87827950f8a729d8e27dc60bb5844d204c17b4cc4330e9ce047e2dc`.
It contains exactly 315 files matching the inventory's backup paths and hashes.
The archive is local artifact storage, intentionally **not committed** under the
repository's generated-archive policy. Its local location is
`provenance/inventory/v12_weight_prune_20261014/METADATA.tar.gz` in this checkout.
The full Furnace metadata-copy directory is the inventory's `output_dir` plus
`metadata`. The [previous published V12 evidence](../../pilots/v12_calibrated_route/OBSERVATIONS.md)
also remains unchanged in Git.

**No weight backups were created. Hashes and metadata cannot reconstruct the
deleted weights.** Re-creation would require retraining and cannot promise the
same bytes. Interrupted deletion would not be an atomic transaction; this run's
terminal receipt and postchecks confirm all 90 authorized paths were removed.

The narrow [pruner](../../../scripts/prune_v12_recorded_weights.py) has
[12 passing local toy-file safety tests](V12_PRUNE_TESTS.xml), covering scope,
changed files, wrong hashes, symlinks, hardlinks, path escapes, exclusive receipts
and a bad inventory seal. These tests are not a claim of crash atomicity.

Capacity is now sufficient for the previously estimated ~104-GiB minimum.
The exact new 7B execution contract must still admit its complete host/GPU/disk
forecast; no admission floor or scientific threshold was relaxed.
