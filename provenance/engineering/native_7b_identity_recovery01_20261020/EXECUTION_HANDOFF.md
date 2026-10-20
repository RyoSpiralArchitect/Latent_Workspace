# Native-memory 7B identity recovery 01 — execution handoff

Ryō explicitly authorized the identity repair, regressions, fresh CPU/CUDA
qualification and a separate two-update/fresh-process-replay attempt at the
same limits. No full training population, generation, judge, further weight
deletion, automatic retry, PR merge, Hub upload or heartbeat.

- Execution source: `03fdb960ef4a1e4c28112deaf03ecad41a440984`.
- Plan: `configs/v1_0/NATIVE_7B_CANARY_RECOVERY_01.json`, canonical SHA-256
  `6f692b785185c60f294925a25fa22e3ee2774a86c85e0372240cc159a8657526`.
- Local checkout:
  `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`;
  branch `SpiralReality/latent-memory-full-ft`;
  origin `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Furnace source:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-native-7b-identity-recovery01-20261020`.
- Furnace output:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-native-7b-identity-recovery01-20261020`.
- Interpreter:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

CPU then CUDA must each pass **244/244**, no skips/errors/failures, from the
same sealed source, before 7B dispatch. Local selected tests: **264/264**.
The new 15 tests supplement every old case. The historical failure bundle
`provenance/engineering/native_7b_canary_20261020` remains unchanged and was
verified offline by the new verifier.

Use only one dispatcher. Inspect `raw/STARTED.json` and
`raw/DISPATCH_<role>.json` for process identities; match commands before
interpreting a PID. Do not resume, overwrite or repeat any role. The primary
plans steps 1/2 and two checkpoints; a new process restores step 1 and exactly
repeats step 2. Each role writes both named original-model hash measurements
before asserting equality. Any failure stops later roles, without retries.

After termination pull only `SOURCE_SEAL.json`, `qualification/` and `raw/`;
do **not** transfer checkpoint bodies. Run
`python -I scripts/verify_native_7b_canary.py --bundle <copied root> --repo .`.
Retain unknown activity and all partial denominators on failure. Record exact
input tokens, actual updates, native BF16 changes, loss/gradient/state/RNG
replay, resource measurements and checkpoint sizes in an English README.
Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED** regardless of an
engineering pass. Commit/push only the current work branch after validation.

## Terminal handoff — 2026-10-20

**NATIVE_7B_TWO_UPDATE_REPLAY_COMPLETE_NOT_QUALITY**, dispatcher elapsed
861.7839248431846 seconds. Both devices passed 244/244. Both real-model roles
matched both original-model identity digests. Primary completed two updates
and two saved checkpoints; replay restored step 1 and exactly repeated step 2.
Three physical update executions / two unique updates / six backward rows.

The [copied raw bundle](furnace/) has 43 files / 846,025 bytes.
[Offline verification](OFFLINE_VERIFY.json) checks the 690-file source seal,
qualifications, identities, manifests, denominators and exact replay.
The [English results](README.md) preserve resource bytes, loss denominators,
BF16-visible change counts and all claim limits. Peak CUDA allocation is
27.6903 GiB in both roles; peak host RSS is 86.8090 / 86.7618 GiB.

Both checkpoint bodies remain exclusively on Furnace in the output path above,
54.0249 GiB combined. Do not rerun/resume this completed canary or delete its
weights. No further training or evaluation is dispatched. The next bounded
decision is the finite full-FT recipe and its length-specific resource and
quality gates; this record does not authorize those new experiments.
