# V18 native selection pilot 01 — execution handoff

2026-10-15 JST. Ryō asked to finish the window owner and the CUDA
update/restart checks, then proceed to full FT. Both qualifications
[passed](../v18_selection_window_20261015/README.md). This is the frozen
[native pilot](../../../docs/v18/NATIVE_PILOT.md): the first real Mistral-7B
full update of the V18 selection window owner, one centered-ordered condition.

Execution source `fb409ed2ba6ff3b2be209f7a97894b02637f5b2f`, pushed before any
remote computation and transferred as `source.bundle` (SHA-256
`9506e35946d6abca15c1040e5bf30e95dc7aafeba0fd606305e04d73a30e2c39`). The clean
detached Furnace checkout is
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-native-pilot-20261015`.
`prepare-seal` there wrote a 599-file `SOURCE_SEAL.json` (SHA-256
`0f0bd799609b7d273a18604293c54b6429693384a240a292d4c4dedfd20a1d1b`), byte-identical
to an independently prepared local seal.

Task root: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-native-pilot-20261015`
(`qualification/`, `raw/`, `checkpoints/` created by the run). Interpreter:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- Local Mac: the 18 new tests pass (51 s); Ruff passes on all new files.
- A separate clean Furnace dev checkout at the same commit ran the same 18
  tests with the qualified interpreter: CPU 18/18 (22.5 s), CUDA 18/18
  (31.1 s). The dev checkout stayed clean. These runs are not the sealed
  qualification and are not counted.
- Tokenizer-only binding census with the pinned tokenizer (no model): all 16
  pilot rows, 2,048 `functional_train` questions and 1,024 population questions
  bind operand spans whose question spans equal the legacy spans.

## Dispatch

One detached run of `launch_native_pilot.sh` in the task root (SHA-256
`95d2699545c90c9ed7b17c071ef736603d7b3d04b241e48e8f3484ec7aa4b1e7`): tiny CPU
qualification, tiny CUDA qualification, then the runner's own `dispatch`
(probe → primary → replay, each a fresh process through `run_source_sealed.py`).
Each stage starts only if the previous exited 0. The script refuses to run over
an existing `qualification/`, `raw/` or `checkpoints/` and appends to
`DISPATCH.log`. Existing STARTED/FINISHED receipts decide what happens next; a
failed, quiet or interrupted stage is recorded, not relaunched.

Preflight immediately before dispatch: no GPU compute client, 10 MiB of 32,607
MiB GPU memory used, 119 GiB host memory available, 164,640,509,952 bytes
(153.3 GiB) free disk on the task filesystem. The primary may retain two full
checkpoints (about 27.1 GiB each); no existing weight is deleted.
