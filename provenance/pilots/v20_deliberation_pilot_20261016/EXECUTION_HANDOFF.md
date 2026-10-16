# V20 Deliberation pilot (D1) — execution handoff

2026-10-16. The first V20 experiment, agreed with Ryō; design and pre-registered
endpoints in [DELIBERATION_PILOT.md](../../../docs/v20/DELIBERATION_PILOT.md).

Execution source `e18657b35003671bca8d8130947c893ef214c3b9` on
`SpiralReality/v20-deliberation-pilot`, pushed before any remote computation.
Transferred as `v20.bundle` (SHA-256 `e2429030…19b36108`), whose only
prerequisite is the V19 execution commit `097d8dd` already on Furnace, and
fetched into the Furnace repository. Clean detached checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v20-deliberation-pilot-20261016`.
`prepare-seal` there wrote a 622-file `SOURCE_SEAL.json` (SHA-256
`bc29d05d7efb5a8321a9cbef575c0450fd52a1da4def1a6eb03424447257ee94`),
byte-identical to an independently prepared local seal from a clean clone.

Task root: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-deliberation-pilot-20261016`.
Interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- Local Mac: 25/25 tests and Ruff. All four arms also ran under
  `torch.use_deterministic_algorithms(True)`, including v4's loss with its
  spectral term.
- Separate clean Furnace dev checkout
  (`worktrees/latent-workspace-v20-deliberation-dev-20261016`, same commit) with
  the run's interpreter: 25/25 on CPU and 25/25 on CUDA.
- Real-model smoke in that dev checkout on 32 **train** rows only: the pinned
  base identity matched (hash in 11.9 s), native parity held on every row,
  prompts were 118–120 tokens with candidates 1476/5849, 0.041 s per row
  (about 4.9 min projected for all 7,168 rows), 13.57 GiB peak CUDA allocation,
  and 0.192 s per `k4` update on CPU at 8 threads (about 1.6 min per arm). No
  dev or final row was extracted and no accuracy was recorded.
- A local count with a cached copy of the v0.3 tokenizer (not the pinned files)
  gave 859,084 prompt tokens, about 6.6 GiB of bf16 features.

## Dispatch

One detached run of [`launch_v20_deliberation_pilot.sh`](launch_v20_deliberation_pilot.sh)
in the task root (SHA-256
`85460d5ae797064610899dfaadb33d96610668c3bdf83cb8c45ed3e42036f604`) at
2026-10-16T00:03:44Z: tiny CPU and CUDA qualification (25 cases each), then the
runner's `dispatch` (extract → 12 CPU arm roles → replay → endpoints), each a
fresh process through `run_source_sealed.py`. Each stage starts only if the
previous exited 0; the script refuses existing `qualification/`, `raw/` or
`checkpoints/` and appends to `LAUNCH_TIMELINE.log`. Failed, quiet or
interrupted stages are recorded, not relaunched.

Preflight immediately before dispatch: no GPU compute client, 119 GiB host
memory available, 90 GB disk free, load average 0. No weight is deleted.
