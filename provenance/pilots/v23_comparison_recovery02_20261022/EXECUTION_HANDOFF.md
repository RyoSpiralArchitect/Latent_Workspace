# V23 P-on recovery 02 — authorized and launched once

Ryō explicitly approved the corrected separate CPU→CUDA→P-on attempt.
Launch: **2026-10-22T00:09:15Z** / 09:09:15 JST.
Source: **`af9cd1a727d98d942df1845c35a14628f8f7481b`**, **792 sealed files**.
Remote source:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-comparison-recovery02-20261022`.
Output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-comparison-recovery02-20261022`.
tmux: `ltws-v23-pon-recovery02-20261022`; initial pane PID `3792838`.

Both qualification suites passed **248/248**, zero skips/failures/errors;
the separately bound CPU isolation audit passed, with zero own GPU clients.
All qualification files and the source seal are copied here. Run
`python3 -B provenance/pilots/v23_comparison_recovery02_20261022/verify_qualification.py`
for offline source/manifest/XML/audit replay. These are not 7B quality results.
The original host loaded and P-on reached MMLU 200/570 at the last launch-period
inspection. The role was active; no terminal success was claimed then.

Do not start another attempt or resume this one. Inspect existing `raw/on` and
`raw/FINISHED.json`. Preserve missingness on any failure. Original comparison
01 and recovery 01 remain byte-for-byte intact. No training, model-body save,
deletion, PR/merge, release or heartbeat monitor.

After terminal success, pull all raw files, replay the dual-origin bank and
qualification/source seals, and publish the complete comparison. The additive
[follow-up design](../../../docs/v23/RECOVERED_FOLLOWUP_01.md) retains the old
judge calibration and benchmark recipes. Its source must be committed before
freezing the study, and the complete recovered bank must verify before any
174-request judge study or 840-score/84-sequence MMLU-Pro model call. Original
base/off and whole recovery-02 on are the only selected arms; never splice
the original 79 scores or fabricate a complete original dispatcher.
