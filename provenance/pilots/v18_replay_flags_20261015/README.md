# V18: parameter flags explain the observed reconstruction discrepancy

2026-10-15. **Both planned processes completed and replayed offline.** The same
reader/storage was evaluated in a fixed A–B–B–A sequence, changing only the
parameter `requires_grad` partition. All calls remained eval/no-grad, with
unchanged saved inputs, weights, batching and reader source code.

**A reproduces all 12 historical logit arrays and complete control dictionaries
exactly on each runtime. B reproduces all 12 preceding diagnostic outputs and
complete control dictionaries exactly on each runtime.** All 24 fits show a
repeatable flag-dependent output difference. This identifies the tested policy
change as sufficient to reproduce the observed discrepancy in these conditions;
the exact backend/kernel mechanism is not established.

Source: `bcf1e1b90ada4e111ddcdcffd32a2795e459eca1`, 584 sealed files.
Original fitted source: `dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`.
Preceding diagnostic source: `57af47858088d67247cbb5c3f77c4724a16db624`.
See the [prospective plan](../../../docs/v18/REPLAY_FLAG_INTERVENTION.md),
[current seal](SOURCE_SEAL.json), [CPU results](cpu/RESULTS.json),
[CUDA results](cuda/RESULTS.json), and [CPU](CPU_VERIFY.json) /
[CUDA](CUDA_VERIFY.json) offline receipts. Both ancestor sources and literal
input bundles remain unchanged. The qualified runtime is the original Furnace
Python 3.12.14 / Torch 2.13.0+cu132 environment.

An independent local Mac audit verified all 24 new raw-fit replays (48 policy
cells) and both terminal hash inventories. Full-chain replay on that different
runtime failed earlier, in the inherited original assay's FP32 mean aggregation:
CPU seed 17 / centered-final / dev unaffected drift was stored as
`0.2550196647644043` and recomputed as `0.2550196945667267`; CUDA seed 17 /
centered-ordered / dev donor margin was stored as `7.408483028411865` and
recomputed as `7.408482074737549`. This is not a successful cross-runtime
full-chain replay. Keep the strict validator unchanged and distinguish these
failures from the successful same-Furnace full-chain checks above.

## All denominators, without replacing historical outcomes

A keeps the historical six interaction parameters trainable and 26 common/writer
parameters frozen. B freezes all 32. Historical gradient buffers were not saved
and are not reconstructed: both current arms have absent `.grad` buffers.

| Observation | CPU | CUDA |
| --- | ---: | ---: |
| Saved fits / flag-policy cells completed | 12/12; 24/24 | 12/12; 24/24 |
| Repeatable flag-dependent output difference | 12/12 fits | 12/12 fits |
| A: historical original logits exact | 12/12 | 12/12 |
| A: historical complete controls exact | 12/12 | 12/12 |
| B: prior original/permuted logits and residuals exact | 12/12 | 12/12 |
| B: prior complete controls exact | 12/12 | 12/12 |
| A: original permutation control passes | 9/12 | 9/12 |
| B: new observation's permutation control passes | 10/12 | 9/12 |
| Historical/current answer changes per policy | 0/13,824 | 0/13,824 |

Each policy has two original and two permuted observations. All within-policy
logit and residual repeats are exact. The 13,824 denominator is 12 saved states
× 1,152 repeated population rows, not independent new tasks. Both runtimes and
policies reuse the same population. No new fits or semantic replications exist.

In particular, CPU seed 29 centered-final changes from the historical
`1.1883676052093506e-6` error under A to `8.568167686462402e-7` under B. That
crosses the unchanged `1e-6` control bound without changing an answer. It does
not repair the historical failure. All six historical centered-final failures
(three seeds × two runtimes) are now reproduced under their original flags.

The largest A/B native-logit difference is `1.564621925354004e-6` on CPU and
`4.76837158203125e-7` on CUDA. A literal CPU example is seed 17 / centered-final,
case 300, "Is E0 ranked above E1? Answer:": A gives
`[-0.22044476866722107, 0.22044476866722107]`, while B gives
`[-0.22044320404529572, 0.22044320404529572]`. The selected answer is unchanged.

The preceding diagnostic remains an honest historical record with its own
`BLOCKED_CONTROL_REPRODUCTION_MISMATCH`; it is not rewritten. Its all-frozen
observations were repeatable but did not reconstruct the original flag policy.
Both arrays are retained here and there, rather than replacing one with the
other or rounding away the difference.

## Implementation consequence

Tensor-value hashes are necessary but insufficient execution-state identity.
Keep the original trainable partition during no-grad diagnostic evaluation;
do not add `requires_grad_(False)` merely as an inference convenience and then
claim unchanged arithmetic. Record module mode, flag partition, layouts and
runtime settings separately. This result does not prove that every backend or
model has the same sensitivity, or that a particular MHA fastpath caused it.

The new [selection state guard](../../../docs/v18/SELECTION_STATE_GUARD.md)
now explicitly checks all 32 production bridge parameters, partitioned
writer 20 / common 6 / interaction 6, and their live trainability/storage/pipeline
policy. It has 76 new local tests; this guard is **not** a qualified optimizer,
checkpoint or resume owner. The fact-only writer helper has 42 focused tests;
the new intervention has 26. The combined selected regression suite is
**533/533 local CPU tests**, with Ruff passing.

This closes the tested reconstruction discrepancy, not the original permutation
failure. Next numerical work must preserve the historical flags and separately
version any centering/attention change across matched arms. Owner engineering
can proceed in parallel: new versioned native/window owners, exact updates and
fresh-process resume, then a resource-bounded Mistral integration/full-update
pilot. No toy observation establishes original-base non-regression or release
readiness.

## Resources and retained ceiling

CPU result snapshot: 5.26918 s, 750,878,720 bytes peak RSS, no CUDA allocation.
CUDA: 6.36684 s, 1,583,943,680 bytes peak RSS, 34,715,136 bytes peak CUDA allocation.
The later terminal receipts record 5.28793 s CPU and 6.38548 s CUDA, including
final artifact bookkeeping; the memory peaks are unchanged.
Each runtime used 1,200 batched forwards with zero optimizer instances, backward
calls, writer calls or training updates. All 48 flag-policy cells completed;
the separate offline replay used zero forwards.

No native 7B FT, benchmark, new generation, paid judge or HF upload occurred in
this intervention. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remains. The separately authorized storage cleanup must use
its own ledger and preserve every original fitted toy state and diagnostic tensor.
