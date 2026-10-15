# V18 saved-state diagnosis: a useful localization, but historical replay is blocked

2026-10-15. Both planned processes completed: **12/12 retained states on CPU and
12/12 on CUDA**, with no fitting. Both offline artifact/provenance replays pass.
However, **0/24 original-order native-logit arrays exactly reproduce the
historical arrays**. Every cell therefore retains
`BLOCKED_CONTROL_REPRODUCTION_MISMATCH`. This is not a repaired baseline or a
successful historical-forward reproduction.

The frozen diagnostic source is
`57af47858088d67247cbb5c3f77c4724a16db624` (580 sealed files).
The separate original fitted source remains
`dd10b20a8fbb0e32e5ac89bcec939802e6940f8b` (572 sealed files).
See the [protocol](../../../docs/v18/SELECTION_NUMERICAL_DIAGNOSIS.md),
[source seal](SOURCE_SEAL.json), [CPU results](cpu/RESULTS.json),
[CUDA results](cuda/RESULTS.json), and
[CPU](CPU_VERIFY.json) / [CUDA](CUDA_VERIFY.json) offline receipts.
Verification ran in the original Furnace Python 3.12.14 / Torch 2.13.0+cu132
runtime, without new forwards. Literal input hashes before/after match.

## What reproduced, and what did not

| Observation | CPU | CUDA |
| --- | ---: | ---: |
| Retained states examined | 12/12 | 12/12 |
| Historical native-logit arrays exactly reproduced | 0/12 | 0/12 |
| Complete historical control dictionaries exactly reproduced | 5/12 | 1/12 |
| Same-input original/permuted repeat pairs, logits and residuals exact | 24/24 each | 24/24 each |
| Instrumented vs ordinary passes, logits and residuals exact | 24/24 | 24/24 |
| Current permutation controls at the unchanged 1e-6 bound | 10/12 | 9/12 |
| Historical original vs current argmax changes | 0/13,824 | 0/13,824 |
| Current original vs permuted argmax changes | 0/13,824 | 0/13,824 |
| Historical or permutation maximum-tie-count changes | 0/13,824 each | 0/13,824 each |

The 13,824 denominator is 12 states × the same 1,152 held-out rows; it is not
13,824 independent examples. The two runtimes reuse this population. Every
full-vocabulary array has 1,152 × 7 = 8,064 scalar logits. Same-input repeatability
and nonintrusive hooks do not establish agreement with the historical process.

Maximum historical-to-current logit differences are
`1.564621925354004e-6` on CPU and `4.76837158203125e-7` on CUDA. No answer changes
were observed, but this does not waive the exact replay requirement or relax the
historical numerical control. Raw arrays are retained in each per-state `.pt`
file, together with the historical original-order logits. Historical permuted
arrays were never stored; their original comparison remains scalar-only.

## Where the current permutation difference first appears

After inverse-permutation alignment, normalized memory and query features are
exact. All **18/18 centered states** first differ in the centered memory; maximum
aligned centered-value difference is `4.76837158203125e-7` on each runtime.
All **6/6 raw-control states** first differ at the interaction SDPA output.
The common branch first differs at SDPA in 24/24 states, but its frozen exact-zero
up projection makes its residual exactly zero in this supplied-slot assay.

Anchor/offset/mean gauge changes are excluded from this localization. It is an
observation of the current replay, not a causal explanation of the historical
failures. In particular, raw-control historical logits also fail exact replay,
so changing centering alone cannot explain the entire reproduction discrepancy.

The final-state permutation observations illustrate why the old receipt must
not be replaced:

| Runtime / seed | Historical max logit error | Current max logit error |
| --- | ---: | ---: |
| CPU / 17 | 1.3113021850585938e-6 | 1.3113021850585938e-6 |
| CPU / 29 | 1.1883676052093506e-6 | 8.568167686462402e-7 |
| CPU / 43 | 1.3113021850585938e-6 | 1.430511474609375e-6 |
| CUDA / 17 | 2.1457672119140625e-6 | 2.086162567138672e-6 |
| CUDA / 29 | 1.8477439880371094e-6 | 1.8775463104248047e-6 |
| CUDA / 43 | 1.9073486328125e-6 | 2.086162567138672e-6 |

CPU seed 29 crosses the fixed bound in this new observation. Its original FAIL
is unchanged. Even CPU seed 17's identical complete control dictionary hides
1,092 changed historical logit elements out of 8,064; matching a maximum error
alone is insufficient evidence of exact execution identity.

Literal examples (no generation or paraphrase): CPU seed17, centered-final,
case300 asks `Is E0 ranked above E1? Answer:` (frame8, order2). Its first two
historical logits are `[-0.22044476866722107, 0.22044476866722107]`; the new
original-order values are `[-0.22044320404529572, 0.22044320404529572]`.
CUDA seed17, centered-final, case392 asks `Is E1 ranked above E0? Answer:`
(frame10, order5). Current original-order first-two logits are
`[0.8114298582077026, -0.8114298582077026]`, versus permuted
`[0.8114277720451355, -0.8114277720451355]`. Both examples retain the answer.
The full-vocabulary control also covers the other five logits, not just this
two-answer illustration.

## Next narrow factor: reconstruct execution state, not only tensor values

Static comparison found one explicit policy mismatch: the original assay keeps
six interaction parameters `requires_grad=True` while evaluating under
`eval()` and `no_grad()`. This diagnostic additionally freezes all parameters.
The saved tensor fingerprint does not include that flag. This is a hypothesis,
not an explanation yet: both paths are no-grad and their non-self-attention
does not support simply asserting a Python MHA inference-fastpath switch.

The separately planned follow-up compares only those two flag partitions, using
unchanged source arithmetic, saved inputs and weights, with no updates. Record
flags, tensor layout and execution settings explicitly. Do not silently rerun
this completed diagnostic or broaden it into a precision repair. FP64 centering
is a possible later numerical factor, not a selected learner modification.

The parallel [fact-only writer helper](../../../scripts/v18_controlled_writer.py)
passes 42 focused local tests. It exposes 20 writer + six interaction parameter
tensors (20,160 scalar parameters), freezes the six common-reader tensors, and
passes neither questions nor labels to the writer. It is engineering wiring,
not factual-input authentication, a fitted writer or checkpoint-owner admission.
The diagnostic has 32 focused tests; 431 selected regression tests pass overall.

## Resources and claim ceiling

CPU result snapshot: 3.94494 s, 751,452,160 bytes peak RSS, no CUDA allocation.
CUDA result snapshot: 4.89310 s, 1,602,273,280 bytes peak RSS and 35,759,616 bytes
peak CUDA allocation. Terminal receipts also retain later elapsed snapshots.
There are 720 batched forwards per runtime, zero training updates, zero
optimizer instances, zero writer calls, and no 7B execution or new generation.

All original bundles and source seals remain unchanged. No paid judge, deletion,
HF upload, PR/merge or recurring monitor occurred. The full-update route remains
the [roadmap](../../../docs/v18/FULL_UPDATE_ROADMAP.md), with historical
**FAIL / winner:none / non_regression NOT_ESTABLISHED** intact.
