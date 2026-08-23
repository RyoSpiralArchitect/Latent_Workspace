# Artifact retention policy

Pruning is never automatic. It requires an explicit operator flag and a
`PRUNE_RECEIPT.json`.

Verified-run weights may be pruned only after all contracted post-training
assays have completed, the pre-prune generation behavior workflow has passed,
its human observation note preserves negative results, and compact receipts
have been exported and rehashed. See
[`GENERATION_BEHAVIOR_WORKFLOW.md`](GENERATION_BEHAVIOR_WORKFLOW.md).
The prune receipt must bind:

- run ID, model revision, contract/source/data hashes;
- explicit opt-in and pruning reason;
- pre-prune file inventory, hashes, and byte counts;
- required verification and assay receipts with their hashes;
- the generation behavior receipt and human observation note hashes;
- every deleted or migrated path and bytes reclaimed;
- durable destination, if migrated;
- recoverability classification;
- start/completion timestamps and post-prune integrity check.

Invalid or interrupted runs require a separate failed-run prune receipt and
must retain enough compact evidence to explain the failure.

One-step transport engineering pilots are not formal verified runs. Their
target-bounded cleanup uses the separate `transport_pilot_weights_pruned` state,
and only after its generation receipt, human observation note, tensor/state
oracles, exact shard inventory, and GitHub-published prune intent are all bound.

## Verified smoke transitions

The seed-42 smoke runs for F0, B, F1, and O3 each satisfied
their run, configured assay, and exact-resume preconditions before moving from
`verified_completed` to `verified_pruned`. The engine SHA-256 used by those
historical transitions is
`755ddaee835cd6cf0d30269212226250a5aeed14e5457385ceca60db0f39aa3c`.

For each run, the exact derived deletion target was `final/base_model`, with a
recorded logical size of 14,496,105,708 bytes. The four transactions removed
57,984,422,832 logical bytes in total. Every compact export was rehashed before
deletion and retains the manifests, coverage, metrics, configured assay,
resume, export, intent, and prune receipts selected by the policy. Post-prune
checks prove each target and quarantine are absent and the retained/exported
inventories still match their receipts.

The compact evidence is under
[`provenance/pilots/v10_cuda_smoke_current/smoke/`](../provenance/pilots/v10_cuda_smoke_current/smoke/).
The full research result and condition-specific receipt hashes are in
[`docs/CUDA_SMOKE_STATUS.md`](CUDA_SMOKE_STATUS.md).

These are tested per-run retention transitions, not authorization to prune
failed attempts automatically and not yet a complete n=3/n=10 profile-level
retention schedule.

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

## Current CUDA duplicate cleanup

After the current F0 oracle and all four same-spill resume comparisons passed,
an independent intent-bound transaction removed the remaining experimental
trained-weight bodies outside the protected model cache. The exact scope was 76
regular, single-link safetensor shards across 19 d5-oracle, current-native,
noncanonical B diagnostic, and resume checkpoint/final bundles.

The transaction revalidated every target SHA-256 twice, moved each exact inode
to a same-filesystem `renameat2(RENAME_NOREPLACE)` quarantine, revalidated the
complete quarantine, and then unlinked only the literal intent paths. It removed
275,425,537,480 logical bytes / 275,426,062,336 allocated bytes; the observed
unlink free-space delta exactly matched the allocated-byte total. Independent
postflight found zero trained safetensors outside the pinned model cache and
reverified all 17 bound evidence artifacts.

The receipt is
[`PRUNE_RECEIPT.json`](../provenance/pruning/current_cuda_oracle_and_resume_raw_weights/PRUNE_RECEIPT.json),
SHA-256
`98572e528ebb9b15475ce9f16a586363ebd026c3b468421662f5a434c1f0b0c8`.
It also records one earlier schema mismatch that failed closed before target
hashing, rename, or unlink.

## Behavior-gated transport-v2 cleanup

The first generation-behavior-gated transition is complete. Its exact intent
was published at GitHub commit
`a80c9539280b51537bb294e1518b9d486efea0f5` before unlink. The transaction then
rehashed all targets and nine compact evidence artifacts, verified the pinned
model-cache metadata, moved the exact inodes through a same-filesystem
`renameat2(RENAME_NOREPLACE)` quarantine, and unlinked only after the full
quarantine passed.

The scope was 80 shards across ten one-step transport run directories, with
both `checkpoint-1/base_model` and `final/base_model` represented. It removed
289,921,618,400 logical bytes / 289,922,170,880 allocated bytes. The observed
unlink free-space delta exactly matched the allocated-byte total. Independent
postflight found zero transport-v2 safetensors, retained 386 non-weight files,
and found zero trained safetensors anywhere under `runs/v10` outside the
protected model cache. The cache retained its four pinned model shards and its
metadata snapshot remained unchanged.

The state is deliberately `transport_pilot_weights_pruned`, not
`verified_pruned`. The
[`PRUNE_INTENT.json`](../provenance/pruning/transport_v2_step1_raw_weights/PRUNE_INTENT.json)
SHA-256 is
`37b193705177d425fe55e81bd526e5d93e953280fd6b6c587cc640fc29303692`;
the
[`PRUNE_RECEIPT.json`](../provenance/pruning/transport_v2_step1_raw_weights/PRUNE_RECEIPT.json)
SHA-256 is
`93866c58f15ed9f8ecb1bc86568e40894c3dade3ce8be14eb5d1ae4d77bd7e63`.
The retained pre-unlink
[`QUARANTINE_VERIFIED.json`](../provenance/pruning/transport_v2_step1_raw_weights/QUARANTINE_VERIFIED.json)
SHA-256 is
`9b7373d147f5a50cc9c46cf4b46ee2e1602251d6b95393ffe10c42de02a8b544`.
The deleted trained weights are not reconstructible from these artifacts.

## Capacity gate

The measured Mistral-7B final base-model bundle selected for pruning was
14,496,105,708 bytes. Keeping 190 such bundles would require about 2.754 TB
(2.505 TiB) before optimizer, workspace, checkpoint, assay, and failure
artifacts. That does not fit the
observed approximately 1.4 TB of free furnace storage.

The four smoke transitions prove the opt-in path, destructive-action target
checks, and `verified_pruned` classification across every smoke condition. The
runner still must not start n=10 until n=3 is complete and a profile-level
export/prune schedule has been frozen, tested, and capacity-checked without
weakening fail-closed matrix accounting.

## Recoverability boundary

Pinned initial model weights remain recoverable from their immutable model
revision. A pruned trained final weight is not reconstructible from hashes or
aggregate delta counts. The prune receipt must say so explicitly; integrity
evidence is not a backup. The four formal runs' `final/base_model` directories
are absent and cannot be reconstructed from their compact evidence. The bounded
duplicate cleanup also removed every scoped loadable trained base-model copy;
postflight found none outside the protected model cache. That cache reconstructs
only the pinned initial model, not any deleted trained state.
