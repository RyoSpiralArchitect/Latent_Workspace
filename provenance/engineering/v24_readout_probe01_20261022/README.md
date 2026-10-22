# V24 readout probe 01: binding exists; reference-format learning dominates

**2026-10-22 — complete, offline replay verified.** This is an exposed,
teacher-forced diagnosis, not a new benchmark score, training run or release.
The three arms are original base and the unchanged V23 P-off/P-on final states.
Execution source: `bb1ecc8b3b3b98f9b63a67da1dbdd76033c76c79`.

## Completeness and provenance

- CPU **350/350** and CUDA **350/350** tests passed, zero failures/errors/skips;
  the sampled CPU/descendant GPU-isolation audit passed.
- All three arms completed **44/44 cases and 197/197 forwards**: **132/132
  traces, 591/591 forwards**, no missing/invalid cases. No retry or partial-arm
  splice. Four MMLU-Pro items and four world groups are the experimental units,
  not 591 independent problems.
- Zero new free generations, updates, checkpoint saves, judge requests or
  deletions **inside this run**. A separate authorized intermediate retirement
  is [recorded independently](../../inventory/v24_intermediates_20261022/README.md).
- Before/after model-state identities match in every arm. All 814 source paths,
  qualification XML/receipts, dispatch/role manifests, frozen input bytes,
  native histories and trace denominators replay offline.
- Base/off/on elapsed times: **77.69 / 229.03 / 226.41 seconds**. Peak native
  CUDA allocation is **15,769,111,552 bytes** in each arm; reserved peak
  **16,145,973,248 bytes**. Host RSS peaks are **5,926,715,392 / 59,852,124,160 /
  59,962,793,984 bytes**. These are diagnostic, not Full-FT memory estimates.

Source: [frozen plan](../../../configs/v24/READOUT_PROBE_01.json),
[source seal](furnace/SOURCE_SEAL.json), [dispatch receipt](furnace/raw/FINISHED.json),
[complete offline analysis](analysis/ANALYSIS.json), and
[read-only verifier](../../../scripts/analyze_v24_readout_probe.py).
The earlier local **346 passed / 4 isolated-import failures** remains
[unchanged](LOCAL_350.xml); Furnace qualification did not skip those tests.
The new offline analysis/retirement tests passed **19/19** locally
([XML receipt](LOCAL_19.xml)).
Offline replay verifies recorded bytes, histories and derived contrasts; it
does not independently recompute the 7B logits. The remote source remained
clean at the sealed commit after completion. Publication checks also matched
all four binding rows, four group rows, four stage rows and eight literal
answer triples to source, and resolved 202 local links across the updated docs.

## 1. A universal missing label readout is not supported

The following entries are **gold option logit minus the best other option
logit**, measured in native full-vocabulary forwards. No option mask or
forced-choice sampler was used. Positive means a strict option-set win;
zero is a tie, not a strict win. These are conditional probes, not generated
correct answers. Each cell is **base / P-off / P-on**.

| Exposed item | Original direct anchor | Unassisted answer-label anchor | Explicit correct option-content anchor |
| --- | --- | --- | --- |
| biology:3462 | 14.625 / 11.6875 / 11.875 | 11.625 / 9.625 / 9.8125 | 10.6875 / 9.375 / 9.375 |
| chemistry:4250 | 0 / -3.875 / -3 | -8.75 / -7.0625 / -7.125 | 0.125 / 0.75 / 0.375 |
| math:9037 | -8 / -3.6875 / -3.75 | -3.875 / -3.125 / -3.1875 | 6.5 / 5.1875 / 5.5 |
| other:5622 | 0.5 / -0.125 / 0.125 | 1.75 / 1.125 / 1.25 | 9.125 / 7.8125 / 7.8125 |

Strict option wins are **2/1/2 of 4** at the direct anchor, **2/2/2 of 4**
at the unassisted label anchor, and **4/4/4 of 4** after supplying the exact
correct option content. For chemistry the assisted margins remain small.

The assistance literally supplies, for example, `The result is 1.4 × 10^-1 mol.`
before `The answer is (` for chemistry and `The result is 840.` for math.
This tells the model the correct semantic result. It **does not** establish
independent derivation, successful binding on a self-generated explanation,
or robustness to paraphrases/option permutations. The assisted/unassisted
prefixes differ; same-anchor model contrasts alone hold token histories fixed.
The old missing-marker, wrong-label and wrong-derivation scores remain unchanged.

## 2. Shorter output is not evidence of EOS at the beginning

EOS probabilities at the reasoning-start anchor remain extremely small in all
12 item/arm cells: maximum **5.75953e-9**. FT raises some of them relative to
base, but this panel does not support frequent immediate termination.

After a supplied *complete correct reference*, EOS probability changes strongly
and unevenly. Again these are full-vocabulary native probabilities:

| Item | Base | P-off | P-on |
| --- | ---: | ---: | ---: |
| biology:3462 | 1.98390e-5 | 0.175935 | 0.103290 |
| chemistry:4250 | 9.56878e-5 | 0.492278 | 0.371203 |
| math:9037 | 9.68699e-12 | 0.000115535 | 0.0000101008 |
| other:5622 | 2.22420e-10 | 0.000107568 | 0.0000240196 |

This is evidence for changed **conditional completion behavior**, not a proof
that EOS causes the earlier reasoning failures. A generated-history stop audit
is still needed. Do not respond by globally suppressing EOS or rewarding length.

## 3. Content sensitivity was already present; likelihood gain is mostly form

For each fixed reference answer, compare its log probability with intact versus
twin memory while keeping question/answer tokens identical. Below is the mean
of the two directional **content-token logprob sums** within each group,
`log p(reference | matching memory) - log p(reference | opposite memory)`.
It is not a probability, accuracy, token-normalized score or independent n=8.

| World group | Base | P-off | P-on |
| --- | ---: | ---: | ---: |
| inventory-test-0008 | 13.71875 | 11.03125 | 11.09375 |
| location-test-0013 | 15.07812 | 15.20312 | 15.39063 |
| order-test-0002 | 4.50000 | 4.31250 | 4.18750 |
| revision-test-0009 | 20.68750 | 17.62500 | 17.98437 |

All eight reference directions have positive content sensitivity in every arm.
That supports conditional use of memory content in this instrument. It does
not show a general increase in semantic selectivity after FT: three of four
group means are lower in each trained arm than in base.

Across the **eight intact references only**, candidate-minus-base target log
probability decomposes as follows. Token roles are the predeclared lexical
oracle partition, not mechanistic proof of internal reasoning. Later tokens
are conditioned on earlier *teacher-forced correct* tokens.

| Stage | Tokens | P-off total gain (nats) | P-on total gain (nats) |
| --- | ---: | ---: | ---: |
| Content/identity | 14 | 1.306049 | 1.288899 |
| Exact-copy continuation | 27 | 0.000022 | 0.000058 |
| Format | 10 | 79.041821 | 79.072415 |
| EOS | 8 | 1.079477 | 1.080634 |

The reference-period probability is a major contributor. This is **not** an
explanation of the entire historical 47→83/96 exactness change. The old scorer
already ignores a final period; it does not accept extra explanatory text.
On these eight affected rows, the old free-generation scores are **5/8 → 8/8 →
8/8**. Two repairs remove an explanation; one changes the answer content.

| Group / side | Exact old base text | Exact old P-off and P-on text |
| --- | --- | --- |
| inventory / 0 | `21` | `21.` |
| inventory / 1 | `24` | `24.` |
| location / 0 | `Nybcfejpyg` | `Nybcfejpyg.` |
| location / 1 | `Not specified.` | `Neuiatciqh.` |
| order / 0 | `Njhxbkoglo is ranked higher.` | `Njhxbkoglo.` |
| order / 1 | `Nukunqizcl is ranked higher.` | `Nukunqizcl.` |
| revision / 0 | `Ncdcwzomlj` | `Ncdcwzomlj.` |
| revision / 1 | `Nptltpauge` | `Nptltpauge.` |

These are **previously generated outputs**, not new V24 generations:
[base](../../pilots/v23_comparison01_20261022/furnace/raw/base/worlds.jsonl),
[P-off](../../pilots/v23_comparison01_20261022/furnace/raw/off/worlds.jsonl),
[P-on](../../pilots/v23_comparison_recovery02_20261022/furnace/raw/on/worlds.jsonl).
See the unchanged [normalizer](../../../src/latent_workspace/native_evaluation.py).

## Carry-forward decision

Preserve the useful response-shaping and copying behavior, but stop treating
reference-format NLL or a world-bank exactness gain as broad intelligence.
Prioritize train-only, independently solved **content/derivation → answer use**
with explicit separation of semantic correctness, binding, format and stopping.
An additional binding loss alone is not justified by these four assisted cases;
binding on actual generated histories remains unresolved. Keep P fixed and
explicit rather than increasing it or promoting P-on without a retention result.

The next capability panel needs fresh source-group holdouts, same-information
inline/workspace controls, no-memory base comparison, true copying and externally
checkable reasoning/code endpoints. The current prefix-memory M is not yet
temporary computational state S. See [next FT design](../../../docs/v24/FULL_FT_DIRECTION.md).
No new learner factor, Full FT or HF release has run here.

**Old gate FAIL / winner:none / non_regression NOT_ESTABLISHED.**

Offline replay (no model load or provider call):

```sh
python3 scripts/analyze_v24_readout_probe.py \
  provenance/engineering/v24_readout_probe01_20261022/furnace \
  --check provenance/engineering/v24_readout_probe01_20261022/analysis/ANALYSIS.json
```
