# V14 boundary-training and free-form diagnostic — 2026-09-07

The frozen task/semantic training comparison and the subsequent 192-generation
diagnostic completed on the Furnace RTX 5090. The scientific disposition remains
**NO_WINNER_NO_PROMOTION**. Neither learned cell passed the grouped F1–F5 gates,
and neither changed a single first answer under intact-to-twin memory exchange.

There is nevertheless a useful mechanistic trace: the semantic cell changed the
later continuation in 12/32 intact-to-twin pairs, versus 4/32 for the task cell.
That trace is side-sensitive but not yet task-aligned. It must not be promoted to
semantic memory use because donor-directed first-answer flips stayed at zero,
unaffected continuations also changed, and the largest first-step chosen-token
probability displacement in the semantic cell occurred on unaffected queries.

## Frozen protocol

- Pinned `mistralai/Mistral-7B-Instruct-v0.3` revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- One matched task cell and one semantic-objective cell, each trained for eight
  updates at the layer-16 deferred boundary. No training occurred in the
  generation run.
- Eight fixed cases: four affected and four unaffected, drawn from two world
  families and both counterfactual sides.
- Greedy plus three common-random-number samples (`temperature=0.7`, `top_p=0.9`).
- Base lanes: inline facts and query-only. Learned lanes: deferred intact memory
  and counterfactual-twin memory.
- Sixteen new tokens maximum, producing 192 continuations in total.
- No K/V cache. Every token used full-prefix recomputation, and the learned
  workspace memory was read again at every generation step.
- Raw symmetric-instruction prompts, no chat template, no added BOS/EOS.

## First-answer comparison

Every continuation began with a valid `no` or `yes` token.

| Model / lane | Affected | Unaffected | All |
| --- | ---: | ---: | ---: |
| Base inline | 11/16 (0.6875) | 12/16 (0.75) | 23/32 (0.71875) |
| Base query-only | 8/16 (0.50) | 12/16 (0.75) | 20/32 (0.625) |
| Task deferred intact | 8/16 (0.50) | 8/16 (0.50) | 16/32 (0.50) |
| Task deferred twin, donor target | 8/16 (0.50) | 8/16 (0.50) | 16/32 (0.50) |
| Semantic deferred intact | 8/16 (0.50) | 8/16 (0.50) | 16/32 (0.50) |
| Semantic deferred twin, donor target | 8/16 (0.50) | 8/16 (0.50) | 16/32 (0.50) |

The base inline lane gained 3/16 affected answers over query-only without losing
an unaffected answer on this deliberately small qualitative slice. Task and
semantic produced identical first choices on all 64 matched rows. These counts
cross the same eight cases with four generation regimes; they are not 32 or 64
independent cases.

## Delayed continuation divergence

| Cell | First-answer changes | Affected full-sequence changes | Unaffected full-sequence changes | Total |
| --- | ---: | ---: | ---: | ---: |
| Task | 0/32 | 0/16 | 4/16 | 4/32 |
| Semantic | 0/32 | 8/16 | 4/16 | 12/32 |

Semantic affected differences appeared only under sampling: 4/4 for seed 101,
2/4 for seed 102, and 2/4 for seed 103. The semantic greedy lane instead changed
2/4 unaffected continuations. The earliest semantic divergence was token four;
no pair diverged at the supervised first-answer token.

For example, one semantic affected pair kept the same first answer (`no`) but
then continued as either “The number of moons of Eris…” or “The order of the
planets…”, depending on which twin memory was read. A greedy unaffected pair
also kept `no` while switching its later continuation. These are trajectory
bifurcations, not donor-directed answer changes.

The route was mechanically active. Both cells had a first-step gate mean of
`0.11767578125`; first-step read norms were 1.0137–1.0273 for task and
1.0474–1.0624 for semantic. Yet the absolute intact-to-twin displacement in the
shared chosen first-token log probability was poorly placed:

| Cell | Affected mean | Unaffected mean |
| --- | ---: | ---: |
| Task | 0.002428 | 0.000790 |
| Semantic | 0.000170 | 0.031859 |

This is not a donor margin, and each partition has only four unique cases. It is
still a useful warning: the semantic objective made the route more visible in
later text without aligning the first decision, while its largest immediate
probability movement was on the queries meant to remain stable.

## The no-cache control changes the interpretation

All delayed differences happened with `use_cache=False`. They therefore cannot
be evidence that a semantic perturbation accumulated in native K/V history.
Repeated workspace reads at longer prefixes can move a later token across a
decision boundary; after that first differing token, ordinary autoregressive
text feedback amplifies the branch. A future cached run must retain this exact
full-recompute lane, otherwise late divergence will be incorrectly attributed
to K/V-mediated recurrence.

This is the most useful result of the generation harness: delayed divergence is
real and reproducible, but is not by itself diagnostic of where recurrence
lives.

## Renderer hand-feel

Only 15/192 continuations stopped after the requested one-word choice; 177 hit
the 16-token cap and often continued with explanations or another synthetic
question. The first token remains a valid categorical instrument, but this raw
completion protocol is not a conversational-quality assay. A later human-facing
chat lane should be kept separate, first qualify the pinned base chat template,
and use an explicit answer stop rule.

## Next smallest gate

Before increasing model size or training length:

1. Add an answer-boundary microscope: record both choice logits, signed donor
   margin, the injected residual's projection onto the `yes`–`no` unembedding
   direction, pre/post RMSNorm state, native-cast visibility, and affected versus
   unaffected allocation.
2. With identical teacher-forced tokens, compare one-shot read, repeated
   no-cache read, one-shot K/V carry, and repeated-read K/V carry. This separates
   workspace recurrence, cache persistence, and token-feedback bifurcation.
3. Admit longer training only if affected donor margin moves in the correct
   direction while unaffected stability holds. Admit natural cached generation
   only if its increment over the no-cache control is directionally specific.

This cut targets the observed wall: the carrier exists and can perturb future
text, but the layer-16 bridge does not place semantic work onto the first answer
boundary.

## Evidence and verification

- `SUMMARY.json` is the compact, machine-readable interpretation.
- `ARTIFACT_INDEX.json` binds the copied training, grouped comparison, and full
  generation receipts.
- `raw/report.json` contains all 192 prompts, token IDs, continuations, chosen
  token log probabilities, gate values, and read norms.
- `verify.py` rechecks hashes, source identity, predecessor linkage, checkpoint
  identities, first-token scores, and trajectory counts without loading Mistral.

Run:

```bash
python3 provenance/pilots/v14_boundary_chat_20260907/verify.py
```

The raw report hash is
`fa104ca3ffc9a16e477a26f42551b5b74ff5955ffe1c01fe8989d454cb35a1f0`.
No checkpoint was selected or promoted, no weights were modified or deleted,
and the retained per-condition checkpoints remain the latest and immediately
previous scheduled checkpoints plus the final bundle.
