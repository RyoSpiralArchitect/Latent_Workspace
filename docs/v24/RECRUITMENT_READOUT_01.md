# V24 FT04: crossed-route post-training readout diagnosis

Prepared on 2026-10-27 after the move. This is a **new bounded development
evaluation**, not a restart of FT04, a new training run, or a release decision.
The original expression gate remains **FAIL**, `winner: none`, and
`non_regression: NOT_ESTABLISHED`.

## Question and provenance

The completed FT04 arms each ran 32 independent full-parameter updates from
original Mistral-7B-Instruct-v0.3, using 538 training rows and 21,112 targets.
Their original source was `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`.
The final checkpoint bodies remain on Furnace; the new
[frozen receipt copy](../../configs/v24/recruitment_readout01/TRAINING_RECEIPTS.json)
binds the original source, restore contracts, terminal manifests, save hashes
and full state fingerprints without editing the historical run.

The old development average mixed answer, formatting, EOS and step targets.
Canonical JSON placed the gold answer **before** the steps. Lower reference NLL
therefore does not establish independently generated computation. Also, comparing
only inline-trained/inline-input with workspace-trained/workspace-input confounds
training and runtime routes. This diagnostic separates those two issues.

## Finite frozen panel

[Plan](../../configs/v24/RECRUITMENT_READOUT_01.json) and
[exact token inputs](../../configs/v24/recruitment_readout01/INPUTS.json.gz):

| Factor | Fixed value |
| --- | --- |
| Checkpoint | original base, inline FT04 step32, workspace FT04 step32 |
| Runtime route | inline facts, query-deferred workspace facts, each checkpoint |
| Source groups | 6: 2 each arithmetic, register trace, stable filtering |
| Unique cases | 36; 48 raw twin/control rows with aliases retained |
| Exclusions | all 3 previously exposed reasoning-dev groups; all train/confirmation groups |
| Per checkpoint | 72 route rows, 144 reference traces, 2,320 fixed forwards |
| Free generation | 72/checkpoint; 216 total, greedy seed 20261027, at most 128 tokens each |
| Total forward ceiling | 6,960 fixed + at most 27,648 generated-token forwards = 34,608 |
| Learning and external activity | zero updates, saves, judges, downloads, weight deletions |

Groups are hash-selected using seed `v24-readout-20261027` from the existing
public synthetic bank, without new source acquisition or teacher calls.
All four controls survive: affected, unaffected, absent and unrelated memory.
They are correlated variants of **six** source problems, not 216 independent
replications. Families are trained families, not held-out tasks. This is a
post-result protocol and development observation, not confirmatory evidence.

## Fixed reference measurements

1. Historical answer-first serialization is byte-preserved. Measure answer
   values, step values, formatting, fused/mixed tokens and EOS separately.
2. For applicable cases, an explicitly labelled **steps-first reference**
   measures step continuation before the supplied gold answer. This is still
   teacher forcing of preceding gold steps, not self-generated reasoning.
3. At each reference token, record whether earlier gold-answer value tokens
   are present. A field's quotes/brackets count as value-prefix assistance;
   empty lists have no lexical-answer token. Mixed boundary tokens remain mixed.
4. On affected twins, score the other twin's answer-first reference too.
   Own-minus-donor likelihood through the end of the answer is descriptive:
   it includes syntax and length, is not normalized two-choice accuracy, and
   must not be interpreted as evidence of latent reasoning by itself.

The first answer-value token may itself be a quote or bracket. The separate
lexical index prevents calling syntax prediction a solved answer. No token
category, invalid row, or missing cell is dropped to improve the result.

## Unassisted generation

Every generation starts from the **original user query only**, with the same
facts placed through its declared runtime route. No gold-answer prefix,
forced intermediate step, grammar constraint, altered EOS rule or score-driven
retry is used. Steps-first references do not change the free-generation prompt.

Retain token IDs, exact decoded text, natural key order, stopping reason and
strict historical JSON scores. Remove only an actually generated terminal EOS
for JSON parsing; keep the full decoding too. Code fences, duplicate keys,
invalid JSON and length-capped responses remain in the planned denominator.
Answer correctness, exact steps, strict joint correctness and parsing are
separate endpoints. Absent/unrelated `answer:null` cases have no step task;
their missing steps are inapplicable, not fabricated errors or successes.

Report each family, source group, memory control and runtime route. Pair base
repairs with base-correct losses on identical cases. Any model-by-route contrast
is descriptive: routes differ in positions, compute and native arithmetic.
This experiment does not add recurrent working state S; external supplied
memory M is not automatically newly created reasoning.

## Execution and replay

- [Model-neutral instrument](../../src/latent_workspace/recruitment_readout.py),
  [runner](../../scripts/run_v24_recruitment_readout.py), and
  [offline verifier/reducer](../../scripts/analyze_v24_recruitment_readout.py)
  are additive. The historical native learner, data generator, sampler,
  readout arithmetic and old run source stay unchanged.
- Commit the source before deployment; use a new isolated Furnace worktree
  and exclusive output. No retry or resume. One role per fresh process; any
  failure prevents all later roles. Completed/missing execution stays explicit.
- Replay frozen inputs in the pinned tokenizer runtime **before loading 7B**.
  Then require all 441 selected tests on CPU and CUDA, with the independent CPU
  visibility observer. Each qualification remains at most 4 GiB / 900 seconds.
- Keep native BF16/eager, the original cut-4 graph, 31-GiB GPU admission,
  30.5-GiB allocator cap, 100-GiB host admission, 24-GiB host floor, 0.75-GiB
  GPU floor, 50-GiB disk floor and 14,400-second limit per model role.
  The launcher additionally reserves 256 MiB for metadata above the disk floor.
- Rehash each final checkpoint body and exactly restore its original owner
  contract/state before switching to inference; verify model bytes unchanged
  across evaluation. Do not save new tensors.
- Release only unused CUDA reservations at existing token boundaries, recording
  that live allocations do not change. No batching, cache-policy, precision or
  model architecture change is introduced for this diagnostic.
- Offline verification requires successful qualification and role/dispatcher
  terminals, full file/source manifests, exact input/score replay, actual forward
  and generation counts, restore identity and sampled safety floors. A missing
  terminal cannot be converted to a completed analysis. Output is exclusive.

Local preparation initially stopped **before input creation or model calls**
because the Mac's older tokenizer library also required `tokenizer.model`.
Copying that original pinned dictionary allowed preparation; no tokenizer
configuration was changed. The pinned Furnace replay is a separate required gate.

No quality result exists merely because the code or qualification passes. After
complete replay, use actual generated answers and paired losses to decide which
learner mechanism to investigate; do not retroactively change this protocol.
