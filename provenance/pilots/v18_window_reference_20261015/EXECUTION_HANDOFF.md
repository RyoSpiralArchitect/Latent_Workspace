# V18 window/reference engineering qualification handoff

2026-10-15. Scope: 310 tiny synthetic tests (85 immutable-bank, 59 reduction,
166 learner integration), in separate fresh CPU and CUDA processes. No 7B
training, learner generation, real reference capture, preservation loss, judge
request, weight deletion, HF write, PR creation or merge is selected.

Publication checkout:
`/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`.
Branch `SpiralReality/v18-window-reference`; origin
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Unrelated `provenance/research/` stays excluded.

The [fixed plan](../../../configs/v18/WINDOW_REFERENCE_QUALIFICATION_PLAN.json)
has a 4-GiB CUDA allocator ceiling, 900 seconds per suite and two CPU threads.
All external model/dataset downloads are disabled. CPU/CUDA are within-runtime
comparisons from the same sealed source, not cross-device bitwise equivalence.

Intended isolated Furnace checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-window-reference-20261015`.
Persistent output parent:
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-window-reference-20261015`.
Qualified interpreter:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

Launch only after final local tests and source freeze. Prepare SOURCE_SEAL.json
after the source commit; `run_source_sealed.py` must verify the exact clean
checkout before importing `qualify_v18_window_reference.py`. Output paths are
exclusive. Existing STARTED/FINISHED receipts take precedence over this plan:
never dispatch again simply because progress is quiet. Inspect process identity
after an ambiguous transport result. Preserve failures, do not overwrite them.

After terminal completion, pull both three-file receipt bundles and replay
`verify_v18_window_reference.py` offline. Publish exact counts, resources,
source/import closure, old-source preservation and bounded conclusions. The
previous 546-file V16 population source and original results remain unchanged.

Claim ceiling: **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
Only tiny engineering ownership/reduction/update/replay may pass here. Real
tokenizer/capture validation, family-split audits, selection-only reader changes,
preservation supervision and 7B admission remain separate work.
