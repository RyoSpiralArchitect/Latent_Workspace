# V22 full-FT recovery 01 — execution handoff

Execution source: **`13c1192fc2727d8ca61ee215a927c0cd77f75b16`**, 724 sealed files.
CPU and CUDA qualification each passed **318/318**, zero errors/failures/skips.
The finite checks phase has been started once; inspect its receipts before any
action. No heartbeat, recurring job or automatic retry was created.

## Exact scopes

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`
- Branch: `SpiralReality/latent-memory-full-ft`
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`
- Furnace worktree:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-full-ft-recovery01-20261021`
- Furnace run bundle:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft-recovery01-20261021`
- Runtime, read-only:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`
- Checks tmux session: `ltws-v22-recovery01-checks-20261021`.
- Same data bundle:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-data01-20261021/bank`.

Use `spiral`; never edit/pull the execution worktree. Source verification must
refer to the execution commit, not a later documentation/ledger HEAD.

## Authority and gates

Ryō approved a corrected, regression-tested, separate trial under unchanged
numerical/resource limits, through exact fresh replay and 32 training updates.
Ryō separately approved deletion of **only** the old failed run's
`canary_step1.pt`, **after** the new replay passes and its hash/ledger are
recorded. No other checkpoint, original model or raw bank is in scope.
See [the frozen recovery design](../../../docs/v22/FULL_FT_RECOVERY_01.md).

`checks/FINISHED.json` is the first phase's terminal authority. Required status:
`V22_RECOVERY_CHECKS_COMPLETE_NOT_TRAINING`, with both role manifests intact and
`raw/replay/REPLAY.json` exact. A successful checks phase is intentionally not a
terminal training result; no root `raw/FINISHED.json` exists until final training
or an earlier failure. Do not launch the checks phase again.

After checks pass: pull the complete finished checks/raw artifacts, independently
verify source/receipts and the actual checkpoint body, and publish those plus
the old-body retirement ledger before removing exactly that approved file.
Confirm disk availability again. The old 42-file terminal bundle must remain
byte-for-byte unchanged; record retirement additively, never rewrite its history.
Then invoke `dispatch-training` once, in the same new bundle/checkpoint root,
with the same source seal and qualifications. No training is inherited from
the canary: Train A starts from pinned original Mistral, saves at 16, and a fresh
Train B restores 16 and continues through 32. Both save actual bodies.

If any role, phase or transport fails, retain outputs and missingness and do not
restart/retry/reissue anything automatically. A terminal failure ends the
authorized trial; report it and ask about a separate recovery when necessary.

## Offline verification and publication

```bash
python3 scripts/verify_v22_full_ft.py \
  --bundle provenance/pilots/v22_full_ft_recovery01_20261021/furnace \
  --repo . \
  --data provenance/data/v22_english_mixture01_20261021/furnace
```

Copy only finished immutable trees while another role is running. Raw training
tokens and checkpoint bodies stay on Furnace. Source/data hashes, all actual
updates and planned denominators, exact replay/resume, per-boundary cache/free
memory, usage peaks, storage retirement and fixed-dev NLL belong in the final
English README. Model quality is not established by engineering parity or dev
NLL. Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED** unchanged.
No extra training, new generation, teacher, paid judge, benchmark, threshold
change, PR merge or HF publication is authorized by this handoff.
