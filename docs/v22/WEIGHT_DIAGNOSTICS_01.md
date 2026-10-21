# V22 fixed-checkpoint diagnostics 01

Ryō requested further analysis of the completed step-32 checkpoint. This is an
additive, **post-result** investigation of every row in comparison 01, not fresh
confirmation, another checkpoint search, or an attempt to revise its losses.

## Frozen questions

1. On all 570 MMLU prefixes per arm, replay the original BF16 logits exactly.
   Capture the normalized head input without changing the forward. Compute a
   full-vocabulary FP32 linear projection of the **same BF16-rounded states and
   weights**, and its BF16 cast. Distinguish final-output quantization from
   upstream differences; this is not an FP32 backbone or replacement benchmark.
2. On all 570 paired head inputs, evaluate the 2×2 base/V22 hidden × base/V22
   head factorial using the same selected-four-row FP32 linear shape. This
   isolates last-layer readout contributions conditional on the measured states;
   it does not replace the whole model, isolate individual decoder layers, or
   authorize a mixed-weight deployment. Saved states are activations, not weights.
3. On all 96 unique worlds × two routes × two arms, replay the complete gold
   teacher-forced calculation and **each previously recorded generation prefix**.
   Never feed a newly calculated prediction back. Retain per-token gold rank,
   margin, log probability, ties, observed next token, and first token mismatch.
   Compare gold and recorded paths only at their first common-prefix fork.
   A different tokenization, punctuation, or length cap is not automatically a
   semantic error. The prior exact-match label and literal text stay unchanged.
4. Census all 291 physical parameter tensors against the pinned original HF
   snapshot and the verified step-32 FP32 masters: changed element counts,
   relative L2, maxima, cast error and master-only sub-BF16 changes. CPU FP64
   reductions are chunked. Require exact master-to-native projection throughout.

## Controls, bounds and provenance

The [plan](../../configs/v22/WEIGHT_DIAGNOSTICS_01.json) binds the old comparison
plan and reuses its exact input seal, checkpoint/body/payload/fingerprint, tokenizer,
BF16 eager native graph, cut 4 and fixed runtime. Original and restored V22 run
in separate processes. Before/after native tree hashes must match. Historical
terminal file manifests and MMLU/teacher scores are checked before interpretation.
Every discrepancy in fixed-prefix argmax replay is retained, counted, and blocks
any claim of exact trajectory reproduction; it is never silently replaced.

CPU then CUDA tiny qualification is gated before 7B. The new observation/runner
tests honor `LTWS_TEST_DEVICE` and keep BF16 on the selected device. Legacy graph
and generation fixtures remain mixed CPU/device coverage; test counts are not
counts of CUDA kernels. Each invocation has 4 GiB / 900 seconds; each real role
has 30.5 GiB allocator / two hours, 24 GiB available host and 50 GiB disk floors.
The managed TRT doctor passed, but the native graph/checkpoint and activation
protocol require PyTorch; no environment change or vLLM fallback occurs.

No retry, new continuation, optimizer update, checkpoint save, weight deletion,
paid judge, model conversion, PR/merge or release. A failure remains a separate
sealed outcome. All earlier artifacts and scores remain immutable. No inspected
test failure enters training. **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remains unchanged; proposed learner changes need a new plan.
