# Local teacher inspection 01 — 64 receipts, no training admission

2026-10-21 JST. Source `a33c373ba542a632f5dab3b708ffba09ebec12ef`,
702 sealed files, checked before and after execution. The teacher run followed
the completed no-update 7B resource probe; the two did not share GPU residency.
All 64 request bodies were frozen before model loading/dispatch. This is
language-rendering inspection, **not** a blind judge, a benchmark, a base-model
comparison or full FT.

## Runtime, provenance and denominators

Official `Qwen/Qwen2.5-32B-Instruct-GGUF`, revision
`a15e3cc10f8bbb2c0af6f8f1f34a32e3b060c09d`, Apache-2.0, **Q5_K_M**.
All six shards (23,262,157,568 bytes) match their published hashes. Runtime:
official llama.cpp **b11756 CUDA 12.8**, source
`d80619397c2ba5cf1366c29f7d43699ca3a159b9`; both archive hashes and 55
extracted regular-file hashes were verified. The model identity, runtime
files, server command/properties and literal server log are retained.

The earlier task-local source build encountered a CUDA 13.1/system-header
`rsqrt` exception-specification incompatibility before any generation. Its
failed build remains on Furnace; the CPU build succeeded but was not used for
this inference condition. The official binary was selected and frozen before
any request. This result makes no CPU throughput or CPU/GPU equivalence claim.
The retained [CMake configure trace](furnace/runtime_build_attempt/CMakeConfigureLog.yaml)
records discovery through compiler identification; it does not include all
terminal stderr from that failed configure command.

| Quantity | Result |
| --- | ---: |
| Planned / attempted / received | 64 / 64 / 64 |
| World / ordinary-instruction items | 48 / 16 |
| Structural passes | 64 / 64 |
| Truncated / invalid / transport-error outcomes | 0 / 0 / 0 |
| Unattempted / retried requests | 0 / 0 |
| Semantic certifications / training admissions | 0 / 0 |
| Native updates / paid judge calls / deletions | 0 / 0 / 0 |

Selection is deterministic: four intact/twin pairs per training-world family
and two instructions per starter family. These are not random representative
samples. No dev, test, OOD or historical evaluation example is exposed.
The world teacher sees canonical answers and ordered evidence IDs. Agreement
with those fields therefore **does not establish independent correctness**.

Settings: one server slot, context 4,096, GPU layers 99, four CPU threads,
temperature 0.2, top-p 0.9, per-request seeds 47–110, at most 256 output tokens,
JSON schema, no retries. Provider-style usage recorded by the local server:
**15,625 prompt + 4,336 completion = 19,961 tokens**.
Run elapsed: **89.646 s**, including hashes/startup; summed request elapsed:
**74.806 s**. Neither is a controlled throughput benchmark.
Minimum of the 64 pre-request samples: **8.398 GiB GPU free**, **115.029 GiB
host available**, **158.319 GiB disk free**. These are sampled floors, not
continuous peak measurements. The owned server exited afterward; the GPU was
observed back at 10 MiB with no compute process.

Terminal SHA-256:
`200992b64ee406882845935e2a11e3d42724d35ecbe0a005dbe959115fe488e7`.
See [offline replay](analysis/REPLAY.json), the
[all-64 literal panel](analysis/REVIEW_PANEL.md) and
[text-contract diagnostics](analysis/TEXT_CONTRACT_DIAGNOSTICS.json).

## What direct inspection found

These are **post-hoc, non-blind observations by the authoring assistant**,
not a revised pass rubric or an independent semantic evaluation:

1. The 48 world answer sentences appear consistent with their supplied facts
   on direct comparison. This is unsurprising given the provided canonical
   answer. Factual agreement does not certify the whole instruction.
2. **48/48 generated world questions omit the memory-only/abstention policy.**
   Literal checks find neither the exact prefix nor `Not specified`; reading
   the questions also finds no equivalent instruction. For example, item 01
   changes the policy-bearing source query into:

   > Where is Nrngpjdlzb located?

   Its answer is:

   > Nrngpjdlzb is located at Nfpdpdinmm.

   The answer fits this visible world, but the omitted policy matters on
   missing or irrelevant memory. No such teacher case was included here.
3. **9/24 twin pairs have different generated question text.** The underlying
   canonical query is identical on both sides. Even harmless paraphrases
   confound a matched memory-only intervention, so the generated questions
   cannot be used directly as matched causal controls.
4. Visible support detail varies. Item 25 states the two dates:

   > Nocodyoskb occurs earlier than Nhrkccmgnk, as it takes place on the 5th day compared to the 18th day.

   Item 17 gives the correct transitive winner but no supporting edges:

   > Njggcvpsfn is ranked higher than Nnayseojcc.

   Copied evidence IDs are metadata, not proof that answer prose teaches
   inference or faithfully exposes the model's computation.
5. All **16/16 instruction queries** are unchanged. The simple arithmetic,
   format, extraction, code and reading outputs match the supplied references;
   translation and polite rewriting remain non-unique natural-language cases.
   Item 57 adds a wrapper:

   > The translation of 'ありがとう。' into English is 'Thank you.'

   This illustrates style transfer, not a quality improvement over original
   Mistral. The sampled translation rows are Japanese-to-English only.

## Additive correction, without re-generating or rewriting the run

Source `ab3035c4ba268e24ec5d32110f60c26b78bf36ee` adds
`compose_teacher_candidate()`. Canonical memory and the **entire canonical
query** are compiler-owned; the teacher contributes only answer prose.
The immutable original 64 responses, questions, statuses and analysis remain.

[COMPOSED_CANDIDATES.json](analysis/COMPOSED_CANDIDATES.json) contains 64
**new, quarantined derivatives**, excludes zero structurally valid items,
and binds each source candidate by hash. All policies are retained and all
24 twin queries are identical by construction. The compiler regression tests
adversarial teacher-question changes and verifies that memory/query never move.
It does **not** certify answer semantics or automatically approve training.
No extra generation, repair request or score optimization was performed.

Student-token counts use the pinned Mistral tokenizer:

- Original teacher-text candidates: **1,189 answer/EOS tokens**, maximum
  memory/query+answer/answer lengths **70 / 64 / 41**.
- Composed derivatives: the same **1,189 answer/EOS tokens**; maximum memory
  **70**, canonical query plus teacher answer **84**; **0/64** outside the
  128-by-128 axes. The latter is exact addition of separately encoded prompt
  and answer lengths, not a new tokenizer or a truncation.
- The counting source is `658bd505a2819a2ec90922502e0fa4148efe4d27` (704 sealed
  files); both source row-count files are hash-bound in the derivative.

## Full-FT implications

Keep semantic oracles, counterfactual pairing and query-deferred memory.
Separate immutable task policy from editable linguistic rendering. Broaden
ordinary instructions before training: the canonical starter contributes
only 1,523/37,615 training-candidate supervised tokens (**4.05%**) under
row-uniform sampling. Larger-teacher imitation is a different objective from
preserving original-Mistral behavior; an original-base rehearsal/anchor
population and frozen unseen non-regression evaluation are still needed.

This run does not resolve catastrophic forgetting, prove generalization or
choose a full-FT recipe. Mixture/update count remain **UNSET**, training
admissions **0**, and the historical
**FAIL / winner:none / non_regression NOT_ESTABLISHED** ceiling is unchanged.

## Offline reproduction

```sh
python scripts/run_native_teacher_inspection.py verify \
  --output provenance/data/native_teacher_inspection01_20261021/furnace/teacher
python scripts/report_native_data_preparation.py teacher \
  --input provenance/data/native_teacher_inspection01_20261021/furnace/teacher \
  --bank provenance/data/native_world_bank01_20261021/furnace/bank \
  --tokens provenance/data/native_world_bank01_20261021/furnace/student_tokens \
  --output provenance/data/native_teacher_inspection01_20261021/analysis --verify
python scripts/diagnose_native_teacher_text.py \
  --teacher provenance/data/native_teacher_inspection01_20261021/furnace/teacher \
  --output provenance/data/native_teacher_inspection01_20261021/analysis/TEXT_CONTRACT_DIAGNOSTICS.json \
  --compose-output provenance/data/native_teacher_inspection01_20261021/analysis/COMPOSED_CANDIDATES.json \
  --bank-tokens provenance/data/native_world_bank01_20261021/furnace/student_tokens \
  --teacher-tokens provenance/data/native_teacher_inspection01_20261021/furnace/teacher_student_tokens \
  --verify
```
