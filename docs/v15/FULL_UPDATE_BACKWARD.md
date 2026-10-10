# V15 full-update native contracts and no-step backward probe

2026-10-10 · prospective engineering protocol, units 1–2 only.

Ryō authorized the proposed progression from the frozen-base native milestone
(conceptually V14.5) toward full-update V15. This unit implements separate live
contracts and tests a real-7B backward/CPU-accumulation window. It **does not**
construct an optimizer, update model weights, generate text, call a judge,
change an old threshold, delete weights or qualify a winning learner.
Historical `v15_5` paths and results are unchanged.

## Implementation boundary

[v15_full_update.py](../../src/latent_workspace_ft_v10/v15_full_update.py) adds:

- A trainable-head subclass inheriting the exact existing native forward,
  full-sequence/full-vocabulary head and dtype composition. The frozen class
  still rejects trainable heads; the new class rejects a frozen head.
- An explicitly Mistral live feature provider. Every call recomputes the current
  query/completion or boundary-16 context. Only tokens may be reused; no hidden
  tensors are cached or detached. Native Mistral layers and RMSNorm retain their
  ownership. Zero attention dropout is required for this parity contract.
- Separate answer/EOS supervision accepting live features. The answer path
  receives no labels; only the checked answer-conditioned completion does.
- Exact full-base/bridge parameter ownership checks, deduplicating physical
  aliases and rejecting frozen, omitted, duplicated or cross-owned parameters.

[Tests](../../tests/test_v15_full_update.py) cover FP32/BF16 native zero and
nonzero readout equality, exact zero-path base gradients with and without
checkpointing, current-base versus original-base distinction after a tiny
synthetic parameter mutation, live feature recomputation, all-layer gradient
reachability, upstream zero-initialization, label separation, unchanged complete
loss denominators, old frozen guards and CPU accumulation corruption detection.
Tiny synthetic mutations are tests, not trained Mistral updates.

The [probe](../../scripts/probe_v15_full_update_backward.py) is a diagnostic
runner, not a completed full-update trainer or checkpoint/resume system. It
retains the original paired objective's **32/4/12/16/48** reductions and moving
stop-gradient current-base unrelated-gap target. No original-base preservation
loss is silently added. The latter still needs its own future comparison.

## Frozen real-model scope

The [plan](../../configs/v15/FULL_UPDATE_BACKWARD_PLAN.json) fixes:

- Pinned original Mistral and identities from the
  [native-answer pilot](../../provenance/pilots/v15_5_native_answer_20261010/README.md).
  All 291 physical base tensors / 7,248,023,552 elements are trainable.
- Two diagnostic bridge states: exact fresh seed-47 initialization and the
  retained answer-only step-8 checkpoint. The latter is **not** a new warm-start
  training arm. All before/after tensor hashes must remain identical.
- Three exposed pairs in order: `(world 0, query 0)`, `(0,1)`, `(0,2)`.
  The first two are affected reciprocal questions; the third is unaffected.
  This is a partial three-pair window, **not the full 16-pair objective**.
- Final reader, cap 1.0, answer CE, EOS coefficient 0, both completion forwards
  still evaluated, unchanged donor/stability/unrelated/residual terms.
- Non-reentrant gradient checkpointing, no KV cache, native BF16 base and FP32
  bridge, existing `cpu_accumulate` after each pair. No step-in-backward.
- Observe intermediate gradient routes: normalized query/completion, context
  into writer, and query into reader. Route hooks store only scalar diagnostics,
  not the live graphs. Zero upstream workspace gradients at initial zero output
  projection are expected, not proof of a broken base gradient path.
- Independently clone each current gradient to CPU and add in declared parameter
  dtype and pair order. Compare every restored gradient exactly against that
  reference. This verifies the tested CPU transport/order, **not GPU-add parity**,
  optimizer correctness, a 16-pair window or pure-native B/F1/O3 equivalence.

Before backward, each selected prefix must have exact ordinary/shared full-logit
and written-zero parity. Its two intact/twin native choice score vectors must
also equal the corresponding historical record. Full-base gradient coverage is
checked per pair; all observations and absent/zero bridge gradients are retained.
No positive accuracy or semantic criterion is inferred from nonzero gradients.

## Admission, stopping and receipts

Furnace must have no other GPU compute client and at least **31 GiB** free.
The Torch allocator cap is **30.5 GiB**; sampled free GPU memory must stay at least
**0.75 GiB**. Host available memory must be at least **80 GiB** on admission and
**48 GiB** at checked phases. Disk free must remain **50 GiB**; the phase-checked
wall-time limit is **900 seconds**; CPU compute threads are **two**. These are
new prospective full-backward limits, not amendments to the old 18-GiB pilot.
The time/free-memory checks are at phase boundaries, not continuous guarantees.

The separate CPU reference may use about one gradient volume in addition to
the existing accumulator and staging buffers. No optimizer/master-weight state
or checkpoint save is measured. The old 29.6–29.8-GiB full-update peak is a
precedent, not a fit promise for this multi-forward graph.

Freeze the new source commit and complete source/data hashes before execution.
Use an isolated checkout, exclusive output creation, STARTED/BASE_IDENTITY,
early parity/forward receipts, per-pair gradients/route/spill receipts, per-state
restore checks and a terminal REPORT or FAILED receipt. Pull all outputs.
A failure stops the run without retries, policy changes, further states, training
or interference with another job. Preserve partial observations and missingness;
on failure, attempt unchanged-weight hashing when the runtime permits it.

## After this unit

Mechanical success would permit designing an authorized one-update/resume audit;
it is not automatic permission to launch one. A fresh frozen/full comparison
must match the bridge optimizer: switching to Adafactor requires a fresh frozen
Adafactor control, not only the historical AdamW result. Keep EOS and reader
redesign as separate factors. Written-zero identity against current `theta_t`
does not establish capability preservation against pinned original `theta_0`.

The [FT-beta floor](../v14/FT_BETA_IMPROVEMENT_PLAN.md) remains separate, and the
old expression gate remains FAIL, `winner: none`, with non-regression unestablished.
No PR, merge or GitHub push is part of this execution unit. Source/results may
be committed locally; the judge heartbeat remains paused.
