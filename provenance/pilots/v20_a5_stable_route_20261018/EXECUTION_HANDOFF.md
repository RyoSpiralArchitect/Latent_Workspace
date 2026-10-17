# V20 A5 stable gated route — execution handoff

2026-10-18. The design and the pre-registered endpoint were frozen in
[A5_STABLE_ROUTE.md](../../../docs/v20/A5_STABLE_ROUTE.md). Every file the run
reads from the depth ladder and A4 is pinned in the plan and rehashed by each
role that reads it:

- `../latent-v20-a2-depth-ladder-20261016/raw`, beside the task root;
- `../latent-v20-a4-gated-route-20261017/raw`, beside the task root.

Interpreter:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Development checks before dispatch (not evidence)

- **Design checks:** on train worlds only, six seeds, in
  [DEV_CHECKS.md](DEV_CHECKS.md), summarized in the design. The development
  features (4.4 GB) stay in `tmp/latent-v20-a5-dev-20261018/features`.
- **Local Mac:**
  - the qualification cases;
  - A4's tests and the architecture rules, documentation, depth-ladder, A1,
    D1 and dispatch-import tests (71 more);
  - Ruff.
- **Furnace dev checkout** `worktrees/latent-workspace-v20-a5-dev-20261018`,
  with the run's interpreter: all qualification cases pass on CPU and CUDA at
  each attempt's commit. The checkout was clean before and after.
- **Smoke of the sealed code path** ([dev_smoke.py](dev/dev_smoke.py), output
  in `tmp/latent-v20-a5-smoke-20261018`, at `5199f99`): the runner's
  reproduction role on the real records returned `exact` in 86 s. All 512
  receipts, fingerprint `a35e796c…` and the final scores equal A4's. No stable
  route was trained and no new route read the final split.

## Attempt 01: stopped at the CUDA qualification

- **Source:** `5199f990cb83c61a7b1e3a1c3f6c928c93c06cbf`, transferred as
  `a5.bundle` (SHA-256 `bd9645e8…f47ad`, 6 commits on top of A4's `6bf97c2`).
- **Seal:** prepared in the clean checkout
  `worktrees/latent-workspace-v20-a5-stable-route-20261018`: 662 files, SHA-256
  `481d9a6b…db735d`, byte-identical to a local clean-clone seal.
- **Plan:** `b8357d51…686bd`.
- **Dispatch:** once at 2026-10-17T17:46:46Z (launcher PID 2516444).
  - The CPU qualification passed.
  - The CUDA qualification's 59 tests all passed, but its envelope check needs
    a positive CUDA peak and no A5 test touches CUDA. It ended
    `INCOMPLETE_NO_RETRY` at 17:47:05Z.
  - Nothing later was dispatched.
- **Records:** [attempt01/](attempt01/README.md). The task root
  `tmp/latent-v20-a5-stable-route-20261018` stays as it is.

## Attempt 02

The only change from attempt 01: the plan qualifies on CPU alone (engine
`execution.qualification_devices`, with its test as the 60th case), and the
launch script runs only the CPU qualification.

- **Source:** `14ddacf93ae11b0434a7599711b2e5520e067641` on
  `SpiralReality/v20-a5-stable-gated-route`, pushed before any remote
  computation. It was transferred as `a5b.bundle` (SHA-256
  `23d82fa5e723e8738ba1b9f500e5661be249add883cd177b4dbc88645ba4eeaf`, 2
  commits on top of `5199f99`).
- **Seal:** the clean detached checkout
  `worktrees/latent-workspace-v20-a5-stable-route-attempt02-20261018` had no
  tracked, untracked or ignored file before or after `prepare-seal`, which
  wrote a 662-file `SOURCE_SEAL.json` (SHA-256
  `39d576aafe46f84d9b9bd4c1e2661256f362949d063e231d8d2e12adce6f3c88`). It is
  byte-identical to an independently prepared local seal from a clean clone.
- **Plan:** `1b5ce8e9e6c9a818fc39222e9a9b80f3e7c0ab11e9add95dcf67c0f247a38d77`.
- **Furnace dev checkout:** 60/60 on CPU and on CUDA at `14ddacf`.
- **Task root:** `tmp/latent-v20-a5-stable-route-attempt02-20261018`.

[`launch_v20_a5_stable_route.sh`](launch_v20_a5_stable_route.sh) was run once,
detached, in the task root at 2026-10-17T18:07:53Z (SHA-256
`82d8ec996348d8d1d4d570e47873779e3b42d6ed4cb6794e8202a7a5897148b1`, launcher
PID 2518999). The stages, in order:

1. Tiny CPU qualification (60 cases).
2. The runner's `dispatch`: `reproduce`, `stable_s1`–`s3`, `replay` and
   `endpoints`. Each role is a fresh process through `run_source_sealed.py`.

Each stage starts only if the previous exited 0. The script refuses existing
`qualification/`, `raw/` or `checkpoints/` and appends to
`LAUNCH_TIMELINE.log`. Failed, quiet or interrupted stages are recorded, not
relaunched.

Preflight immediately before dispatch:

- no GPU compute client;
- 119 GiB host memory available;
- 63.7 GB disk available;
- load average 0.25;
- the sealed checkout clean at `14ddacf`;
- no other run of this project in progress.

No weight is deleted by the run.
