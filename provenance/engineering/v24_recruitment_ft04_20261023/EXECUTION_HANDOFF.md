# V24 R1 FT04: operation-specific snapshot/storage admission

**Current update:** checks passed and the subsequently authorized FT03/FT04
canary-only retirement is complete. The same frozen FT04 source entered paired
scientific training at about **16:52 JST on 2026-10-23**. Inline runs first;
workspace is gated on its success. **RUNNING, not a completed training or quality
result.** The [results/progress](README.md) and [offline checks replay](OFFLINE_CHECKS_VERIFICATION.json)
separate the completed checks from this new phase. Earlier progress notes below
are historical. Do not rerun checks, training, or the retirement helper.

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

## Dispatch record

Execution source **4b69c6b0d604f4947b7075e40430b9b8f113f4ad** was published
before deletion or execution. The new detached Furnace checkout was clean and
the GPU idle at dispatch. The one-shot checks launcher was started in tmux
`ltws-v24-recruitment-checks04-20261023` at approximately 16:12 JST.
The qualified test-file list was independently collected: **643 cases**.
No source changes are to be applied to this checkout while the run is active.

The FT01-only deletion is complete; the post-deletion journal shows about
97.24 GiB free. All current scientific comparators and FT03's body remain.
Training has not been dispatched. Once checks close, copy metadata only and
use the separately published `scripts/verify_v24_recruitment_ft04.py` to replay
source, qualification, per-operation resources, full next-update equality,
and the unchanged FT03 numerical fingerprints. Do not rerun a failed role.

## Closed qualification / real-model checks in progress

The source seal contains **856 files** at the execution commit above.
Both qualifications passed **643/643**, with zero failures/errors/skips:
CPU **74.029 s**, CUDA **80.163 s**. The independent observer recorded
**140 successful samples / zero errors**, exited normally on requested stop,
and rejected the child CUDA-init probe. CPU PID 5486; observer PID 5513.
These sampled observations are not continuous OS-level GPU isolation.

The closed [qualification artifacts](furnace/qualification/) and source seal
have been copied byte-for-byte, with no tensor bodies or private data.
[Offline verification](OFFLINE_QUALIFICATION_VERIFICATION.json) passes against
the complete frozen source archive. The independent verification/retirement
and historical regressions now pass **77/77** locally. These post-publication
tests are not added retroactively to the frozen 643-per-device run.

The 7B canary is running as PID **17311**, beginning the same mixed-route
windows from original Mistral. Its two-update terminal, payload hash and fresh
process replay have not yet completed at this progress handoff. Do not
restart, edit the execution checkout, or invoke training before its gates.

## Final handoff: checks passed, training awaits storage authority

The checks terminal is `V24_ROUTE_CHECKS_COMPLETE_NOT_TRAINING`, completed roles
`canary,replay`, **3 total engineering/replay updates**. Both processes exited;
the GPU was idle afterward. Canary elapsed 489.139 s, replay 343.692 s, dispatcher
843.772 s. Full metadata/logs were copied without weights or private data and
verified offline against source `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`.

The capacity gate remains: approximately 70.23 GiB free versus 110 GiB required
for the paired finals. Only FT01's previously approved body was removed. FT03
and FT04 canaries remain; original Mistral/V22/V23 finals stay protected.
A new specific cleanup decision or other storage is needed before proceeding.
Do not invent a retirement receipt, lower the floor, retry either old failure,
change data or source, or dispatch a scientific arm with insufficient capacity.

Final publication verification: **87/87** selected offline cases and Ruff pass.
Both retained engineering bodies were independently rehashed after the run;
scientific final file identities still match the retirement ledger. The
execution checkout remains clean at its original source commit. Further
publication commits change local analysis/docs only, not that checkout.

## New authority, completed cleanup and live training

Ryō explicitly accepted the two-canary proposal. The
[published retirement ledger](../../inventory/v24_ft04_canaries_20261023/README.md)
at `62f2d78afb626db0809c7bfab4c7df14e2dc9f77` preceded whole-body revalidation
and deletion of exactly the FT04 and FT03 `canary_step1.pt` paths. The terminal
at 07:49:33 UTC records **54.0249 GiB reclaimed / 124.2520 GiB free**. Original
Mistral, V22 step32, both V23 finals and historical failures remain protected.
FT03 has no synthetic replay or retirement-training receipt. FT04's real
[spent-canary receipt](furnace/CANARY_RETIREMENT.json) is separately bound to
its completed exact replay. Deletion records were pushed at
`509f52328c1fc63d00efeefb078c7abf7ac9552b` before training launch.

The GPU was idle, host available memory about 120 GiB, and the execution
checkout still clean at **4b69c6b0d604f4947b7075e40430b9b8f113f4ad**.
One-shot tmux: **`ltws-v24-recruitment-training04-20261023`**.
Launcher: `scripts/launch_v24_recruitment_ft04_training.sh`, with that exact
source commit. Output remains the FT04 path above, not a new attempt.
All 856 source files passed pre-import verification. Inline admission reported
133,414,256,640 free disk bytes and a 64,424,509,440-byte future-write forecast,
thus preserving more than the 50-GiB floor. Original base loading completed.
At that initial launch observation no completed scientific update was claimed.

The frozen dispatcher runs inline then workspace, each 32 updates / 538 rows /
21,112 targets and one final save; both initialize independently from original
Mistral. Development NLL is descriptive only. A foreign GPU client, resource
failure or nonzero child exit stops the run without retry. Do not restart it,
edit source/data, remove another checkpoint, or lower any safety threshold.
No new generation, judge, benchmark, PR or HF export is included.

On completion, copy metadata/logs only (never the checkpoint directory), then
run `scripts/verify_v24_recruitment_ft04.py <local-furnace-bundle> --phase training`.
Expect 32 updates per scientific role, 64 scientific / 67 total including checks,
and complete closed manifests before calling training complete. If stopped,
preserve all missingness and request recovery direction, never resume silently.
No recurring monitor was created. Local publication regressions remain
**103/103 PASS** plus Ruff; old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

### First scientific update observed, 16:57:16 JST

[Timestamped progress](TRAINING_PROGRESS_20261023T075716Z.json) records the live
inline process **PID 21717**, completed **1/32 updates / 2 backward rows /
545 target tokens**, and the next window at `step2:before_update`. The first
[complete numerical receipt](furnace/raw/inline/step1.json) matches the frozen
row order exactly. All 291 FP32 master tensors changed; native, master and
optimizer hashes differ from the original-base initial state. Both named
[original-weight hashes](furnace/raw/inline/ORIGINAL_IDENTITY.json) match, and
all 76 pretraining development NLL rows are recorded. These are execution
checks, not improvement evidence or a completed scientific arm.

Only closed startup/first-step files were copied into the local partial bundle;
no tensor body, mutable log or invented terminal was copied. The training and
workspace terminals were still absent at observation. The live dispatcher
continues independently in tmux, with no recurring monitor. Collect the actual
terminal and remaining immutable metadata before full training verification.
