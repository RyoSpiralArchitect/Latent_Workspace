# V23 P-on recovery 01 — stopped at CPU test collection

Source: `106e12314d72a16a0515a5961989ed49a193a4f8`.
Launch: `2026-10-21T23:39:49Z` / 2026-10-22 08:39:49 JST.
No CUDA qualification, P-on evaluation, training, saved weight, deletion,
judge study or MMLU-Pro model call was dispatched in this attempt.

## Separate the two gates

The [CPU isolation audit](furnace/qualification/CPU_ISOLATION.json) passed:
parent PID `3789547` and child PID `3789579` saw zero CUDA devices; the child
rejected `torch.cuda.init()` with RuntimeError and stayed uninitialized.
The parent also stayed uninitialized; sampled parent/descendant GPU clients
were empty and there were no monitoring errors. This is sampled visibility
evidence, not an OS security sandbox or proof about the earlier initializing API.

The [CPU test receipt](furnace/qualification/cpu/FINISHED.json) is
**INCOMPLETE_NO_RETRY**: pytest exit 2, **one collection error**, zero completed
test bodies, out of 244 planned tests. Its XML counter `tests:1` is the failed
collection record, not one successful test. Elapsed qualification 3.432172 s.
The error is `CPU visibility must be set before importing torch`.

Cause: the entry ran as `__main__`, correctly masked before imports, then
pytest collected a test importing that same entry under its module name.
The second entry call mistook an already registered, correctly isolated
process for a late attempt to mask torch. This is another operator harness
error, not a result about P-on quality. The sequential launcher stopped at
the nonzero CPU qualification exit. The separate isolation PASS cannot
override the failed test gate.

All six raw files are preserved, including the [launch log](furnace/LAUNCH.log).
`python3 -B provenance/pilots/v23_comparison_recovery01_20261022/verify_terminal.py`
replays every historical source hash, CPU manifest/XML and isolation audit.
Original comparison source `84073310cd7b2c56b5e3de046fb3bdc99e461bfb` and its
completed base/off and 79-row stopped P-on arm are still unchanged.

## Repair prepared, not executed

The additive repair admits reentry only when this PID was registered before
the first imports and its mask is still empty. An unregistered PID, a changed
PID, or a removed mask still fails. Regressions include a fresh actual-entry
reload and pytest collection with the real `qualify --device cpu` argv.
The local boundary/judge/MMLU-Pro selection passes **64/64**. This is not a
new Furnace gate. The separately named
[recovery-02 plan](../../../configs/v23/COMPARISON_RECOVERY_02.json) requires
**248/248 CPU and 248/248 CUDA** tests before a whole fresh P-on arm.
An explicit recovery decision was requested; recovery 02 remains
**NOT_DISPATCHED** pending that decision.

The calibrated Mistral controls remain 32/32 valid/expected, with zero of 174
study requests dispatched. MMLU-Pro remains zero of 840 direct scores and
zero of 84 reasoning sequences. The old expression gate remains **FAIL**,
winner **none**, non-regression **NOT_ESTABLISHED**.
