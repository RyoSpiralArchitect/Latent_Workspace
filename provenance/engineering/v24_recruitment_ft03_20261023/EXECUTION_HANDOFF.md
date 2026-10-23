# V24 R1 FT03: external-observer recovery and unchanged paired Full FT

2026-10-23 JST. Ryō authorized fixing and regression-testing the failed audit
in a **new source and separate trial**, with the same numerical conditions and
safety floors. [FT01](../v24_recruitment_ft01_20261023/README.md) and
[FT02](../v24_recruitment_ft02_20261023/README.md) remain immutable stopped trials.
This document starts at pre-dispatch status; actual observations are added below.

## Audit-only source change

The old `qualification_isolation.py`, original V24 runner and original plan
are unchanged. The new [entry](../../../scripts/run_v24_recruitment_ft03.py)
uses the exact original numerical/phase functions in a separate module namespace
and a new `qualification_isolation_v2.py` boundary. Its standalone stdlib-only
`qualification_observer.py` process is outside pytest's module/mocking state.
It records PID identity, observer source hash, each sample and its own terminal
in an exclusively created, flushed JSONL journal, bound into qualification.

Each bad command/parse sample preserves stage, command, error type/message,
bounded stdout/stderr and whole-output hashes, and stops the observer. Missing
or failed samples, absent terminals, changed source/journals and own GPU clients
still reject admission. The successful-sample interval remains 0.5 seconds;
commands remain bounded at 10 seconds. This remains sampled observation and
CUDA visibility, **not an OS sandbox or continuous proof of GPU absence**.
The historical ValueError cause remains unknown; shared-state exposure is a
separately identified vulnerability, not an asserted historical root cause.

The new [plan](../../../configs/v24/RECRUITMENT_FT_03.json) retains all original
570 tests and adds 38 audit/recovery regressions: **608 per device**, no exclusions.
The same 4-GiB / 900-second qualification envelope remains. Local targeted
verification: **76/76 PASS**. Local full suite: **604/608 PASS**, with four existing
fresh-process owner/preservation replay tests unable to import `typing_extensions`
under macOS Python 3.13 `-I` (Torch 2.11.0). These environment failures are not
waived or described as a green full suite. Furnace's already-used Torch 2.13.0
environment must pass **all 608** tests on each device before 7B admission.
Ruff and both shell syntax checks passed; no global dependency was modified.

## Exact scope and phase gates

Source checkout on Furnace:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft03-20261023`.
New output only:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft03-20261023`.
The published exact source commit is passed explicitly to each launcher;
it rejects a different HEAD or dirty checkout and seals all relevant sources.

1. `scripts/launch_v24_recruitment_ft03_checks.sh <exact-source-commit>`:
   CPU qualification plus independent audit, then CUDA qualification, then
   two mixed-route canary updates and exact fresh-process update-2 replay.
2. Only after verified complete replay: separately inventory and publish any
   spent/superseded canary retirement. There is no automatic deletion. Preserve
   FT01's interrupted status even if its obsolete body is subsequently retired.
3. `scripts/launch_v24_recruitment_ft03_training.sh <exact-source-commit>`:
   require matching checks and a published one-canary retirement receipt;
   inline then workspace, both initialized independently from original Mistral.

Both scientific arms: seed 47, native BF16 / FP32 CPU optimizer masters,
Adafactor 2e-7, P=0, 32 updates / 538 matched ordered rows / 21,112 targets.
No data resampling, target changes, altered numerical body, changed source
recipe, threshold change, held-out model exposure or inherited canary weights.
GPU admission/cap/abort 31/30.5/0.75 GiB; host 100/24 GiB; disk floor 50 GiB;
14,400 seconds per real role. Another GPU client still stops only this trial.
Final-save forecast remains two times 28 GiB plus the 50-GiB floor.

After the [V18 retirement](../../inventory/v24_v18_engineering_20261023/README.md),
the shared disk sample was 99.89 GiB: enough for one canary but not yet both
scientific finals. Recheck live capacity. Any additional retirement requires
its exact published ledger and body/hash/in-use/protected-input verification.
Original Mistral, V22 step32, both V23 finals and private data remain protected.

No automatic retry, recurring monitor, judge, new generation, PR, HF export
or release is included. Old FAIL / winner:none / non-regression NOT_ESTABLISHED.
On any new failure, retain evidence and request a recovery decision.
