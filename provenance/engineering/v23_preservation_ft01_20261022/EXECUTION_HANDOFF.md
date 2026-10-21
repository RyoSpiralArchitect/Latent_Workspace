# V23 preservation comparison 01 — execution handoff

Pre-launch handoff, 2026-10-22. **NOT_DISPATCHED** at this record's creation.
Ryō requested comparative FT after the completed gradient audit.
[Design](../../../../docs/v23/PRESERVATION_FT_01.md) and
[plan](../../../../configs/v23/PRESERVATION_FT_01.json) define this new trial.

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
