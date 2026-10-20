# V22 recovery 01: cache-boundary parity passes; training dispatched

**Interim state: checks PASS; the 32-update training phase is running, not yet
complete.** Execution source `13c1192fc2727d8ca61ee215a927c0cd77f75b16` has
724 sealed files. [Frozen design](../../../docs/v22/FULL_FT_RECOVERY_01.md),
[handoff](EXECUTION_HANDOFF.md), [English data](../../data/v22_english_mixture01_20261021/README.md).

CPU and CUDA each passed **318/318** with zero errors, failures or skips.
Pytest wall times were 214.27 / 195.99 seconds; wrappers 217.553 / 199.756 seconds.
CUDA qualification peak allocated was 139,254,272 bytes. These are tiny-host
engineering tests, not 318 real-7B tasks. Local targeted tests passed 67/67.

## Actual 7B qualification

The [checks phase](furnace/checks/FINISHED.json) finished successfully in
889.186 seconds: two canary updates, one checkpoint and one fresh-process
replayed update. Both new canary update JSON records exactly match their
corresponding old trial records (all nine loss/gradient records, realized native
updates, masters/optimizer/RNG/history fingerprints). The changed execution
source contract makes complete checkpoint payload/file hashes different; these
are not asserted equal across sources.

[Fresh replay](furnace/raw/replay/REPLAY.json) matches all five rows and the
entire step-2 optimizer/native/RNG state and payload. The payload SHA-256 is
`44d5a087b896ee73f79be422f30100e2ce8106f2ab71ee550512d29573c4b789`.
Canary/replay took 526.615 / 351.125 seconds. No later role was inferred from
partial progress; each predecessor's terminal manifest is checked.

At the previously failing [first replay spill](furnace/raw/replay/CACHE_step2_row0.json),
CUDA-reported free bytes rose from **460,652,544 to 18,114,478,080** after cache
release, while live allocated bytes stayed **14,563,156,992**. The unchanged
resource guard then passed. The canary's nine cache operations took 0.299 seconds
in total and left at least 16.835 GiB free. This is a measured boundary effect,
not a general speed benchmark or a guarantee for other lengths/models.

The new retained canary body is 29,004,378,380 bytes, SHA-256
`795b96b53811f5b886f071f72203d01db4afe79489b724e481c10549d88d86e6`.
An independent complete-body `sha256sum` matched its save receipt. Raw token
data and weight bodies remain on Furnace, not Git.

## Storage and subsequent training

After the new replay passed and its evidence was published, exactly the
authorized **old failed trial's canary body** was hash-checked and deleted.
[Storage ledger and receipt](../../inventory/v22_failed_canary_retirement_20261021/README.md)
record 29,004,378,380 bytes retired, disk free 97,154,629,632 → 126,158,893,056 bytes.
The old body is not backed up; Git retains metadata, not reconstructable weight
bytes. Original Mistral, the new canary and all other weights are untouched.
The old 42-file failure bundle remains unchanged. Training processes themselves
delete zero files; this whole recovery workflow has **one** separately approved
weight deletion.

Training A/B were then dispatched once against the same execution source.
The frozen target is **32 training updates / 723 unique rows / 20,860 supervised
tokens**, not a completed count at this interim state. Train A starts from the
original model, saves at 16; fresh Train B must restore exactly and finish 32.
The fixed 40-row dev panel is diagnostic only, not public benchmark evidence.

Old **FAIL / winner:none / non_regression NOT_ESTABLISHED** stays unchanged.
No new generation, paid judge, benchmark, beta replacement, PR merge or Hub
release follows from these engineering passes.
