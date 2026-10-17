# V20 A5: the gated cut-4 route with a stable end of training

2026-10-18. **Frozen before launch.** After A4, Ryō asked to merge and keep
moving toward the LTWS β. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

## Starting point

[A4](A4_GATED_ROUTE.md) trained D1's route over the host's final states, with
memory written at cut 4 and content gating.

- **What gating fixed:** the ungated route's weak point. Random memory no
  longer moves answers (random-pair flips 4 in every seed, against 24, 32 and
  46).
- **Where A4 fell short:** seeds 2 and 3 met lane A's endpoint by wide
  margins. Seed 1 was scored at update 512 under a constant learning rate,
  right after a late loss spike, and failed the world sign test (p = 0.046).

The [development checks](../../provenance/pilots/v20_a5_stable_route_20261018/DEV_CHECKS.md)
(train worlds only, six seeds) showed the cause directly. Under a constant
rate, one seed's held-out flips ranged from 9 to 33 within its last 64
updates. A learning rate that decays over the second half removed the swing:
every seed reached 0.89–0.90 accuracy and 29–36 flips against 2 random.

## Question

Does A4's gated route meet lane A's endpoint in every seed when its learning
rate decays over the second half of training?

## What changes, and what does not

- **Changed: the learning rate only.** It stays at 3e-4 to update 256, then
  falls linearly: 3e-4 × (513 − step) / 257, reaching 1.2e-6 at update 512
  (engine `TrainConfig.decay_from`, `training.learning_rate_at`).
- **Unchanged, all of A4:**
  - the depth ladder's cut-4 features and A4's 4,096 mismatch rows, read from
    their sealed records and pinned by hash (no new extraction, no GPU role);
  - content gating at 0.3;
  - D1's route and settings, and seeds 2026101711–13;
  - lane A's endpoint, unchanged.

## Roles (all CPU)

1. **`reproduce`:** retrains A4's gated route of seed 1 from the pinned
   records. All 512 update receipts, the final fingerprint and the final
   scores must equal A4's. The comparison below then differs only by the
   learning rate.
2. **`stable_s1`–`stable_s3`:** one per seed. Each route must start exactly
   at the host's logits, and every update records its learning rate.
3. **`replay`:** a fresh process replays update 257 of seed 1, the first with
   a decayed rate, from the update-256 checkpoint.
4. **`endpoints`:** writes the verdicts.

Every role runs once as a fresh process from the seal, with no retry.

## Pre-registered endpoint

On the ladder's final split (128 world pairs, 256 affected questions), lane
A's rule from V19, unchanged:

- **Sign test:** exact, one-sided, over worlds, on the summed donor-directed
  gap change, at α = 0.001.
- **Thresholds:** at least 26 flips, and at least 20 more than under the
  random pair.
- **Verdict (primary):** `stable` is `CONTENT_REACHES_ANSWERS` if every seed
  reaches it, `DIRECTIONAL_ONLY` if every seed is at least directional, and
  `NOT_ESTABLISHED` otherwise.
- **Comparison:** each seed against A4's gated route and the ladder's ungated
  route. Both are recomputed from their pinned scores and must equal their
  records:
  - A4: `NOT_ESTABLISHED` (`NOT_ESTABLISHED`, `CONTENT_REACHES_ANSWERS`,
    `CONTENT_REACHES_ANSWERS`);
  - the ladder: `DIRECTIONAL_ONLY` (`CONTENT_REACHES_ANSWERS`,
    `CONTENT_REACHES_ANSWERS`, `DIRECTIONAL_ONLY`);
  - the host alone: `NOT_ESTABLISHED`.
- **Descriptive:**
  - accuracy and the gap moved from the host's under every condition;
  - unaffected prediction changes;
  - the residual on the mismatch rows;
  - the mean of the three stable seeds' logits, read by the same rule.
- **β candidate, fixed now:** if the primary verdict is
  `CONTENT_REACHES_ANSWERS`, the stable route of seed 2026101711 is the LTWS β
  candidate, and the other two seeds are replicates. This keeps the choice off
  the final split. Publication remains Ryō's separate decision, under the
  [release checklist](../v18/HF_RELEASE.md).

## Validity and execution

- **Records:** every file the run reads from the ladder and A4 is pinned in
  the plan and rehashed by each role that reads it.
- **Alignment:** A4's mismatch rows align with the ladder's train rows, row
  for row.
- **Qualification:** tiny CPU and CUDA runs of the
  [A5 tests](../../tests/test_v20_a5_stable_route.py) and the engine's
  [stack](../../tests/test_latent_workspace_stack.py) (with the schedule
  option's tests),
  [availability](../../tests/test_latent_workspace_availability.py) and
  [execution](../../tests/test_latent_workspace_execution.py) suites: 59
  cases.
- **Verifier:** the [offline verifier](../../scripts/verify_v20_a5_stable_route.py)
  recomputes every verdict from the saved scores, and checks each route's
  logged learning rates against the plan's schedule.
- **Plan:** [plan](../../configs/v20/A5_STABLE_ROUTE_PLAN.json).

## What it can and cannot show

- **A verdict:** whether this frozen system (host plus the stable gated route)
  answers held-out questions from a memory written at cut 4, on this task
  family, in every seed.
- **The comparison:** whether the end of training, not the route, decided A4's
  failed seed.
- **Not shown:** that memory moves the native head, general reasoning,
  non-regression or language quality. A verdict is not a release decision.

No sequences are generated, no judge is called, no native weight changes and
nothing is deleted or uploaded.
