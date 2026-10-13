# Full adapter recovery 02 handoff

2026-10-14. **PRELAUNCH**. See the [execution contract](../../../../docs/v16/ADAPTER_FULL_RECOVERY_02.md).

Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`.
Branch: `SpiralReality/v16-slot-contrast`; origin:
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`; stacked Draft PR #13.

Only the missing full adapter two updates and one replay are selected (48 pairs).
Never rerun the original frozen 80 pairs or continuation-01 legacy 32 pairs.
Both historical bundles/source seals remain immutable. No heartbeat is enabled.

Planned fresh Furnace source:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v16-adapter-recovery-02-20261014`.
Evidence/checkpoints parent (persistent filesystem):
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-adapter-recovery-02-20261014`.
Qualified interpreter:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

Prepare source seal only after committing the exact source. First run the
isolated `qualify` subcommand of `scripts/run_v16_adapter_full_recovery_02.py`.
Only a terminal same-seal 22/22 CUDA PASS can admit its separate `run` subcommand.
Keep the tiny raw receipts in `tiny_cuda/`, 7B receipts in `raw/` and large weights
in `checkpoints/` outside source. Copy source seal/tiny/raw receipts back, not
large checkpoint binaries. Record STARTED PID/source/output before monitoring.

Do not rerun either subcommand after a failure or ambiguous connection loss.
Inspect receipts/process identity; preserve missingness and request a decision.
No training factor, new generations, paid judge, deletion or merge is authorized.
Finish with offline replay, unchanged historical seals, selected tests/Ruff,
source-backed English results, bounded next steps and branch-only publication.

Prelaunch ordinary local CPU regression: 295/295 cases in 35.73 seconds;
see `PRELAUNCH_TESTS.xml`. Ruff passed on all five new Python source/test files.
Both historical evidence bundles and their source hashes replay unchanged.
