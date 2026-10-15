# Next V18 factor: text-bound ordered operand selection

2026-10-15. **PROPOSAL ONLY — not implemented, qualified or launched.**
This follows the [window/reference ownership](WINDOW_REFERENCE.md) prerequisite.
It is not selected for the current CPU/CUDA recovery run.

## Why this factor

The [V16 population results](../../provenance/pilots/v16_population_diagnostics_20261015/RESULTS.md)
show nonzero centered-slot variation, substantial remaining norm budget,
near-uniform selection, mixed intended donor direction and 0/256 donor flips.
They motivate testing query selection; they do not prove that written slots
already encode a usable relation. Do not increase gain or add a same-purpose
loss and call that evidence of content binding.

One minimal candidate is an ordered, inference-text-derived operand query:
`q_relation = mean(h_subject_tokens) - mean(h_object_tokens)`. Bind both spans
from a supported question grammar and exact tokenizer offsets. Labels, donor
IDs, world metadata and diagnostic factor names are not inputs. Ambiguous or
unsupported binding rejects; the grammar is not a general-language competence
claim. The normalized hidden sequence comes from the architecture adapter.

## Keep the intervention narrow

Keep the common route's final-position query unchanged. Only the interaction
query changes in a new additive reader/pipeline: the current
[`parts`](../../src/latent_workspace_ft_v10/v16_slot_contrast.py) computes common
and interaction from one input, so passing the new query to it wholesale would
also alter the common output and remaining budget. Preserve writer, slot
centering, projection/normalization, attention, output map, cap, initialization,
optimizer and update budget. No additional trainable parameters are required
by this query proposal. Any actual compute/transfer mismatch must be reported.

Bind operand indices to the original inference prefix and retain them through
teacher-forced completion and generation. The native output head still reads
its original final-position state. Freeze pooling dtype/device/order explicitly;
do not change CPU/GPU reduction geometry as an incidental optimization. A new
reader descriptor and owner qualification are necessary: the exact-class V18
ownership guard intentionally does not admit this proposal today.

Controls: existing final-state interaction; ordered operand difference;
symmetric operand mean using the same tokens and parameters. Retain common-only
and raw-slot references. Contextual token representations depend on word order,
so neither exact negation under question reversal nor end-to-end invariance of
the symmetric control is assumed. Keep preservation supervision off in this
first mechanism comparison; it is a separate experimental axis.

## Tiny reciprocal-binding assay before 7B

Freeze train/dev/held-out world and entity-renaming splits, several seeds, loss
weights and the update/compute budget before execution. Use three-entity worlds,
twins swapping one adjacent pair, both reciprocal questions, and unaffected
third-entity questions. First use controlled slot features to test whether the
selection primitive can learn the relation; then repeat with the actual writer.
Success on controlled slots alone does not qualify the writer or a real model.

Track native donor-directed margins, reciprocal correctness and unaffected
drift together, with identical-memory, zero/equal-slot, unrelated-memory and
consistent slot/mask-permutation controls. Stronger query gradients or separated
attention alone cannot pass. Freeze numerical pass criteria before results;
no current diagnostic score is a newly untouched test set.

Avoid a misleading alternative: using uncentered keys but centered values,
with bias-free key projection, only shifts all valid attention logits by a
shared offset in exact arithmetic and leaves softmax unchanged. Finite-precision
differences are not a new relational access path. Temperature/gain changes or
opposite-query subtraction can also amplify an existing weak response without
demonstrating better binding.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. This
proposal neither admits V18 full updates nor changes the conditional HF gates.
