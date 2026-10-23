# V24 FT03: observer recovered; storage forecast stopped the canary

2026-10-23. **`INCOMPLETE_NO_RETRY`, not a successful replay or scientific FT.**
The new observer passed; a separate capacity-planning defect then stopped this
trial after two recorded native updates. Original FT01/FT02 evidence is unchanged.

| Stage | Observation |
| --- | --- |
| Frozen source | `09addc856ba6f10da31054f1674c7547b1ab91ad`, 845 sealed files |
| CPU / CUDA qualification | 608/608 each; zero failures/errors/skips; 72.308 / 80.340 s |
| Independent CPU/GPU observer | 137 samples, zero errors, clean terminal; no own GPU client observed |
| Canary execution | 2/2 update records, 8 backward rows, 2,220 targets |
| Saved tensor bodies | One step-1 checkpoint, 29,004,378,444 bytes |
| Terminal update count | `null`; no completed role is claimed |
| Step-2 payload hash / fresh-process replay | Not written / `NOT_RUN` |
| Scientific updates / new generations / judge calls | 0 / 0 / 0 |

The first-window rows, losses, accumulated-gradient hashes, update receipt and
entire state fingerprint exactly reproduce FT01. This supports first-update
numerical equivalence of the audit-only recovery, not a capability result or a
successful save/restore guarantee. FT03's whole serialized payload hash differs
from FT01 because the source-bound run contract differs.

## Exact stop, and the overlooked forecast

The canary ran for **500.812 seconds**. After writing `step2.json`, it called
the old `snapshot_admission` before constructing a CPU payload solely to hash
it and write a small JSON digest. The shared helper nevertheless invoked
`guard("before_checkpoint", forecast_bytes=32 GiB)`.

The [host-resource journal](furnace/raw/canary/HOST_RESOURCES.jsonl) records:

- Actual disk free: **76,828,856,320 bytes = 71.5524 GiB**.
- Additional disk forecast: **34,359,738,368 bytes = 32 GiB**.
- Unchanged floor: **50 GiB**. Actual free exceeded the floor, but
  `71.5524 - 32 < 50`, so `ValueError: Forecast disk envelope` stopped the role.
- Last GPU sample contained only this trial's PID. Peak allocated/reserved:
  **29,797,427,712 / 32,210,157,568 bytes** (27.751 / 29.998 GiB).

This is **not an OOM or a repeat of the observer error**. The launcher behaved
fail-closed. Our 78-GiB pre-admission estimate accounted for one at-most-28-GiB
canary plus the 50-GiB floor, but missed the inherited *post-save* 32-GiB
forecast. The unchanged implementation therefore needed about 109.01 GiB
before the actual 27.0124-GiB save for that later gate, not merely 78 GiB.
The same helper also forecasts a new file while restoring an existing one.
These are code-path observations, not retrospective waivers of this failure.

No second tensor checkpoint was going to be written at the failed call site.
The intended next operation was `tree_hash(owner.payload())`; the full payload
was not materialized because admission failed first. Its independent host-memory
headroom check must still be preserved in any repair. Actual file writes also
must retain their conservative forecast, as well as all GPU/host/disk floors.

## Frozen evidence and retained weights

The [offline stop replay](OFFLINE_STOP_VERIFICATION.json) verifies source,
qualification, terminal manifests, all eight row receipts, both updates, missing
successors and the exact forecast failure. It deliberately preserves terminal
`native_weight_updates: null` separately from two observed update records.
The original terminal SHA256 is
`6aa7c9f5c3296f5588170261b92c3298faf816c5c5d8ec0c5aee6daf61f2eb7f`.

[Post-stop whole-body rehash](POST_STOP_BODY_REHASH.json) confirms both retained
FT01 and FT03 canaries match their save receipts. FT03 checkpoint SHA256:
`471776810c42359141b59e7bb7f1dc607668a63114b69d4c9af8d7351b413418`;
payload SHA256: `56338bf1774ff7805cd359ea55fe11fd33dd6ab9a1656bc6ba22a81feb1a2c05`.
Rehashing is not restoring or replaying. Neither canary was deleted.

The prepared [two-canary retirement helper](../../inventory/v24_ft03_canaries_20261023/retire.py)
**rejects this failed FT03**; its successful-replay precondition is unmet.
No retirement inventory or deletion was executed. Offline verification and
retirement regressions now pass **56/56**, including rejection of this actual
failure and mutations of its evidence. This does not alter the frozen 608-test
execution denominator. Ruff passes.

## Proposed next decision, not a dispatched recovery

Separate in-memory snapshot/restore admission from actual file-write admission,
retain the independent host-memory reserve and all safety floors, and regression
test both kinds of operation before sealing a new source/attempt. Do not resume
FT03 in place or manufacture its missing payload/replay receipt.

Space is also insufficient for another new canary at the current 71.55 GiB.
A separate proposed cleanup selects only FT01's older 27.0124-GiB canary after
rehashing and publishing its ledger, while retaining FT03, original Mistral and
all V22/V23 finals. Its first-update numerical equivalence is established, but
exact fresh-process replay remains unverified. That changed cleanup decision
and the new recovery were explicitly put to Ryō; neither is assumed approved.

Old expression gate **FAIL**, winner **none**, non-regression **NOT_ESTABLISHED**.
No PR, release, held-out exposure, new model generation or judge call occurred.
