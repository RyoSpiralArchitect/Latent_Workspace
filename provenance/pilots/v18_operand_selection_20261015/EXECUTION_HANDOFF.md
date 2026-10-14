# V18 operand-selection bounded study

2026-10-15. Ryō selected implementation and small controlled comparison after
the window/reference qualification. This is not a 7B or full-update launch.

Execute only the committed source recorded by `SOURCE_SEAL.json`, in the clean
new Furnace checkout
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-operand-selection-20261015`.
Fresh output parent:
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-operand-selection-20261015`.
Use the existing qualified Python at
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

First run the fixed 200-case selection qualification in separate CPU and CUDA
processes through `run_source_sealed.py`. Only if both pass, run the fixed
controlled-slot study once per runtime in fresh processes through the same
pre-import launcher. Each process has a 900-second limit, two CPU threads and
a 4-GiB CUDA allocation limit. The toy additionally gates observed peak RSS at
4 GiB; it is not an OS-enforced RSS cap. Use existing STARTED/FINISHED receipts
before considering any dispatch; a quiet transport is not authority to retry.

The four matched toy factors, three seeds, data/splits, optimization budget and
pass criteria are committed before execution in the two `configs/v18` plans.
All states, failed outcomes, literal cases and exact denominators are retained.
No study results may change the criteria or the old scientific FAIL gate.

Outputs are external to the execution source tree. Pull literal terminal
artifacts, verify the qualification source/receipts, replay case metrics and
gates offline, then publish bounded English conclusions. No model downloads,
7B training, preservation loss, new learner generations, judge/API call, old
weight deletion, PR/merge or HF upload is selected. No recurring monitor is
created. A failed/incomplete runtime remains separate and requires a new
decision before any repeated trial.
