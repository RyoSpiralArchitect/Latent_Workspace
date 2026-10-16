# V20 A1 Availability ladder — execution handoff

2026-10-16. The first of the three experiments agreed with Ryō (A1 → A2 → D2);
design and pre-registered endpoint in [A1_LADDER.md](../../../docs/v20/A1_LADDER.md).

Execution source `5b5776bcceb35c55f495e1a60c9b346354bfed53` on
`SpiralReality/v20-a1-ladder`, pushed before any remote computation.
Transferred as four incremental bundles fetched into the Furnace repository;
the first one's only prerequisite is the D1 execution commit `e18657b`, already
on Furnace.

| Bundle | Adds | SHA-256 |
| --- | --- | --- |
| `a1.bundle` | 10 commits through `abeb6e2` (main's D1 and engine merges, then A1) | `60d44d45136717398b30019277a8fc2b6ed15a2690ebc3272eb1b1769e64b7e7` |
| `a1b.bundle` | `5f95299` (pyproject path, later reverted) | `007846a949ae470f9b946863db7a24ffd791311e834189f8da2f119560c0625a` |
| `a1c.bundle` | `1c00192`, `15b9564` (revert; conftest and legacy-pin guard) | `682a598a5257ad9e502a164be15991e0c9d14202680efce7ee74dcf8aef57b7c` |
| `a1d.bundle` | `5b5776b` (V19 runtime before restore) | `391c3393d2be6112fb6d44eb90f8efd5478d194c48eb21cf65841c5eb0f355d8` |

Clean detached checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v20-a1-ladder-20261016`
(no tracked, untracked or ignored file before or after `prepare-seal`). There,
`prepare-seal` wrote a 646-file `SOURCE_SEAL.json` (SHA-256
`dff3b0718a94cc3a2b87a47eb2ce6eaad65bdc0b1ae7cf22d39de0549f46d246`),
byte-identical to an independently prepared local seal from a clean clone.

Task root: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a1-ladder-20261016`.
Interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
V19 inputs read in place (attempt 01, `ordered_cap025`):
`tmp/latent-v19-frozen-diagnostic-20261015/raw/ordered_cap025` and
`.../checkpoints/ordered_cap025/step{256,512}.pt`, pinned by hash in the
[plan](../../../configs/v20/A1_LADDER_PLAN.json).

## Development checks before dispatch (not evidence)

- Local Mac, clean clone at `5b5776b`: the 18 qualification tests, 55 engine,
  architecture and D1 tests, and Ruff on every A1 and engine file.
- Separate clean Furnace dev checkout
  (`worktrees/latent-workspace-v20-a1-dev-20261016`, same commit) with the
  run's interpreter: 18/18 on CPU and 18/18 on CUDA.
- Real-model smoke in that dev checkout (`a1_smoke.py` in the task root,
  SHA-256 `5c9ed085da58a26f7fa6f85a224dbdbed723a214c3f09d2e26136752af5a1760`):
  restored `step512` and `initial`
  and extracted **two held-out final worlds** for each. Only timings, shapes
  and the mean intact workspace-route norm were printed; no probe was fitted,
  no label was compared and no tensor was kept. `step512` restored in 38.4 s
  at 1.41 s per world with every extraction invariant holding (workspace-route
  norm 0.25); the rebuilt `initial` state matched V19's recorded `INITIAL`
  fingerprint exactly (workspace-route norm 0.0); peak CUDA allocation
  13.65 GiB. The smoke first found that the V19 restore refuses without V19's
  runtime arithmetic, which `5b5776b` fixed.

## Dispatch

One detached run of [`launch_v20_a1_ladder.sh`](launch_v20_a1_ladder.sh) in the
task root (SHA-256
`2e6cf9444f239686a523a876f083a460a668f85d2455c03d289d48885c6ee13c`, launcher
PID 2202079) at 2026-10-16T04:07:31Z: tiny CPU and CUDA qualification (18
cases each), then the runner's `dispatch` (`extract_initial` →
`extract_step256` → `extract_step512` → `probe`), each a fresh process through
`run_source_sealed.py`. Each stage starts only if the previous exited 0; the
script refuses existing `qualification/`, `raw/` or `checkpoints/` and appends
to `LAUNCH_TIMELINE.log`. Failed, quiet or interrupted stages are recorded, not
relaunched.

Preflight immediately before dispatch: no GPU compute client (10 MiB of
32,607 MiB in use), 119 GiB host memory available, 81 GB disk free, load
average 0.00. Both qualifications exited 0 (04:08:02Z and 04:08:33Z) and the
ladder dispatch started at 04:08:33Z. No weight is deleted.
