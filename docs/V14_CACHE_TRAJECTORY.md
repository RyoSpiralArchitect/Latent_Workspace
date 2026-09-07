# V14-T — cache-mediated trajectory lane

Current status: **MECHANICAL_CANARY_COMPLETE_AND_PASSED /
SEMANTIC_NOT_ADMITTED**.

This lane asks whether a one-time activation perturbation can be written into a
native decoder K/V cache, persist under fixed teacher-forced tokens, affect K/V
written at later token positions, and be removed or transplanted by replacing
that cache. It does not yet ask whether a learned workspace carries useful
semantic content.

The previous `inline_sidecar` is retained as an important null control: it runs
the base model with `use_cache=False` and composes a residual only at final
logits. With identical forced tokens it cannot write that residual back into
future native K/V. V14-T therefore introduces a separate, model-dependent cache
binding rather than silently changing the old route.

## First bounded canary

One cached Mistral-7B-Instruct-v0.3 instance, one fixed 14-token prefix, five
fixed continuation tokens, middle decoder layer 16, no optimizer, no free
generation. A deterministic random vector (seed 1413) is normalized to unit
RMS and added once immediately before the selected decoder layer's
RMSNorm/self-attention computation. Composition is in FP32 and is cast once to
the native hidden dtype. Its signed RMS amplitude is `+1/16` or `-1/16`;
these are engineering probes, not intact/twin semantic states. The random
direction is not claimed to be exactly orthogonal to the current hidden state.

Every condition receives exactly the same input IDs, positions and attention
mask. The five cells are:

| Cell | Pulse at horizon 0 | Cache used from horizon 1 onward |
| --- | --- | --- |
| A | none | its native cache |
| B | positive | its pulse-written cache |
| C | negative | its pulse-written cache |
| D | positive | replaced by an independent clone of A's matched no-pulse cache |
| E | negative | replaced by an independent clone of A's matched no-pulse cache |

The central descriptive contrast is `(C-B)-(E-D)`. At horizon 0, D/E retain the
same immediate pulse outputs as B/C; replacement only acts on future state.
The canary additionally clones and transplants a complete cache to test that
the receiving continuation reproduces its donor. K-only, V-only and selected-
layer patches are explicitly deferred until the complete-cache operation is
qualified.

Predeclared structural expectations:

- A duplicated from independent cache clones is numerically exact.
- Before layer 16, the current-position K/V is unchanged by the pulse. At or
  above layer 16, at least one current-position K/V tensor changes.
- At the next forced token, a changed newly-written K/V tensor above the pulse
  layer is evidence of cache-mediated propagation. Growth of the stored-cache
  norm alone is not evidence because cache length grows.
- D/E must match A after replacement. A full B-cache transplant must reproduce
  B on the next identical forced token.
- Incremental no-pulse logits are compared with full-history recomputation, but
  this cross-shape numerical comparison is reported separately from exact
  cloned-cache controls and never tuned after observing results.
- The pulse hook must fire exactly once, change only the selected current-token
  hidden state, preserve all input tensors, and leave model parameters and disk
  snapshot payloads unchanged.

The adapter rejects sliding/recurrent/offloaded or unrecognized cache layouts
for this first run. It records Transformers version, architecture, layer/head
dimensions, RoPE/position contract, dtype, per-layer cache shape and content
hash, and every requested/observed pulse property. Requesting SDPA is not proof
of which CUDA kernel executed.

## Metrics and claim boundary

For future admitted semantic directions, an affected pair with original answer
`a` and donor answer `b` uses:

```text
m_t       = z_t[b] - z_t[a]
delta_m_t = m_t[perturbed] - m_t[matched baseline]
```

Signed endpoint and signed trajectory AUC are primary. A ratio such as
`abs(delta_m[t+1]) / (abs(delta_m[t]) + epsilon)` is secondary and becomes
UNKNOWN below a frozen observability floor. It does not estimate a Jacobian
norm. State/K/V displacement and task-aligned margins remain separate.
Changing probe questions also changes the readout, so a primary trajectory uses
one fixed probe on forked state snapshots; probe evaluation must not advance the
main trajectory.

Family bootstrap resamples all horizons, intervention cells and controls from
one original-world family together. Semantic qualification additionally needs
an elicitation-qualified task, an actual checkpoint-derived direction, sham and
equal-norm random directions, irrelevant donor, affected directionality and
unaffected retention. The first random-pulse run cannot satisfy those gates.

Passing this canary supports only **native K/V write, persistence,
replacement/transplant, and later-position propagation for the specified
artificial pulse**. It does not establish semantic amplification, model
capability, a learned R-to-D bridge, necessity, generalization, or a free-chat
effect. A failure is preserved as a model/runtime/interface result and does not
prove the mechanism impossible.

## Stop rule

After one fixed Mistral mechanical run, stop. Do not adjust pulse amplitude,
layer, text or horizon from its outcome; do not open the held-out corpus, train,
sample, or launch a layer sweep. If mechanics pass, the next decision is whether
to qualify the Mistral task interface and then freeze a checkpoint-derived
semantic direction experiment. If mechanics fail, repair the smallest stated
interface/integrity gate under a new source-bound plan.

## Frozen run result — 2026-09-07

The one authorized target-model execution completed on the Furnace RTX 5090
from source commit `0db95e668f9c071529750659e71bbe81eba81f67`. All 18
structural checks, source/plan/snapshot integrity checks, coverage and protocol
checks passed. Runtime was 28.73 seconds and peak Torch allocation was
14,580,253,696 bytes.

At the pulse position, only layers 16–31 changed. At the first later forced
token, the newly written K/V remained exact through layer 16 and changed at
layers 17–31 in both signed branches. Replacing either pulse branch with the
matched base cache erased all future differences exactly. Independent base
replay and complete-B-cache transplant were bit exact, and the stored pulse
position remained hash-exact while later positions were appended.

The random-direction future displacement persisted but generally contracted:
new-position K/V L2 went from 12.18 to 5.50 in the positive branch and 17.06 to
6.08 in the negative branch over horizons 1–5. Aggregate cache L2 grew because
changed positions accumulated; it is not evidence of amplification. The fixed
`no`/`yes` argmax never differed from base.

Semantic qualification is therefore
`NOT_APPLICABLE_NON_SEMANTIC_SCREEN`. No training, held-out access, free
generation, semantic direction, download, weight change, retry or sweep
occurred. The complete receipt and independently replayed metrics are under
`provenance/pilots/v14_cache_trajectory_20260907/`.
