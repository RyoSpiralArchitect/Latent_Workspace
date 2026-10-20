# V22 full-FT recovery 01 — terminal handoff

**Complete, not a quality promotion.** Both `raw/FINISHED.json` and
`training/FINISHED.json` report
`V22_NATIVE_TRAINING_32_STEPS_COMPLETE_NOT_QUALITY`.
All 32 training updates / 723 unique rows / 20,860 supervised tokens finished.
The training workers exited. Do not re-run either phase or any role.
No heartbeat, recurring job or automatic retry was created.

Execution source: **`13c1192fc2727d8ca61ee215a927c0cd77f75b16`**, 724 sealed files.
CPU and CUDA each passed 318/318, with zero errors, failures or skips.
The checks phase completed exact fresh step-2 replay; Train B separately
restored the complete step-16 state exactly and continued to step 32.
There was no uninterrupted 32-step reference comparison.
See [the English results](README.md), [summary](SUMMARY.json),
[verification](VERIFICATION.json), and [frozen design](../../../docs/v22/FULL_FT_RECOVERY_01.md).

## Exact scopes

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`
- Branch: `SpiralReality/latent-memory-full-ft`
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`
- Furnace execution worktree:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-full-ft-recovery01-20261021`
- Furnace run bundle:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft-recovery01-20261021`
- Runtime, read-only:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`
- Same data:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-data01-20261021/bank`.
- Completed checks/training session names:
  `ltws-v22-recovery01-checks-20261021` /
  `ltws-v22-recovery01-train-20261021`.

Use `spiral` for read-only inspection. Never pull/update the execution worktree.
Verify execution against its frozen commit, not later publication HEADs.
Raw token banks and all retained weight bodies stay on Furnace, not Git.

## Authority already exercised

Ryō approved the cache-boundary fix, regressions and a new separate trial with
unchanged numerics/resources, through replay and 32 updates. Both finite
phases have executed once and are terminal. No further run is pending.

After the new exact replay passed, its evidence and the one-file retirement
ledger were committed/pushed as
`b6fdfc7ce7d10c7798a81f5426b2765dc9b3652b` before deletion. The separately
approved old `latent-v22-full-ft01-20261021/checkpoints/canary_step1.pt`
was then removed once: 29,004,378,380 bytes / 27.0124 GiB.
The [retirement ledger](../../inventory/v22_failed_canary_retirement_20261021/README.md)
records the hash and terminal receipt. Do not invoke deletion again.
Git metadata is not a recoverable backup of that old body.

The original failure's **42-file Furnace bundle / 842,396 bytes** remains
unchanged (its raw subdirectory contains 35 files). Original Mistral and all
other previous weight bodies were untouched. This trial retains exactly the
new canary, training-step-16 and training-step-32 checkpoints; all three full
body hashes matched their receipts. Training roles themselves deleted zero
files; the overall recovery workflow deleted one separately approved file.

## Interpretation and next boundary

The same native-memory graph's fixed 40-row / 4,694-token development panel
has lower NLL on all 40 rows. Token-weighted NLL changes 1.267038 → 1.058723.
No generated replies, paid judge, public benchmark or further training was run.
This is not 100% task accuracy or an unseen population-level non-regression
result. **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.

Potential next work is a separately frozen original-base non-regression panel,
counterfactual memory-use controls, and paired fixed-prompt/seed generation.
No new experiment, threshold change, weight deletion, beta replacement,
PR/merge or Hub publication is authorized merely by this handoff.

## Offline reproduction

```bash
python3 scripts/verify_v22_full_ft.py \
  --bundle provenance/pilots/v22_full_ft_recovery01_20261021/furnace \
  --repo . \
  --data provenance/data/v22_english_mixture01_20261021/furnace
python3 provenance/pilots/v22_full_ft_recovery01_20261021/summarize.py \
  --verify provenance/pilots/v22_full_ft_recovery01_20261021/SUMMARY.json
```

Both are offline, read-only and make no model calls. The publication helper is
outside the sealed execution source and refuses partial artifacts as complete.
Local verification does not claim to inspect weight bytes; the separate
Furnace verification in VERIFICATION.json did inspect all three bodies.
Preserve raw manifests/log bytes and the original failure.
