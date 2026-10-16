# V20 D1: does the v4 lattice deliberate on Mistral-7B?

2026-10-16. **RESULT: `LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE`** (all roles
complete; the dispatcher's endpoint step failed on an import path, so the
endpoints were computed offline by the sealed function). The route lifts
held-out accuracy by 20–23 points in every seed, but four latent steps do not
beat one, and a readout without any lattice gets most of the gain. See the
[results](../../provenance/pilots/v20_deliberation_pilot_20261016/README.md).
Frozen before launch as follows. The first V20 experiment, agreed with Ryō,
reads the Deliberation corner (潜在熟考) of the [V20 square](SCOPE.md). The
old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Question

With pinned Mistral-7B-Instruct-v0.3 frozen and the world facts inline, does
the v4/v5 latent lattice formed from the model's own final hidden states improve
held-out answers through its latent steps: more with four steps than with one,
at matched parameters?

The facts are inline so that Deliberation can be read while Availability is
still null: the base already sees everything, and only computation in the
lattice can add. Availability's lower rungs are read separately, without
training, by probing the V19 checkpoints on the same splits (A1, next).

## What is reused unchanged

- **Lattice:** v5's `CausalBroadcastLatentWorkspace` from
  [`engine.py`](../../src/latent_workspace_ft_v10/engine.py). Attention and
  feed-forward weights are shared over latent steps; only small per-step
  embeddings and scales differ, so four steps against one is a matched-capacity
  comparison (2.98M parameters each). v9's values: width 256, 8 heads,
  feed-forward ×2, dropout 0.05, anchor refresh at the first step only.
- **Route:** v4's gated low-rank vocabulary residual. The lattice reads the
  hidden state that enters the frozen LM head; logits become
  `base + sigmoid(gate) · adapter(final latent state)`, with the engine's gate
  (bias −2) and `LowRankWorkspaceLogitAdapter` (rank 32). Its zero-initialized
  output leaves the base exact at step 0.
- **`LatentWorkspaceLoss`** with v9's values, for one arm.
- **Rendering:** V15's qualified `render_case` (native chat, cue present,
  facts inline as `canonical_facts`), candidates " no"/" yes" (ids 1476, 5849).
- **Capture:** V15.5's `last_hidden_state` capture, with the frozen head
  reproducing the full native logits bitwise for every row.
- **Data:** the V18/V19 splits and oracle checks: 256 train, 64 dev and 128
  held-out final world pairs, 16 rows each (intact and twin side × 8 queries).
- **Execution:** the sealed pre-import launcher, GPU contention guard, STARTED
  and FINISHED receipts, deterministic gzip records and no-retry dispatch.

## Design

**Features (one GPU role).** For every row, the final hidden states at every
prompt position (bf16) and the base logits of the two candidates are written
to safetensors files, about 6.6 GiB in all. The base is frozen, so the lattice
can train on these features exactly; the GPU is needed only for minutes.

| Arm | Latent steps | `LatentWorkspaceLoss` |
| --- | ---: | ---: |
| `k4` | 4 | 0 |
| `k1` | 1 | 0 |
| `k4_lw` | 4 | 0.02 (v9 `lw`) |
| `readout` | none (anchor only) | 0 |

Three seeds. Every component is initialized from its own derived seed, so arms
of one seed share every common parameter, and `k1`'s step embedding equals
`k4`'s first. Training runs on CPU in FP32 with deterministic algorithms and 8
threads: choice-normalized cross-entropy over the two candidates at the last
prompt position, AdamW (learning rate 3e-4, weight decay 0.01 on weight
matrices, clip 1.0), batch 32, 512 updates (4 epochs over 4,096 train rows).
Data order, dropout and loss sampling derive from (seed, update).

Dev is evaluated at 0/128/256/384/512 (descriptive); the final split at 0 and
512. A row is correct when the target candidate's logit is strictly higher.

## Pre-registered endpoint (final split, update 512)

- **Route gain** (`k4` against base inline): at least 2 points more accuracy
  over the 2,048 rows and a one-sided exact sign test over world pairs (those
  whose 16-row correct count differs) at p ≤ 0.01.
- **Step gain** (`k4` against `k1`): the same rule.

| Verdict | Condition |
| --- | --- |
| `DELIBERATION_STEP_GAIN` | route and step gains in all three seeds |
| `LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE` | route gain in all three seeds only |
| `NO_LATTICE_GAIN` | otherwise |

`readout`, `k4_lw`, the dev curve and truncated inference are descriptive, not
part of the verdict. Descriptive tables, fixed now: final accuracy per arm and
seed; four-step arms run with only their first one, two or three steps; accuracy
by hop distance, affected or unaffected question, and wording; repairs and
regressions against base; content following on affected pairs (both sides
right); gate and residual size.

A fresh process restores `k4` seed 1 at update 256 and must reproduce update
257 bitwise. Tiny CPU and CUDA qualification ([25 tests](../../tests/test_v20_deliberation.py))
runs first, including an end-to-end check that the
[offline verifier](../../scripts/verify_v20_deliberation_pilot.py) accepts the
receipts the [runner](../../scripts/run_v20_deliberation_pilot.py) writes and
rejects a tampered prediction. [Plan](../../configs/v20/DELIBERATION_PILOT_PLAN.json).

## What it can and cannot show

With the backbone frozen, bypassing the route restores base inline exactly by
construction, so necessity is not a finding here; after a full update it would
be. A step gain would show that the lattice does useful computation over latent
steps on this task family. It would not show memory use (Availability),
general reasoning, non-regression or language quality. A null result is about
this lattice, budget and data. With the facts inline the base answers multi-hop
questions better than one-hop ones (V11 Gate-0), so hop depth is reported, not
used as the difficulty axis.

No sequences are generated, no judge is called, no native weight changes and
nothing is deleted or uploaded.
