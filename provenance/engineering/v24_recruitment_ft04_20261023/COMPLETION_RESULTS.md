# V24 R1 FT04 — completed training, local recovery, shutdown handoff

Observed and recovered on **2026-10-23, 19:25–19:32 JST**.
Both independently initialized scientific arms completed **32/32 updates**.
This is an execution/recovery result, **not a model-quality or release gate**.

## Verified execution and recovery

- Frozen source: `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`; **856/856 source files** match the live Furnace checkout and the local Git archive. The remote checkout remains clean.
- Inline and workspace: **538 ordered backward rows and 21,112 supervised target tokens per arm**. Scientific updates: **64**; engineering plus exact replay: **3**; total: **67**.
- Initial numerical fingerprints and original-base identity receipts are identical between arms. Both start from original pinned Mistral, not from the canary or the other arm.
- Existing qualification: **643/643 CPU and 643/643 CUDA tests**, no failures/errors/skips. Qualification was not rerun during recovery.
- Canary next-update and full payload replay remain exact; the two canary updates still reproduce the immutable FT03 numerical receipts.
- Closed role, phase and whole-run manifests pass [the unchanged offline verifier](../../../scripts/verify_v24_recruitment_ft04.py). Its [saved output](OFFLINE_TRAINING_VERIFICATION.json) is `PAIRED_NATIVE_FT_COMPLETE_NOT_QUALITY`.
- **2,312 files / 11,597,024 bytes** of closed metadata and logs were recovered to [furnace/](furnace/). The whole allowlisted metadata manifest matches Furnace byte-for-byte: `f88b6bd7a50c057346d3f1345ea2b58b25d2790a8262ead5abb38a2acf16eb04`. Previously recovered files also match; none were replaced by divergent data.
- [Metadata/source verification](METADATA_RECOVERY_VERIFICATION.json), [recorded-resource and NLL audit](RECOVERY_RESOURCE_AND_DEV_AUDIT.json), and [final tensor-body verification](FINAL_CHECKPOINT_BODY_VERIFICATION.json) are separate receipts. No model was loaded or run for recovery.

Inline elapsed **4511.125 s**; workspace **4543.137 s**; paired dispatcher **9,063.214 s**.
Both arms report peak allocated CUDA memory **27.7510 GiB**, peak reserved **28.8516 GiB**.
The 31-GiB GPU admission, 30.5-GiB allocator cap, 0.75-GiB sampled free floor, 100/24-GiB host floors, independent snapshot reserve, 50-GiB disk floor, and 14,400-second role cap were not changed. Recorded checks satisfy the applicable bounds; no foreign GPU client was observed. These receipts are sampled checks, **not continuous OS-level isolation**.

## Descriptive development NLL — no new evaluation

The already-run, frozen teacher-forced development set contains **76 rows / 5,002 target tokens per arm per observation**, with identical ordered row keys and target counts across all four observations. These are token-weighted bucket NLLs, recalculated from the closed loss-sum receipts. Lower is better for this specific likelihood measure.

| Bucket | Rows | Targets | Inline: original → step 32 | Workspace: original → step 32 |
|---|---:|---:|---:|---:|
| code | 4 | 1713 | 0.608802 → 0.515583 | 0.608802 → 0.513944 |
| instruction | 8 | 2267 | 0.906922 → 0.802132 | 0.906922 → 0.801458 |
| prose | 4 | 508 | 2.441028 → 2.403962 | 2.441028 → 2.403663 |
| reasoning | 18 | 242 | 3.245476 → 0.216048 | 4.779231 → 0.255778 |
| world/absent | 7 | 28 | 2.618527 → 0.004118 | 2.618527 → 0.007799 |
| world/affected | 14 | 106 | 3.109987 → 0.163604 | 3.330069 → 0.138985 |
| world/unaffected | 14 | 110 | 2.283114 → 0.011617 | 3.074761 → 0.029600 |
| world/unrelated | 7 | 28 | 2.233769 → 0.038292 | 2.432826 → 0.072385 |

Across all development target tokens: inline **1.167729 → 0.798667**; workspace **1.265121 → 0.799777**.

Sources: [inline original](furnace/raw/inline/DEV_BASE.json), [inline step 32](furnace/raw/inline/DEV_STEP32.json), [workspace original](furnace/raw/workspace/DEV_BASE.json), [workspace step 32](furnace/raw/workspace/DEV_STEP32.json). Full-precision values and denominators are retained in the [audit](RECOVERY_RESOURCE_AND_DEV_AUDIT.json).

Every displayed bucket decreases within its own route. Workspace has lower final affected-world NLL than inline, but higher final reasoning, unaffected-world, absent-world and unrelated-world NLL. This is a **descriptive route/training contrast**, not evidence that one arm improves general intelligence. Route-dependent inputs already differ at step 0; this is not matched FLOPs, a newly computed S, a causal workspace-utility assay, an accuracy result, or a free-generation comparison. The code/prose buckets each contain only four rows. No benchmark, generation, judge or confirmation/OOD call was added.

**Unchanged claim ceiling:** old expression gate **FAIL**; **winner: none**; **non_regression: NOT_ESTABLISHED**. Development NLL does not satisfy the base-preservation or release gate.

## Final checkpoint bodies

Both complete files were read and independently SHA-256 hashed on Furnace from **19:26:03 to 19:27:20 JST**. Sizes and modification times were unchanged before/after reading, and both full-file hashes match their original save receipts.

| File | Bytes | Full-file SHA-256 |
|---|---:|---|
| `inline_step32.pt` | 29,004,413,900 | `a906d6dcfe8d4ced05bcc76580f807b155a3ff98167b186d4eaebaad0bf6d468` |
| `workspace_step32.pt` | 29,004,413,900 | `2b62622f1702384a718662d975181540b13618ddfde0dedc80166ff1523d688f` |

Both bodies remain under `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft04-20261023/checkpoints` on **Furnace's SSD**. This is **not an off-host weight backup**. No tensor body was copied to the Mac or Git; no checkpoint was deleted. Original Mistral and the protected V22/V23 finals were not modified.

## Shutdown disposition — action required

[Terminal handoff](SHUTDOWN_HANDOFF.json): **READY_FOR_SHUTDOWN_AUTH_REQUIRED**.
This means recovery is ready for the human shutdown handoff, **not that automatic poweroff is cleared**.

- The training processes exited; the GPU has no compute client. No transfer CLI process or queued systemd job was observed at the final check.
- Filesystems were synchronized successfully at **19:32:34 JST**, after recovery and both body hashes passed.
- `sudo -n -l` requires interactive authentication; logind `CanPowerOff` remains `challenge`.
- Existing login/Codex/Claude sessions and SMB clients remain. SMB clients showed some CPU activity; their transfer/write status could not be verified without root access. No claim is made that shared transfers or unsaved interactive work are safe to discard.
- Normal ModemManager/UPower sleep-delay and Unattended Upgrades shutdown-delay inhibitors remain. No inhibitor was bypassed, no process was terminated, and no authentication policy was changed.
- **No poweroff command was issued; the host is not confirmed powered off.** Ryō should confirm/finish shared transfers and unsaved work, then authenticate ordinary graceful shutdown in their own terminal. Do not send a password in chat or force shutdown.

The completion heartbeat was **deleted at 19:34:59 JST** after this terminal handoff to prevent repeat recovery or shutdown; see [automation-removal receipt](AUTOMATION_REMOVAL.json). All recovered files and summaries remain local and uncommitted; **no GitHub push, PR, upload, new model call, or weight deletion** was performed in this follow-up.
