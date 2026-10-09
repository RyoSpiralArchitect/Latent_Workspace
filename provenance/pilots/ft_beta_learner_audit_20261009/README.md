# FT-beta learner audit: native controls, reciprocal gradients, and resource gate

2026-10-09 · **COMPLETED CPU TRAIN-ONLY DIAGNOSTIC / NOT A LEARNER UPDATE**.

This implements only the requested inspection steps 1–2. No optimizer was
constructed, no parameter was updated, no new response bank or judge call was
made, and no checkpoint was deleted. The next learner modification is **not
implemented or authorized by this receipt**.

Source freeze: `434af9818092966ffe58b89a841bad15e99cab6f`.
[Runner](../../../scripts/run_ft_beta_learner_audit.py),
[gradient helper](../../../src/latent_workspace_ft_v10/learner_gradient_audit.py),
[execution report](raw/REPORT.json), [feature/native gates](raw/FEATURES.json),
and [resource observation](RESOURCE_SNAPSHOT.json).
The [prior improvement plan](../../../docs/v14/FT_BETA_IMPROVEMENT_PLAN.md)
remains a proposal, not an FT-beta qualification.

## Scope and controls

The independently loaded original is `mistralai/Mistral-7B-Instruct-v0.3`,
revision `c170c708c41dac9275d15a8fff4eca08d52bab71`. Its full tensor-state SHA-256
matches the historical pinned base and matches before/after this run:
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.

- Furnace **CPU only**, BF16 frozen decoder and FP32 bridge; CUDA was hidden and
  never initialized. Torch 2.13.0+cu132 and Transformers 5.15.0 were retained.
- First **two already exposed training worlds**, eight queries each. This is
  16 world/query rows (four affected, 12 unaffected), not 16 independent worlds.
- Four states: zero-initialized legacy, legacy task step256, legacy semantic
  step256, and centered semantic step256. Retained checkpoint bytes and tensor
  states were checked against the historical receipts; nothing was retrained.
- The gradient batch groups reciprocal queries together. It is an intentionally
  balanced diagnostic batch, **not a replay of the old shuffled training schedule**.
- 139.060 seconds elapsed; peak process RSS **14.916 GiB**. The complete frozen
  feature cache used **12 MiB**. This says nothing about a CUDA feature cache's
  bitwise identity or a GPU bridge's future peak allocation.

### Step 1: what passed, and what is still missing

All **16 collected query prefixes** passed ordinary-model versus split/native
full-sequence, full-vocabulary logit equality on this CPU runtime. Every state
passed 16 actual written-zero/full-logit checks: **64/64**. Zeroed *written
slots* preserve the slot mask; they are not zeroed source text. The base and
all four bridge states remained unchanged, without accumulated `.grad` values.

Each state also has **256 two-candidate control rows**: two worlds × eight
queries × two sides × eight controls. These cover intact, twin, written-zero,
fixed carrier, historical global-L2 random, unrelated different entities with
the same ranking schema, an unrelated inventory schema, and same-world fact
sentence reordering. Total: **1,024 rows**. Same-world reserialization retains
all original facts and the header, reversing only fact-sentence order.

These controls are diagnostic, not completely matched causal interventions.
Random matching is global **raw-memory** L2; it does not match each normalized
slot, covariance, residual amplitude, or full-vocabulary effects. The inventory
control has different length/content and is not amplitude matched. It must not
be treated as a clean estimate of a schema effect.

Historical seals were reverified separately. Their stronger CUDA/free-generation
receipts are not relabeled as new CPU results: the old answer bank has 32 initial
ordinary/full-head gates and 2,973 centered-zero generation-position checks.
The ten selected legacy changed answers still lack matched **legacy free-text
zero/twin/unrelated controls**; the old bank's corresponding controls were
centered-only. This two-world score panel does not fill that 48-case-regime
generation gap. New full G0/G1 and offload qualification remain incomplete.

## Step 2: observed gradient and query-path geometry

The diagnostic calls the existing objective and actual production reader.
It measures each raw/weighted loss separately with `autograd.grad`, splitting
packed reader Q/K/V weights without changing forward computation. It records
pairwise dot/cosine, missing versus zero gradients, and weighted-term gradient
reconstruction against the total. All four reconstruction receipts passed the
frozen `atol=1e-6, rtol=1e-5` check. This is not bitwise gradient equivalence.

### A. Reciprocal donor signals nearly cancel

For each affected direction, let `g_even` and `g_odd` be the gradient of its
mean donor hinge. The two groups have equal size and remain hinge-active here.
The reported ratio is the combined donor-hinge norm divided by
`0.5 * (norm(g_even) + norm(g_odd))`. A small ratio describes cancellation on
this batch, not a gradient disappearing from the computation graph.

| State / parameter group | Even/odd cosine | Combined / mean individual norm |
|---|---:|---:|
| Initial / up | -0.999999845 | 0.027883% |
| Legacy semantic256 / writer | -0.999999958 | 0.014588% |
| Centered semantic256 / writer | -0.999985859 | 0.271502% |

Sources: [initial gradients](raw/initial_gradients.json),
[legacy semantic gradients](raw/legacy_semantic256_gradients.json),
[centered semantic gradients](raw/centered_semantic256_gradients.json).

At initialization, writer/query/Q/K/V gradients are present but exactly zero:
the zero-initialized `up.weight` blocks them. The up gradient is nonzero.
This is expected topology, not evidence of a detached writer. At retained
semantic checkpoints, all these paths receive nonzero gradients.

For legacy semantic256's writer, the **weighted** local gradient norms are:

| Objective term | Writer gradient L2 |
|---|---:|
| Paired CE | 1.203069e-4 |
| Donor hinge (weight 0.25) | 2.543350e-7 |
| Unrelated gap preservation (weight 0.25) | 6.741046e-2 |

This motivates examining signal balance and query sensitivity. It does **not**
prove that the unrelated term caused training failure: these are final-state
gradients on one balanced batch, not optimizer-history measurements. AdamW
moments, clipping and the shuffled schedule can change actual update behavior.
Do not weaken preservation or raise donor weight merely from this table.

### B. Query differences survive input, then contract strongly

Mean reverse-query relative L2 across 16 pairs (two worlds × two sides × four
reciprocal query pairs), using the production path:

| State | Final normalized query | Projected query | Attention output | Bounded residual |
|---|---:|---:|---:|---:|
| Legacy semantic256 | 0.115211 | 0.018338 | 2.443678e-5 | 2.435564e-6 |
| Centered semantic256 | 0.115211 | 0.041413 | 8.706902e-4 | 2.615117e-5 |

Sources: [legacy reader panel](raw/legacy_semantic256_reader.json),
[centered reader panel](raw/centered_semantic256_reader.json).
This is consistent with weak query dependence at the output, not proof of one
unique bottleneck or a new centered-reader quality win. Relative endpoint
distances are not a Jacobian or layerwise causal attribution.

The existing query is the **final normalized answer-prefix state**, which does
contain contextual information; it is not simply a context-free `Answer:` token.
The same tensor also anchors the frozen base readout (`last_hidden + delta`).
Any later pooled-query comparison must change **only the reader query**, keeping
the base's final-position state unchanged. Changing both would confound the
intervention with base prediction geometry.

### C. Reordering alone is comparable to the tiny twin effect

Mean absolute two-candidate gap change relative to intact, over 32 descriptive
side/query rows (still only two worlds):

| State | Counterfactual twin | Same-world sentence reordering |
|---|---:|---:|
| Legacy semantic256 | 0.000636935 | 0.000627577 |
| Centered semantic256 | 0.000124216 | 0.000289202 |

Sources: [legacy controls](raw/legacy_semantic256_controls.json),
[centered controls](raw/centered_semantic256_controls.json).
The magnitude alone cannot isolate changed facts from serialization sensitivity.
These are absolute, side-duplicated differences, not donor success rates or
independent semantic gains. Free-text behavior has not been tested here.

### Instrumentation repair made before the run

A toy test found that a final-row view passed directly to FP32 `F.linear` could
differ from materialized `query + zero` through GEMM stride/alignment selection.
The new control runner now composes its baseline with `query + zeros_like(query)`,
matching its intervention and historical adapter-zero geometry. Strict equality
was retained; no tolerance was widened. Historical source and votes were not
modified. The gradient runner still uses the original objective computation.

## Resource gate before step 3

Explicit `nvidia-smi memory.free` was **12,540 MiB = 12.246 GiB** before and
after the diagnostic. Another job retained 19,540 MiB. No job was interrupted
or changed. Total minus used is not substituted for the explicit free value.

| Execution route | Bytes / capacity | Meaning |
|---|---:|---|
| Pinned 7B BF16 parameters only | 14,496,047,104 B = **13.5005 GiB** | Exact loaded-parameter floor; cannot fit current free VRAM |
| Old fully resident frozen-base + bridge pilot | **13.7919 GiB** | Historical peak CUDA allocation; excludes other process/context/reserved-memory effects |
| FP32 bridge parameters | **16.0225 MiB** | 4,200,192 parameters |
| Bridge params + grads + FP32 Adam m/v | **64.0898 MiB** | Persistent-state lower bound only |
| Detached-feature bridge-only GPU trial | **2 GiB initial budget** | Planning estimate, not measured or a guarantee; canary must measure allocation/reservation/process usage |
| Fully resident base BF16 params + BF16 grads | **27.0010 GiB** | Full-backbone lower bound before optimizer or activations |
| Above + FP32 Adam moments | **81.0030 GiB** | State-only, no FP32 master copy |
| Above + FP32 master weights | **108.0040 GiB** | Conventional mixed-precision state-only bound |

The exact Mistral count is **7,248,023,552** parameters; each decoder layer has
the byte count retained in [REPORT.json](raw/REPORT.json). Bounds for full-base
updates do not describe a sharded/offloaded/compressed optimizer. Such execution
needs its own separately validated contract, not an assumption that “7B fits”.

The feasible next **bridge-only** route is phased: frozen features on CPU (or a
separately parity-qualified offload extractor), then compact bridge computation
on GPU. The backbone must actually be absent from GPU; the existing runner
keeps it resident and cannot be reused unchanged. An illustrative FP32 context
batch of `3 * 16 * 192 * 4096` elements is **144 MiB**, before writer activations,
workspace, gradients, optimizer scratch and CUDA context. Budget headroom must
also protect the concurrently running job. A 2 GiB cap is a proposed admission
budget to validate, not permission to fill the remaining memory.

CPU-derived features are **not** automatically interchangeable with prior CUDA
features. Before an actual learner comparison, freeze and qualify one execution
contract and match both comparison cells on it. Full-vocabulary evaluation and
free generation still need a separately budgeted backbone execution path.

## Next decision, without implementing it here

The useful next hypothesis is to improve **query-conditioned direction**, not
just residual size. A minimal future comparison keeps the final-position base
readout fixed while testing the reader's query representation on a tiny train-only
reciprocal overfit task. Before doing so, lock its feature/backend contract and
memory budget, retain the unchanged learner, and predeclare base-preservation
checks. This remains step 3, not a completed improvement.

Do not infer a population result from two training worlds or turn selected
judge preferences into training gold. Keep **winner: none**, full free-text
legacy controls **NOT_RUN**, offload parity **NOT_TESTED**, and correctness
non-regression **NOT_ESTABLISHED**. No model-quality qualification is claimed.

## Reproduction

Run the frozen source on an isolated Furnace worktree, with the pinned model
already cached and the historical retained checkpoint root supplied read-only:

```sh
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 nice -n 10 python3 -u \
  scripts/run_ft_beta_learner_audit.py \
  --checkpoint-root /absolute/path/to/historical-checkout \
  --output /absolute/path/to/new-unused-output-directory
```

The output directory must not exist. The runner is frozen to the first two train
worlds; it creates no optimizer and fails closed on identity, zero parity or
gradient reconstruction failure. Model loading uses local files only.

Portable verification, without models or GPU:

```sh
python3 scripts/verify_ft_beta_learner_audit.py --verify
```

[ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) binds the 15 raw JSON artifacts;
[SUMMARY.json](SUMMARY.json) is reconstructed from them.
[VALIDATION.json](VALIDATION.json) checks recorded contracts and raw integrity,
not a second execution of autograd or a portable rehash of absent weight bodies.
The README/resource/test notes are explanatory additions, not part of that raw
index. The resource snapshot is a point-in-time observation, not a reservation.

Validation: **71 selected tests passed locally**; the corresponding 63 execution,
gradient, native/control tests also passed on Furnace CPU at the run freeze.
The eight portable-verifier tests were added afterward and run locally. Targeted
Ruff and diff whitespace checks passed. [TESTS.json](TESTS.json) records these
scopes; there is no GitHub CI result or claim of a full-repository test pass.
