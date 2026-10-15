# Fresh cue-by-envelope confirmation: no qualified generation interface

Client date: 2026-10-10. **Execution complete; primary expression gate FAIL.**
No optimizer updates, workspace weights, quality judges, or weight pruning.

Removing the literal ` Answer:` cue did not repair the pinned base's answer
interface. Native-chat inline strict correctness decreased from **44/64 with
the cue to 40/64 without it**. All four renderer/cue combinations failed the
frozen generation gate; none is promoted as a fallback winner.

There is a narrower positive diagnostic: with native chat and the cue retained,
atomic candidate ranking changes from **21/32 at the first token to 30/32 for
answer-plus-EOS paths**. This repeats the earlier initial-token/completed-answer
discrepancy on new instances. It is not repaired natural generation, a trained
workspace result, or a correctness-floor qualification. **V15 learning remains
deferred.**

## Frozen design and scope

- GPU source: `eabd3306d18e097ef69fbb398aa39750db1fd0ef`.
- [Protocol](../../../docs/v15/CUE_CONFIRMATION_PLAN.md),
  [machine plan](../../../configs/v15/CUE_CONFIRMATION_PLAN.json), and
  [frozen inputs](../../../configs/v15/CUE_CONFIRMATION_INPUTS.json).
- Pinned `mistralai/Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`; native BF16 full-vocabulary readout.
- Seed 15002 produces 16 six-entity worlds. Each contributes reciprocal yes/no
  queries for one atomic fact and a three-hop relation over five facts:
  **64 cases**. Eight families use `ranked_above`; eight use `outrank`.
- New exact world orders exclude 640 historical orders and eight preceding
  elicitation orders. All 16 new unordered atomic pairs are unique and exclude
  the 10 pairs exposed by that elicitation panel. Names and templates are reused;
  these are fresh instances, not unseen-vocabulary or unseen-task generalization.
- Cross raw/native-chat envelopes, cue present/absent, and query-only/inline
  facts: **512 prefixes, 2,048 forced one-token alias continuations, and 512
  greedy generations**. Atomic/full-chain and reciprocal cases within a world
  are related; the 512 outputs are not 512 independent reasoning trials.
- Cue removal deletes only the final eight characters ` Answer:` from the
  inference user content. The original query remains task metadata. No prompt
  demonstrations, new system message, grammar constraint, or whitespace repair
  was added. Exact renderings and token IDs are retained.
- EOS token 2 alone terminates generation, with 64 new tokens maximum and
  full-prefix recomputation, not a KV cache. Strict success requires the entire
  stripped, case-folded answer to be the correct `no` or `yes`, followed by EOS.
  Extra text and truncation fail; no first-word or explanation rescue is used.

The prospective primary method is **native chat / cue absent / inline**. Its
gate requires 64/64 valid EOS answers, at least 24/32 correct in each view, and
at least 12/16 correct in each view-by-wording and view-by-label slice. The
same gate is shown for comparators without making them alternative primaries.
Query-only conditions lack authoritative facts and are prior/format controls,
not equal-information capability baselines.

## Generation outcome

All counts below use the 64 inline cases per method.

| Envelope | Cue | Valid whole answer + EOS | Strictly correct | Length-limited | Gate |
|---|---|---:|---:|---:|---|
| Raw | Present | 0/64 | 0/64 | 64/64 | FAIL |
| Raw | Absent | 0/64 | 0/64 | 62/64 | FAIL |
| Native chat | Present | 51/64 | 44/64 | 0/64 | FAIL |
| Native chat | Absent, primary | 47/64 | 40/64 | 2/64 | FAIL |

The primary's failures are not explained only by a demanding format gate:

| Primary view | Valid EOS | Correct | Correct yes | Correct no | Reciprocal pairs both correct |
|---|---:|---:|---:|---:|---:|
| Atomic | 17/32 | 16/32 | 16/16 | **0/16** | 0/16 |
| Full chain | 30/32 | 24/32 | 12/16 | 12/16 | 9/16 |

Atomic correctness is 8/16 under each wording. Full-chain correctness is
13/16 for `outrank` and 11/16 for `ranked_above`, so its wording floor also
fails. The full-chain eight errors consist of six EOS-terminated wrong labels
and two length-limited explanations, both on positive queries.

Paired cue removal under native chat corrects **0** atomic cases and regresses
**5**, while changing generated token sequences in 14/32 cases. For full-chain
cases, it corrects **1**, regresses **0**, and changes tokens in 11/32 cases.
These are bounded descriptive contrasts, not a model-wide effect estimate.

Of the primary's 16 atomic negative cases, all terminate at EOS: 13 start with
`yes`/`Yes` (12 with additional text, one as a bare wrong answer); three explain
the correct negative answer but violate the whole-answer format. For example:

`family0000_atomic_d1`, correct answer `no`:

```text
yes (This is the opposite of the given fact, but since the ranking is transitive, if Eris is ranked above Ione, then Ione is not ranked above Eris.)
```

`family0011_atomic_d1`, correct answer `no`:

```text
Based on the information provided, Ione is not ranked above Mira. Therefore, the answer is "no".
```

These are illustrative retained failures, not selectively rescored successes.
Full IDs start with `v15-cue-seed15002-`; inspect **all 512 outputs** in the
[answer bank](ANSWER_BANK.md), including query-only controls and truncations.

## Initial choice, completed paths, and actual output are different observables

Four fixed suffixes (` no`, ` No`, ` yes`, ` Yes`) are validated as exact
one-token extensions. Within-class duplicate token IDs are counted once;
cross-class collisions are rejected. Class scores sum native full-vocabulary
probability mass, first for the aliases alone and then for each alias followed
by immediate EOS. No best-alias selection is used.

Each cell below is correct class rankings or strict generated answers **out of
32 inline cases**. Forced-path scores are diagnostics, not a changed decoder.

| Envelope / cue | View | Lowercase choice | Alias-start sum | Alias + EOS sum | Actual strict generation |
|---|---|---:|---:|---:|---:|
| Raw / present | Atomic | 32 | 32 | 32 | 0 |
| Raw / absent | Atomic | 32 | 32 | 32 | 0 |
| Raw / present | Full chain | 23 | 23 | 23 | 0 |
| Raw / absent | Full chain | 15 | 16 | 16 | 0 |
| Native chat / present | Atomic | 21 | 21 | **30** | 21 |
| Native chat / absent | Atomic | 19 | 19 | 20 | 16 |
| Native chat / present | Full chain | 25 | 25 | 25 | 23 |
| Native chat / absent | Full chain | 24 | 26 | 25 | 24 |

With native chat and the cue present, atomic completed-path ranking has
16/16 correct positive and 14/16 correct negative queries, with both directions
correct in 14/16 pairs. Actual generation gets both directions right in only
5/16 pairs. Removing the cue reduces completed-path correctness to 20/32:
answer-conditioned termination interacts with the prompt; it is not a universal
EOS fix. For full-chain reasoning, the completed-path score is 25/32 with either
chat cue setting and does not establish a qualified reasoning instrument.

Mean absolute probability mass covered by the four answer-plus-EOS paths is
shown below, rounded to six decimals. This includes **wrong-label mass** and
is neither correctness probability nor exhaustive accepted-answer probability.
The full-precision per-path values are in [SCORES.json](raw/SCORES.json).

| Envelope / cue | Atomic covered mass | Full-chain covered mass |
|---|---:|---:|
| Raw / present | 0.209748 | 0.174092 |
| Raw / absent | 0.047390 | 0.039470 |
| Native chat / present | 0.656320 | 0.895514 |
| Native chat / absent | 0.493657 | 0.813345 |

## Execution, resources, and verification

Furnace completed the frozen assay in **502.30 seconds** on the RTX 5090.
Torch peak allocation was **14.1255 GiB**, peak reservation **14.2598 GiB**;
sampled process memory reached **14.9219 GiB**. Minimum sampled device-free
memory was **16.4180 GiB**. The 18 GiB allocator cap is not a whole-process cap,
and sampled peaks are not continuous maxima. Admission required 20 GiB free;
the guard would abort below 4 GiB free. CPU use was limited to two threads,
with niceness 10. The post-run resource check found no compute processes.

There were 512 exact ordinary/shared native initial-logit checks, 2,560
shared/historical checks across scoring prefixes and alias continuations,
and 23,047 shared/historical generation checks. The base tensor hash before
and after was unchanged:
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.

The frozen portable verifier passed on both Mac and Furnace CPU, with
byte-identical validation and raw-index files. It verifies 66 source files,
raw hashes, scalar/categorical accounting, rendering receipts, and complete
denominators; it does **not** reload the model or reconstruct unretained full
logits/tokenizer execution. The new scalar tolerance policy was committed
before this run. The earlier completion diagnostic's exact Mac replay failure
remains unchanged and is not waived by this result.

[TESTS.md](TESTS.md) records 625 selected local regression tests, 58 remote CPU
tests, the real-tokenizer preflight, cross-host hashes, and the initial
tokenizer-only boundary failure and pre-scoring correction. Raw evidence is
indexed by [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json); the final portable receipt
is [VALIDATION.json](VALIDATION.json). Execution and resource details are in
[REPORT.json](raw/REPORT.json), [STARTED.json](raw/STARTED.json), and
[RESOURCES.jsonl](raw/RESOURCES.jsonl).

## Decision and claim ceiling

Do not remove `Answer:` as an accepted fix, select a comparator post hoc, widen
the gate, rescue first words, increase generation budgets after seeing answers,
or start V15 training on this result. There is no qualified winner here.

The useful next decision is whether to prospectively define **completed-answer
choice scoring as a separate instrument**, retaining free generation as an
independent outcome. That would need frozen acceptance criteria and another
untouched confirmation panel; it cannot convert this failed generation gate
into a pass. Repeated prompt search alone is not a substitute for deciding
which observable the learner is intended to improve. Answer-conditioned
completion remains a candidate learner factor, not a demonstrated repair.

The [updated next-step design](../../../docs/v15/NEXT_STEPS.md) preserves
aligned serialization controls, semantic donor direction, the base correctness
floor, and the earlier judge-motivated strengths as separate requirements.
This base-only assay did not measure any trained model's response quality.
`training_performed: false`, `semantic_promotion: false`,
`non_regression: NOT_ESTABLISHED`, `quality_judging: NOT_RUN`.
