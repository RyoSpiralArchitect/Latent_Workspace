# V24 R1 FT04: operation-specific snapshot/storage admission

2026-10-23 JST. Ryō explicitly authorized a correction and regression-tested
**new source/new attempt**, keeping numerical conditions and all safety floors.
[FT03's closed failure](../v24_recruitment_ft03_20261023/README.md), its source,
null terminal update count and missing replay are immutable. No in-place retry.

## Correction and scope

The inherited snapshot helper required both 32 GiB of independent host memory
and another 32-GiB disk write even for in-memory hashing or reading an existing
checkpoint. FT03 had 71.55 GiB free at the failed read-only boundary. Its actual
free space exceeded the unchanged 50-GiB floor; its fictitious future write did
not. Our earlier admission forecast missed that inherited post-save condition.

[Explicit snapshot admission](../../../scripts/native_snapshot_admission.py)
separates `checkpoint_write` (unchanged **32-GiB write reserve**),
`checkpoint_read` and `payload_hash` (**zero new tensor-file bytes**). Every
operation still requires the full independent host snapshot reserve and calls
the original GPU/host/disk/time guard. Model payload, serializer, data, BF16
forward/backward, ordered CPU FP32 master/Adafactor update and RNG are unchanged.
Phase-named resource receipts make these three operations distinguishable.

The [new entry](../../../scripts/run_v24_recruitment_ft04.py) explicitly routes
canary/save, replay/read/hash, and scientific final saves through this adapter.
It retains the original data preparation, model construction, phase/replay and
retirement gates. Historical runners/helpers are untouched; no shared module
monkeypatch or caller-name inference changes the accounting.

The [frozen plan](../../../configs/v24/RECRUITMENT_FT_04.json) retains all 608
FT03 tests, adding 35 admission/call-site/numerical-replay regressions:
**643 per device**, no excluded tests, under the same 4-GiB / 900-second caps.
Local targeted regression and historical publication/retirement checks:
**121/121 PASS**, including FP32/BF16 exact next-update and payload replay.
Ruff and launcher syntax checks pass. This is not a claim of a green local full
suite: the previously recorded four macOS isolated-import environment failures
are not waived. Furnace must qualify every selected case independently.

## Capacity and authorization boundaries

- Checks: one bounded 28-GiB canary; conservative real-write admission is
  **32+50=82 GiB**. Hashing and fresh restore do not reserve another tensor file.
- Scientific pair: prior bounded final plus last real-write reserve plus floor
  = **28+32+50=110 GiB**, before the first arm. This corrects the earlier
  56+50-GiB summary; it does not lower the old per-write or free-space safeguards.
- [Separate FT01-only cleanup](../../inventory/v24_ft01_superseded_20261023/README.md)
  has specific new authority. Both its first-step numerical equivalence and
  **NOT_RUN replay** remain explicit. It does not satisfy any training gate.
- Retain FT03's canary, original Mistral, V22 step32, and V23 off/on finals.
  After checks, neither a further deletion nor insufficient paired-FT storage
  is silently waived. No automatic deletion or training transition occurs.

Exact new Furnace source checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft04-20261023`.
Exact fresh output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft04-20261023`.
The published source commit must be passed explicitly to
`scripts/launch_v24_recruitment_ft04_checks.sh`; it rejects dirty/wrong source
and an existing output. No source checkout changes after launch.

Sequence: CPU qualification plus independent observer; CUDA qualification;
two original-base mixed-route canary updates with one step-1 save; separate
process restore and exact update-2/payload comparison. Only a successful replay
and separate authorized/published spent-canary retirement can unlock training.
No qualification or 7B result is claimed at this pre-dispatch handoff.

Numerical recipe remains seed 47, native BF16/FP32 CPU masters, Adafactor 2e-7,
P=0, 32 updates / 538 rows / 21,112 targets per scientific route, original-base
independent initialization. GPU admission/cap/abort 31/30.5/0.75 GiB; host
100/24 GiB; disk floor 50 GiB; 14,400 seconds per real role. No generation,
judge, held-out/OOD exposure, automatic retry, monitor, PR or HF publication.
Old FAIL, winner:none, non-regression NOT_ESTABLISHED remain unchanged.
