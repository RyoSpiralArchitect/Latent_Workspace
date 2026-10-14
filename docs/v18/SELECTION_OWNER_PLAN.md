# V18 selection owner: additive engineering plan

2026-10-15. **Native owner implemented; 150/150 local tiny mechanics tests pass.**
The window owner and source-isolated Furnace CPU/CUDA/7B qualification remain
pending. The 150 native-owner tests use same-process reconstruction. A separate
[10-case test](../../tests/test_v18_selection_fresh_process.py) now passes with
20 independent CPU child interpreters: eight ordered-query FP32/BF16 ×
frozen/full × raw/centered cases, plus BF16/full/centered final and symmetric
controls. This is not the entire factorial matrix or CUDA qualification.
The [local engineering record](../../provenance/pilots/v18_selection_owner_local_20261015/README.md)
retains source hashes, process receipts and their offline consistency audit.
The [selection state binding](../../src/latent_workspace_ft_v10/v18_selection_state.py)
remains a guard, not a learner by itself. Historical precision and whitelists
are unchanged; no semantic or base-preservation result follows from these tests.

## Minimal implementation boundary

1. Implemented: [SelectionNativeLearner](../../src/latent_workspace_ft_v10/v18_selection_learner.py), a separately
   versioned successor of [AdapterNativeLearnerV2](../../src/latent_workspace_ft_v10/adapter_native_learner_v2.py).
   Specialize construction, ownership validation, payload format and restore
   preflight, following [SlotContrastNativeLearner](../../src/latent_workspace_ft_v10/slot_contrast_learner.py).
   Construct the exact [SelectionWorkspacePipeline](../../src/latent_workspace_ft_v10/v18_selection_pipeline.py)
   and bind it with `SelectionStateBinding`. Independently expected run policy
   must select interaction mode; a checkpoint may not choose its own policy.
2. Pending: add `v18_selection_window_learner.py` with `V18SelectionWindowLearner`, using
   a new envelope format and the selection owner. Retain the ordered schedule,
   cursor, complete-window denominators and supplied-reference-bank semantics
   of [V18WindowLearner](../../src/latent_workspace_ft_v10/v18_window_learner.py).
   Check the complete outer envelope and inner state before publication.

Reuse the unchanged [V15 accumulation/update](../../src/latent_workspace_ft_v10/v15_native_learner.py),
native-dtype CPU gradient accumulation, FP32 CPU masters, Adafactor/AdamW,
V2 independent snapshots and bridge → native casts → RNG restore publication.
Reuse [WindowReductionSpec/reduced_pair_objective](../../src/latent_workspace_ft_v10/v18_window_objective.py);
do not add losses, change centering or introduce a precision workaround here.

The old native owner constructs `AdaptedWorkspacePipeline` and validates its
`_reader`; the selection pipeline has no such member. The old window guard
rejects the new reader, and its dispatch does not select a selection owner.
These are explicit integration blockers, not reasons to broaden old whitelists.
Native `save()` reports the new payload format correctly. The future window
owner must not inherit an outer `save()` receipt hard-coded to an old `FORMAT`.

Keep common/native final-state policy separate from interaction selection.
The old nested objective admits `query_mode="final"`; bind the interaction's
`final`, `ordered_difference` or `symmetric_mean` policy separately rather than
silently reinterpreting that objective field. Preserve historical prototype
descriptors; put new ownership qualification in the new versioned envelope.

## Ownership and input boundaries

Production owns all **32 FP32 bridge tensors**: writer 20/common 6/interaction 6.
Full update additionally owns all 291 pinned native tensors and their CPU masters;
frozen mode owns no native masters. Reject the toy frozen-common 26 profile,
shared storage, hooks, replaced methods, flags and policy changes. The native
binding still separately owns model preparation, context extraction and readout.
The new version admits only materialized contiguous offset-zero owned tensors,
records exact strides, and checks live parameter/master/buffer storage identity.
Restore requires an independent selection policy matching its reserved run key;
saved tensor layouts are checked before clones can normalize them.

The runner must bind `OperandSpan` from the actual inference text/tokenizer and
seal fact-only context identities. Structural guards do not authenticate forged
spans or prove arbitrary caller features are label-independent. Full-update
context features remain live: no detached context/memory cache across updates.
The writer receives facts/masks, never question, answer or donor-role inputs.

## Qualification before native FT

The [150 native-owner cases](../../tests/test_v18_selection_learner.py) pass locally
with Ruff clean, including malformed-restore nonmutation and accepted-payload
independence. An earlier development run had 138 passes and one brittle source-
inspection assertion failure after live file edits; a delegated-restore spy
replaced that assertion before the final stable-source run. Continue qualification
without rewriting [V16 owner tests](../../tests/test_slot_contrast_learner.py),
[V2 restore tests](../../tests/test_adapter_native_learner_v2.py) or
[window tests](../../tests/test_v18_window_learner.py):

- Final/final matches V16 losses, ordered gradient spills, masters, optimizer,
  native/bridge updates and RNG exactly, extending [pipeline parity](../../tests/test_v18_selection_pipeline.py).
- Native tiny raw/centered × final/ordered/symmetric mechanics pass. The pending
  window owner must also qualify complete unequal-stratum windows,
  FP32/BF16, frozen/full and checkpointing on/off; serialized next-update replay.
- **Fresh-process resume** now passes for the ten local CPU cases above:
  producer/resumer match exact dependency origins/versions and thread policy,
  next-window complete receipts, state and RNG draws. The saved bytes remain
  unchanged. An initial unqualified system-interpreter development attempt
  stopped at the preparation-version guard before updating; the qualified
  repository interpreter was used for the passing run. The runtime guard was
  not weakened. Source-isolated Furnace/CUDA and the future window envelope
  still need their own fresh-process qualification.
- Native-owner rehashed malformed policy, partitions, native preparation,
  optimizer IDs/moments, unknown fields and old formats reject before changing
  target values, versions, pointers, guards or process RNG. Schedule/bank and
  outer-envelope rejection remain required for the pending window owner.
- Writer/common/interaction gradients are present and finite. Zero upstream
  gradients at zero-initialized output projections are expected; test warmup
  separately instead of confusing zero gradients with missing ownership.

The [ABBA flag intervention](../../provenance/pilots/v18_replay_flags_20261015/README.md)
shows that no-grad alone does not fix execution identity: changing parameter
trainability changed logits with unchanged weights. Keep and record original
flags, module modes, layouts and runtime settings during diagnostics/resume.
This finding does not identify a particular backend kernel or repair centering.

## Static one-arm storage forecast, not resource qualification

For unchanged pinned Mistral H4096 / workspace 256 / slots 4, the native schema in
[V16 context](../../provenance/pilots/v16_full_comparison_20261014/raw/slot_contrast/CONTEXT.json)
contains 7,248,023,552 parameters/291 tensors: FP32 masters alone use
**28,992,094,208 bytes**. The existing [writer](../../src/latent_workspace_ft_v10/workspace_core.py)
and [selection reader](../../src/latent_workspace_ft_v10/v18_selection_reader.py)
give 1,840,384 writer + 2,359,808 common + 2,359,808 interaction parameters,
**6,560,000 total**. Selection changes query routing, not these shapes.

The matched [V16 checkpoint](../../provenance/pilots/v16_full_comparison_20261014/raw/slot_contrast/CHECKPOINT_step1.json)
is 29,083,160,804 bytes (**27.085804 GiB**); two are 54.171608 GiB before new
envelope/reference/receipt additions. Retain the conservative 64-GiB single-arm
durable-output forecast plus 50-GiB free floor: **114 GiB**. Three arms require
**242 GiB**, not 114 GiB. These are planning estimates, not a frozen V18 budget.
Writing a third full checkpoint before rotating the oldest adds about 27.086 GiB
transiently; reserve this separately (a 32-GiB allowance makes one arm 146 GiB
including the floor). Large reference banks or export copies require extra space.

Re-measure GPU/host peaks with actual context lengths and retained graphs; equal
parameter counts do not qualify VRAM. Owner engineering and a bounded native
no-update/backward probe can proceed alongside the [controlled-writer gates](ACTUAL_WRITER_TRANSITION.md).
Neither substitutes for semantic evidence, base non-regression or export parity.
Old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.
