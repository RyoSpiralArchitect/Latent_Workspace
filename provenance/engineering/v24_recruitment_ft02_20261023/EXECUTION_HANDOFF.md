# V24 R1 attempt 02: same-source, fresh-output recovery

2026-10-23 JST. Ryō confirmed that Furnace was cleared and authorized the
same-conditions separate attempt through checks and paired Full FT. This is
not an in-place resume of [FT01](../v24_recruitment_ft01_20261023/README.md).
FT01 remains `INCOMPLETE_NO_RETRY`, with its one update, contention record,
missing replay and all original receipt bytes retained.

## Immutable execution and separate orchestration

Reuse the clean isolated source checkout at
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft01-20261023`,
exact commit **d43382833f6dc85787720bda80aec511c66f58be**. No numerical engine,
test selection, data, seed, model, target budget, coefficient, resource floor
or source seal changes. The new seal must equal the FT01 seal byte for byte.
Reusing the isolated checkout also avoids copying another 1.3-GiB source tree.

New output only:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft02-20261023`.
The two external launch scripts in this directory are publication-controlled
orchestration, not edits to the frozen execution checkout. They are copied
into the output for provenance and each permits only a previously absent
phase. The original hardcoded FT01 launchers must not be invoked again.

1. [Checks](launch_checks.sh): fresh isolated CPU/CUDA 570-test qualifications,
   then two mixed-route 7B updates and exact fresh-process update-2 replay.
   No auto-retry or training transition.
2. After complete replay, separately inventory, publish and retire the spent
   FT02 canary. FT01's failed canary may be retired as a superseded engineering
   body only with its own explicit ledger and without rewriting its failure.
3. [Training](launch_training.sh): exact original runner, inline then workspace,
   each from original Mistral, 32 updates / 538 rows / 21,112 targets; two finals.
   The unchanged 50-GiB disk floor must hold for both saves.

GPU admission/allocator/abort 31/30.5/0.75 GiB; host admission/abort 100/24 GiB;
14,400 seconds per real role. Another GPU client still stops only our job.
Tiny qualification remains 4 GiB / 900 seconds per device. No weakening to
accept contention, no automatic retries, no other-project cleanup.

## Capacity and disposition

On this turn the GPU was idle, but shared disk free space was only
49,089,667,072 bytes (45.72 GiB). The old, completely replayed two-update V18
engineering pair is now a retirement candidate under the existing unused-body
cleanup authorization. It has no role in the current V22/V23/V24 comparisons.
Publish its full hashes/ledger before deleting it. Keep original Mistral,
V22 step32, both V23 finals, private teacher/preservation arrays, and FT01's
canary until the separate recovery succeeds. No source worktree is deleted.

The preceding V15 deletion remains a distinct historical action, not evidence
that shared disk space has stayed constant. Recheck live storage at every gate.

**Pre-dispatch status:** preparation only. No FT02 role has run yet. Record
actual receipts below after launch; never convert engineering completion into
a capability or release claim. Old FAIL / winner:none / non-regression
NOT_ESTABLISHED remain. No new generation, judge call, held-out model exposure,
HF export, PR or recurring monitor is part of this attempt.
