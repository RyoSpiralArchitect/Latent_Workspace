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

Pre-execution status: inventory complete; deletion awaits ledger publication.
The one-shot journal will report the actual result separately. **Git retains
metadata only, not the tensor body; deletion cannot be undone from Git.**
