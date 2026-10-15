# Historical V14 base-control identity correction

2026-10-09. This additive correction does not alter the sealed September 13
multi-turn report, its hashes, or its negative semantic conclusions.

## What the historical labels actually mean

In `scripts/run_v14_multiturn_choice.py`, `_process_checkpoint` loads the task
checkpoint through `engine.load_bundle`. When `model_id == "task"`, it also
admits the conditions labelled `base_query_only` and `base_inline`; those
conditions hard-bypass the workspace on that same loaded backbone. The script
does not load an independent pinned-original model for those two conditions.

The task checkpoint used full-base optimization for updates 5–8 after four
frozen-base updates. Its manifest field `base_storage: "pretrained"` means a
saved `save_pretrained` model bundle, not proof of equality to the original
Hugging Face snapshot. Optimizer-coverage success also does not establish such
equality.

Read-only CPU inspection on October 9 compared all 291 saved tensors from each
final checkpoint with the pinned original Mistral snapshot. Both task and
semantic had 234 unequal tensors and 57 equal tensors; all compared tensors
were BF16 on both sides. `lm_head.weight`, embeddings, and final
`model.norm.weight` were among the unequal tensors. These are counts of tensors
containing at least one difference, not counts or fractions of changed scalar
weights, nor a measurement of behavioral impact.

Consequently the earlier two conditions must be interpreted as
**task-trained backbone controls with workspace hard-bypassed**, not original
model controls. Their measured trajectories remain observations of that loaded
model. This correction neither invalidates the recorded intact/twin comparisons
within each learned checkpoint nor supplies evidence for semantic specificity;
`winner: none` remains unchanged.

## Identities and reproducible receipt

The pinned original is `mistralai/Mistral-7B-Instruct-v0.3`, revision
`c170c708c41dac9275d15a8fff4eca08d52bab71`. Saved bases are under
`runs/v14/boundary_training/{task,semantic}_seed47_step8/final/base_model`.
The checkpoint manifest and workspace hashes matched the historical frozen
plan during inspection. The original and both trained final bases are still
present on Furnace; no weights were deleted by this audit.

`scripts/audit_v14_base_identity.py` reproduces the comparison with CPU
`safe_open` and `torch.equal`, without casting or tolerances. It verifies the
historical source, manifests, workspace/config identities, and pinned-original
shard content hashes; binds all compared shard hashes; and rehashes the input
files afterward. Its required `--output` argument is fresh-only. The durable
execution receipt, once run, is `BASE_IDENTITY_RECEIPT.json` in this directory;
the existence of this note alone does not certify that script execution.

The new precision-bridge comparison must independently load the pinned original
for original-model lanes and keep those labels distinct from any trained
hard-bypass lanes. It must not silently substitute a trained checkpoint for the
original, even when many weights are unchanged.
