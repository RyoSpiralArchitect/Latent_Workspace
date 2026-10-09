# FT-beta: bounded synthesis of the three V14 judge settings

2026-10-09. Status: **ANALYST SYNTHESIS / NOT A NEW EVALUATION**.
This English note summarizes the original Japanese judgments and their sealed evidence.
It is not a translated replacement judgment, a new blind vote, or human evaluation.
No training, answer generation, judge calls, weight changes, or sealed-artifact edits are part of this note.
The companion [improvement plan](FT_BETA_IMPROVEMENT_PLAN.md) separates proposals from observations.

## Evidence and denominators

The current source is the [capacity bundle](../../provenance/pilots/v14_judge_capacity_20261009/README.md),
its [machine-readable summary](../../provenance/pilots/v14_judge_capacity_20261009/analysis/SUMMARY.json),
[complete answer/rationale panel](../../provenance/pilots/v14_judge_capacity_20261009/analysis/PANEL_REVIEW.md),
and [strict diagnostics](../../provenance/pilots/v14_judge_capacity_20261009/analysis/STRICT_DIAGNOSTICS.json).
OpenAI and Gemini are reused sealed observations, not new calls in the capacity run.
The [OpenAI-era summary](../../provenance/pilots/v14_judge_panel_20261009/analysis/SUMMARY.json)
and [extension summary](../../provenance/pilots/v14_judge_extension_20261009/analysis/SUMMARY.json)
remain historical records; their then-current missingness is not overwritten.

- All ten text-changed pairs were selected from 96 primary pairs; prior preference was not the selection rule.
  This is nevertheless a change-selected diagnostic bank, not a representative quality sample.
- All ten compare **legacy semantic** against base; none is a centered-reader success example.
  They comprise seven prompts and six task/world clusters, with five general and five relation pairs.
- Four exactly identical-answer controls are separate calibration pairs, not additional quality gains.
- Per setting: 14 pairs × two presentation orders, AB/BA, × five replicates = **140 planned calls**.
  AB assigns base to A and workspace to B; BA reverses this assignment.
- A replicate preference requires two valid order judgments agreeing after normalization to base/workspace.
  Five-repeat stability requires all five replicates to be valid, order-consistent, and identically preferred.
  Invalid/missing and order-conflicting outcomes are neither ties nor losses.
- Replicates are repeated calls on the same answers, not independent tasks or five independent judges.
  Providers, models, settings, and budgets differ together; a model-family-only effect is not identified.

| Judge setting | Saved / planned calls | Strictly valid | Stable W / T / nonstable, changed pairs | Stable base | Identical controls: stable tie |
|---|---:|---:|---:|---:|---:|
| OpenAI `gpt-5.4-2026-03-05`, low, 4,000-token cap | 140 / 140 | 140 | 2 / 3 / 5 | 0 | 4 / 4 |
| Gemini `gemini-3.8-flash`, LOW, 4,000-token cap | 140 / 140 | 140 | 1 / 5 / 4 | 0 | 4 / 4 |
| Mistral Large 4, temperature 0.2, 16,384-token cap | 140 / 140 | 136 | 1 / 4 / 5 | 0 | 4 / 4 |

Counts above were checked against the summary's per-order records, not inferred from the prose.
Strict validity certifies the JSON/quote contract, not a rationale's correctness.
Model IDs identify returned API products; they do not establish immutable remote weights.
Mistral Large 4 is the judge here, not the FT-beta Mistral-7B-Instruct learner.

## All ten changed pairs: retain disagreement and invalidity

W = workspace, B = base, T = tie, C = AB/BA conflict, I = invalid/missing replicate.
Each row contains five replicate outcomes per setting, not five independent tasks.
`summary`, `causal`, and `clarification` abbreviate `general-01-summary`, `general-05-causal`, and `general-08-clarification`.

| Case / generation regime | OpenAI | Gemini 3.8 | Mistral16k |
|---|---|---|---|
| summary / greedy | T5 | T5 | T4 C1 |
| causal / greedy | W5 | T4 C1 | W3 C2 |
| causal / sample211 | W5 | W5 | W5 |
| clarification / greedy | B1 T2 C2 | T5 | T5 |
| clarification / sample212 | B3 C2 | T5 | T5 |
| relation-01-forward / sample211 | T5 | T5 | T1 I4 |
| relation-01-forward / sample212 | B1 C4 | B2 T1 C2 | T1 C4 |
| relation-03-forward / sample211 | C5 | T5 | B4 C1 |
| relation-04-forward / sample211 | T5 | T1 C4 | T5 |
| relation-04-reverse / sample211 | T3 C2 | T1 C4 | T5 |

## Shared observation: one stable preferred pair, not general improvement

Only **general-05-causal / sample211** has stable workspace preference in all three settings.
Base has 80 whitespace-separated words; workspace has 54, satisfying the 60-word limit.
The cautious conclusion is retained, and the follow-up changes from before/after measurement
to a separate-team test with unchanged logging. This is a bounded, repeatedly preferred textual change.
It does not establish that workspace acquired valid causal experiment design: the answer does not
explicitly specify a contemporaneous no-checklist group or randomization.

The rationales do not all support the preference in the same way. Some emphasize design wording,
others the length constraint, and some read an untreated comparison into an answer that does not state it.
Agreement on the winner is not agreement on a valid explanation or three independent replications.
The four identical controls are stable ties throughout, but equally wrong answers can also tie.
No changed pair is a stable tie across all three settings; absence of stable base wins is not non-regression.

## OpenAI: repeated preference for a comparison-oriented follow-up

OpenAI's two W5 pairs are **the same causal prompt**, greedy and sample211.
For `causal / greedy`, r0 AB and BA favor the “separate, controlled group” phrase over
temporarily suspending the checklist, interpreting it as closer to the reference comparison.
See the original [r0 AB](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-5e78466d882107046c19-AB.json)
and [r0 BA](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-5e78466d882107046c19-BA.json).
Both answers violate the limit, however: **79 → 80 words**, not a length improvement.
The missing untreated comparison limits the design claim even when the wording is consistently preferred.

For `causal / sample211`, [r0 AB](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-da8cdd651c14ade06f1f-AB.json)
combines the shorter answer, cautious conclusion, and a perceived more concrete comparison in its rationale.
This supports preserving the candidate behavior for further tests, not labeling it content-causal success.

The partial base preference on `clarification / sample212` is also informative: B3 C2.
[r0 AB](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-3bad153670799cedc584-AB.json)
finds base's wording more straightforward and workspace's “アナライズしてください” ("please analyze it")
and “決定してください” ("please decide it") unnatural in context.
It also recognizes that both are truncated and fail the requested two-question form.
This is a relative wording preference amid shared failure, not an acceptable base answer.

Counterexample: `relation-03-forward / sample211` is C5.
[r0 AB](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-1915711d71c2e39d8256-AB.json)
detects base's compliance and workspace's excess over 30 words, preferring base;
[r0 BA](../../provenance/pilots/v14_judge_panel_20261009/cells/openai/r0/responses/openai-r0-1915711d71c2e39d8256-BA.json)
instead ties them and says both likely violate the bound. Mechanical truth is **29 → 32 words**.

## Gemini 3.8: shared constraint failures often dominate small wording changes

For `causal / sample211`, [r0 AB](../../provenance/pilots/v14_judge_extension_20261009/cells/gemini/r0/responses/gemini-r0-da8cdd651c14ade06f1f-AB.json)
makes length compliance central, but reports **66/48 words**, not the observed 80/54.
It also describes an independent control more strongly than the answer itself warrants.
The preferred side satisfies the actual limit, but the rationale's exact counts and design reading are not gold.

`causal / greedy` is T4 C1, contrasting with OpenAI's W5.
[r0 AB](../../provenance/pilots/v14_judge_extension_20261009/cells/gemini/r0/responses/gemini-r0-5e78466d882107046c19-AB.json)
treats the two follow-up designs as reasonable and their shared length violations as comparable.
Both clarification pairs are T5; for example,
[greedy r0 AB](../../provenance/pilots/v14_judge_extension_20261009/cells/gemini/r0/responses/gemini-r0-20eab673d93c4a3dea88-AB.json)
points to excessive questions and overlength already visible before truncation.
Here tie means comparably failing, not comparably successful.

Counterexample: `relation-03-forward / sample211` is T5 despite workspace alone exceeding 30 words.
[r0 AB](../../provenance/pilots/v14_judge_extension_20261009/cells/gemini/r0/responses/gemini-r0-1915711d71c2e39d8256-AB.json)
reports 27/29 words and treats both as compliant while correctly flagging the wrong “No” and invented explanation.
Its speculation that both models lacked world facts is not an observation of their input pathways.

## Mistral16k: capacity recovered; quotation and interpretation weaknesses remain

All 140 requests produced saved, normally stopped responses: no truncations, HTTP failures, or undispatched calls.
Reported completion length is 3,695 / 7,154 / 14,988 tokens for minimum / median / maximum;
139/140 exceed the old 4,000-token cap. This resolves capacity for this input set, not all future inputs.

The sole W5 is `causal / sample211`.
[r3 AB](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r3/responses/mistral-r3-da8cdd651c14ade06f1f-AB.json)
is a particularly bounded rationale: it makes 80/54-word compliance decisive while explicitly acknowledging
that neither answer specifies the ideal comparison and workspace lacks an explicit untreated group or randomization.
For greedy, W3 C2 does not corroborate OpenAI's stable preference: r0
[AB](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r0/responses/mistral-r0-5e78466d882107046c19-AB.json)
favors workspace's controlled-group wording, whereas
[BA](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r0/responses/mistral-r0-5e78466d882107046c19-BA.json)
favors base's explicit on/off comparison and criticizes workspace's unspecified untreated comparison.

`relation-03-forward / sample211` is B4 C1. Its
[r1 AB](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r1/responses/mistral-r1-1915711d71c2e39d8256-AB.json)
correctly gives 29/32 words and says the relative base win does not make either answer correct.
But [r0 BA](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r0/responses/mistral-r0-1915711d71c2e39d8256-BA.json)
incorrectly calls both within 30 words and returns tie. Mistral is not a replacement mechanical checker.

Preference stability also differs from score stability. For `clarification / greedy`, r0
[AB](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r0/responses/mistral-r0-20eab673d93c4a3dea88-AB.json)
and [BA](../../provenance/pilots/v14_judge_capacity_20261009/cells/mistral_cap16384/r0/responses/mistral-r0-20eab673d93c4a3dea88-BA.json)
both tie, but both answers' calibration scores change from 0 to 4.
AB penalizes constraint neglect as overconfidence; BA rewards not inventing a deadline.
This is a concrete rubric-interpretation example, not a population-level estimate of order effects.

The four invalid judgments are exactly `relation-01-forward / sample211`, **BA, r1–r4**.
They insert absent `in` into base's “such as a particular category or competition” quote.
The [diagnostics](../../provenance/pilots/v14_judge_capacity_20261009/analysis/STRICT_DIAGNOSTICS.json)
retain each raw path, hash, and rejection: no quote repair or substitute votes. Keep **T1 I4**, not T5.

## Exclusions and the ceiling on interpretation

Old Mistral4k is a separate method: 140 planned, 95 reserved, 93 saved, one strict-valid judgment,
92 truncated responses, two HTTP failures, and 45 undispatched calls.
Its only valid vote is one identical-control AB judgment; it has no valid changed-pair vote or complete AB/BA pair.
The new 16k votes do not repair its denominator, and returned model identity does not prove unchanged preview weights.
Claude was skipped by user decision after a metadata GET returned 401; study/generation/capacity-probe calls were zero.
See the preserved [scope update](../../provenance/pilots/v14_judge_capacity_20261009/SCOPE_UPDATE.md).

English word checks are post-hoc `len(answer.split())` diagnostics, not tokenizer or linguistic counts.
They do not check Japanese character limits, rewrite historical votes, or resolve semantic correctness.
For relation tasks, query-only base and fact-bearing workspace are unequal-information conditions.
The unchanged “No,” fluent explanation, or judge tie does not demonstrate memory grounding.
For clarification, visible violations already precede truncation; an imagined continuation cannot rescue them.

The learner-facing hypothesis is to preserve cautious, useful, constraint-compliant changes while testing their cause.
It is not to imitate preferred wording or train directly on these selected labels.
The [companion plan](FT_BETA_IMPROVEMENT_PLAN.md) retains G0/G1 and matched-content controls before learner changes.
Three judge settings do not establish quality, non-inferiority/non-regression, human agreement, latent capability,
or memory-content causality. Retain **`winner: none`**, **`semantic_promotion: false`**,
**human evaluation `PENDING`**, and **non-regression `NOT_ESTABLISHED`**.
