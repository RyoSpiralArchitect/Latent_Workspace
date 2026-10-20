# Native world bank 01 — deterministic data, not a trained result

2026-10-21 JST. Source `a33c373ba542a632f5dab3b708ffba09ebec12ef`,
702 sealed source files. The bank is original programmatic fictional data,
not imported benchmark, historical judge or exposed beta evaluation material.
The generator, exact plan, compressed rows, instruction references, teacher
selection and hashes are preserved under `furnace/`.

## Population and checks

| Split | World groups | World rows | Role |
| --- | ---: | ---: | --- |
| train | 768 | 6,144 | Six trained-family candidates |
| dev | 96 | 768 | Group-disjoint development |
| test | 96 | 768 | Group-disjoint, same-family evaluation |
| OOD | 64 | 512 | Entire owner-to-location composition family held out |
| total | 1,024 | 8,192 | 2,048 original/twin world variants |

Each group contains two counterfactual sides and affected, unaffected, absent
and unrelated-memory questions. Canonical answers/evidence are computed from
visible atoms, independently of the stored answer fields. Rendering, answer,
evidence and memory hashes are checked for every row. Full regeneration and
byte-manifest replay pass; cross-split group and exact-text overlaps are **0**.
The six training families are location, ownership, transitive order, event
order, inventory arithmetic and latest-version lookup.

**Do not equate 8,192 rows with independent problems.** There are **2,048**
within-split exact-content duplicates: paired absent/unrelated controls retain
their side identifiers for causal comparison. Unique world content rows:
6,144 overall. All siblings stay in one split. There are no declared training
sampling weights; duplicated controls must not silently double their influence.

The **128 no-memory instruction seeds** contain 16 examples each of arithmetic,
sorting, extraction, JSON formatting, translation, small Python functions,
short-passage reading and polite rewriting. Translation and rewriting targets
are explicitly assistant-authored references, not unique gold. Other targets
come from executable templates. This is a deliberately small starter, not a
coverage or capability-retention guarantee; it has no separate instruction
evaluation split.

## Pinned student token accounting

[Token summary](furnace/student_tokens/SUMMARY.json) uses Mistral-7B-Instruct-v0.3,
revision `c170c708c41dac9275d15a8fff4eca08d52bab71`, its chat template, a leading
space before the answer and EOS. It counts tokens, not model quality.

- 8,320 total world/instruction rows; **49,768 supervised tokens** across all
  splits. Training candidates: **37,615**, including only **1,523** instruction
  tokens. Evaluation tokens are not training tokens.
- Maximum memory: **78 tokens**; query including answer: **58**; answer
  including EOS: **24**. **0/8,320** rows exceed either tested 128-token axis.
- No truncation, training admission, optimizer update or teacher text is
  included in these canonical-bank counts.

Being within a synthetic backward length bound does not itself establish
update/save/restart fit or generalization. Row-uniform mixing would give
ordinary instructions only about **4.05%** of supervised training tokens.
That is an accounting warning, not a selected FT recipe.

## Teacher use and next gate

The fixed inspection selects **48 affected world examples** (four twin pairs
from each of six training families) and **16 instructions** (two per family).
No dev, test or OOD row is sent to the teacher. World answers/evidence are
provided to the teacher for language rendering, so it is not an independent
correctness judge. Every output remains quarantined until semantic review.

Before full FT, freeze the sampling/token budget by role, control duplicate
weighting, a substantially broader no-memory preservation population and an
unseen evaluation with the original-base non-regression rule. A larger
teacher's prose is not an original-Mistral preservation target. Keep those
purposes separate rather than letting teacher style replace the base by default.

Mixture weights, update count and training admissions remain **UNSET / 0**.
Historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.

```sh
python scripts/build_native_world_bank.py verify \
  --output provenance/data/native_world_bank01_20261021/furnace/bank
```
