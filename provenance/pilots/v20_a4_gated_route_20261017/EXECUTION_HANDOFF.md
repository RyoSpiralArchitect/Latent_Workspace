# V20 A4 content-gated cut-4 route — execution handoff

2026-10-18. The design and the pre-registered endpoint were frozen in
[A4_GATED_ROUTE.md](../../../docs/v20/A4_GATED_ROUTE.md) (plan SHA-256
`1f4de6c04e83389671c65e0928c80bf89d0d08363c41e82c325e34bd4daa6ddc`).

Execution source `6bf97c24133dea7eb5a786c64697de184832d85c` on
`SpiralReality/v20-a3-shallow-writer`, pushed before any remote computation. It
was transferred as `a4.bundle` (SHA-256
`d912c851f57971e324f6a8ac7c8aa6cef19057882621e491c64c93d667b5cd3c`, 14 commits
on top of the ladder's `1daa358`, which was already on Furnace) and fetched into
the Furnace repository.

The clean detached checkout is
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v20-a4-gated-route-20261017`.
It had no tracked, untracked or ignored file before or after `prepare-seal`.
`prepare-seal` there wrote a 658-file `SOURCE_SEAL.json` (SHA-256
`3fc0f4bacfcc21298200d3dfab9595f688de1ef39720418e72b242513071176f`),
byte-identical to an independently prepared local seal from a clean clone.

- **Task root:** `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a4-gated-route-20261017`.
- **Ladder files read:** `../latent-v20-a2-depth-ladder-20261016/raw`, beside
  the task root. Every file the run reads is pinned in the plan and rehashed by
  each role that reads it.
- **Interpreter:** `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- **Design checks:** on train worlds only, in
  [DEV_CHECKS.md](DEV_CHECKS.md), summarized in the design.
- **Local Mac:**
  - the 59 qualification cases;
  - the architecture rules, documentation, depth-ladder, A1, D1 and dispatch-import
    tests (64 more);
  - Ruff.
- **Furnace dev checkout:** `worktrees/latent-workspace-v20-a4-dev-20261017`,
  same commit, with the run's interpreter: 59/59 on CPU and 59/59 on CUDA. The
  checkout was clean before and after.
- **Smokes of the sealed code path** ([dev_smoke.py](dev/dev_smoke.py), in the
  dev checkout, output in `tmp/latent-v20-a4-smoke-20261018`, 20 KB):
  - `extract`: the runner's mismatch extraction on the first two train worlds
    (32 rows), each row checked against the head and the ladder's stored
    features, bitwise. Every check passed; stride steps 1 and 2 occurred; the
    peak CUDA allocation was 13.57 GiB.
  - `reproduce`: the runner's reproduction role on the real ladder files
    returned `exact` (all 512 receipts, fingerprint `defd29fb…` and the final
    scores equal the ladder's) in 50 s.
  - No gated route was trained and no new route read the final split.

## Disk

The resource guard keeps 50 GiB free; the mismatch features need about 2 GiB.
On 2026-10-17 at 15:25Z, 46,323,671,040 bytes were available. At 15:28:36Z Ryō
ran the published [retirement](../../inventory/v20_retirement_20261017/README.md)
of the finished runs' feature files. All 16 hashes matched, 25.2 GiB were freed,
and 73,339,457,536 bytes were then available. The postflight rehashed the kept
cut-4 features: both equal the pinned hashes.

## Dispatch

[`launch_v20_a4_gated_route.sh`](launch_v20_a4_gated_route.sh) was run once,
detached, in the task root at 2026-10-17T15:29:05Z (SHA-256
`beae0c7108fa3ddb9533ddd1e715d9f7f9f509ee95de583dfbc87e001716c274`, launcher
PID 2501604). The stages, in order:

1. Tiny CPU qualification, then tiny CUDA qualification (59 cases each).
2. The runner's `dispatch`: `reproduce`, `extract_mismatch`, `gated_s1`–`s3`,
   `replay` and `endpoints`. Each role is a fresh process through
   `run_source_sealed.py`.

Each stage starts only if the previous exited 0. The script refuses existing
`qualification/`, `raw/` or `checkpoints/` and appends to
`LAUNCH_TIMELINE.log`. Failed, quiet or interrupted stages are recorded, not
relaunched.

Preflight immediately before dispatch:

- no GPU compute client (10 MiB in use);
- 119 GiB host memory available;
- 73.3 GB disk available;
- load average 0.16;
- the sealed checkout clean at `6bf97c2`;
- the task root holding only the seal, the bundle and the launch script.

Both qualifications exited 0 (15:29:15Z and 15:29:25Z). No weight is deleted by
the run.
