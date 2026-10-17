# V20 A4 content-gated cut-4 route — results

2026-10-18. **All 7 roles complete and verified. Pre-registered verdict:
`NOT_ESTABLISHED`** (seeds: `NOT_ESTABLISHED`, `CONTENT_REACHES_ANSWERS`,
`CONTENT_REACHES_ANSWERS`). The ladder's ungated route was `DIRECTIONAL_ONLY`
(`CONTENT_REACHES_ANSWERS`, `CONTENT_REACHES_ANSWERS`, `DIRECTIONAL_ONLY`).

- **Gating did what it was built to do, in every seed:**
  - Random-pair flips fell from 24, 32 and 46 to 4, 4 and 4.
  - Memory that is not about the question barely moves the answer any more:
    random, unrelated or none, 0.02–0.14 against 2.7–5.9 ungated. None of
    these kinds of memory was trained on.
- **Seed 3, the ladder's weak seed,** now meets the endpoint: 54 flips
  against 4 (it had 21 against 46).
- **Seeds 2 and 3 meet the endpoint** with margins of 51 and 50 over random
  memory. The ungated route had margins of 42, 22 and −25.
- **Seed 1 does not.** Its flips pass (30 against 4), but its accuracy is 0.68
  and its world sign test fails (74 against 54, p = 0.046). Its training loss
  spiked six updates before the end, and the route was scored at update 512
  in that disturbed state. On its own training rows it scores 0.72, against
  0.87–0.88 for the other seeds.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

- **Source:** execution commit `6bf97c24133dea7eb5a786c64697de184832d85c`,
  bound by the [658-file seal](furnace/SOURCE_SEAL.json) (SHA-256
  `3fc0f4ba…71176f`), byte-identical on Furnace and locally.
- **Design:** frozen before launch in
  [A4_GATED_ROUTE.md](../../../docs/v20/A4_GATED_ROUTE.md). The
  [handoff](EXECUTION_HANDOFF.md) records the development checks, the smokes
  and the disk retirement that preceded launch.
- **Dispatch:** one detached [dispatch](furnace/launch_v20_a4_gated_route.sh)
  (UTC, [timeline](furnace/LAUNCH_TIMELINE.log)):
  - CPU qualification exited 0 at 15:29:15Z (59/59);
  - CUDA qualification exited 0 at 15:29:25Z (59/59);
  - the roles ran from 15:29:25Z and ended `gated route exit=0` at 15:37:15Z.

| Process | Status | Elapsed |
| --- | --- | ---: |
| `reproduce` (the ladder's ungated route, seed 1, retrained) | `V20_A4_UNGATED_ROUTE_REPRODUCED_EXACTLY` | 51.1 s |
| `extract_mismatch` (GPU; peak CUDA 14,815,970,304 bytes) | `V20_A4_MISMATCH_ROWS_EXTRACTED` | 87.0 s |
| `gated_s{1,2,3}` (CPU, 8 threads) | `V20_A4_GATED_ROUTE_COMPLETE` | 101.0–104.2 s |
| `replay` (seed 1, update 257 from 256) | `V20_A4_FRESH_PROCESS_EXACT_REPLAY` | 4.5 s |
| `endpoints` | `V20_A4_ENDPOINTS_COMPLETE` | 1.8 s |

- **Reproduction:** all 512 update receipts, the final fingerprint
  (`defd29fb…`) and the final scores equal the ladder's. The comparison below
  therefore differs only by the gating.
- **Mismatch rows:** 4,096, in the ladder's train order. A first step found
  the other world for 3,144 rows; 756 needed two steps and 196 needed three to
  six. On 64 rows, the head equaled the decoder continued from the cut, and
  the row re-read with its own memory equaled the ladder's stored features,
  bitwise.
- **Verification:** the [offline verifier](../../../scripts/verify_v20_a4_gated_route.py)
  passed from a clean clone at the seal ([local](OFFLINE_VERIFY_LOCAL.json))
  and in the sealed checkout on Furnace ([Furnace](OFFLINE_VERIFY_FURNACE.json)).
  On Furnace it also rehashed this run's features and the ladder's reused
  ones. It recomputed every verdict from the saved scores, and checked every
  mismatch row against the plan's rule on the pinned training data.
- **Storage:** the mismatch features (1.86 GB) and seed 1's update-256
  checkpoint stay on Furnace; their hashes are in the role manifests.

## Pre-registered endpoint (final split, update 512; 256 affected questions, 128 worlds)

Lane A's rule from V19, unchanged: at least 26 flips, at least 20 more than
random memory, and the world sign test at α = 0.001.

| Arm | Seed | Flips / random (margin) | Worlds +/− | p | Verdict |
| --- | ---: | --- | --- | ---: | --- |
| host | — | 44 / 3 (41) | 54 / 73 | 0.96 | `NOT_ESTABLISHED` |
| **gated** | 1 | 30 / 4 (26) | 74 / 54 | 0.046 | `NOT_ESTABLISHED` |
| **gated** | 2 | 55 / 4 (51) | 85 / 43 | 1.3e-4 | `CONTENT_REACHES_ANSWERS` |
| **gated** | 3 | 54 / 4 (50) | 83 / 45 | 5.0e-4 | `CONTENT_REACHES_ANSWERS` |
| ungated (ladder) | 1 | 66 / 24 (42) | 84 / 44 | 2.6e-4 | `CONTENT_REACHES_ANSWERS` |
| ungated (ladder) | 2 | 54 / 32 (22) | 84 / 44 | 2.6e-4 | `CONTENT_REACHES_ANSWERS` |
| ungated (ladder) | 3 | 21 / 46 (−25) | 85 / 43 | 1.3e-4 | `DIRECTIONAL_ONLY` |

**Verdict (primary):** `gated` is `NOT_ESTABLISHED` by the all-seeds rule.
The ladder's ungated route stays `DIRECTIONAL_ONLY`; the endpoint role
recomputed its verdicts from its pinned scores, and they equal its record.

## Descriptive (declared before launch)

Accuracy on all 1,024 final questions:

| Arm | Memory | Twin | Random | Reversed | Unrelated | None |
| --- | --- | --- | --- | --- | --- | --- |
| host | 0.58 | 0.60 | 0.50 | 0.61 | 0.50 | 0.53 |
| gated s1 | 0.68 | 0.68 | 0.50 | 0.67–0.68 | 0.50 | 0.53 |
| gated s2, s3 | 0.84 | 0.83–0.86 | 0.50 | 0.84–0.86 | 0.50 | 0.53 |
| ungated s1–s3 | 0.79–0.83 | 0.81–0.83 | 0.49–0.51 | 0.79–0.84 | 0.47–0.50 | 0.48–0.50 |

How far the route moves the answer from the host's: the mean absolute change
of the candidate gap.

| Arm | Memory | Twin | Random | Reversed | Unrelated | None |
| --- | --- | --- | --- | --- | --- | --- |
| gated s1 / s2 / s3 | 2.99 / 4.56 / 3.90 | 2.95 / 4.54 / 3.88 | 0.04 / 0.05–0.07 / 0.10–0.12 | 2.87–3.06 / 4.33–4.61 / 3.67–3.95 | 0.03 / 0.02 / 0.02 | 0.14 / 0.08 / 0.08 |
| ungated s1 / s2 / s3 | 3.83 / 3.95 / 5.24 | 3.78 / 3.93 / 5.23 | 4.28–4.38 / 4.41–4.51 / 5.23–5.30 | 3.66–3.97 / 3.78–4.09 / 5.02–5.24 | 3.06 / 3.99 / 5.75 | 5.89 / 5.53 / 2.73 |

From [descriptive.py](descriptive.py) ([output](DESCRIPTIVE.json)), which
reads the receipts only:

- **Training-split accuracy at update 512:**
  - gated: 0.72, 0.88 and 0.87;
  - ungated: 0.87, 0.84 and 0.82;
  - host: 0.60.
- **Residual on the training mismatch rows at update 512** (the term gating
  pushes to zero): gap moved 0.04, 0.04 and 0.07.
- **Reversed-memory agreement:**
  - gated: 0.87–0.88, 0.83–0.85 and 0.83–0.84;
  - ungated: 0.83, 0.84 and 0.87–0.89.
- **Unaffected predictions changed** between intact and twin (of 768): gated
  63, 32 and 39; ungated 55, 64 and 41.

## Seed 1 (descriptive)

Seed 1's gated and ungated runs start from the same parameters and follow
nearly the same training loss to update 448 (32-update means 0.33 and 0.32).
The gated run's last 32 updates average 0.43 against the ungated run's 0.31.
At updates 506 and 507 its task loss was 1.01 and 0.95, with gradient norms of
15.2 and 13.7 before clipping. The gating term stayed near 0.001 in those
updates. The route was scored at update 512, five updates later, by the
frozen rule. On its own training rows it then scores 0.72.

The other gated seeds' largest losses in their last 64 updates came at least
25 updates before the end: 0.66 at update 464, and 0.86 at update 487
(gradient norm 15.5). Every ungated run's largest loss there was 0.69, so two
of the three gated runs spiked higher late in training than any ungated run.
One run cannot separate a late fluctuation from an effect of gating on
stability. The receipts do show that, under a constant learning rate, the
score at a fixed update depends on the last few updates.

## What it means

1. **The ungated route's weak point is closed.** Without gating, memory that
   is not about the question moved the route's answers as much as the right
   memory, or more: none 2.7–5.9, random 4.3–5.3, against 3.8–5.2. Lane A's
   margin over random memory caught this in seed 3. With gating such memory
   barely moves answers in every seed. That includes kinds never trained on
   (Gaussian memory, complement-entity facts, no memory) and held-out worlds.
2. **When the gated route trains well, it reads content better.** Seeds 2 and
   3 answer at 0.83–0.86 and flip 54–55 affected answers against 4 under
   random memory. Those are the largest margins at cut 4 so far.
3. **The every-seed criterion is still not met.** The remaining fragility has
   moved from what the route reads to where training stops. One seed of three
   was scored right after a disturbance.
4. **Score:** two seeds of three meet the endpoint, as before. They are
   different seeds, and the two that pass do so by much more.

No sequences were generated, no judge was called, no native weight changed and
nothing was deleted by the run.
