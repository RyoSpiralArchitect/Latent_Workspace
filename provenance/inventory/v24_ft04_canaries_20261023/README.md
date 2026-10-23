# FT04 spent / FT03 superseded engineering-canary retirement

Ryō explicitly approved this two-file cleanup after FT04's exact fresh-process
replay passed. This is a new, separately published inventory, not permission to
retry or rewrite an old run. **Tensor bodies are not backed up in Git.** Only
their identities, hashes, receipts and numerical evidence remain recoverable.

## Exact scope

All paths below are on Furnace, under
`/home/ryospiralarchitect/spiralreality/SpiralReality/`.

| Authorized body | Bytes | Full-file SHA-256 |
| --- | ---: | --- |
| `latent-v24-recruitment-ft04-20261023/checkpoints/canary_step1.pt` | 29,004,378,444 | `c18804e64d48c94f8046dffba7907bacb6863fddc3434223bbd03438c3682699` |
| `latent-v24-recruitment-ft03-20261023/checkpoints/canary_step1.pt` | 29,004,378,444 | `471776810c42359141b59e7bb7f1dc607668a63114b69d4c9af8d7351b413418` |

Total: **2 files / 58,008,756,888 bytes / 54.0249 GiB**. Original Mistral, V22
step32, both V23 final comparison weights, every other checkpoint, dataset and
project are outside the deletion allowlist. FT01's old canary was already
retired under a separate authorization; it is not targeted again.

## Evidence and bounded claims

FT04 execution stays pinned to
`4b69c6b0d604f4947b7075e40430b9b8f113f4ad` (856 sealed files), independently of
this publication commit. [Its checks](../../engineering/v24_recruitment_ft04_20261023/README.md)
passed 643/643 tests per device, two canary updates and one exact replay update.
Both complete numerical update records match FT03. FT03 still has its original
`INCOMPLETE_NO_RETRY` terminal, null terminal update count, two observed updates,
and historical replay **NOT_RUN**. It does not become a successful run merely
because a separate run reproduced its numerical state.

The [helper](retire.py) verifies both frozen source archives, closed qualification
and execution receipts, both numerical update records, protected-final file
identities, and all non-tensor run evidence. It requires canonical, non-symlink,
single-link targets of exact size and full-file SHA-256, checks for open files,
then publishes an exclusive inventory. Execution requires the published
inventory hash and commit, rechecks everything and rehashes both whole bodies
before unlinking only those exact paths. It journals each unlink separately.
Only FT04 receives a spent-canary receipt bound to its actual successful replay;
no receipt is added to FT03 and no historical failure artifact changes.

The helper and verifiers execute outside the immutable scientific source tree.
They cannot launch training. Local offline/tiny-file publication regressions:
**103/103 PASS**, Ruff PASS. This selection is separate from the frozen
643-per-device qualification; it does not add tests retroactively to that run.

## Publication-before-deletion gate

[Exclusive inventory](latent-v24-ft04-canary-retirement01-20261023/INVENTORY.json)
must be committed and pushed before execution. At this pre-deletion publication
stage, no body has been removed by this helper and scientific FT is still unrun.
The later deletion terminal, exact FT04 spent-canary receipt, and live resource
admission will be recorded separately. Paired FT admission remains **110 GiB**,
including the unchanged **50-GiB disk floor**, with no host/GPU threshold change.
Both scientific arms start independently from original Mistral, not a canary.
Old expression gate **FAIL**, winner **none**, non-regression **NOT_ESTABLISHED**.

## Completed retirement (2026-10-23 07:49:33 UTC)

The inventory SHA-256
`6bec3c6b913ded104bd57d448943dde1918483876e2b5c23fd88463ce33e447e`
was published at commit `62f2d78afb626db0809c7bfab4c7df14e2dc9f77` before
execution. Both complete bodies were rehashed again immediately before the
exclusive deletion sequence. [Terminal](latent-v24-ft04-canary-retirement01-20261023/DELETE_FINISHED.json):
**2/2 exact files retired, 58,008,756,888 bytes**, all protected-final identities
and historical non-tensor evidence unchanged. Free space rose from
75,405,856,768 to **133,414,617,088 bytes / 124.2520 GiB** at that boundary.
This exceeds 110 GiB; training still rechecks live availability at admission.

The [FT04-only spent-canary receipt](../../engineering/v24_recruitment_ft04_20261023/furnace/CANARY_RETIREMENT.json)
binds the actual replay, original save receipt, published ledger and combined
deletion terminal. Its one-file count refers only to the FT04 body; the combined
journal has two. FT03 has no such receipt and its historical failed status is
unchanged. No deletion was applied to original Mistral or V22/V23 final weights.
Deleted tensor bytes cannot be restored from Git.
