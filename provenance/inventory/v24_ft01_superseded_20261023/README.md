# Explicit FT01-only retirement, without a replay claim

2026-10-23 JST. Ryō approved deleting **only** the old FT01
`canary_step1.pt` after rehash and a published ledger. FT03's newer body,
original Mistral, V22 final and both V23 finals stay protected.

The [inventory](latent-v24-ft01-superseded-retirement01-20261023/INVENTORY.json)
records the exact canonical one-link file, complete SHA-256, original save
receipt, unchanged failure evidence, first-update numerical equivalence,
protected identities, and the full retained FT03 hash. The [helper](retire.py)
requires unchanged ledger/helper/evidence/identities, another complete target
and retained-body rehash, and an unused-file check immediately before deletion.
Eleven temporary-file-only regression cases pass; no historical helper is
weakened to accept a failed replay.

Target on Furnace:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft01-20261023/checkpoints/canary_step1.pt`.
Size **29,004,378,444 bytes (27.0124 GiB)**; whole-file SHA-256
`19a09fcccc84960795bd02aa563a6e64d1d7061eac02e3dafaa5a780b9c4d4a8`.

FT01 and FT03 remain `INCOMPLETE_NO_RETRY`; both had **NOT_RUN fresh replay**.
No `CANARY_RETIREMENT.json` training handoff is created for either failed run.
This ledger authorizes a storage action, not scientific success.

Completed once at **2026-10-23 07:10:41 UTC / 16:10:41 JST**, after publishing
the ledger and helper in `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`.
The [terminal journal](latent-v24-ft01-superseded-retirement01-20261023/DELETE_FINISHED.json)
confirms **one file / 27.0124 GiB removed**. Retained identities and historical
evidence passed post-deletion checks. Shared free space was **104,414,429,184
bytes (97.2435 GiB)** afterward, including the concurrently prepared FT04
source worktree. It is sufficient for the new checks, not the 110-GiB pair gate.
**Git retains metadata only, not the tensor body; deletion cannot be undone
from Git.** No training-admission receipt was created.
