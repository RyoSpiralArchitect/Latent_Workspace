# V23 gradient audit 01 — fixed training panel, no weight update

This stage follows [preparation 01](PREPARATION_01.md), not a new learner.
The original preparation's successful child results and failed outer receipt
remain unchanged. [The new plan](../../configs/v23/GRADIENT_AUDIT_01.json)
must qualify independently before a real-model role runs.

## Instrument and numerical boundary

The engine-owned [gradient spill](../../src/latent_workspace/gradient_spill.py)
uses a post-accumulate leaf hook: one synchronous CPU copy of the final native
gradient, followed by release of that leaf's device gradient. Shared/tied leaves
must produce exactly one event per backward. Unexpected repeats, missing full
gradients, nonfinite values, dirty gradients or parameter mutation fail closed.
Hooks are removed and device gradients cleared on failure; the accumulator is
then poisoned, never resumed. See the [PyTorch hook contract](https://docs.pytorch.org/docs/2.14/generated/torch.Tensor.register_post_accumulate_grad_hook.html)
for API semantics; empirical qualification uses the pinned 2.13 Furnace runtime,
not an assumption that documentation substitutes for local parity.

Each objective/row traverses the backward graph once, rather than once per
parameter. Across-row gradients accumulate on CPU in FP32, in frozen row order.
This is a **diagnostic sum**, not the owner's BF16 accumulation, optimizer,
preconditioned step or guaranteed loss improvement. Dot products/norms use
bounded FP64 chunks. Null cosine means a zero vector, never agreement.
The owner, update rule, checkpoint payload and training loss remain unchanged.

The whole world-panel target count is the denominator for total, identity,
copy, format and mixed contributions. Preservation CE and full-vocabulary
teacher-to-student KL each use the whole preservation-panel target count.
An absent component is an explicit zero, counted without a pointless backward.
State diagnostics retain their separately labeled **per-row** denominator.
No component-mean reweighting, loss coefficient selection or outcome-dependent
token partition occurs.

## Finite execution

1. 338 selected tiny cases on CPU and CUDA, separately, with 4 GiB / 900-second
   limits. Existing update/save/fresh-process replay tests remain mandatory.
   New tests cover four host families, FP32/BF16, shared/tied leaves, recompute,
   hook cleanup, W/Q/R reconstruction, exact causal KL layout and the real runner.
2. Original base: largest-memory training world (query length then key breaks
   ties), a separate longest preservation-row sentinel, trace/no-trace exact
   forward and W + Q + R parameter-gradient reconstruction. The independently
   rounded BF16 path-sum tolerance is unchanged from the tiny reference:
   1e-4 absolute + 3% of each tensor's full-gradient max. It is an engineering
   comparison, not a scientific acceptance gate. No tolerance repair/retry.
3. Only after that passes, prepare the 12 fixed no-memory base target rows:
   932 causal target positions × 32,768 vocabulary entries × FP32 = 116.5 MiB.
   Native BF16/eager logits, FP32 log-softmax, T=1, complete identical contexts.
   Input token arrays and target bodies stay private on Furnace; hashes and
   exact counts are public. No external teacher or API call.
4. Fresh-process strict restore of V22 step32 and the same canary. Then all
   84 world rows / 14 training groups and 12 preservation rows: parameter
   gradient sums, world-component conflicts against preservation CE/KL, and
   M/question/continuation component VJPs for every nonempty world row.
   Parameter W/Q/R reconstruction is **one canary per model**, not an all-row
   parameter-path decomposition. No base world-panel gradient comparison is
   implied by the base resource canary.

Original Mistral identity and V22 checkpoint/owner state are checked before use;
native tensor hashes must remain identical after each arm. Full FT, checkpoint
writes, new generations, judges and held-out evaluations are all zero.

## Resources and storage

Each role has a four-hour wall limit, 31 GiB free-GPU admission, 30.5 GiB
allocator cap, 0.75 GiB GPU free floor, 100 GiB host admission, 24 GiB host
available floor and 50 GiB disk floor. One full CPU FP32 sum is about 27.0 GiB;
the W/Q/R canary temporarily uses two. Only two preservation sums are written
as temporary reference files (~54.0 GiB total), then hashed and retired after
the scalar reductions. These are newly generated scratch gradients, not model
checkpoints. On failure all evidence and missingness remain; no automatic retry.

[Three obsolete engineering canaries](../../provenance/inventory/v23_obsolete_canaries_20261022/README.md)
were separately inventoried, published and retired under Ryō's weight-cleanup
authorization, freeing 81.0373 GiB. Base Mistral and V22 step16/step32 remain.
Other scientific checkpoint branches and activation banks remain untouched.

Furnace managed-runtime doctor is checked without changing its environment.
Native differentiable cut states, gradients and strict owner restore are not
provided by the serving runtime; this is the documented native PyTorch lane,
not a silent alternative serving backend.

## Interpretation

This small, short-context **training diagnostic** may prioritize P (ordinary
preservation), B (question recruitment) or I (identity transport). Negative
gradient dot products are first-order local conflicts, not proof of a harmful
Adafactor update. Larger norms are not evidence of better reasoning. Newly
reserved confirmation/OOD groups and exposed benchmarks are not used here.
No new training recipe, coefficient, release or winner follows automatically.
Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED**.

## Interim execution

The [published interim record](../../provenance/engineering/v23_gradient_audit01_20261022/README.md)
passes all 338 tiny cases on each device and both 291-tensor real-7B path-sum
canaries. Base targets are complete; V22 owner restore is exact. Base native
weights remain unchanged and its peak GPU allocation is 17.7802 GiB.
The fixed conflict panel is still running at the interim snapshot, with its
final V22 hash and analysis pending. This is not an all-complete experiment,
a new training objective or a reason to change acceptance thresholds.
