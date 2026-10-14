# Selection state and query-policy guard

2026-10-15. **STATE_GUARD_ONLY_NOT_LEARNER_QUALIFIED**.

The additive `SelectionStateBinding(bridge, pipeline)` owns the exact existing
split-query bridge and selection pipeline. It does not add an optimizer, update,
save or restore API. Historical reader guards and checkpoint whitelists remain
unchanged and still reject this bridge.

Unlike the controlled writer fixture, the production profile requires all32
FP32 parameter tensors trainable: writer20, common reader6, interaction6. The
frozen-common26 profile and all-frozen profile are rejected. Current flags are
rechecked on every validation, rather than inferred from saved tensor values.
Canonical meta-device construction consumes no RNG and performs no native-model
forward.

The guard binds the module graph, parameter identities and storage, typed
execution attributes, query mode, pipeline identity and adapter object identity.
It rejects shared/aliased/replaced storage, unowned state, module and parameter
hooks, callbacks, method replacement (including `_validate_queries`), named
query-helper replacement, and grammar substitution. Parameter backward and
post-accumulate hooks were added after independent review; original compiled
grammar objects are bound, not merely their pattern/flag metadata.

The implementation is in
[`v18_selection_state.py`](../../src/latent_workspace_ft_v10/v18_selection_state.py),
with [76 focused tests](../../tests/test_v18_selection_state.py). The combined
operand/query/reader/pipeline/writer/state suite passes 318 local CPU tests.
These are state-policy fixtures, not tiny optimizer/resume qualification or
CUDA/7B qualification. The descriptor states this ceiling explicitly.

## Remaining owner responsibilities

Native adapter internals, native/reader storage separation and base parameter
ownership still belong to a future selection-native owner. Structurally valid
operand spans do not authenticate tokenizer/text/data provenance. The runner
must use the supported binder and preserve the exact rendered-prefix/tokenizer
receipts, rejecting unsupported grammars before a forward.

Next, introduce separate versioned native and complete-window checkpoint formats.
Reuse qualified update arithmetic and V2 reject-before-publication restoration;
do not widen old whitelists or reinterpret an old checkpoint by matching shapes.
Qualify all query policies, FP32/BF16 native dtype, frozen/full base scope and
checkpointing on/off, including exact updates and fresh-process resume.
Future numerical policies require an explicit new binding/version; this guard
does not admit arbitrary subclasses or future centering changes automatically.

The [full-update roadmap](FULL_UPDATE_ROADMAP.md) remains conditional on those
engineering gates and an actual resource probe. No semantic gain, original-base
preservation, V18 FT, export or HF readiness follows from this component alone.
