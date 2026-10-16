# V20 A2: the depth ladder — how deep can a memory enter the host?

2026-10-16. **FROZEN BEFORE LAUNCH.** V20 is A2, the flip through v4's logit
route (Ryō). The [power checks](../../provenance/pilots/v20_a2_flip_20261016/DEV_POWER_CHECKS.md)
that stopped A2's first design found the wall is depth. Ryō chose to seal that
finding as A2 first, then build toward a workspace that writes into the lower
layers. The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is
unchanged.

## Question

With pinned Mistral-7B-Instruct-v0.3 frozen, the world facts and the question
are each encoded on their own. How deep can the facts' states enter the host
and still be read? The flip endpoint of lane A is read, unchanged, at cuts 0,
4, 8 and 16:

- by the frozen host alone;
- with v4's route reading the host's final states.

## Memory written into the host at cut k

- **Memory:** V19's memory text and tokens. These are the canonical facts
  (intact, twin, reversed, unrelated), without special tokens, run alone
  through the layers below cut k (engine `DecoderHost.to_cut`).
- **Question:** V15's query-only prompt, rendered identically for both sides,
  run alone through the same layers.
- **Entry:** the memory's cut-k states enter as positions before the
  question's (engine `CutPrefixRoute`), and the host continues through its
  own remaining layers.
- **Cut 0:** the facts become a text prefix. The run checks this bitwise
  against the inline forward on sampled rows; the engine's tests show it for
  Mistral and OLMo2.
- **Cut 16:** this is V16–V19's context boundary.

## Arms (per cut)

| Arm | What answers | Training |
| --- | --- | --- |
| `host` | the frozen host's own logits with the memory in place | none |
| `route` | `host` plus D1's route (`DeliberationRoute`, 4 latent steps, D1's values) over the final states at the question positions: a gated low-rank residual on the host's logits | D1's settings: CPU FP32, 8 threads, AdamW 3e-4, batch 32, 512 updates over the 4,096 train rows (both sides, each side's own facts) |
| `readout` (descriptive) | D1's readout control: no lattice step, last position | the same |

Three seeds for `route` and `readout`. The arms of one seed share every common
parameter. A route starts exactly at the host's logits, because its residual is
zero at initialization; the run checks this on every row.

## Conditions (final split, 128 world pairs, 1,024 questions)

- **Endpoint:** intact, twin, random_intact and random_twin (V16's
  norm-matched Gaussian memory, seed 470016 + world).
- **Descriptive:** reversed intact and reversed twin (same content in the
  other order), unrelated facts, and no memory.

## Pre-registered endpoint (per cut and arm)

Lane A's rule from V19, unchanged: 256 affected held-out questions. A flip is
the intact answer under the intact memory and the twin answer under the twin.

- **Sign test:** exact one-sided, over worlds, on the summed donor-directed
  gap change, at α = 0.001.
- **Thresholds:** at least 26 flips, and at least 20 more than under the
  random pair.
- **Verdicts:** `CONTENT_REACHES_ANSWERS`, `DIRECTIONAL_ONLY` or
  `NOT_ESTABLISHED`. `host` has one verdict per cut. `route` and `readout` are
  `CONTENT_REACHES_ANSWERS` if every seed reaches it, `DIRECTIONAL_ONLY` if
  every seed is at least directional, and `NOT_ESTABLISHED` otherwise.
- **Read depth:** the deepest cut whose verdict is at least
  `DIRECTIONAL_ONLY`, for `host` and for `route` (or none).

Descriptive, fixed now:

- accuracy under every condition;
- unaffected prediction changes;
- reversed-memory agreement;
- the readout arm;
- the training-split accuracy at update 512.

## Power and expectations (development, train split only)

The draft's within-train checks used 192 training worlds and read 64 held-out
training worlds, 128 affected questions, with the rule applied as written.

| Cut | `host` accuracy | `host` flips / random | Route (question positions) accuracy | Route flips / random | Route worlds +/− |
| ---: | --- | --- | --- | --- | --- |
| 0 | 0.77 / 0.79 | 31 / 2 | 0.84 (all positions) | 27 / 15 | 58 / 6 |
| 4 | 0.57 / 0.58 | 23 / 1 | 0.84 / 0.81 | 23 / 9 | 46 / 18 |
| 8 | 0.48 / 0.48 | 1 / 5 | 0.59 (all positions) | 20 / 11 | 35 / 29 |
| 16 | 0.48 / 0.49 | 2 / 14 | not run | — | — |

The route learns at cut 0 and 4 with these exact settings, so a null there
would not be a power failure. These dev figures are not the endpoint.

## Validity and execution

- **Checks every 64 rows:** the head on the final states equals the decoder
  continued from the cut, bitwise, and at cut 0 the inline forward, bitwise.
- **Identity and data:** pinned base hash, data file hashes, V19's oracle data
  checks, and identical question prompts for both sides.
- **Roles:**
  - one GPU role per cut;
  - one CPU role per cut and seed, training `route` then `readout`;
  - a fresh-process replay of `route` at cut 4, seed 1, update 257 from the
    update-256 checkpoint;
  - an endpoint role.
- **Execution:** every role runs as a fresh process from the seal, with no
  retry. The verdicts are computed inside a role.
- **Qualification:** tiny CPU and CUDA runs of the
  [depth-ladder tests](../../tests/test_v20_a2_depth_ladder.py) and of the
  engine's [stack](../../tests/test_latent_workspace_stack.py),
  [availability](../../tests/test_latent_workspace_availability.py) and
  [execution](../../tests/test_latent_workspace_execution.py) suites.
- **Verifier:** the [offline verifier](../../scripts/verify_v20_a2_depth_ladder.py)
  recomputes every verdict from the saved scores.
- **Plan:** [plan](../../configs/v20/A2_DEPTH_LADDER_PLAN.json).

About 21 GiB of features stay on Furnace. The resource guard keeps 50 GiB free.

## What it can and cannot show

- **A verdict at cut k:** whether this frozen system answers held-out
  questions from a memory that entered at cut k, on this task family.
- **`host` across cuts:** where the pretrained model's own layers stop
  reading memory they did not see below.
- **`route`:** whether a small learned readout recovers what the host
  computed with the memory.
- **Not shown:** that memory moves the native head beyond the cut, general
  reasoning, non-regression or language quality. Positions above the cut
  differ from the inline forward's for the question, which is part of what
  is measured.

No sequences are generated, no judge is called, no native weight changes and
nothing is deleted or uploaded.
