# V19 frozen dual-budget diagnostic — execution handoff

2026-10-15 JST. Ryō proposed V19 (separate norms for the ordinary and workspace
read routes) after the [V18 frozen diagnostic](../v18_frozen_diagnostic_20261015/README.md).
Design and pre-registered endpoints: [DUAL_BUDGET.md](../../../docs/v19/DUAL_BUDGET.md).
V15, V16 and V18 were merged into `main` first (#14, #12, #13, #15, #16, #17);
V19 branches from that `main`.

Execution source `097d8dd13856ed1611f9b1c0ab41f9f069773606` on
`SpiralReality/v19-dual-norm-budget`, pushed before any remote computation.
Transferred as `source.bundle` (SHA-256 `e166a747…64dd4db`, to `36b9ab8`) plus
`source-delta.bundle` (`30795c08…bd55a798`, to `097d8dd`); Furnace verified all
13 bundle prerequisites. Clean detached checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v19-frozen-diagnostic-20261015`.
`prepare-seal` there wrote a 613-file `SOURCE_SEAL.json` (SHA-256
`f33307b201413af77df767221491524ed10038c29e83632fed8ab0e70f537dad`),
byte-identical to an independently prepared local seal.

Task root: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v19-frozen-diagnostic-20261015`.
Interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- Local Mac: 47 V19 tests pass (30 owner/reader + 17 diagnostic); Ruff passes.
- Separate clean Furnace dev checkout, qualified interpreter. At `36b9ab8` the
  CPU run passed 47/47, but CUDA failed 3 tests: the tests filled CUDA
  parameters with a CPU random generator. Only the tests changed (values are now
  drawn on CPU and copied), giving `097d8dd`; CPU 47/47 (26.8 s) and CUDA 47/47
  (33.0 s) then passed. No library code changed between the two.
- Real frozen-7B smoke in that dev checkout (`ordered_cap025`, four windows and a
  four-world final-split evaluation twice): 8.4 s per window, 2.2 s per
  evaluated world, 15.37 GB peak CUDA allocation, 5.9 GB RSS, 79.7-MB checkpoint,
  native weights unchanged, zero-memory rows exact. No endpoint metric recorded.

## Dispatch

One detached run of `launch_v19_frozen_diagnostic.sh` in the task root (SHA-256
`bc318a0e70c1b8d0e990f55541d177f2de40f8add37c31c88c2d4002935988b8`): tiny CPU
qualification, tiny CUDA qualification (47 cases each), then the runner's
`dispatch` (`ordered_cap025` → `final_cap025` → `ordered_cap100` → replay, each a
fresh process through `run_source_sealed.py`). Each stage starts only if the
previous exited 0; the script refuses existing `qualification/`, `raw/` or
`checkpoints/` and appends to `LAUNCH_TIMELINE.log`. Failed, quiet or interrupted
stages are recorded, not relaunched.

Preflight immediately before dispatch: no GPU compute client, 119 GiB host
memory available, 99,911,454,720 bytes (93.1 GiB) free disk. Expected duration
about 4.8 h. Existing checkpoints remain; no weight is deleted.
