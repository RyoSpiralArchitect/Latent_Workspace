# Preservation candidate bank 01 — existing prose plus bounded human instructions

2026-10-21 (JST). **Prepared and replayed, not trained or quality-approved.**
Ryō authorized assembling the preservation bank, inspecting Q_Space_Manifold's
code assets, and a small HF acquisition where existing material was insufficient.
The work used CPU tokenization only. No model forward/generation, judge request,
native update, weight deletion, PR operation or Hub publication was performed.

## Result

[Summary](furnace/SUMMARY.json), [metadata-only index](furnace/index.json.gz),
[manifest](furnace/MANIFEST.json), [frozen plan](furnace/PLAN.json).

| Role / language | Train candidates | Development candidates | Train supervised tokens | Development supervised tokens |
| --- | ---: | ---: | ---: | ---: |
| Prose / English | 1,084 | 100 | 137,356 | 12,647 |
| Instructions / English | 512 | 64 | 134,979 | 18,995 |
| Code answers / English | 125 | 15 | 46,278 | 5,898 |
| Instructions / Japanese | 33 | 5 | 6,003 | 2,221 |
| Code answers / Japanese | 0 | 0 | 0 | 0 |
| **Total** | **1,754** | **184** | **324,616** | **39,761** |

There are 1,938 rows / 1,050 source groups: 941 train groups and 109 development
groups. These are candidates, not 1,938 independent quality observations.
The group split is deterministic and precedes any learner evaluation. No final
test set was constructed or opened for selection.

Tokens use the existing Mistral-7B-Instruct-v0.3 snapshot
`c170c708c41dac9275d15a8fff4eca08d52bab71`, not Aether or teacher IDs.
The summary records actual tokenizer file hashes and the chat-template hash.
Supervised-token counts exclude causal position zero and masked prompt tokens.
They are denominators, **not frozen training-mixture weights**.

## Sources and boundaries

### Aether: reuse raw human prose, not its pretokenized stream

The existing standalone component bundle
`aether_next_pretrain_components_v2_2048_20260827` contains 13,820 documents.
All 13,838 inventory files were hashed again and matched its frozen manifest
`4290534b2fefd5c173f84cf807abc2232f662c77e4149cc3e6aa9e585d2f3498`.

The allowlist contains 6,803 human-original / human-translation chunks from
296 declared root works. The 7,000 synthetic items and 17 user-owned items are
excluded. One seeded, hash-ranked chunk per root supplies up to four disjoint,
seeded 127-token spans, each preceded by BOS. No artificial EOS is added at an
internal excerpt boundary. All 1,184 resulting prose sequences are at most
128 tokens; all continuation tokens are supervised. They are not converted
into invented user/assistant conversations.

The 569-document / 35-root Aether evaluation index was verified against its
pinned hash. Declared root and full-content overlaps with the source training
bundle were both zero. This is not an independent audit of all editions,
paraphrases or bibliographic identities.

The PG source records assert public-domain status **in the United States** and
explicitly require jurisdiction-specific review. We preserve those assertions,
not a new legal clearance. Original text and token arrays stay in Furnace
artifact storage; this Git-ready report includes only metadata and hashes.
Cross-jurisdiction use and any future release still require a decision.

### OpenAssistant: one pinned, small acquisition

Upstream: [OpenAssistant/oasst1](https://huggingface.co/datasets/OpenAssistant/oasst1/tree/fdf72ae0827c1cda404aff25b6603abec9e3399b),
revision `fdf72ae0827c1cda404aff25b6603abec9e3399b`.
The upstream card declares Apache-2.0; the exact [card](source_cards/README.md)
and [license](source_cards/LICENSE) are retained. This is a source declaration,
not an independent rights audit of every contributed code fragment.

Only four files were fetched: train parquet (39,516,251 bytes), validation
parquet (2,080,179 bytes), README (10,168 bytes), LICENSE (11,357 bytes):
**41,617,955 bytes total**. Both parquet SHA-256 values and both Git documentation
blob IDs are checked by the builder. No other dataset or model was acquired.
`pyarrow==23.0.1` was installed into this task's separate `deps/` directory;
the shared training environment was not modified.

The official train split has 84,437 messages, of which 52,912 assistant messages
were considered. Only complete first-turn root-prompt/assistant pairs are
eligible: no orphaned follow-up is flattened into an unrelated prompt.
Both sides must have positive review, be undeleted and explicitly non-synthetic,
have matching `en`/`ja` labels and a PII annotation. Positive PII/spam/hate/
sexual/not-appropriate flags exclude a pair. The assistant must be rank zero
and have an annotated quality value at least 0.5. These are fixed source-label
filters, not new model judgments or a correctness guarantee.

The 4,401 official validation messages / 518 trees are exclusion-only.
They contribute **zero training rows**. Candidate rows are further separated
by tree into train/development, de-duplicated by normalized prompt/answer,
and selected by seeded hash order with the fixed per-role/language quotas.
Only assistant tokens and the template EOS receive loss. The full-chat token
sequence must have the independently rendered user prefix exactly; otherwise
the builder fails rather than guessing a boundary. Answers over 1,024 total
chat tokens are excluded, never silently truncated.

Outcome: 754 selected pairs; 52,158 assistant-message rejections, including
23,394 incomplete-root pairs, 18,487 language exclusions, 5,678 non-rank-zero,
1,910 over-quota, 558 missing PII annotation, 37 over-length, 10 duplicate
prompt/answer, and 7 evaluation-text overlap exclusions. Other fixed rejection
categories and every denominator remain in the summary.

Quotas were **not relaxed after inspection**. Shortfalls are 3 train / 1 dev
English code answers, 31 train / 3 dev Japanese instructions, and all
16 train / 2 dev Japanese code answers. A code tag is a deterministic
code-fence/syntax heuristic, not a language inventory or execution-test result.
No downloaded code was executed.

### Q_Space_Manifold: exclusion asset, not training data or a fresh coding test

The inspected Furnace checkout `Q_space_manifold` was at
`383e79d2f2dca7e8c835baa8b49ec8f564022308`. Its code-language research uses
CodeXGLUE / CodeSearchNet **validation** material: 1,000 rows for each of Python,
Java, JavaScript, Go, PHP and Ruby, 6,000 total.

The existing [ingress receipt](source_cards/codexglue_codesearchnet_code_language_validation_n1000.ingress.json)
binds the actual text artifact to SHA-256
`f4e5a63d9ba5c486c0f1239083e58bdcd58beb6000823dd043abf710ac15219d`.
Its upstream revision and row IDs were not recorded; code bodies were already
capped at 3,000 characters. These limitations remain UNKNOWN, not repaired by
inventing a revision. It is a historically exposed language-routing probe, not
an unseen functional-code benchmark.

All 6,000 bodies are used only for exclusion. NFKC/casefold word-normalized exact
matches or shared 50-word spans against this artifact and official OASST
validation exclude candidates. This cannot certify no semantic contamination,
uncapped-code overlap or overlap with other public benchmarks. HumanEval/MBPP
and other future evaluation suites are not imported as training gold.

## Verification and retained ceilings

- New focused regressions: **24/24 PASS locally and on Furnace** before building;
  [Furnace JUnit](furnace/tests.xml).
- Full offline regeneration matched compressed rows, index, plan and summary
  byte-for-byte: `OFFLINE_REPLAY_PASS`.
- Post-build local regressions, including the public-index/source checks and
  existing world-bank/data-reporting tests: **56/56 PASS**. Ruff and tracked
  diff whitespace checks pass. [Observed verification record](VERIFICATION.json)
  identifies its agent-recorded nature; it is not an independent signature.
- Zero duplicate token sequences, cross-split declared groups, or cross-split
  normalized OASST prompt/answer components.
- Raw bank `rows.json.gz`: 1,654,375 bytes,
  SHA-256 `cdd69db1a30021bb9fc38b8ab07ad70ef28306cdb9128b60df59f011af19a615`.
- CPU source identities are in the manifest. This is a file-hashed data build,
  **not a committed-source GPU training seal**.

The final full-FT recipe remains UNSET. In particular:

1. **635/1,938 sequences exceed the tested 128-query-token backward axis**
   (564 train, 71 dev), up to 1,024 tokens. Even shorter rows are not an
   optimizer/save/restart certification for the eventual mixed recipe.
2. English prose is a narrow literature/essay-heavy sample. Japanese has only
   38 pairs overall; Japanese code has none. Code answers have not been tested
   for functional correctness. Do not claim broad coverage from these counts.
3. No original-Mistral logits, KL anchors, teacher answers or generations were
   newly computed. Human-target rehearsal is not proof of base retention.
4. Select training-mixture weights and a finite update budget using student
   supervised-token denominators. Preserve memory-writing/reading world rows
   as a separate role; these preservation rows have **no memory**.
5. Finish rights/admission review, resource qualification, matched base controls
   and frozen non-regression criteria before any full FT.

Historical `FAIL / winner:none / non_regression NOT_ESTABLISHED` remains
unchanged. Training approvals, native updates, new learner/teacher generations,
judge requests and weight deletions are all zero.

## Reproduction and storage

Furnace artifact root:

```text
/home/ryospiralarchitect/spiralreality/SpiralReality/latent-preservation-bank01-20261021
```

`bank/rows.json.gz` contains canonical token arrays, masks and source excerpts.
`bank/index.json.gz` is the text-free metadata index copied here.
`inputs/oasst1/` holds the four pinned upstream files. Original Aether/QSpace
inputs remain in their existing locations, unchanged.

Run from a source tree containing the recorded script/module/plan bytes:

```sh
python -B scripts/build_native_preservation_bank.py verify \
  --aether /home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/artifacts/aether_next_pretrain_components_v2_2048_20260827 \
  --aether-eval /home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/artifacts/aether_pg19_curated_v2_eval_20260824 \
  --oasst /home/ryospiralarchitect/spiralreality/SpiralReality/latent-preservation-bank01-20261021/inputs/oasst1 \
  --qspace /home/ryospiralarchitect/spiralreality/SpiralReality/q_space_runs/datasets/cuda_dense_all_models_qkv/codexglue_codesearchnet_code_language_validation_n1000.json \
  --output /home/ryospiralarchitect/spiralreality/SpiralReality/latent-preservation-bank01-20261021/bank \
  --deps /home/ryospiralarchitect/spiralreality/SpiralReality/latent-preservation-bank01-20261021/deps
```

`build` uses an exclusive new output directory. `verify` is offline/read-only
and regenerates the entire bank; neither path loads model weights.
