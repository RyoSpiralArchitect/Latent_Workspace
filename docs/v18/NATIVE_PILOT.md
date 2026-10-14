# V18 native selection pilot 01: first real 7B full update

2026-10-15. **FROZEN BEFORE LAUNCH.** Ryō asked to finish the window owner and
the CUDA update/restart checks, then proceed to full FT. Both
[qualifications passed](../../provenance/pilots/v18_selection_window_20261015/README.md).
This is the roadmap's bounded native integration and full-update pilot: the
first real Mistral-7B run of the V18 selection window owner. It is an
engineering and mechanism pilot, not held-out generalization, base-floor
qualification or a release candidate. The old **FAIL / winner:none /
non_regression NOT_ESTABLISHED** is unchanged.

## One condition, matched to V16

Storage permits one retained condition at a time. The trained condition is the
selected factor from the controlled study: **centered (slot-contrast) memory with
the ordered operand-difference interaction query**. Every native Mistral
parameter (7,248,023,552 in 291 tensors) and all 32 writer/common/interaction
bridge tensors are trainable, with FP32 CPU masters, native CPU gradient
accumulation, Adafactor for the base (2e-7) and AdamW for the bridge (1e-4).

Everything else repeats the V16 slot-contrast arm, so that arm is the frozen
comparator: pinned Mistral-7B-Instruct-v0.3 revision and tokenizer, the same two
exposed training worlds × eight questions (4 affected / 12 unaffected per
window), seed 47 after reader construction, context boundary 16, the same
objective weights, two update windows, evaluation at steps 0/1/2 and checkpoints
at steps 1/2. The complete-window reduction gives exactly the historical
32/4/12/16/48 denominators. No reference bank or preservation loss is added.

## Three fresh processes, in order, stopping at the first failure

1. **Parity probe** (`final` interaction query, one window, no checkpoint).
   With the same tensor in both queries, the V18 owner must reproduce the V16
   slot-contrast step-1 receipt exactly: original-model hash, preparation,
   native binding, prompt/context features, initial state, then for all 16
   pairs the loss components (V16's extra total excluded), spill receipt,
   accumulated-gradient hash and bridge-gradient norms, followed by the update
   receipt and full state fingerprint. Any mismatch stops the pilot before the
   trained condition. This checks real-text operand binding, the 7B ownership
   and layout guards, contextual backward and the resource envelope at once.
2. **Primary** (`ordered_difference`): evaluation at step 0, window 1,
   evaluation, checkpoint, window 2, evaluation, checkpoint. The step-0
   evaluation is also compared field by field with V16's; this is recorded
   but not gating.
3. **Replay**: a fresh interpreter independently rebuilds the run contract,
   schedule and metadata, restores checkpoint 1 with `weights_only=True`, must
   reproduce window 2 exactly and reach the step-2 checkpoint's state hash.

Evaluation repeats V16's 10 memory conditions and 5 factor contrasts (160
workspace, 16 direct-base and 80 factor rows per step) through the selection
pipeline with the exact `OperandSpan`, splitting common and interaction
residuals from the reader's two captured queries.

Operand binding has been checked once with the pinned tokenizer, without the
model: all 16 pilot rows, all 2,048 `functional_train` questions and all 1,024
population questions bind, and every question span equals the legacy span.

## Admission, limits and claims

Before any project import each process passes the sealed source launcher; it
also requires the 594 Furnace-qualified owner sources, the pinned V16 comparator
receipts and the training data to be byte-identical. Tiny CPU and CUDA
qualification of the runner (18 tests per device) must pass first. Resource
limits are V16's: 31 GiB free GPU memory at admission, a 30.5-GiB allocator
cap, 0.75-GiB GPU abort floor, 100/24-GiB host admission/abort floors, 50-GiB
disk floor with a 64-GiB primary storage forecast, 7,200 s and two CPU threads
per process. V16's measured peaks were about 29.8 GB CUDA allocated, 95.8 GB
RSS and 22 minutes per arm.

This pilot can establish engineering integration, exact resume and resource use
on the real model, and record bounded mechanism observations on two exposed
worlds. It cannot establish held-out benefit, selection advantage, base
non-regression or release readiness. No new sequences, judge calls, weight
deletion, upload or automatic retry are part of it. A larger run needs its own
frozen population, splits, size and decision rule, informed by this pilot's
measured resources.

Runner: [run_v18_native_pilot.py](../../scripts/run_v18_native_pilot.py);
plan: [NATIVE_PILOT_PLAN.json](../../configs/v18/NATIVE_PILOT_PLAN.json);
evaluation: [v18_native_eval.py](../../src/latent_workspace_ft_v10/v18_native_eval.py);
tests: [test_v18_native_pilot.py](../../tests/test_v18_native_pilot.py);
offline verifier: [verify_v18_native_pilot.py](../../scripts/verify_v18_native_pilot.py).
