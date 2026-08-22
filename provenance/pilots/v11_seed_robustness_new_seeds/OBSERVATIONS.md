# V11.0 F1 low-LR seed robustness — `1e-7` selected

## Question

Across three new training-order seeds, does `1e-7` or `2e-7` provide the
more robust four-update F1 full-update baseline under the already qualified
metric and generation-behavior gates?

## Frozen design

- Launch and finalizer source commit:
  `1968bd77a453b414d40bdb9ab6c5ad03eb5eeb1a`
- Runtime source SHA-256:
  `2d45a3c45bdd0a56d33103e8acfa629b7256b2b38d6836f85c1aaa2f097343cf`
- Contract SHA-256:
  `b5e513c390a392946ccf43715e8a1ae62e381d4a0c43a43c10d5a9394456b820`
- Pinned model revision:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`
- New seeds: 43, 44, and 45. Seed 42 informed the two learning-rate choices
  but was excluded from the robustness aggregation.
- Compared base learning rates: `1e-7` and `2e-7`.
- Every cell started fresh from the same pinned BF16 model and ran four
  optimizer steps. The frozen alternating order was `1e-7/seed43`,
  `2e-7/seed43`, `2e-7/seed44`, `1e-7/seed44`, `1e-7/seed45`, and
  `2e-7/seed45`.
- Held fixed: symmetric F1 inline route, choice-normalized objective with zero
  full-vocabulary loss weight, Adafactor, clipping, weight decay, cosine
  scheduling, eight-microbatch CPU accumulation, complete 1,024-case eval at
  step 0 and after every update, and the deterministic generation suite.
- Generation was captured before any weight pruning for the untouched original
  and all six checkpoints with seed 20260823, greedy decoding, and a 96-token
  cap.
- A learning rate was robust only if all three new seeds passed integrity,
  persisted-update, metric, and behavior gates. Selection prioritized
  worst-seed behavior accuracy, then worst-seed complete-eval accuracy and
  minimum recall, then choice loss, with lower LR only as a final tie-break.

The canonical receipt is
[`SEED_ROBUSTNESS_RECEIPT.json`](SEED_ROBUSTNESS_RECEIPT.json), SHA-256
`58d9543e24ba2cc0031a44ed6a85cd27e5e62747b1b8460f9b45d352501ba577`.
The complete deterministic behavior capture is
[`GENERATION_BEHAVIOR.json`](GENERATION_BEHAVIOR.json), SHA-256
`4dc6a984067d84b3728a5a81b95c774bb03edaa8eceb77256f7842e446dcee52`.

## Integrity result

Integrity is `PASS` for all six cells, and the scientific status is
`ROBUST_BASELINE_SELECTED`.

- All cells bound to the frozen config bytes, launch source, runtime digest,
  model revision, train/eval data, and behavior suite.
- All six exactly replayed the same step-0 metrics. Within each seed pair, the
  first pre-update forward window was byte-exact; the three pair digests are
  preserved in the canonical receipt.
- Optimizer coverage and all-base update coverage passed. Each cell recorded
  four restored CPU accumulation windows, 32 ordered microbatch spills, no
  discarded window, and all 7,338,138,890 trainable parameters.
- The applied learning-rate schedules, four-step row sequences, offload
  receipts, and final bundles passed their frozen checks.
- Exact CPU comparison covered all 291 persisted tensors and 7,248,023,552
  base-model elements for every checkpoint. Every checkpoint had a non-zero
  persisted update.
- The remote receipt, behavior capture, and contract matched their local bytes.
  All 38 fetched per-run artifacts matched the hashes embedded in the receipt.
  The six final manifests were verified but left out of Git under the
  repository's Furnace-path sanitization policy; their hashes remain in the
  canonical receipt.
  Full coverage arrays are retained in Git for the representative selected
  cell `lr_1e_7_seed43`; repeated arrays for the other five cells are omitted
  from Git but remain bound by the receipt and retained on Furnace.
- Source-state validation before launch: 268 passed and 3 CUDA-only skipped
  locally; 271 passed on Furnace. `ruff check .` and `git diff --check` passed.

All six final weight bundles remain on Furnace. No weight was pruned.

## Four-update matrix

The common step-0 anchor was choice loss 0.6750, full-vocabulary NLL 0.8429,
accuracy 0.7793, no recall 0.6758, and yes recall 0.8828.

| execution cell | choice loss | full NLL | accuracy | no recall | yes recall | 32-case behavior | exact changed elements | changed fraction | eligible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `1e-7/seed43` | 0.6384 | 0.8103 | 0.7754 | 0.7188 | 0.8320 | 0.84375 | 70,717,056 | 0.9757% | yes |
| `2e-7/seed43` | 0.5748 | 0.7546 | 0.7607 | 0.7773 | 0.7441 | 0.71875 | 142,182,949 | 1.9617% | no |
| `2e-7/seed44` | 0.5755 | 0.7552 | 0.7480 | 0.7871 | 0.7090 | 0.71875 | 135,132,136 | 1.8644% | no |
| `1e-7/seed44` | 0.6350 | 0.8074 | 0.7793 | 0.7227 | 0.8359 | 0.84375 | 69,287,955 | 0.9560% | yes |
| `1e-7/seed45` | 0.6396 | 0.8115 | 0.7793 | 0.7227 | 0.8359 | 0.84375 | 70,152,407 | 0.9679% | yes |
| `2e-7/seed45` | 0.5744 | 0.7549 | 0.7539 | 0.7812 | 0.7266 | 0.75000 | 137,341,546 | 1.8949% | yes |

Both learning rates passed the complete-eval numeric gates in all three seeds.
The decision changed only when the pre-registered behavior veto was applied.
All three `1e-7` cells passed, giving a passed-seed fraction of 1.0. At `2e-7`,
seed 43 and seed 44 scored 0.71875, below the 0.75 threshold; only seed 45
passed, exactly at 0.75. Its passed-seed fraction was therefore 1/3, so `2e-7`
was not robust.

The two rates expose a consistent tradeoff. `2e-7` produced lower choice and
full-vocabulary losses and about twice the exact BF16 changed-element fraction.
`1e-7` produced higher complete-eval accuracy in every matched seed and a much
better worst-seed behavior score. The frozen ranking therefore selected
`1e-7`; the lower-LR tie-break was not needed.

## Generation behavior before pruning

The untouched original scored 0.875 on the balanced 32-case inline slice with
14 `no` and 18 `yes` predictions. Every `1e-7` model scored 0.84375 with the
same prediction hash and a 17/15 `no`/`yes` split. The `2e-7` seed-43 and
seed-44 models shared a different prediction hash, scored 0.71875, and shifted
to 21/11. Seed 45 scored 0.75 with a 20/12 split. Thus the selected branch is
stable across these seeds, but it does not improve this slice over the original.

All seven models emitted both task choices and passed the bounded repetition
diagnostics. No extreme free-form token loop appeared. The qualitative surface
is nevertheless mixed and does not establish a broad quality gain.

- Ranked-world explanation and instruction-precision completions are token-ID
  exact across the original and all six checkpoints. The first still ignores
  the short-answer constraint and reaches the 96-token cap; the second remains
  concise and well formed.
- Counterfactual completions vary slightly but retain the previously observed
  relation-swap confusion and reach the token cap.
- Mechanism-boundary completions remain fluent but infer stability or
  independence from one negative intervention more strongly than the prompt
  licenses.
- Japanese synthesis completions remain coherent but reach the token cap and
  end mid-answer.
- Creative completions remain coherent, yet they use one paragraph rather than
  the requested four-line form.

These observations are why behavior PASS must be read as a bounded veto, not
as proof of general instruction following or model improvement.

## Failed hypotheses and interpretation

The seed-42 `2e-7` promotion did not generalize into a robust reference across
the three new seeds under the same behavior gate. The tempting interpretation
from complete-eval loss alone would have selected `2e-7`; that interpretation
is falsified by its replicated task-slice regression in seeds 43 and 44.

The lower `1e-7` update did replicate: all three new seeds passed every frozen
gate and produced exactly the same bounded task predictions. But this is not a
claim that smaller is universally better. It trades away short-run loss
reduction, was chosen from a basin discovered using seed 42, and has only four
updates and three new seeds behind it.

The useful result is therefore not “training improved Mistral.” It is that the
F1 full-update harness now has one reproducible low-LR control branch, and that
generation behavior caught a failure mode missed by the larger evaluation
aggregate.

## Decision and claim boundary

`1e-7` becomes the candidate V11.0 F1 full-update baseline under this bounded
contract. `candidate_f1_baseline_ready` is true and design of the next matched
contract is authorized. Further training and O0 execution are explicitly not
authorized by this receipt.

Supported claim: for the pinned Mistral-7B model, symmetric F1 route,
choice-normalized Adafactor/BF16 implementation, four-update schedule, and new
training-order seeds 43–45, `1e-7` passed every frozen integrity, metric,
persisted-update, and behavior gate.

Not supported: active-workspace superiority, B/F1/O3 pure-native equivalence,
sixteen-step stability, broad seed or optimizer robustness, 14B transfer, or
general capability improvement. The learning rates were selected after seed-42
exploration, so this n=3 confirmation is descriptive rather than an untouched
model-selection estimate.

## Next handoff

Freeze a separate matched F1-versus-O0 contract using `1e-7` as the passive
full-update control, identical seeds and CPU-accumulation transport, identical
base-update exposure, and the same complete-eval plus generation-veto workflow.
Do not launch it until O0 parameter ownership, optimizer coverage, and the
comparison's exact update budget are written into that contract.
