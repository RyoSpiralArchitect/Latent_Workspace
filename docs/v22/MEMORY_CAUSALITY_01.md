# V22 memory causality 01 — frozen diagnostic design

This is further analysis of the **existing step-32 checkpoint**, not V23 training
or a 1.0 release. All 96 rows / 16 groups were exposed in comparison 01. No
result here is an independent generalization or non-regression confirmation.
The plan is [MEMORY_CAUSALITY_01.json](../../configs/v22/MEMORY_CAUSALITY_01.json).
The native-memory graph has no separate trained adapter: the same host writes
memory and question separately to cut 4, then the remaining host layers read
their packed states through the native full-vocabulary head.

## Order and stopping policy

Qualify selected tests on CPU then CUDA in fresh processes (4 GiB / 900 s each),
including four tiny architectures in BF16 and FP32, no-op state parity, actual
three-role execution and a deliberately leaky negative-control graph. Then
run fresh-process `base`, `v22`, `base_cross` roles. Use the exact original
identity and full-owner restore/fingerprint before the inference transition.
Any failed qualification, resource guard, source seal, parity or fixed-layout
future-invariance gate stops later work. No retry or source adjustment inside
the trial. All previous sources, receipts and weights remain unchanged.

The per-role envelope retains 31 GiB free GPU admission, 30.5 GiB allocator
cap, 0.75 GiB free-GPU floor, 100/24 GiB host admission/abort, 50 GiB disk floor,
two CPU threads and four hours maximum. Native PyTorch is necessary for the
custom intermediate-state interventions; managed TRT serving does not expose
this graph. The managed environments are not modified.

## 1. Separate future content from sequence extent

For **every gold next-token position**, both latent and inline routes, both
original and V22 (2,492 positions), compare:

- Full gold teacher sequence at the designated prediction position.
- Cropped prefix ending at that position.
- Same full extent with the future replaced by padding and masked out.
- Same full extent and mask, changing every future token by `(id + 1) % vocab`.

Record native full-vocabulary hash, max/RMS difference, changed-element count,
argmax identity, ties, gold rank/log-probability and margin. Fixed-extent future
content must be **bitwise invariant** before that arm's causal generations.
Cropping/padding differences are measured, not forced equal or substituted for
the original scores. This separates numerical/layout evidence; it does not
prove a particular CUDA kernel is the cause. No full-FP32 7B model is assumed
to fit the existing envelope.

## 2. Ask whether memory content changes the answer

All 80 nonempty-memory rows (32 affected, 32 unaffected, 16 unrelated controls)
get identity, empty-memory bypass, zero cut-state and reversed cut-state
conditions in both arms. The 64 affected/unaffected rows also get reciprocal
natural twin memory at cut 4. Identical query tokens are mandatory. Identity
and twin generations must exactly replay the corresponding prior native
generation, and identity logits must match the ordinary graph bitwise.

The natural twin comparison is directional: at the first differing **oracle
answer** token, with the identical common answer prefix, record the native
donor-minus-original logit margin. Also retain the full generated answer and
match to both oracle answers, unaffected-query stability and abstention.
Report separately the **10/16 groups with identical memory token length** and
the other six. Reciprocal directions share groups and are not independent N.

Empty memory also changes positions and the graph path. Zero keeps the carrier
length/positions but is off-manifold. Reverse retains encoded state values but
changes their packed order; contextual facts may already be distributed across
states. Neither is a clean semantic counterfactual. Their failure alone cannot
prove semantic content use; natural twin direction and unaffected controls are
needed. Unrelated queries preserve the original oracle abstention targets.

## 3. Cross the memory writer with the fixed reader

Save a deduplicated, hashed BF16 cut-4 activation bank, never a new checkpoint.
Use base memory states with the V22 reader, then V22 memory states with the base
reader. This yields the four writer/reader cells on the same 80 nonempty rows.
The query encoder, remaining layers and head all belong to the reader arm;
only the memory-writer output is exchanged. This does not identify which
reader layer/objective changed, and nonlinear interactions are retained.

Every answer uses greedy **full-vocabulary**, no-KV generation, cap 24, EOS 2,
seed 20261021. No sampled free writing, paid judge or model substitution.
Total planned sequences: base 384 + V22 464 + base-cross 80 = **928**, including
288 identity/twin replay controls. Count all capped outputs, not just matches.
Foreign memory states are fixed for this frozen inference assay; query and
continuation states are re-encoded each step. This is not detached-memory
training and adds no runtime cache to the learner.

## Claim ceiling and V23 handoff

Preserve **FAIL / winner:none / non_regression NOT_ESTABLISHED**. Useful causal
evidence would justify a narrower next learner factor, not a release. V23 must
still qualify update/save/restart, protect independent base capabilities, pass
fresh disjoint benchmarks and inspect matched free generations. Neither the
old two MMLU losses nor qualitative unknowns disappear through this assay.
