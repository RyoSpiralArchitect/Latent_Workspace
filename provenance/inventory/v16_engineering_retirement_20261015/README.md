# Retirement of four completed V16 engineering checkpoints

2026-10-15. **Pre-deletion intent; no deletion is claimed by this revision.**
Ryō requested: "途中保存のすでにいらない重みはgit管理にして台帳にデータを記載して消して進もう☯️".
The bounded interpretation is to retire the four checkpoint bodies below after
fresh integrity checks and publication of this ledger. It is not an automatic
retention policy or permission to remove other conditions.

## Exact scope and why these files are no longer needed

All targets are under the Furnace prefix
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/`.

| Relative target | Completed step | Expected bytes | Role being retired |
| --- | ---: | ---: | --- |
| `latent-v16-adapter-migration-20261014/checkpoints/frozen_step1.pt` | 1 | 50,547,559 | Frozen adapter update/resume qualification |
| `latent-v16-adapter-migration-20261014/checkpoints/frozen_step2.pt` | 2 | 50,547,559 | Frozen adapter update/resume qualification |
| `latent-v16-adapter-recovery-02-20261014/checkpoints/full_step1.pt` | 1 | 29,054,823,004 | Full adapter update/resume qualification |
| `latent-v16-adapter-recovery-02-20261014/checkpoints/full_step2.pt` | 2 | 29,054,823,004 | Full adapter update/resume qualification |

Expected total: **58,210,741,126 logical bytes / 54.212977296 GiB**.
These are the last two saves of two **closed engineering conditions**, not
byte-identical duplicates of the main comparison, and not ordinary rotation
within an active condition. Their completed update/replay checks have served
their integration purpose. No scientific comparison or generation claim is
inferred from those qualification tests, and no new behavioral assay is invented
to justify cleanup.

The [original migration](../../pilots/v16_adapter_migration_20261014/README.md)
retains its `INCOMPLETE_NO_RETRY` result: the frozen arm completed, while full
admission did not. The separate
[full recovery](../../pilots/v16_adapter_full_recovery_02_20261014/README.md)
retains its exact engineering PASS. Source seals, raw equivalence/replay records,
checkpoint hashes, state hashes and negative receipts stay in Git unchanged.
Historical statements that the binaries existed remain historical; the later
terminal retirement receipt is authoritative for current file existence.

## Protected and excluded

- All six active V16 scientific saves remain: `common`, `raw_matched_control`,
  and `slot_contrast`, steps 1 and 2, under
  `latent-v16-full-comparison-20261014/checkpoints/`. This preserves the latest
  and previous save **per comparison condition** and the population-evaluation
  inputs.
- V15's eight saves remain across its four distinct conditions. A newer version
  number is not permission to collapse those conditions.
- The pinned original Mistral snapshot and underlying Hugging Face cache blobs
  remain. No other project's files are in scope.
- All V18 fitted toy states, populations, diagnostic tensors, source seals and
  raw control evidence remain. None is treated as a disposable checkpoint.
- No directory, metadata file, failure record or historical source is deleted.

## Transaction and recoverability

The fixed-path utility records and verifies file sizes, SHA-256, filesystem
identity, single-link regular-file status, non-symlink ancestry and visible
open-handle/process checks. It records protected-state metadata. The complete
plan and live inventory must be committed and verified on the exact GitHub
branch before any unlink. A separate deletion transaction repeats live checks
and preserves per-file and terminal outcomes, including partial failures.
Privileged processes are not fully observable; do not claim an all-process audit.

**Git contains evidence, not the checkpoint payloads.** No weight backup is
created. Hashes and metrics cannot reconstruct the deleted trained state.
Direct replay from these four files will no longer be possible after deletion;
rerunning an experiment is not a guaranteed restoration of its binary output.

## Capacity and research ceiling

The inventory's measured free space, and the terminal receipt's actual free-space
delta, must be reported separately from the logical file total. Other filesystem
activity can change available space. The previous three-arm envelope was
242 GiB including its reserve; this cleanup alone is not evidence that it fits.
A new single-arm estimate and separate GPU/host-memory admission are required.

Cleanup does not qualify the V18 native/window owner, run 7B FT, establish base
non-regression, create benchmarks or publish a model. The historical
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.
