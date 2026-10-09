# V15.5 diagnostic judges: terminal partial result

Client date: 2026-10-10 (Asia/Tokyo). **HALTED_NO_RETRY** for Mistral study;
combined status **INCOMPLETE_OR_CALIBRATION_BLOCKED**. This is not completion of
the planned two-setting panel. The previous V15 expression gate remains **FAIL**.
No learner update, new learner generation, GPU run, weight deletion, or provider
substitution was performed.

## Scope and admission

The [frozen protocol](../../../docs/v15_5/DIAGNOSTIC_JUDGE_PROTOCOL.md) reused
all 512 stored pinned-base generations from the cue-confirmation experiment:
256 inline primary outputs and 256 query-only secondary controls. It separates
symbolic truth, strict parsing and termination from evidence-backed unary model
diagnoses. These outputs span 16 correlated world clusters, not 512 independent
tasks. All are exposed development data.

Paid inference used source `59ac10623c0f088d61481e1cfbb9898c206002b5` and the
unchanged [source seal](../../../configs/v15_5/DIAGNOSTIC_JUDGE_SEAL.json).
[Calibration](CALIBRATION_REVIEW.md) admitted Mistral Large 4: 16/16 expected-
field matches and 8/8 equal three-field repeat signatures. GPT-5.4 retained
FAIL: 15/16 matches and 6/8 equal signatures against a 7/8 requirement. Its
study was never dispatched. This is not a two-judge study consensus.

## Terminal execution and complete denominators

| Setting / phase | Planned | Valid diagnosis | Invalid diagnosis | Transport result unknown | Not dispatched |
|---|---:|---:|---:|---:|---:|
| OpenAI calibration | 16 | 16 | 0 | 0 | 0 |
| OpenAI study r0 | 512 | 0 | 0 | 0 | 512 |
| OpenAI fixed repeats r1 | 32 | 0 | 0 | 0 | 32 |
| Mistral calibration | 16 | 16 | 0 | 0 | 0 |
| Mistral study r0 | 512 | 188 | 0 | 4 | 320 |
| Mistral fixed repeats r1 | 32 | 31 | 1 | 0 | 0 |
| **Total** | **1,120** | **251** | **1** | **4** | **864** |

There were 256 reserved requests and 252 recorded provider responses. Four
requests have no returned response or usage receipt; remote execution and
billing are **UNKNOWN**, not zero. OpenAI's valid calibration responses did not
qualify its study. Mistral's 219 valid study/repeat diagnoses are not 219 unique
main observations: 188 are r0 and 31 are r1.

Mistral study started at 05:19:01 JST and finished draining in-flight requests
at **06:36:40 JST on 2026-10-10**. Each of the four terminal failures recorded
`TimeoutError` after approximately 1,201 seconds. New dispatch stopped at the
first failure; the other in-flight calls were retained as they timed out.
The record does not identify whether the timeout originated at the provider,
an intermediary, or the local network. No cell was restarted and no request
was retransmitted. See [terminal receipt](mistral/study/FINISHED.json).

The four ambiguous request IDs are:

- `mistral-study-69e56845c6faccbc29c8cf47-r0`
- `mistral-study-6a3e0f06e01e2960cfc09ebb-r0`
- `mistral-study-6a61091eaf7e0cd85102bd21-r0`
- `mistral-study-6b986e9ff2486d40db59447a-r0`

The invalid repeat, `mistral-study-17100d1c059ed3ecc160b8be-r1`, returned **five**
added-fact evidence quotes where the frozen validator permits at most four.
Offline replay raises `ValueError: Evidence list`. Its original response is
retained; no quote was dropped, label rescued, or replacement call issued.

## Partial content diagnosis, not corpus-wide prevalence

All original machine results remain available for the full 512-response bank.
Only 95/256 inline and 93/256 query-only r0 outputs have valid Mistral diagnoses.
Dispatch followed frozen opaque-ID order; the timeout creates an incomplete
prefix, not a new randomized or representative sample. No missing-at-random
assumption, population confidence claim, or extrapolated failure rate is made.

| Frozen descriptive bucket | Inline, planned 256 | Query-only, planned 256 |
|---|---:|---:|
| Strict success | 29 | 0 |
| Incomplete observed text | 44 | 63 |
| Internal contradiction | 11 | 13 |
| Unambiguous wrong commitment | 9 | 6 |
| Explanation or grounding failure | 1 | 4 |
| Format-only candidate, **not rescued** | 1 | 0 |
| Abstention | 0 | 7 |
| Unavailable judgment | 161 | 163 |

These buckets are hierarchical: a length stop takes precedence over a
contradiction bucket, for example. Full component axes remain in
[SUMMARY.json](analysis/SUMMARY.json) and [LEDGER.json](analysis/LEDGER.json).
Mistral marked contradiction present in 16 of the 95 available inline diagnoses,
including some incomplete texts; this is distinct from the 11 contradiction
buckets. A model diagnosis is not independently verified human gold.

Original strict correctness remains **84/256 inline** and **1/256 query-only**,
irrespective of judge availability. The 29 inline strict-success buckets above
cover only diagnosed rows. Query-only respondents lacked the facts; their
truth-relative matches cannot establish grounded capability. No old score was
replaced by commitment extraction or a preferred explanatory clause.

## Fixed repeat panel

All 32 additional calls were attempted. Thirty-one pairs have two valid
diagnoses; the remaining pair has the invalid r1 evidence list described above.

| Diagnostic comparison | Equal / 31 valid pairs | Different |
|---|---:|---:|
| Commitment | 31 | 0 |
| Contradiction | 30 | 1 |
| Visible reasoning | 28 | 3 |
| Added facts | 26 | 5 |
| All four jointly | 25 | 6 |

Keep **25 equal, 6 different, 1 invalid** against the full planned denominator
of 32. These are repeated measurements of fixed answers, not independent new
tasks. Study comparison uses four axes; calibration admission used three.
There is no post-hoc study pass threshold, and consistency does not prove truth.

The six disagreements include no-additional-fact versus entailed-meta-statement
judgments for justified abstentions, supported versus unclear truncated
explanations, and a hypothetical premise read as either an asserted false fact
or an unhelpful conditional. Thus the taxonomy/completion boundaries seen in
OpenAI calibration also appear within the admitted Mistral setting.

## Verbatim illustrations, deliberately not representative examples

The following retained outputs illustrate distinct failure modes; they do not
estimate prevalence or constitute new training targets. Selection is post-hoc:
the first inline ledger row in each of the four named buckets. Full visible facts,
questions, diagnoses, literal evidence spans and missing judgments are in the
[all-512-output human panel](analysis/DIAGNOSTIC_PANEL.md). “Complete” in that
generated panel's title refers to the original output inventory, **not** to
complete judge coverage.

**Format-only candidate:** `216b4bf4831b4ace1491ed55`, family0015 atomic d1,
native chat / cue absent / inline. Fact: Galen is ranked above Ione. Question:
Does Ione outrank Galen? Symbolic answer: no; EOS observed, strict failure.

```text
Based on the information provided, no, Ione is not ranked above Galen.
```

**Answer/explanation conflict:** `3815e6879abc8ca330352a71`, family0000 atomic d1,
native chat / cue absent / inline. Fact: Eris is ranked above Ione. Question:
Is Ione ranked above Eris? Symbolic answer: no; EOS observed, strict failure.

```text
yes (This is the opposite of the given fact, but since the ranking is transitive, if Eris is ranked above Ione, then Ione is not ranked above Eris.)
```

**Well-terminated but wrong:** `330a2cbcd94d10a9b4678dc7`, family0002 full-chain
d1, native chat / cue absent / inline. The supplied chain includes
Eris > Joren > Fenn > Aster. Question: Is Aster ranked above Eris? Symbolic
answer: no. The case-folded whole-answer parser accepts the form, but not the
truth value; lowercase compliance is separately false.

```text
Yes
```

**Correct conclusion with a false explanatory premise:**
`68db7a2d8383f327002f6df6`, family0007 full-chain d1, native chat / cue present /
inline. The facts imply Luma > Cyra > Neris > Joren > Kestrel, with Fenn > Luma.
Question: Does Joren outrank Luma? Symbolic answer: no; EOS observed, strict
failure. The explanation reverses the supplied Joren/Kestrel relation.

```text
No. (Joren is ranked below Luma, as Fenn is ranked above Luma and Joren is below Kestrel, who is below Luma.)
```

These examples distinguish excess text, incompatible commitment, incorrect
content, and unsupported explanation. They do not establish an internal
mechanism or show that a learned workspace caused any of these base outputs.

## Usage, replay and publication checks

API-reported usage, including calibration: OpenAI 15,034 input / 7,145 output
tokens; Mistral 257,581 input / 1,024,652 output tokens. Using the plan's
conservative undiscounted rates gives **$0.1447600 + $4.63335552 = $4.77811552**
for the 252 responses with reported usage. This is not an invoice or a cost for
the four ambiguous calls. The sum of reserved request bounds is **$20.26277180**;
the original full-plan bound remains $118.173444. Actual billed cost is UNKNOWN.

The frozen summarizer reproduced SUMMARY, the 512-row ledger, verbatim panel,
and every raw-index file hash. All 79 sealed source/input files revalidated.
The original cue verifier returned `VERIFIED_RECEIPTS` with expression gate
still FAIL. The selected local suite passed **241 tests** in 21.05 seconds;
Ruff passed. These are local checks, not CI or model-quality qualification.
No CI workflow is present in this checkout.

`git diff --check` reports three trailing-whitespace lines inside verbatim
generated-answer fences in `analysis/DIAGNOSTIC_PANEL.md` (lines 5792, 11397,
13523). They are preserved original output, not formatting edits to repair.
The check passes for the rest of the staged publication; exact panel replay
passes with those original spaces intact.

## Carry-forward and recovery decision

The [V15.5 proposal](../../../docs/v15/NEXT_STEPS.md) remains conditional:
qualify a separately frozen output instrument, then consider native answer CE
versus the same CE plus answer-conditioned EOS supervision as one isolated
factor. Restrict such termination supervision to its declared one-word task;
do not globally reward terse free text or assume EOS repairs wrong content.
Keep content direction, reciprocal queries, aligned serialization controls,
base correctness, and fresh qualitative behavior preservation separate.

Evaluator revisions should clarify world facts versus meta-statements,
hypothetical premises, and unfinished explanations, then use untouched
calibration controls. Do not repair the present rubric after observing outcomes
or train directly on unstable judge labels.

The current run is closed as partial. Recovery requires an explicit decision.
A possible new scope would handle only the 320 **never-dispatched** Mistral
requests in a separately recorded continuation, keeping the four ambiguous
requests and invalid repeat untouched. This is **proposed, not authorized or
executed**; the frozen runner does not support implicit resume. Neither these
results nor the timeout authorize new learning, OpenAI study calls, or a PR merge.
