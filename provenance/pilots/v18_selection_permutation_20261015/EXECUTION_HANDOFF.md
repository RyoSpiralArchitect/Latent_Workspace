# V18 saved-state diagnostic execution handoff

2026-10-15 JST. Authorized scope is the fixed
[saved-state diagnostic](../../../docs/v18/SELECTION_NUMERICAL_DIAGNOSIS.md),
followed by bounded engineering toward V18 full updates. No historical source
or artifact is changed. The actual-writer helper is tested wiring only, not a
new fit or state-owner admission.

Before execution, freeze the additive source and write its external
`SOURCE_SEAL.json`. Use a new clean detached Furnace worktree and
`python -I scripts/run_source_sealed.py`, with the original input seal supplied
separately. Run CPU and CUDA once into distinct new output directories. Preserve
STARTED/FINISHED/FAILED receipts and do not automatically retry. Verify each
terminal output offline with the original bundle and both seals.

Inputs are the completed `assay_cpu` and `assay_cuda` directories under Furnace
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-operand-selection-continuation-01-20261015`.
Input source is `dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`.
The qualified Python is
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
Planned new output parent is
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-selection-permutation-20261015`;
planned new checkout is
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-selection-permutation-20261015`.
Check that both targets are absent before reserving them.

Furnace preflight on 2026-10-14 at 19:11 UTC found 10 MiB used of 32,607 MiB
GPU memory, no compute clients, and 119 GiB available host memory. This is
availability, not a 7B capacity qualification. Recheck before CUDA execution.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
No new monitor, paid request, old-weight deletion, PR/merge or HF upload is
selected by this diagnostic. Terminal results and next-factor interpretation
will be appended after the literal outputs have been verified.

## Terminal handoff

Source froze at `57af47858088d67247cbb5c3f77c4724a16db624`, with 580 source files.
Both processes completed once (CPU and CUDA, 12 retained states each). The
literal directories were pulled and both offline verifiers passed on Furnace.
All24 cell promotion statuses are `BLOCKED_CONTROL_REPRODUCTION_MISMATCH`:
hook parity and repeated execution are exact, but historical original logits
are not. See the results README for all denominators and unchanged failures.
No process is pending and this diagnostic is not to be rerun.

A separately specified flag-partition intervention is the next investigation,
not an implicit retry or precision repair. It compares the historical six
trainable interaction parameters with this diagnostic's all-frozen parameters,
under the same no-grad evaluation. The cause is not yet established.
