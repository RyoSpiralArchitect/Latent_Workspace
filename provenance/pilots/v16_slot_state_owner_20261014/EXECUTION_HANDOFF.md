# V16 slot-state qualification handoff

2026-10-14. Source-preparation record; terminal results are appended separately.

Ryō asked to integrate V16 slot-contrast into state management and save/resume.
This attempt selects only the new 145-case tiny engineering suite, on CPU and
CUDA. It does not select any 7B update, semantic pilot, generation, paid judge,
weight deletion, heartbeat or merge. Old source files and evidence stay sealed.

Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`.
Branch: `SpiralReality/v16-slot-contrast`; origin:
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`; Draft PR #13 remains
stacked on `SpiralReality/v15-adapter-state-owner`.

Prelaunch ordinary local CPU regression: 440/440 in 170.33 seconds, comprising
145 new ownership cases plus 295 retained regression cases. The separate offline
receipt-verifier suite passes 14/14 in 0.26 seconds. Neither is presented as an
isolated CUDA result. Ruff passes on the six new Python files.

Fresh isolated Furnace source is planned at:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v16-slot-state-20261014`.
Persistent evidence parent:
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-slot-state-20261014`.
Existing qualified interpreter:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

Use the committed source seal and `run_source_sealed.py` to launch
`qualify_v16_slot_state.py run` in a fresh process per device. The fixed plan
caps CUDA allocation at 4 GiB and each test suite at 900 seconds. Outputs are
exclusive: do not reuse a run directory. After a terminal failure or ambiguous
connection loss, preserve receipts and inspect the process before any decision
about another attempt. No retries are selected by this record.

Only complete same-source terminal PASS and offline verification qualify a
device. Candidate/raw × FP32/BF16 × full/frozen × checkpointing on/off are
within-runtime comparisons, not CPU/CUDA equality or response-quality evidence.
Old FAIL / winner:none / non_regression NOT_ESTABLISHED remain unchanged.
