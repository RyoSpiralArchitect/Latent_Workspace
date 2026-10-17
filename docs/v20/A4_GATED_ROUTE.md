# V20 A4: the content-gated cut-4 route

2026-10-18. **Frozen before launch.** Ryō's fallback after A3: take "the
workspace works better in the lower layers" as the knowledge, and refine the
low-layer version the [depth ladder](A2_DEPTH_LADDER.md) supports. The old
**FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Starting point

In the depth ladder, the facts' states after four layers enter pinned
Mistral-7B at cut 4, and D1's route reads the host's final states at the
question positions. That system answers from memory: 0.79–0.83 accuracy,
against 0.50 with random memory. It met lane A's endpoint in two seeds of
three (66 and 54 flips against 24 and 32 under the random pair). The third
seed fell short because random memory moved its answers: 46 random-pair flips
against 21 real ones.

## Question

Does **content gating** make the cut-4 route meet lane A's endpoint in every
seed? Content gating means training the route to leave the host's answer alone
when the memory does not answer the question.

## What changes, and what does not

- **Unchanged:**
  - **Data:** the ladder's sealed cut-4 features, reused and pinned by hash
    (train rows with each side's own facts, final rows under every
    condition).
  - **Route:** D1's route and its settings: CPU FP32, AdamW 3e-4, batch 32,
    512 updates over 4,096 rows.
  - **Seeds:** 2026101711–13.
  - **Endpoint:** lane A's rule, as in the ladder.
- **Added, for training only:** a **mismatch row** for every train row: the
  same question read at cut 4 with the facts of another training world, on
  the same side.
  - **The other world** is the first one, stepping by 97 through the 256
    training worlds, that does not name both of the question's entities.
  - **Why not both:** the name pool has 12 names and a world uses 6. In 23%
    of plain choices the other world names both entities, so its facts state
    an answer.
- **Gating:** each update adds 0.3 times the mean square of the route's
  residual on the same batch rows read with their mismatch memory (engine
  `training.update(mismatch=...)`, `TrainConfig.mismatch_weight`).
- **Never trained on:** lane A's random-pair control (V16's norm-matched
  Gaussian memory), the dev split and the final split.

## Development (train split only; not evidence)

All checks fit train worlds 0–191 and read 192–255 (128 affected questions).
Details are in [DEV_CHECKS.md](../../provenance/pilots/v20_a4_gated_route_20261017/DEV_CHECKS.md).
The rule's thresholds were set for twice this size.

| Weight | Accuracy (intact / twin) | Flips / random | Answer moved by random memory |
| ---: | --- | --- | --- |
| 0 | 0.77–0.89 / 0.77–0.84 | 7–25 / 9–25 | 3.7–5.6 |
| 0.3 | 0.83–0.86 / 0.79–0.85 | 18–20 / 2 | 0.01–0.03 |
| 1.0 | 0.72–0.83 / 0.73–0.82 | 7–19 / 2 | 0.003–0.08 |

The last column is the mean change of the candidate gap from the host's; with
the right memory it stays 3.5–4.5 at weight 0.3. Two more checks:

- **Feature reproduction:** a fresh process re-extracted the 3,072 own rows
  bitwise equal to the ladder's stored features.
- **Route reproduction:** retraining the ladder's ungated route of seed 1
  from those features reproduced it bitwise.

## Roles

1. **`reproduce` (CPU):** retrains the ladder's ungated route of seed 1 from
   the pinned features. All 512 update receipts, the final fingerprint and the
   final scores must equal the ladder's. The comparison below then differs
   only by the gating.
2. **`extract_mismatch` (GPU):** writes the 4,096 mismatch rows in the
   ladder's train row order. Every 64th row checks two things, bitwise:
   - the head on the final states equals the decoder continued from the cut;
   - the row re-read with its own memory equals the ladder's stored features.
3. **`gated_s1`–`gated_s3` (CPU):** one per seed. Each route must start
   exactly at the host's logits.
4. **`replay` (CPU):** a fresh process replays update 257 of seed 1 from the
   update-256 checkpoint.
5. **`endpoints` (CPU):** writes the verdicts.

Every role runs once as a fresh process from the seal, with no retry.

## Pre-registered endpoint

On the ladder's final split (128 world pairs, 256 affected questions), lane
A's rule from V19, unchanged:

- **Sign test:** exact, one-sided, over worlds, on the summed donor-directed
  gap change, at α = 0.001.
- **Thresholds:** at least 26 flips, and at least 20 more than under the
  random pair.
- **Verdict (primary):** `gated` is `CONTENT_REACHES_ANSWERS` if every seed
  reaches it, `DIRECTIONAL_ONLY` if every seed is at least directional, and
  `NOT_ESTABLISHED` otherwise.
- **Comparison:** each seed against the ladder's ungated route, recomputed
  from its pinned scores. The recomputed verdicts must equal the recorded
  ones: `DIRECTIONAL_ONLY` (`CONTENT_REACHES_ANSWERS`,
  `CONTENT_REACHES_ANSWERS`, `DIRECTIONAL_ONLY`), with the host alone at
  `NOT_ESTABLISHED`.
- **Descriptive:** accuracy and the gap moved from the host's under every
  condition (the reversed facts, the unrelated facts and no memory included),
  unaffected prediction changes, and the residual on the mismatch rows.

## Validity and execution

- **Identity and data:** pinned base hash, data file hashes, V19's oracle data
  checks, and identical question prompts for both sides.
- **Alignment:** every rendered train row equals the ladder's.
- **Qualification:** tiny CPU and CUDA runs of the
  [A4 tests](../../tests/test_v20_a4_gated_route.py) and the engine's
  [stack](../../tests/test_latent_workspace_stack.py) (with the gating
  option's tests),
  [availability](../../tests/test_latent_workspace_availability.py) and
  [execution](../../tests/test_latent_workspace_execution.py) suites: 59
  cases.
- **Verifier:** the [offline verifier](../../scripts/verify_v20_a4_gated_route.py)
  recomputes every verdict from the saved scores. It also checks every
  mismatch row against the plan's rule on the pinned training data.
- **Plan:** [plan](../../configs/v20/A4_GATED_ROUTE_PLAN.json).
- **Storage:** about 1.9 GB of new features. The resource guard keeps 50 GiB
  free; this run follows the
  [retirement](../../provenance/inventory/v20_retirement_20261017/README.md)
  of the finished runs' features.

## What it can and cannot show

- **A verdict:** whether this frozen system (host plus gated route) answers
  held-out questions from a memory written at cut 4, on this task family, in
  every seed.
- **The comparison:** whether gating removes the ungated route's weak point
  (answers moved by random memory) and at what cost in real flips.
- **Not shown:** that memory moves the native head, general reasoning,
  non-regression or language quality. One gating weight is tested.

No sequences are generated, no judge is called, no native weight changes and
nothing is deleted or uploaded.
