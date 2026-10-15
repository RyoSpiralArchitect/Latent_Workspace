# V18 frozen-backbone selection diagnostic — execution handoff

2026-10-15 JST. After the [native pilot](../v18_native_pilot_20261015/README.md),
Ryō chose option B ("bでいこう！"): a frozen-backbone diagnostic of whether
memory content can reach native answers. Design and pre-registered endpoints:
[FROZEN_DIAGNOSTIC.md](../../../docs/v18/FROZEN_DIAGNOSTIC.md).

Execution source `3789a4bc4329e614feb606391aad30324695322f`, pushed before any
remote computation and transferred as `source.bundle` (SHA-256
`4f8f874a573cea530c5dac9c534c5fcfee873a14c213cc753b6e96b622d3c3c8`). Clean
detached Furnace checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-frozen-diagnostic-20261015`.
`prepare-seal` there wrote a 603-file `SOURCE_SEAL.json` (SHA-256
`2d9dcfa04d66b7c607f01c011d8580cb281d8fdf87c84f40ef30f391662c33b0`),
byte-identical to an independently prepared local seal.

Task root: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-frozen-diagnostic-20261015`.
Interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- Local Mac: 16 new tests pass (11.5 s), with the 18 pilot tests (34 total);
  Ruff passes on all new files.
- Separate clean Furnace dev checkout at the same commit, qualified
  interpreter: CPU 16/16 (11.0 s), CUDA 16/16 (15.1 s); the checkout stayed clean.
- Real frozen-7B smoke in that dev checkout, centered-ordered, four windows and
  a four-world final-split evaluation twice: 8.3 s per window, 2.1 s per
  evaluated world, 15.4 GB peak CUDA allocation, 5.9 GB RSS, 79.7-MB checkpoint,
  native weights unchanged, zero-memory rows exact. Its outputs stay in the
  Furnace dev directory and are not used; no endpoint metric was recorded.
- All 7,168 labels in the three splits agree with the symbolic oracle and the
  splits share no pair ID, order, twin set or context.

## Dispatch

One detached run of `launch_frozen_diagnostic.sh` in the task root (SHA-256
`94d5421a2253455f665c2d703a184a8c977277f509548d6bbb2db902a8adc11c`): tiny CPU
qualification, tiny CUDA qualification, then the runner's `dispatch`
(centered_ordered → centered_final → replay, each a fresh process through
`run_source_sealed.py`). Each stage starts only if the previous exited 0; the
script refuses to run over existing `qualification/`, `raw/` or `checkpoints/`
and appends to `LAUNCH_TIMELINE.log`. Log names are distinct case-insensitively.
A failed, quiet or interrupted stage is recorded, not relaunched.

Preflight immediately before dispatch: no GPU compute client, 10 MiB GPU memory
used, 120 GiB host memory available, 104,311,869,440 bytes (97.1 GiB) free disk.
Expected duration about 3.3 h. The native pilot's two checkpoints remain; no
weight is deleted.

## Terminal handoff — do not relaunch

All stages exited 0 (`2026-10-15T01:54:05Z`): tiny CPU/CUDA qualification, the
centered-ordered and centered-final arms and the fresh-process exact replay.
Receipts are copied under `furnace/`; local and Furnace offline verification
pass (Furnace also rehashed all four checkpoint bodies). Both arms are
`NOT_ESTABLISHED`; no selection advantage. Checkpoints stay on Furnace; nothing
was deleted. No process from this dispatch remains. See the [results](README.md).
