# V20 A5 stable gated route — results

2026-10-18. **Attempt 02: all 6 roles complete and verified. Pre-registered
verdict: `NOT_ESTABLISHED`** (seeds: `CONTENT_REACHES_ANSWERS`,
`CONTENT_REACHES_ANSWERS`, `NOT_ESTABLISHED`). The β candidate, seed 1's
route, is not eligible, because the rule required the primary verdict.

- **The stable end did what it was built to do.** The three seeds now end
  nearly identical:
  - accuracy 0.841–0.846 (intact) and 0.852–0.854 (twin);
  - 58–60 flips against 4 under random memory, a margin of 54–56 where the
    rule asks for 20;
  - random memory moves the answer by 0.02–0.04;
  - training-row accuracy 0.879–0.883.
  - Seed 1, A4's failed seed, now meets the endpoint (58 against 4).
- **Seed 3 falls short on the world sign test alone.** Its flips (60) and
  accuracy (0.846) are the best of the three, but 80 of 128 worlds point the
  donor's way (p = 0.003). At α = 0.001 the test needs 82. The three seeds
  sit at 83, 85 and 80, around that line.
- **The mean of the three seeds' logits** (descriptive) meets the endpoint:
  65 flips against 4, 85 of 128 worlds, p = 1.3e-4.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

- **Attempt 01** stopped at the CUDA qualification before any role ran. Its
  envelope needs a positive CUDA peak, and A5's CPU-only tests never touch
  CUDA. Nothing about the outcome was observed
  ([attempt 01](attempt01/README.md)).
- **Attempt 02** differs only in qualifying on CPU alone:
  - execution commit `14ddacf93ae11b0434a7599711b2e5520e067641`, bound by the
    [662-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `39d576aa…6f3c88`),
    byte-identical on Furnace and locally;
  - design and endpoint frozen in
    [A5_STABLE_ROUTE.md](../../../docs/v20/A5_STABLE_ROUTE.md); the
    [handoff](EXECUTION_HANDOFF.md) records both attempts;
  - one detached [dispatch](furnace/launch_v20_a5_stable_route.sh) (UTC,
    [timeline](furnace/LAUNCH_TIMELINE.log)): CPU qualification exited 0 at
    18:08:02Z (60/60), and the roles ran from 18:08:02Z to
    `stable route exit=0` at 18:15:01Z.

| Process | Status | Elapsed |
| --- | --- | ---: |
| `reproduce` (A4's gated route, seed 1, retrained) | `V20_A5_A4_GATED_ROUTE_REPRODUCED_EXACTLY` | 90.5 s |
| `stable_s{1,2,3}` (CPU, 8 threads) | `V20_A5_STABLE_ROUTE_COMPLETE` | 101.7–103.1 s |
| `replay` (seed 1, update 257 from 256, the first decayed update) | `V20_A5_FRESH_PROCESS_EXACT_REPLAY` | 5.0 s |
| `endpoints` | `V20_A5_ENDPOINTS_COMPLETE` | 1.9 s |

- **Reproduction:** all 512 update receipts, the final fingerprint
  (`a35e796c…`) and the final scores equal A4's. The comparison with A4
  differs only by the learning rate. Every stable route logged the plan's
  rate at every update.
- **Verification:** the
  [offline verifier](../../../scripts/verify_v20_a5_stable_route.py) passed
  from a clean clone at the seal ([local](OFFLINE_VERIFY_LOCAL.json)) and in
  the sealed checkout on Furnace ([Furnace](OFFLINE_VERIFY_FURNACE.json)).
  On Furnace it also rehashed the ladder's and A4's reused features. It
  recomputed every verdict from the saved scores, and checked each route's
  logged learning rates against the schedule.
- **Storage:** seed 1's update-256 checkpoint (35.8 MB) stays on Furnace; its
  hash is in the role manifest.

## Pre-registered endpoint (final split, update 512; 256 affected questions, 128 worlds)

Lane A's rule from V19, unchanged: at least 26 flips, at least 20 more than
random memory, and the world sign test at α = 0.001 (at least 82 of 128
worlds).

| Arm | Seed | Flips / random (margin) | Worlds +/− | p | Verdict |
| --- | ---: | --- | --- | ---: | --- |
| host | — | 44 / 3 (41) | 54 / 73 | 0.96 | `NOT_ESTABLISHED` |
| **stable** | 1 | 58 / 4 (54) | 83 / 45 | 5.0e-4 | `CONTENT_REACHES_ANSWERS` |
| **stable** | 2 | 59 / 4 (55) | 85 / 43 | 1.3e-4 | `CONTENT_REACHES_ANSWERS` |
| **stable** | 3 | 60 / 4 (56) | 80 / 48 | 3.0e-3 | `NOT_ESTABLISHED` |
| gated (A4) | 1 / 2 / 3 | 30 / 4, 55 / 4, 54 / 4 | 74/54, 85/43, 83/45 | 0.046, 1.3e-4, 5.0e-4 | `NOT_ESTABLISHED` |
| ungated (ladder) | 1 / 2 / 3 | 66 / 24, 54 / 32, 21 / 46 | 84/44, 84/44, 85/43 | 2.6e-4, 2.6e-4, 1.3e-4 | `DIRECTIONAL_ONLY` |
| mean of the stable seeds (descriptive) | — | 65 / 4 (61) | 85 / 43 | 1.3e-4 | `CONTENT_REACHES_ANSWERS` |

**Verdict (primary):** `stable` is `NOT_ESTABLISHED` by the all-seeds rule.
The endpoint role recomputed A4's and the ladder's verdicts from their pinned
scores; both equal their records.

## Descriptive (declared before launch)

Accuracy on all 1,024 final questions:

| Arm | Memory | Twin | Random | Reversed | Unrelated | None |
| --- | --- | --- | --- | --- | --- | --- |
| host | 0.58 | 0.60 | 0.50 | 0.61 | 0.50 | 0.53 |
| stable s1–s3 | 0.84–0.85 | 0.85 | 0.50 | 0.84–0.85 | 0.50 | 0.53 |
| mean of the stable seeds | 0.85 | 0.86 | 0.50 | 0.85–0.86 | 0.50 | 0.53 |
| gated (A4) s1 / s2, s3 | 0.68 / 0.84 | 0.68 / 0.83–0.86 | 0.50 | 0.67–0.68 / 0.84–0.86 | 0.50 | 0.53 |
| ungated (ladder) s1–s3 | 0.79–0.83 | 0.81–0.83 | 0.49–0.51 | 0.79–0.84 | 0.47–0.50 | 0.48–0.50 |

How far each route moves the answer from the host's (mean absolute change of
the candidate gap):

| Arm | Memory | Twin | Random | Reversed | Unrelated | None |
| --- | --- | --- | --- | --- | --- | --- |
| stable s1 / s2 / s3 | 4.21 / 4.21 / 4.29 | 4.20 / 4.19 / 4.28 | 0.02 / 0.02–0.03 / 0.04 | 4.00–4.27 / 4.08–4.33 / 4.01–4.27 | 0.01 / 0.02 / 0.02 | 0.07 / 0.07 / 0.09 |
| ungated s1 / s2 / s3 | 3.83 / 3.95 / 5.24 | 3.78 / 3.93 / 5.23 | 4.28–4.38 / 4.41–4.51 / 5.23–5.30 | 3.66–3.97 / 3.78–4.09 / 5.02–5.24 | 3.06 / 3.99 / 5.75 | 5.89 / 5.53 / 2.73 |

From [descriptive.py](descriptive.py) ([output](DESCRIPTIVE.json)), which
reads the receipts only:

| Arm | Training-row accuracy at 512 | Training loss, last 32 updates | Largest loss, last 64 | Reversed agreement | Unaffected answers changed (of 768) |
| --- | --- | --- | --- | --- | --- |
| stable s1 / s2 / s3 | 0.879 / 0.883 / 0.881 | 0.265 / 0.270 / 0.291 | 0.51 / 0.71 / 0.47 | 0.82–0.85 | 46 / 35 / 32 |
| gated (A4) s1 / s2 / s3 | 0.719 / 0.880 / 0.874 | 0.425 / 0.339 / 0.421 | 1.01 / 0.66 / 0.86 | 0.83–0.88 | 63 / 32 / 39 |
| ungated s1 / s2 / s3 | 0.868 / 0.838 / 0.824 | 0.313 / 0.349 / 0.357 | 0.69 / 0.69 / 0.69 | 0.83–0.89 | 55 / 64 / 41 |

The stable routes' residual on the training mismatch rows is 0.02–0.03.

## What it means

1. **Where training stops no longer decides the result.** The stable seeds
   agree to within a hundredth on accuracy, flip 58–60 answers against 4,
   and leave answers alone when the memory is not about the question.
2. **The remaining shortfall is the world sign test at its threshold.** Each
   seed points the donor's way in 62.5–66.4% of worlds. The test at α = 0.001
   needs 64%. With three seeds at about that rate, "every seed passes" is
   close to a coin toss, and seed 3 landed two worlds short.
3. **Raising the per-world rate is the lever.**
   - The seeds now err in similar places, so averaging them helps only a
     little: 85 worlds for the mean, against 83 and 85 for the best seeds.
   - A clearer per-world signal needs a route that answers more of each
     world's questions right, for example from more training worlds than
     the 256 used so far.

No sequences were generated, no judge was called, no native weight changed and
nothing was deleted by the run.
