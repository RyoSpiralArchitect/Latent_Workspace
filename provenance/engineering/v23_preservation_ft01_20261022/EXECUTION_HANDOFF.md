# V23 preservation comparison 01 — execution handoff

## Launch recorded

**LAUNCHED**, at `2026-10-21T19:23:04Z`
(2026-10-22 04:23 JST, Furnace clock).
Frozen source: `b46f04caefcfd596ccde3b0af8fd886d859f11b7`.
tmux: `ltws-v23-preservation-ft01-20261022`; initial pane PID `3677962`.
The exact-source launcher was called once. No model call preceded the tiny
gates. This launch receipt does not establish qualification or FT completion.
The remote source is a clean detached worktree; subsequent local publication
commits must not change it. The initial Git fetch succeeded, but this checkout
does not maintain the requested remote-tracking branch; a failed tracking-ref
check created no output/worktree. The verified exact `FETCH_HEAD` was then used
to create the isolated source. That setup correction was not a trial retry.

At `2026-10-21T19:26:15.927189Z`, CPU and CUDA have each finished with
472 tests, zero failures/errors/skips. Their raw receipts and independent
offline replay are published in [README.md](README.md). Dispatcher PID
3689226 and teacher PID 3689304 were active; the teacher is loading the pinned
base. Real-model update/save/replay and off/on training remain pending.
Check current on-disk receipts before making any newer progress claim.

At `2026-10-21T19:27:19.841440Z`, teacher role finished successfully: 89 rows,
18,727 positions, all 89 same-weight eval/train log-probability sentinels
bitwise equal (zero initial KL). Public teacher metadata are preserved locally;
the private 2.286-GiB target body remains remote. Canary PID 3690246 had started.
No comparative training completion is implied. Do not relaunch the teacher.

## Original pre-launch handoff

Pre-launch handoff, 2026-10-22. **NOT_DISPATCHED** at this record's creation.
Ryō requested comparative FT after the completed gradient audit.
[Design](../../../docs/v23/PRESERVATION_FT_01.md) and
[plan](../../../configs/v23/PRESERVATION_FT_01.json) define this new trial.

Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/latent-memory-full-ft`.
Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Furnace source: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-preservation-ft01-20261022`.
Furnace output: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-preservation-ft01-20261022`.
Exact committed source and launch PID/session must be recorded before handoff.

Terminal receipts, not process absence, establish completion. The only pipeline
is CPU qualification -> CUDA qualification -> teacher -> positive-P canary ->
separate replay -> off -> on. Each stage is exclusive and stops on failure;
there is no automatic retry. Qualification failure means no 7B dispatch;
canary/replay failure means no comparative training. Do not repair a frozen
trial's source or reuse its output paths.

Do not restart the old gradient audit. Its terminal artifacts were verified
and pushed in `db70b0f` plus `f147695` (ignored-log publication fix). It remains
a no-update diagnostic at its original source. The private 12-row audit bank
is not this trial's 89-row training reference. No original/V22/scientific
weights or old evidence may be modified or deleted.

There is no heartbeat monitor. Check the existing process within the normal
thread; do not create new monitoring/provider/generation jobs. Publish only
receipts, manifests and scalar results. Private tokens, teacher bodies and
weights stay on Furnace. Keep old FAIL, no winner and unestablished
non-regression. No PR/merge or release is part of this dispatch.
