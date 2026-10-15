# V14 precision-aware bridge — visible, but not query-directed

2026-10-09 · Furnace RTX 5090 · execution qualified; **winner: none**.

The frozen-original comparison completed both 256-update training cells,
step-zero and heldout single-turn evaluation, and 896 four-turn trajectories
(3,584 generated no/yes decisions). Runtime was 61.848 seconds and peak CUDA
allocation 14,808,936,448 bytes. This is a bounded one-seed pilot, not a full-base
update comparison or an unconstrained chat benchmark.

## What changed, and what did not

The independently loaded original `mistralai/Mistral-7B-Instruct-v0.3` revision
`c170c708c41dac9275d15a8fff4eca08d52bab71` stayed frozen. Its full state SHA-256
matched before/after, with no parameter version changes or accumulated gradients.
Before training, split-adapter native logits matched the ordinary model exactly.

A query-independent writer converts layer-16 context states into four 256-wide
memory slots. A compact query-conditioned reader maps these slots to a bounded
4096-wide residual at the **post-final-normalization** boundary. The FP32 route
adds this residual in FP32 and uses the fixed LM-head rows; the native ablation
casts the sum to BF16 and retains a full-sequence/full-vocabulary head operation.
This changes both composition and head arithmetic. It is not full-model FP32,
and does not establish a repair of the old layer-16 return path.

Only 4,200,192 bridge/writer parameters are trained. Both cells share seed 47,
initialization, examples, and 256 AdamW updates at 1e-4, batch 16. Task uses paired
cross-entropy plus residual regularization. Semantic adds a donor-margin hinge
(target 0.25), unaffected gap stability, and unrelated-context gap suppression.
The residual L2 cap is 1.0, frozen before scoring. There was no heldout tuning.

All 256 training worlds and 64 evaluation worlds were used. IDs, single-world
orders, unordered twin pairs, and context strings have zero cross-split overlap;
the entity vocabulary is shared. Unrelated contexts use the six complementary
entity names, in a label-independent order. Labels, query indices, affected flags
and world-side indices never enter the bridge forward call.

## Heldout single-turn results

Each evaluation contains 6,144 rows: 64 worlds × 8 queries × 2 sides × 6 controls.
Accuracy uses both sides; affected directional comparisons use 128 unique
world/query pairs (two reversed queries per world), not 128 independent worlds.

| FP32 measurement | Original query-only | Task bridge | Semantic bridge |
| --- | ---: | ---: | ---: |
| Intact accuracy | 508/1,024 (49.61%) | 476/1,024 (46.48%) | 477/1,024 (46.58%) |
| Correct intact→twin affected flips | 0/128 | 0/128 | 0/128 |
| Mean donor-directed gap change | 0 | −1.0431e−7 | +1.0431e−7 |
| Mean absolute unrelated gap change | 0 | 0.322830 | 0.082947 |

Native BF16 intact accuracy is 516/1,024 for the original, 488/1,024 for task,
and 487/1,024 for semantic. Neither precision yielded a correct affected flip.
Zeroed written memory reproduces base scores exactly, including after training.
All step-zero controls also reproduce base scores exactly. Writer gradients after
step 1 and checkpoint reload identity were verified.

The semantic objective reduced unrelated gap disturbance relative to task, but
did not deliver useful donor direction. Residual size is not the remaining
explanation by itself: semantic intact residuals averaged L2 0.996314, near the
preregistered cap, and unrelated residuals averaged 0.985430. A small two-choice
gap does not mean the whole residual is small or generally harmless.

## Post-hoc failure-mode inspection — no new fitting

For a fixed world, reversing the question should reverse the required donor
direction. Instead, semantic twin-minus-intact yes/no gap changes have the same
sign for q0 and its reverse q1 in **64/64 worlds**. Their mean absolute difference
is 1.6391e−6; the mean range across all eight questions is 4.5598e−6.
The 64 positive / 64 negative donor effects therefore reflect near-cancellation
between reversed questions, not 128 independent signs.

Mean absolute affected and unaffected differences are almost identical:
0.006974384 and 0.006974414. Even that average is dominated by one world:
world 22 has q0 absolute effect 0.418745 and contributes 93.8% of total absolute
q0 effect. The median absolute q0 effect is only 0.000281334.

The supported output-level description is **memory-dependent, nearly
query-insensitive bias**, not relation-conditioned answer transport. These
outputs do not identify whether the loss occurs in slot writing, attention,
projection, normalization, or optimization. In particular, they do not yet
establish LayerNorm or slot collapse as the cause.

## Four-turn generation, with the original model present

The old q0→q2→q0→q2 schedule is retained: affected and unaffected questions
alternate. Two worlds × two sides, fixed original-answer history versus each
branch's generated-answer history, greedy plus matched seeds 211–213 at T=0.7,
and both readouts give 896 trajectories. The new 14-condition grid consists of
two original-base controls plus six memory controls for each trained bridge;
it is not the old full/boundary/non-boundary condition grid.

Intact/twin trajectories are identical in **all eight model/history/readout
panels: 0/16 changed**, with zero affected answer changes or correct donor flips.
Sixteen pairs here are repeated regimes/sides from two worlds, not n=16 worlds.
Actual token prefixes are recomputed (identical prefixes may reuse frozen
features); there is no KV-cache intervention.

An example fixed in advance by scenario order: `w0_s0`, FP32, greedy, free
history. Original answers are `yes yes yes yes`; twin answers would be
`no yes no yes`.

| Condition | Four generated answers |
| --- | --- |
| Original inline facts | yes / yes / yes / yes |
| Original query-only | yes / no / yes / no |
| Task intact | no / yes / no / yes |
| Semantic intact | no / yes / no / yes |
| Semantic twin | no / yes / no / yes |

The latter sequence happens to match twin labels, but its identical appearance
with intact memory is precisely why it is **not** donor-directed evidence.
These are constrained no/yes generations, not natural-language conversation.

## Historical control correction and storage

[BASE_CONTROL_CORRECTION.md](BASE_CONTROL_CORRECTION.md) records an independent
CPU comparison: both old trained backbones differ from the pinned original in
234 of 291 tensors. The earlier harness's two `base` lanes used the task-trained
backbone with workspace bypassed, not original Mistral. Old raw artifacts remain
unchanged; their negative semantic result is not promoted or erased.
[BASE_IDENTITY_RECEIPT.json](BASE_IDENTITY_RECEIPT.json) binds the comparison and
all shard hashes.

Contrary to the initial assumption, old V14 checkpoints remain on Furnace.
This run deleted no weights and made no base-model copies. It saved only step
128 and step 256 for each new condition: four files, **67,243,220 bytes total**,
under `runs/v14/precision_bridge_20261009/`. They remain on Furnace, not GitHub.
The source, plans, raw metrics, and receipts are the GitHub-managed record.

## Reproduction and next gate

Source commit: `6381353` (full identity in `raw/STARTED.json`). The immutable plan
is `configs/v14/PRECISION_BRIDGE_PLAN.json`; raw reports and the compact
`SUMMARY.json` are hash-indexed by `ARTIFACT_INDEX.json`. Run this directory's
`verify.py` for the portable evidence checks, adding `--verify-weights` on Furnace
to hash the four saved bridge bodies. Old sealed source files were not edited.
The post-hoc output diagnostics are reproduced by
`scripts/summarize_v14_precision_bridge.py` (fresh output only).

The next minimal gate is **not longer conversation or another learning-rate
sweep**. With these saved bridges fixed, trace the same memory with positive and
reversed questions through projected query → attention weights / slot-value
diversity → residual → LM-head direction. Identify the first point where query
dependence disappears, then change only that component and repeat the matched
controls. Twin contexts also change sentence serialization, so any later positive
effect needs a same-world reserialization control before a single-fact causal
claim.
