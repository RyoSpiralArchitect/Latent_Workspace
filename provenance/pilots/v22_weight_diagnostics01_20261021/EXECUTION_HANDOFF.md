# V22 weight diagnostics 01 — execution handoff

Frozen source: `35cbe95fa498d95c8f967b428758ddac0bd29966`.
Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/latent-memory-full-ft`.
Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Furnace checkout: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-diagnostics01-20261021`.
Evidence: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-diagnostics01-20261021`.
Read-only interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
Finite tmux session: `ltws-v22-diagnostics01-20261021`.

Ryō authorized further analysis of the existing V22 step-32 weights. The
[frozen plan](../../../docs/v22/WEIGHT_DIAGNOSTICS_01.md) covers two
fresh-process arms after 158 selected checks on CPU and CUDA, 1,140 MMLU
rows, 384 world conditions with predetermined token-prefix replay, a 570-row
head factorial and a 291-tensor update census. No new continuation, real-model
update, checkpoint save, paid judge, deletion, PR/merge or release is authorized.

Use only `spiral` for Furnace. Managed TRT doctor passed with no failure codes;
its existing modelopt/transformers compatibility warning was retained, not
repaired. Native PyTorch is necessary for the custom cut-4 graph, complete
owner-state restore, and head-input/fixed-prefix observation. No environment
was changed. The initial GPU had no compute clients; host available memory
was 119 GiB and filesystem available space approximately 77 GB.

The launch is finite and stops at the first failure. A vanished process is not
a terminal receipt. Check qualification and role `FINISHED.json` plus manifests.
Do not rerun a role or modify this run's source, input seal or results. Earlier
comparison/training bundles remain immutable. Publish any missingness or
failure and ask before a distinct recovery. The old gate remains
**FAIL / winner:none / non_regression NOT_ESTABLISHED**.

Status at handoff creation: source prepared; qualification/dispatch not yet
confirmed. Later terminal verification belongs below, not in historical files.

## Terminal handoff

Both 158-test qualifications passed; both fresh-process arms and the dispatcher
are terminal: `V22_DIAGNOSTICS_COMPLETE_NOT_RELEASE`. Source seal: 734 files.
All 1,140 MMLU rows, 384 world conditions, 2,814 fixed-prefix next-token steps,
570 four-cell head factorials and 291 physical tensors completed. Recorded
generation replay disagrees at zero positions. No checkpoint file was written;
before/after native identities match. No run worker remains on the GPU.

All evidence is copied into [furnace/](furnace/). `summarize.py --verify` checks
both the original comparison and this run, including terminal manifests and
literal publication; `interpret.py --verify` checks the additive post-result
contrasts. Read [README.md](README.md) and [FAILURE_PANEL.md](FAILURE_PANEL.md)
for the findings and their limits. No rerun, training, new generation, judge,
deletion, PR/merge or release is part of this completed handoff.
