# V15 readout adapters: native ownership and transport localization

Client date: 2026-10-10. This is an **additive, opt-in learner component**.
The historical V15 learner, optimizer/resume format, source seals and FAIL gate
are unchanged. An adapter refactor is not a semantic mechanism win.

## What the last result does and does not locate

The [full-update pilot](../../provenance/pilots/v15_native_learner_20261010/README.md)
establishes real updates and stronger question gradients, but no native donor
flips. There are at least three separate questions:

1. Does the reader produce useful question/content interaction, rather than
   only common response and memory bias? The earlier four-corner audit remains
   the diagnostic for that question; larger gradients alone do not answer it.
2. What survives FP32 composition, native hidden casting, the head computation,
   and native model output transformations? Measure those stages separately.
3. Which reference is preserved? Current-theta zero identity and preservation
   of the pinned original remain distinct; this refactor adds no teacher loss.

## Boundary of the model-independent core

`AdaptedWorkspacePipeline` depends on a `ReadoutAdapter` protocol, not Mistral
attributes, normalizer formulae, selected head rows or a model family switch.
It reuses the exact final/anchored-span reader policy and unmodified bridge.
An inference call receives tokens, written memory, its mask and a bound query
span. Labels enter only the separate answer/EOS CE helper. The completion
prefix is explicitly teacher-forced, never represented as generated evidence.

The adapter invokes the original causal-LM **outer forward**, with no cache,
one complete unpadded prefix, the full sequence and full vocabulary. Its temporary
head pre-hook computes the reader delta from the actual normalized states and
applies the historical FP32-add/native-cast operation at the last position.
The model still owns embeddings, positions, all decoder blocks, its actual
normalizer and every post-head operation. This matters for Gemma2: published
logits include a softcap after the linear head. Calling only `get_output_embeddings`
would omit that operation. RMSNorm and LayerNorm are not reimplemented here.

The HF backend explicitly admits the exact GPT-2, Mistral, OLMo2 and Gemma2
causal-LM classes in Transformers 5.15.0, with FP32/BF16 native linear heads.
That is a small tested layout set, **not universal model support**. Other
frameworks or nonlinear heads require an explicit backend implementing the
protocol and its own qualification. Native normalization is not a replaceable
workspace operator. No pre-normalization intervention is added by this change.

## Same path, explicit exclusions

Training CE, choice evaluation and next-token decoding consume the same returned
model-native logits. The adapter neither registers nor copies model parameters,
and does not freeze the base. Live gradients reach the reader and base when
the owner enables them. Written zero uses the real reader path, not a bypass.

This first backend requires exclusive use of the model instance, ordinary
uncompiled execution, a single materialized device, no offload/quantization
wrappers or pre-existing head hooks, and deterministic dropout. A shared lock
rejects concurrent/recursive adapter calls; direct external calls to the model
must also be excluded by the owner. Hooks are removed on success and failure.
Ambient autocast cannot change the declared native route. Config/parameter
replacement is rejected. Process-local tensor version keys catch ordinary
updates between paired probes; they are **not checkpoint hashes**, nor a defense
against out-of-band `.data` edits. Experiment runners still hash model contents.

There is no KV persistence, batched padding policy, `generate()` integration,
distributed serving or new optimizer/checkpoint state owner. In particular,
the sealed `V15NativeLearner` is not silently migrated. A future complete-window
runner must bind the adapter descriptor in checkpoint metadata and repeat the
matched next-update/resume test before replacing that runner.

## Transport arithmetic, not another loss

For a paired intact/twin intervention at the **same prefix and current weights**,
report candidate-1 minus candidate-0 gap changes at four stages:

| Stage | Measurement | Interpretation ceiling |
|---|---|---|
| Intended residual | FP64 projection of the FP32 delta difference on the current linear head axis | Ideal linear diagnostic, not native logits |
| Applied hidden change | Same projection after FP32 addition/native casting | Separates hidden transport from head arithmetic |
| Raw native head | Gap difference in the actual full-geometry head output | Includes native multiply/accumulate/output rounding |
| Published native output | Gap difference returned by the original model | Includes architecture-owned postprocessing |

Adjacent differences sum to the final gap change. Input-cast residual includes
FP32 addition rounding; the head residual is a combined arithmetic discrepancy,
not identification of a particular kernel's internal accumulator precision.
Full-vocabulary changed counts and greedy-token differences remain separate.
The probe is detached and never supplies an objective, head replacement, donor
label or diagnostic factor to inference. A projected nonzero difference need
not survive; a surviving logit difference need not change a generated token.

## Prospective retained-state audit

[The fixed plan](../../configs/v15/READOUT_ADAPTER_PLAN.json) selects all four
final states from the last pilot: legacy/modulated reader step 8 and frozen/full
modulated step 2. Use the exact retained checkpoint hashes, original pinned
Mistral and all 16 exposed queries per state. Reconstruct full base weights from
the full checkpoint's FP32 masters, without creating an optimizer or stepping.

Each state has 16 queries × intact/twin/written-zero = 48 adapter forwards.
Total: **192 full-logit old/new comparisons, 64 paired transport probes, of
which 16 are affected pairs**. Compare native choices to the historical rows,
and compare zero to ordinary base at current theta. This is no-update replay,
not new learner sequences, held-out correctness evidence or semantic promotion.
No judge requests, threshold changes, weight deletion or retry are permitted.
Any failure receives a terminal error receipt and remains visible.

The next architecture hypothesis is still a separately budgeted common-response
versus query/content-interaction route, **not implemented by this refactor**.
Use the new measurements to decide whether to improve semantic binding first
or add an explicit, separately controlled transport policy. Do not erase the
common route, relax correctness gates, or infer that a higher cap fixes meaning.
