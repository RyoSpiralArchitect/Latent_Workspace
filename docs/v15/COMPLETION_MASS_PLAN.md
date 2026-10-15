# Pre-V15 learning: fixed answer-plus-EOS mass diagnostic

Client date: 2026-10-10. **POST-RESULT PROTOCOL / NOT EXECUTED**.
The machine contract is [COMPLETION_MASS_PLAN.json](../../configs/v15/COMPLETION_MASS_PLAN.json).
This is one bounded no-training scoring diagnostic, not another generation
qualification attempt or a modification of the completed elicitation assay.

## Why this question remains open

The preceding base-only assay did **not** establish that native chat fixes the
instrument. Native-chat inline greedy confirmation terminated all 32 answers,
but only 24 were valid whole yes/no answers and 16 were strictly correct.
Atomic outcomes were 9/16 correct, including all eight positive targets but
only one of eight negatives. The seven other atomic-negative responses began
with the wrong lowercase `yes` and then continued with explanations. Their
first-token `yes` probabilities were approximately 0.644--0.900, so omitted
capitalized aliases cannot explain those first-token decisions: each wrong
lowercase `yes` already had more mass than the rest of the vocabulary combined.

Conversely, raw inline initial choice scoring was 16/16 on atomic cases and
12/16 on full-chain cases, while all 32 raw greedy generations failed the
whole-answer contract. A high probability of a label token does not establish
a high probability of that label **followed immediately by EOS**. Three
native-chat full-chain outputs also used capitalized `Yes`; these were already
correct under the casefolded scorer, but lowercase-only choice probes omit
their probability mass.

The new question is therefore **how label-start mass differs from complete
label-plus-EOS mass**, not whether capitalization retrospectively rescues the
failed outputs or proves why the model made its errors.

## Immutable predecessor and model

Use the complete existing
[elicitation artifact](../../provenance/pilots/v15_base_elicitation_20261010/ARTIFACT_INDEX.json),
whose source commit is `9983e42d082a9452feedc60bb0b72d0b810795b8` and whose
artifact-index SHA-256 is
`45563fddd8edcc3cf1ce150cdc777b0d1012848632b8bab830aaa597ed6b1d7b`.
Verify that artifact and its recorded `FAIL` before execution. Do not edit any
sealed source or predecessor raw file.

The Mistral-7B-Instruct-v0.3 revision remains
`c170c708c41dac9275d15a8fff4eca08d52bab71`, with base state SHA-256
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.
Check the pinned tokenizer/template metadata and base identity before and
after the run. The base remains frozen; there is no workspace checkpoint,
optimizer, parameter update, or new weight file.

## Inputs and symmetric fixed paths

Reuse all **144 exact initial prompt-ID sequences**: 36 existing cases crossed
with raw/native-chat rendering and query-only/inline information. Do not
rerender, add an instruction, change the answer cue, construct a new case, or
select only failures. Preserve historical split labels as provenance, but
**all cases are now exposed**; none constitutes untouched confirmation here.

For every prefix, bind the same four prespecified textual suffixes:

| Class | Fixed suffixes |
|---|---|
| no / 0 | ` no`, ` No` |
| yes / 1 | ` yes`, ` Yes` |

Require that encoding each prefix-plus-suffix preserves every original prefix
token and adds exactly one token. Record all **576 string-binding receipts**.
Deduplicate equal token IDs within each class so equivalent paths are not
counted twice; reject any cross-class token collision. The number of distinct
scored paths is the sum of the unique within-class IDs for all prefixes, at
most 576. Binding failure stops the diagnostic rather than triggering another
alias, alternate prefix, or multi-token fallback.

Every distinct path is that one forced alias token followed immediately by
the pinned model EOS token, ID 2. Both class alternatives are scored for every
prefix regardless of its oracle label. The target label and historical answer
do not choose a branch, a suffix, or any token supplied to the model.

## Probability decomposition

At each original prefix, obtain the actual native full-vocabulary logits and
apply FP64 `log_softmax` over the full vocabulary, without temperature scaling.
For each unique alias token `a`, separately forward the complete original
prefix plus `a`, using `use_cache=False`, and obtain the full-vocabulary
conditional EOS log probability. This is teacher forcing, **not generation**.

For class `c`, record:

```
start_log_mass[c]    = logsumexp(log P(a | prefix))
complete_log_mass[c] = logsumexp(log P(a | prefix)
                                + log P(EOS | prefix, a))
```

Each sum includes **all** unique aliases assigned to the class. There is no
best-alias, best-path, maximum-probability verbalizer, or outcome-based alias
selection. Preserve each path's start/EOS/joint log probabilities as well as
the two class aggregates. Check that complete path mass cannot exceed its
start mass and that each total covered mass is bounded by one.

Record the unnormalized class masses and their sum for both start and complete
scoring. Also report the separately labeled probabilities conditional on this
finite two-class path set, plus its strict-greater-mass prediction. Exact ties
are unknown and not correct. Conditional probabilities must not be presented
as unconditional chances of a valid response: the omitted vocabulary and
other continuations can have most of the actual probability mass.

This four-string set is **not** an exhaustive enumeration of outputs accepted
by the historical parser. Other whitespace, capitalization and tokenization
paths may decode to accepted text. The diagnostic neither estimates all
valid-answer probability nor changes the parser's definition.

## Comparisons and verification

Recheck ordinary/shared native full-logit parity and exact replay of the
historical lowercase choice logits on every original prefix. Keep model,
precision, head, tokenizer and prefix geometry pinned so a score change cannot
be attributed to a different model call silently. The next-token distributions
after forced aliases are new observations, not historical generation replay.

Publish per-prefix comparisons of historical lowercase-only choice prediction,
all-alias start prediction, and complete-path prediction. Summarize correctness,
ties, reciprocal-pair both-correct counts, per-label counts, and paired changes
by renderer, information, original split, view and wording. Show coverage mass
beside conditional classification so an attractive closed-set result cannot
hide negligible probability of producing one of these paths.

Do not replace the historical **288 generated outputs**, their parser results,
their strict accuracy, or their failed primary gate. A higher complete-path
classification score would only describe this post-hoc scoring method on
exposed examples. It would not show that the model generated a better answer,
that the instrument is qualified, or that the preferred judge behavior was
preserved. There is no new quality/correctness acceptance gate or renderer
selection in this unit.

The portable verifier should recompute deduplication, scalar path/class sums,
covered mass, conditional normalization, ties, paired classifications and the
complete denominator from receipts. It can verify recorded source/artifact
identities and accounting, not independently reproduce GPU full logits or
model-state hashes without reloading the model. Preserve that distinction.

## Execution bounds and stop

Use one clean isolated Furnace worktree and the offline pinned cache. Retain
the prior resource contract: at least 20 GiB free at admission, an 18 GiB Torch
allocator cap, abort only this run below 4 GiB sampled device-free memory,
two CPU threads, and `nice 10`. Report Torch allocated/reserved peaks separately
from sampled process usage; the allocator cap does not cover all process GPU
allocations.

Run exactly this fixed scoring panel, publish the receipts and analysis, then
stop. No further experiments, new generation, training, workspace intervention,
new prompt, gain/cap adjustment, decoder constraint, paid judge, weight
deletion, or FT-beta release decision is included. `semantic_promotion` remains
false and non-regression remains `NOT_ESTABLISHED` regardless of the diagnostic
classification result.
