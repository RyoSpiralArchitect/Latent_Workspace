# V20 Deliberation pilot (D1) — results

2026-10-16. **All 14 roles complete and verified. The dispatcher's final
endpoint step failed on an import path, so the pre-registered endpoints were
computed offline by the sealed function: `LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE`.**
With Mistral-7B frozen and the facts inline, the v4 route lifts held-out accuracy
from 0.680 to 0.882–0.911 in every seed. Four latent steps do not beat one: the
step gain holds in one seed of three, and a trained four-step lattice answers
the same with only its first step. **Deliberation is not established.** What the
run does show is a large readout gap: even the control that reads only the last
position's hidden state, with no lattice, reaches 0.81–0.89. The old **FAIL /
winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

Execution commit `e18657b35003671bca8d8130947c893ef214c3b9`, bound by the
[622-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `bc29d05d…57ee94`),
byte-identical on Furnace and locally. Design and endpoints were frozen before
launch in [DELIBERATION_PILOT.md](../../../docs/v20/DELIBERATION_PILOT.md); the
[handoff](EXECUTION_HANDOFF.md) records the dev checks. One detached
[dispatch](furnace/launch_v20_deliberation_pilot.sh) (UTC,
[timeline](furnace/LAUNCH_TIMELINE.log)): CPU qualification 00:03:44Z (25/25),
CUDA 00:03:50Z (25/25), pilot 00:03:57Z → `pilot exit=1` at 00:25:03Z.

| Process | Status | Elapsed |
| --- | --- | ---: |
| Extract (GPU; peak CUDA 15,167,136,768 bytes) | `V20_FROZEN_INLINE_FEATURES_EXTRACTED` | 245.3 s |
| `k4` ×3 | `V20_DELIBERATION_ARM_COMPLETE` | 118.0–120.7 s |
| `k1` ×3 | `V20_DELIBERATION_ARM_COMPLETE` | 54.7–58.0 s |
| `k4_lw` ×3 | `V20_DELIBERATION_ARM_COMPLETE` | 122.9–124.4 s |
| `readout` ×3 | `V20_DELIBERATION_ARM_COMPLETE` | 34.6–35.6 s |
| Replay (`k4` seed 1, update 257) | `V20_DELIBERATION_FRESH_PROCESS_EXACT_REPLAY` | 4.5 s |

The extract role rendered 7,168 rows (train 4,096 / dev 1,024 / final 2,048;
844,748 prompt tokens, at most 122) and checked for every row that the frozen
head reproduces the full native logits bitwise from the stored hidden state.
The pinned base hash matched. Features (6.92 GB) and checkpoints (about 395 MiB)
stay on Furnace under the task root.

**The failed step.** After all 14 roles had completed, the dispatcher's
`endpoints_for` ran `from latent_workspace_ft_v10 import v20_deliberation` in a
process that never calls `load_runtime`, which is what puts `src/` on the path
in every role process. The run interpreter does not have the package installed,
so the import failed (`ModuleNotFoundError`), and the dispatcher wrote no
`ENDPOINTS.json` and ended `INCOMPLETE_NO_RETRY` with all 14 roles listed as
completed. The local tests passed because the local environment has the package
installed in editable mode. Nothing was relaunched.

## Pre-registered endpoint (final split, update 512; computed offline)

The endpoints were computed by the sealed `endpoints_for` from `e18657b`,
unchanged, on the verified receipts: the same function and inputs the
dispatcher would have used. 2,048 rows, 128 world pairs.

| Seed | Base inline | `k4` | `k1` | `k4` − base (worlds +/−/0, p) | `k4` − `k1` (worlds +/−/0, p) |
| --- | ---: | ---: | ---: | --- | --- |
| 2026101601 | 0.680 | 0.911 | 0.921 | **+23.1 pt** (119/3/6, 6e-32) pass | −1.0 pt (16/30/82, 0.99) fail |
| 2026101602 | 0.680 | 0.888 | 0.855 | **+20.9 pt** (112/7/9, 9e-26) pass | +3.3 pt (61/22/45, 1e-5) pass |
| 2026101603 | 0.680 | 0.882 | 0.895 | **+20.2 pt** (112/6/10, 1e-26) pass | −1.3 pt (43/54/31, 0.89) fail |

Route gain in all three seeds; step gain in one: **`LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE`**.

## Descriptive tables (declared before launch)

| Arm | Seed 1 | Seed 2 | Seed 3 | Mean |
| --- | ---: | ---: | ---: | ---: |
| `k4` | 0.911 | 0.888 | 0.882 | 0.894 |
| `k1` | 0.921 | 0.855 | 0.895 | 0.890 |
| `k4_lw` | 0.913 | 0.859 | 0.897 | 0.890 |
| `readout` (last position, no lattice) | 0.888 | 0.893 | 0.812 | 0.864 |

- **The trained lattice does its work in its first step.** Run with only its
  first one, two or three steps, every four-step model stays within 0.0024 of
  its full accuracy (for `k4`, within 0.0005).
- **By hop distance**, the base answers 0.66 / 0.70 / 0.72 / 0.60 / 0.71 for
  hops 1–5. After training, `k4` reaches 0.996–1.0 on hop 5, 0.90–0.98 on hops
  2–4, and 0.79–0.84 on hop 1, the adjacent pairs, which stay the hardest.
- **Affected questions** (the edited fact itself): base 0.58, `k4` 0.76–0.81.
  Both sides of an affected pair right: base 61/256, `k4` 136–170, `k1`
  142–176, `readout` 100–156.
- **Repairs and regressions** against base: `k4` 543–584 repaired rows against
  81–157 regressed.
- The gate opens fully (1.0) in every arm; the mean candidate residual ends at
  3.6–5.2 logits. Dev curves are noisy (for example, `k4` seed 2 dropped to 0.68
  at update 256 and ended at 0.88); they are descriptive.

## What it means

1. **Deliberation is not established** for this route and task: no consistent
   gain from more latent steps, and the trained lattice does not use its later
   steps.
2. **A readout gap, not a reasoning gap.** With the facts in view, the frozen
   model's last hidden state already supports 81–89% held-out accuracy (readout
   control), against 68% from its own head. The lattice's cross-position
   attention adds about three points on average over that, not through steps.
   The v4 route here acts as a learned readout of what the model already
   computed in one forward pass.
3. For the square: a Deliberation test needs a setting where one forward pass
   does not already contain the answer, for example a lattice whose output
   feeds back into the model's own processing (as v9's boundary-layer injection
   did, or under a full update), or a task family that requires composition
   beyond a single pass. Hop depth in these worlds does not: hops 2–5 approach
   1.0 under a readout.
4. Scope: a task-specific classifier on held-out worlds of the same family. It
   says nothing about language quality, general reasoning, memory use or
   non-regression.

## Verification

All 215 pulled receipt files are byte-identical to Furnace. The sealed
verifier requires a dispatcher `PASS`, so an additive
[dispatch-01 check](verify_dispatch01.py) loads it from a clean checkout of
`e18657b` and reuses it unchanged. It verifies sources (622), both qualification
bundles, the dispatch binding and every role receipt. It then gives the sealed
`verify_results` the endpoints computed by the sealed `endpoints_for`, through
an overlay directory that stands in for a dispatcher-written `ENDPOINTS.json`.
That recomputes every arm's correctness from the saved logits, the step-0
equality with base, fingerprints, checkpoint receipts and the replay.
[Local](OFFLINE_VERIFY_LOCAL.json) and [Furnace](OFFLINE_VERIFY_FURNACE.json)
(clean dev checkout; all three feature files and every checkpoint body
rehashed) both report `OFFLINE_V20_D1_DISPATCH01_ROLES_PASS_ENDPOINTS_COMPUTED_OFFLINE`;
only the rehash flags differ.

The branch now makes `endpoints_for` put `src/` on the path itself, with a
[regression test](../../../tests/test_v20_dispatch_imports.py) that blocks the
package unless `src/` is on `sys.path`. It fails on the sealed code even where
an editable install exists, and it sits outside the plan's 25 qualification
cases. Any future dispatch would need a new seal; the plan is unchanged.
