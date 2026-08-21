# Artifact retention policy

Pruning is never automatic. It requires an explicit operator flag and a
`PRUNE_RECEIPT.json`.

Verified-run weights may be pruned only after all contracted post-training
assays have completed and compact receipts have been exported and rehashed.
The prune receipt must bind:

- run ID, model revision, contract/source/data hashes;
- explicit opt-in and pruning reason;
- pre-prune file inventory, hashes, and byte counts;
- required verification and assay receipts with their hashes;
- every deleted or migrated path and bytes reclaimed;
- durable destination, if migrated;
- recoverability classification;
- start/completion timestamps and post-prune integrity check.

Invalid or interrupted runs require a separate failed-run prune receipt and
must retain enough compact evidence to explain the failure.

## Verified F0 transition

The fixed-engine F0 seed-42 run satisfied the run, assay, and exact-resume
preconditions and was transitioned from `verified_completed` to
`verified_pruned`. The retained bindings include:

- engine SHA-256
  `3139c6edea71575310a2e6f245999e504318fedede202786fe2c949861ad2e1c`;
- run-verification SHA-256
  `ba5d5a524565a9e59e6bfc207b861d786ea9e21514008318db63e1f6d8ed1191`;
- assay-verification SHA-256
  `410b295534e25f7d24faa1fd988cf86ef85bef06d2b77dff210572571ef2480a`;
- resume-equivalence SHA-256
  `5e5b4178005a89beacfb5742edd307e15401a49d1af33543da5f36374330a645`.

The path-free public summary is
[`PUBLIC_EVIDENCE.json`](../provenance/pilots/F0_fixed_engine_verified_pruned/PUBLIC_EVIDENCE.json),
SHA-256
`d787e5ac95fc355c1397d4bff2e6bcda95e41065b722ac2ac482447d35686fcb`.

The compact export was rehashed before deletion and retains manifests,
coverage, metrics, assay, resume, export, intent, and prune receipts. The exact
deleted target was `final/base_model`, with a recorded logical size of
14,496,105,708 bytes. Post-prune checks prove the target and quarantine are
absent and the retained/exported inventories still match their receipts.

This is a tested per-run retention transition, not authorization to prune
failed attempts automatically and not yet a profile-level n=3/n=10 retention
schedule.

## Failed resume attempt cleanup

The obsolete optimizer-dtype resume failure was handled by a distinct,
target-bounded transaction. It deleted 16 safetensors totaling 57,984,323,680
bytes after recomputing every target's size and SHA-256 and checking that each
was a regular, non-symlink file. Compact failure diagnostics, trainer/workspace
states, metrics, and manifests remain; the deleted shard bodies are not
guaranteed reconstructible.

The retained intent and receipt are under
[`provenance/pruning/F0_resume_attempt2_failed_optimizer_dtype_weights/`](../provenance/pruning/F0_resume_attempt2_failed_optimizer_dtype_weights/).
This explicit cleanup is negative-result retention, not a successful-resume
claim and not authorization for automatic pruning of failed or interrupted
runs.

## Capacity gate

The measured Mistral-7B final base-model bundle selected for pruning was
14,496,105,708 bytes. Keeping 190 such bundles would require about 2.754 TB
(2.505 TiB) before optimizer, workspace, checkpoint, assay, and failure
artifacts. That does not fit the
observed approximately 1.4 TB of free furnace storage.

The F0 transition proves the opt-in path, destructive-action target checks, and
`verified_pruned` classification for one run. The runner still must not start
n=10 until smoke and n=3 are complete and a profile-level export/prune schedule
has been frozen, tested, and capacity-checked without weakening fail-closed
matrix accounting.

## Recoverability boundary

Pinned initial model weights remain recoverable from their immutable model
revision. A pruned trained final weight is not reconstructible from hashes or
aggregate delta counts. The prune receipt must say so explicitly; integrity
evidence is not a backup. For the current F0 transition, the baseline run's
`final/base_model` is absent and cannot be reconstructed from its compact
evidence. Exact loadable copies currently remain in the successful
resume-equivalence pilot, but those experimental outputs are not declared or
managed as a durable backup and must not be described as one.
