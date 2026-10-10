# V15: end-to-end native workspace learner

2026-10-10. Prospective implementation and bounded qualification contract.
Ryō authorized proceeding from reader validation through the full-update learner.
The preceding diagnostics are separated in PR #9; no historical file, gate or
versioned result is renamed. The frozen-native milestone is conceptually V14.5.

## Definition and milestones

V15 is the explicit, resumable full-update path connecting question features,
query-independent memory writing, question/value interaction, native residual
composition and the native full-vocabulary LM head. Normalization and model
boundaries remain architecture-owned. The initial architecture under qualification is
pinned Mistral-7B-Instruct-v0.3; this is not a generic-model qualification.

1. **Internal difference:** already observed, but not proof that the state holds
   decodable answers or useful semantic content.
2. **Usable content binding:** jointly correct native donor direction on both
   reciprocal questions, stability controls and actual generated behavior.
   Still unestablished. Larger gradients, interaction norms or an auxiliary
   decoder fitted to exposed answers cannot substitute for this milestone.
3. **Full-update engineering:** complete balanced windows, live current-theta
   features, explicit parameter/optimizer ownership, visible update accounting,
   checkpoint/RNG ownership and exact next-update resume. Separate from (2).
4. **FT-beta quality:** fresh matched original-base non-regression and useful
   behavior, not the exposed-set mechanics used here. Not claimed by this pilot.

The question-modulated reader remains an explicitly named experimental mechanism,
not a chosen semantic winner. It has the same trainable tensors as the legacy
reader. Do not add a second redundant donor loss or delete the common output
direction. Keep old losses, cap one, final query, native renderer and exact
answer-token targets. No labels, factual side or diagnostic four-corner factors
enter an inference forward. The current-base unrelated target is stop-gradient
and moving in the full arm; it is not an original-base preservation objective.

## Bounded execution sequence

The [machine-readable plan](../../configs/v15/NATIVE_LEARNER_PLAN.json) fixes:

- **Reader study:** fresh seed-47 legacy and modulated readers, eight bridge-only
  AdamW updates each. Same complete 16-pair windows and unchanged reductions
  (32 answer/EOS, 4 affected, 12 unaffected, 16 unrelated, 48 residual). Full
  diagnostics at steps 0/1/8; factor controls at 0/8. Greedy behavior at 0/8,
  five conditions × four exposed queries × two steps × two readers = 80 sequences,
  at most 16 generated tokens each. No judges or sampling.
- **Full engineering pair:** a fresh modulated frozen control and fresh modulated
  full-update candidate, two updates each, with the same bridge AdamW and per-family
  complete-window clipping. The full candidate additionally updates every physical
  base parameter with CPU FP32-master Adafactor. Compare at 0/1/2 and greedy
  behavior at 0/2 (another 80 sequences total). The frozen control also uses the
  same CPU accumulation order, so historical frozen runs are not substituted.
- Save step-1 and step-2 full states; reload step 1 and replay the complete second
  window once. Require exact native, master, optimizer and RNG state equality to
  uninterrupted step 2, with separately stored replay receipts. This is **three
  executed full backward/update windows, two distinct progression steps**, not
  three independent training steps. No checkpoint for the replay is saved.
  Apply the same one-window resume replay to the frozen engineering control;
  across both phases this is 20 distinct updates and 22 executed windows.
- Every new output directory is exclusive. A failure preserves partial receipts
  and stops without retry or numeric-tolerance changes. No longer training budget
  follows automatically. Semantic failure does not masquerade as a pass; it may
  coexist with completion of this separately authorized engineering qualification.

Both phases use only the same two exposed training worlds. No fresh holdout
qualification or inference-quality selection is performed. Ordinary pinned base
scores are captured before updates; current-backbone zero parity is checked at
every diagnostic checkpoint and is distinct from original-base preservation.
The reader-only phase may reuse immutable original-base features; both arms of
the full engineering pair recompute current features from token-only inputs.
Inspection must leave global training RNG unchanged. Checkpoints are written
before inspection so uninterrupted and replayed step-2 fingerprints refer to
the same update boundary; the replay does not generate extra sequences.

## CPU ownership and precision

Retain the already-tested native-dtype, same-order CPU gradient accumulation.
Transfer only completed accumulations to optimizers; no step during backward or
partial window. Keep bridge AdamW (LR 1e-4, weight decay .01) unchanged across
arms. Clip bridge and base families independently at one, once per full window;
there is no hidden base-induced change to the bridge's clipping denominator.

For full updates, persist a CPU FP32 master for each physical base parameter,
use Adafactor with explicit LR 2e-7, no first moment, no relative schedule, no
parameter scaling and no base weight decay. Promote completed BF16 gradient
accumulations to FP32 for that optimizer. Copy the resulting master to native
BF16 exactly once after each complete update. This preserves sub-BF16 updates
across steps, not infinite precision or a promise of useful updates. Record
master tensor changes separately from native changed-element counts, especially
normalization weights. This is a new declared precision/optimizer contract, not
claimed equality to historical BF16-only Adafactor runs.

Use the existing CPU accumulator via a new consumption adapter; historical
engine source stays sealed. Completed base gradients need not be restored to
GPU merely for the CPU optimizer. The actual backward still holds native GPU
gradients. CPU/GPU casts and copy completion must precede reuse; no speculative
asynchronous overlap is introduced. Verify tiny-reference accumulation, dual
optimizer ownership, per-family clipping and next-update resume before real use.

Checkpoints store FP32 masters and optimizer/RNG/bridge state; native base weights
are deterministically reconstructed by cast rather than stored redundantly.
Only a payload with its completed hash receipt is resumable. Latest two per
condition are produced directly; no old weights are deleted. Approximate full
checkpoint storage is 27 GiB each / 54 GiB for two, plus compact optimizer and
bridge state. The preflight free disk is about 116 GiB; enforce the 50-GiB free
floor including forecast checkpoint writes. Host admission 100 GiB available,
runtime floor 24 GiB; measure actual staging and save/load peaks.

## Resource and publication gates

Furnace only, isolated committed worktree, no competing GPU clients. Reader:
20-GiB admission, 18-GiB allocator, 4-GiB sampled free floor. Full: 31-GiB
admission, 30.5-GiB allocator, .75-GiB sampled free floor. Two CPU threads,
phase-checked limits of 30 minutes / two hours. Admission is repeated for the
full process; an engineering issue cannot justify interrupting another job.

Preserve complete denominators and literal generations, no first-token rescue.
Keep memory-zero/mean/random/unrelated controls and C/Q/M/I, operator and cap
diagnostics at fixed checkpoints; original and current head axes must be labelled.
Runtime, source and data identities are sealed before dispatch. No judge/API
calls, threshold/rubric changes, provider substitutions, monitoring restarts or
weight deletion. Publish bounded results and PRs only; no merge is authorized.
Old FAIL / winner:none / non-regression unestablished and judge missingness stay.
