# V20 A2 depth ladder — execution handoff

2026-10-16. V20 is A2 (Ryō). The design and the pre-registered endpoint were
frozen in [A2_DEPTH_LADDER.md](../../../docs/v20/A2_DEPTH_LADDER.md) (plan
SHA-256 `295392251ca596e55997bf8ada4ec530ce6ac6ac46af5bfc7eb6db1d4231ecd1`).

Execution source `1daa358d0a745fc71baa62aefef3c9858dc1920b` on
`SpiralReality/v20-a2-depth-ladder`, pushed before any remote computation. It
was transferred as `a2d.bundle` (SHA-256
`d67d73d208ec9d9ab6db93dd95df620dc7509cd620d96573b76edcad7c5755c0`, 9 commits
on top of `1fe66c8`, which was already on Furnace) and fetched into the
Furnace repository.

The clean detached checkout is
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v20-a2-depth-ladder-20261016`.
It had no tracked, untracked or ignored file before or after `prepare-seal`.
`prepare-seal` there wrote a 654-file `SOURCE_SEAL.json` (SHA-256
`caaeb0b71af99485bf4e3d1ded0ee234e044b07f2360252a586f4c922c5fccf6`),
byte-identical to an independently prepared local seal from a clean clone.

- **Task root:** `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a2-depth-ladder-20261016`.
- **Interpreter:** `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- **Power:** the draft's checks on train-split worlds only, in
  [DEV_POWER_CHECKS.md](../v20_a2_flip_20261016/DEV_POWER_CHECKS.md),
  summarized in the design. With these exact settings the route learns at
  cuts 0 and 4.
- **Readout input:** a check on the cut-4 development features (worlds 0–191
  fitted, 192–255 read) compared what the route reads. The final states at
  the question positions gave 0.84 / 0.81 accuracy (23 flips against 9 random
  memory). All positions gave 0.76 / 0.76, so the run stores question
  positions only. The last position alone, without a lattice, gave 0.88 /
  0.85 (24 against 25).
- **Local Mac:** 105 tests across the depth ladder, engine stack,
  availability, execution, architecture rules, documentation, A1 and D1, plus
  Ruff.
- **Furnace dev checkout:** `worktrees/latent-workspace-v20-a2-depth-dev-20261016`,
  same commit, with the run's interpreter: 58/58 on CPU and 58/58 on CUDA.
- **Real-model smoke** in the dev checkout: two **train** worlds at every
  cut, with parity on every row.
  - The head on the final states equaled the decoder continued from the cut
    on all 160 rows per cut, and at cut 0 it equaled the inline forward,
    bitwise.
  - Timing: 0.022–0.057 s per row; the pinned base loaded in 1.4 s from page
    cache. Questions average 55.6 tokens, which gives about 5.2 GiB of
    features per cut.
  - Peak CUDA allocation was 13.56 GiB. No final or dev row was read.
- **Disk:** at 59.8 GiB available, the guard's 50 GiB floor would have
  stopped the second extraction. At 09:08:23Z Ryō ran the published
  [retirement](../../inventory/v20_a2_dev_retirement_20261016/README.md) of
  two development folders: all six hashes matched, 16.2 GiB were freed, and
  79.35 GB were then available.

## Dispatch

[`launch_v20_a2_depth_ladder.sh`](launch_v20_a2_depth_ladder.sh) was run once,
detached, in the task root at 2026-10-16T09:09:33Z (SHA-256
`416037dbb930d32bd210cfc94522fdeb55a6229d582b51e732723c61d4f5c21b`, launcher
PID 2313553). The stages, in order:

1. Tiny CPU qualification, then tiny CUDA qualification (58 cases each).
2. The runner's `dispatch`: four extraction roles, then twelve route roles,
   the replay and the endpoints. Each role is a fresh process through
   `run_source_sealed.py`.

Each stage starts only if the previous exited 0. The script refuses existing
`qualification/`, `raw/` or `checkpoints/` and appends to
`LAUNCH_TIMELINE.log`. Failed, quiet or interrupted stages are recorded, not
relaunched.

Preflight immediately before dispatch:

- no GPU compute client (10 MiB in use);
- 119 GiB host memory available;
- 79.35 GB disk available;
- load average 0.07;
- the sealed checkout clean at `1daa358`.

The CPU qualification exited 0 at 09:09:41Z. No weight is deleted by the run.
