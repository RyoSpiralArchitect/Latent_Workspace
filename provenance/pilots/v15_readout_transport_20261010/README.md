# V15: native readout transport, serialization, and generation

Client date: 2026-10-10. **Completed engineering assay; no new training,
winner, semantic promotion, or FT-beta qualification.**

The shared native path is connected: loss gradients reach the workspace and
workspace corrections reach actual generated tokens. Two limitations remain:
world-content effects depend strongly on fact serialization, and the unchanged
functional prompt does not yield a valid one-word answer, including for base.
These are separate learner and elicitation problems, not evidence that the
output wire was absent.

## Fixed source and scope

Source commit: `8e461f0` (full identity in [STARTED](raw/STARTED.json)).
[Frozen protocol](../../../docs/v15/PLAN.md) and
[machine plan](../../../configs/v15/READOUT_TRANSPORT_PLAN.json).
The [prior micro-fit](../ft_beta_query_pool_20261010/README.md) remains sealed.

- Frozen pinned Mistral-7B-Instruct-v0.3, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`, BF16 CUDA / SDPA.
- Retained step-256 final-position and question-mean readers; cap 1.0;
  **zero optimizer steps**. Base and bridge states/checkpoint bytes unchanged.
- Two already exposed training worlds, eight queries, both factual sides.
  The 32 side/query outcomes are correlated, not 32 independent worlds.
- Shared differentiable full-sequence/full-vocabulary native readout serves
  the loss diagnostic, evaluation, and generation. Legacy FP32 two-choice
  arithmetic remains a diagnostic; no historical trainer was silently changed.
- Mean pooling remains bound to original question-token positions and uses
  CPU FP32 reduction, matching the retained checkpoint's training.
- No cap increase, paid judges, weight deletion, KV cache, or base/full FT.

## Engineering gates

| Check | Completed result |
|---|---:|
| Original versus split native full logits | 16/16 prefixes exact |
| Shared versus historical native crossover logits | 384/384 exact |
| Written-zero crossover | 32/32 exact |
| Native two-choice / full-vocabulary gradient diagnostics | 8/8 finite, connected |
| Shared versus historical generation readouts | 4,681/4,681 exact |
| Written-zero generation full logits | 1,024/1,024 exact |
| Base/zero generated token sequences | 16/16 pairs exact |

Gradient diagnostics cover two questions per reader, two native losses each;
there is no optimizer update or claim that a finite update crosses a BF16
rounding boundary. Train/eval readout equality uses the same written memory,
not independently recomputed train/eval writer outputs. Generator comparisons
use base **at each condition's current prefix**; after divergence, histories
must not be treated as identical.

## Content and serialization crossover

384 rows = two readers × 16 world/query pairs × 12 memory conditions.
The six factual conditions are original/canonical/canonical-reverse, each with
both world sides. Other conditions are written-zero, fixed carrier, two seeded
raw-memory-norm-matched random controls, unrelated same-schema facts, and
different-schema facts.

| Reader / fact order | Native correct /32 | FP32 correct /32 | Correct donor flips: native / FP32, out of 4 |
|---|---:|---:|---:|
| Final / original historical | 24 | 25 | 2 / 3 |
| Final / canonical | 22 | 22 | 0 / 0 |
| Final / canonical reverse | 21 | 22 | 0 / 0 |
| Mean / original historical | 24 | 25 | 2 / 3 |
| Mean / canonical | 22 | 23 | 0 / 1 |
| Mean / canonical reverse | 23 | 24 | 1 / 2 |

Native ties count as incorrect. Query-only base is 15/32 native and 18/32
FP32, but lacks the world facts: this is **not an equal-information base-floor
test**. The previous cap audit's seven unreachable FP32 rows and failed perfect
fit gate remain unchanged. No gain was tuned to overcome them.

### Interpretation clarification to the prospective protocol

The raw summary field `orders.original.*.affected_content` is a historical
paired-world contrast, **confounding content with serialization**. The original
intact/twin texts were independently permuted. They are not a matched-order
content intervention merely because both use the order name `original`.
The prospective protocol's matched-order language must be read with this
clarification; its bytes and raw field names are preserved.

For these two worlds only, canonical and canonical-reverse do align subject
order across the two factual sides. Each twin changes three adjacency
sentences, so this is a world-content intervention, not isolated single-fact
causality. Subject order receipts can be recovered directly from
[FEATURES](raw/FEATURES.json):

| World | Original side 0 | Original side 1 | Canonical, both sides |
|---|---|---|---|
| 0 | Galen, Kestrel, Ione, Fenn, Hira | Ione, Kestrel, Fenn, Hira, Galen | Fenn, Galen, Hira, Ione, Kestrel |
| 1 | Aster, Doran, Joren, Kestrel, Beryl | Aster, Beryl, Doran, Kestrel, Joren | Aster, Beryl, Doran, Joren, Kestrel |

Final-reader canonical donor-signed FP32 change is near zero (mean
-0.0002613), versus +0.6455092 in the confounded historical contrast. Mean
reader canonical/reverse means are +0.1347427 / +0.2388020, versus +0.6462436
historically, and vary substantially across reciprocal queries. These small
exposed panels do not select a reader or establish robust semantic access.

Full-vocabulary controls matter beyond yes/no gaps. For example, unrelated
memory for the final reader has mean residual norm 0.9623, despite mean FP32
yes/no-gap drift only 0.0041873. Native total variation reaches 0.0309857 and
one of 16 top tokens changes. Fixed carrier changes 2/16 top tokens for each
reader. Raw-memory norm matching is not residual or distribution matching.

## Actual generation: transport succeeds, output contract fails

All [64 full answers](ANSWER_BANK.md) and [token traces](raw/GENERATION.json)
are retained: four affected prompts × greedy/sample211 × eight conditions.
Each condition has eight sequences, capped at 64 new tokens. Sampling shares
counter-based uniform coordinates. Inline base has the same facts but a
different prompt path; it is not the identical-prefix parity reference.

- **0/64 strict valid correct answers; 64/64 unparseable as a whole yes/no
  response; 63/64 length-truncated.** Every base and inline-base sequence also
  fails. The one EOS completion contains additional prose and is still invalid.
- Do not retroactively score the first yes/no word as a successful completion,
  extend the token budget, or introduce a stop rule to rescue this assay.
- Among 32 nonzero-workspace sequences, 16 differ from matched base: 10 first
  differ at token index 0 and six later. Sixteen stay token-identical despite
  possible distribution changes. Zero lanes remain exactly identical to base.
- For greedy world 0/query 0, base starts `no`; intact readers start `yes`;
  twin readers start `no`. The intact responses then invent more questions.
  This exhibits output transport, not a valid completed answer or isolated
  semantic causality under the confounded original serialization.
- Delayed changes include a generated numbering token and off-task continuation
  changes. Full-prefix recomputation carries text only, not residual hidden
  state or K/V. No semantic-amplification or improved-quality claim follows.

| Condition | First-token divergence from base /8 | Later divergence /8 | No divergence /8 |
|---|---:|---:|---:|
| Final intact | 4 | 1 | 3 |
| Final twin | 1 | 1 | 6 |
| Mean intact | 4 | 1 | 3 |
| Mean twin | 1 | 3 | 4 |

The free-form three-judge findings are **not re-tested by this functional
probe**. Calibrated, concise, measurement-aware behavior remains a development
sentinel, not gold supervision or evidence that it was preserved by new FT.

## Resources and verification

Furnace completed the assay in **125.72 seconds**. Torch peak allocated
**14.157 GiB**, reserved **14.324 GiB**; sampled own-process peak **15.049 GiB**;
minimum sampled free device memory **16.291 GiB**. Admission required 20 GiB
free, Torch allocator cap was 18 GiB, and the abort threshold was 4 GiB free.
Allocator limits exclude CUDA context/non-Torch allocations; process peaks
are sampled, not continuous. CPU threads 2, nice 10. The existing GPU client
was not modified and disappeared from later snapshots on its own.

Runtime: Python 3.14.4, Torch 2.13.0+cu132, Transformers 5.15.0, CUDA 13.2.
Execution used a new isolated worktree after contention checks.
Remote source: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v15-readout-20261010`.
Run path within it: `runs/v15_readout_transport_20261010`.
The latest two checkpoints per condition remain in the predecessor worktree;
this assay writes no new model weights.

[Index](ARTIFACT_INDEX.json) seals seven raw receipts.
[SUMMARY](SUMMARY.json) independently recomputes scalar summaries, common
uniforms, token divergence, counters, denominators and zero traces.
[Validation](VALIDATION.json) and [test receipt](TESTS.md).

```sh
PYTHONPATH=src:scripts python3 scripts/verify_v15_readout_transport.py \
  --bundle provenance/pilots/v15_readout_transport_20261010
python3 scripts/render_v15_answer_bank.py \
  --bundle provenance/pilots/v15_readout_transport_20261010 --check
```

Portable verification does not reload checkpoint bodies, replay gradient/full
logit tensors, redo tokenizer decoding, or continuously measure process VRAM.
Those remain execution receipts. All prior sealed query-pooling receipts and
source identities also pass their portable verifier.

## Next boundary

[V15 follow-on design](../../../docs/v15/NEXT_STEPS.md) separates no-training
elicitation/termination calibration from a single serialization-distribution
learner change. Native-loss training, a consistency penalty, and capacity
changes are distinct later factors. The independent correctness-floor battery,
48-case legacy controls, fresh quality bank and blind human review remain
pending. Keep `winner: none`, `semantic_promotion: false`, and
`non_regression: NOT_ESTABLISHED`.
