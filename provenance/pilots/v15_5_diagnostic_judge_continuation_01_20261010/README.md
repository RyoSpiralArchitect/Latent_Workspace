# V15.5 diagnostic continuation 01: terminal partial result

Client date: 2026-10-10 (Asia/Tokyo). **HALTED_NO_RETRY**; combined status
**INCOMPLETE_OR_CALIBRATION_BLOCKED**. The continuation added **155 valid main
diagnoses**, then four calls timed out; **161 requests remain never dispatched**.
Combined main coverage is **343/512**, not a completed study. The old expression
gate remains **FAIL**. No learner update, new learner generation, provider
substitution, threshold/rubric change, or weight deletion was performed.

## Scope, provenance and terminal execution

This separately authorized continuation selected only the original 320
never-dispatched Mistral study r0 requests, in their frozen opaque-ID order.
Original paid source: `59ac10623c0f088d61481e1cfbb9898c206002b5`;
continuation paid source: `92bd66a0024f8c4b4442d1addfa4105f60287b96`, committed
and pushed before dispatch. All 1,042 files in the
[original bundle](../v15_5_diagnostic_judge_20261010/README.md), including its
historical partial report and analysis, remain byte-for-byte unchanged.

The original [calibration](../v15_5_diagnostic_judge_20261010/CALIBRATION_REVIEW.md)
is unchanged: Mistral passed with 16/16 expected-field matches and 8/8 equal
three-field repeat signatures; OpenAI failed with 15/16 matches and 6/8 equal
signatures against a 7/8 requirement. OpenAI's study remains undispatched.
There is no two-judge study consensus. Remote weight revision is UNKNOWN even
when the requested/returned model ID is unchanged.

The continuation reused `mistral-large-4`, temperature 0.2, seed 15501, a
16,384-token output cap, 1,200-second timeout, at most four concurrent calls and
at least two seconds between starts. No original reservation was retransmitted.
See the [protocol](../../../docs/v15_5/DIAGNOSTIC_CONTINUATION_01.md),
[seal](CONTINUATION_SEAL.json), [start receipt](mistral/study/STARTED.json),
[terminal receipt](mistral/study/FINISHED.json) and [handoff](EXECUTION_HANDOFF.md).

The process ran from **07:02:25 to 08:00:02 JST**. The last valid result arrived
at 07:40:02; the first timeout was recorded at 07:59:24. The four failures each
recorded `TimeoutError` after approximately 1,200.1 seconds. New admission
stopped on the first failure and the remaining in-flight calls drained; the
process has exited. The timeout does not identify a provider, intermediary or
local-network root cause. Remote execution and billing remain UNKNOWN.

The four new ambiguous request IDs are:

- `mistral-study-b1b5fdf238ae0984c5f812d8-r0`
- `mistral-study-b1e12d4a28f1534d6df992d1-r0`
- `mistral-study-b1f2d8555ce27de9450ae837-r0`
- `mistral-study-b24b0aebe2dad7e24fe0f8e4-r0`

They are additional to the four original timeout outcomes, not replacements.
The heartbeat was **paused at Ryō's request before termination**; this terminal
publication was followed directly in the chat. It remains paused.

## Complete accounting, including missing rows

The continuation's 320-coordinate selection has 159 reservations: 155 valid
responses, four ambiguous timeouts, and 161 never dispatched. There were no new
invalid diagnoses, no retries, and no new calibration/repeat/OpenAI requests.

| Combined setting / phase | Planned | Valid | Invalid | Transport result unknown | Not dispatched |
|---|---:|---:|---:|---:|---:|
| OpenAI calibration | 16 | 16 | 0 | 0 | 0 |
| OpenAI study r0 | 512 | 0 | 0 | 0 | 512 |
| OpenAI fixed repeats r1 | 32 | 0 | 0 | 0 | 32 |
| Mistral calibration | 16 | 16 | 0 | 0 | 0 |
| Mistral study r0 | 512 | 343 | 0 | 8 | 161 |
| Mistral fixed repeats r1 | 32 | 31 | 1 | 0 | 0 |
| **Total** | **1,120** | **406** | **1** | **8** | **705** |

There are **415 distinct reserved coordinates** and **407 recorded responses**.
Mistral's 374 valid study/repeat diagnoses comprise 343 r0 and 31 r1, not 374
unique main observations. The original invalid repeat remains
`mistral-study-17100d1c059ed3ecc160b8be-r1`: five added-fact evidence quotes where
the frozen limit is four. No quote was dropped and no label was repaired.

The original 512 learner outputs span **16 correlated world clusters**. They
are exposed development data, not independent tasks or an untouched test set.
Collection stopped twice in opaque-ID order; available diagnoses are not
assumed representative or missing at random. Do not extrapolate prevalence to
the unobserved remainder or interpret unavailable diagnoses as model failures.

## Content diagnosis with the renderer kept separate

Primary inline coverage is **171/256** (four unknown, 81 never dispatched).
Secondary query-only coverage is **172/256** (four unknown, 80 never dispatched).
The original strict scores for all outputs remain **84/256 inline** and
**1/256 query-only**. No model judgment rescues those scores.

| Frozen descriptive bucket | Inline, planned 256 | Query-only, planned 256 |
|---|---:|---:|
| Strict success | 58 | 1 |
| Incomplete observed text | 82 | 109 |
| Internal contradiction | 13 | 31 |
| Unambiguous wrong commitment | 13 | 9 |
| Explanation or grounding failure | 1 | 11 |
| Format-only candidate, **not rescued** | 4 | 0 |
| Abstention | 0 | 11 |
| Unavailable judgment | 85 | 84 |

Buckets are hierarchical: a length stop takes precedence over contradiction,
for example. Component axes remain separate in [SUMMARY.json](analysis/SUMMARY.json)
and [LEDGER.json](analysis/LEDGER.json). Mistral marked contradiction present in
23/171 available inline diagnoses and 44/172 query-only diagnoses, distinct
from the contradiction-bucket counts above. Diagnoses are not human gold.
Query-only respondents lacked the ranking facts; apparent truth matches do not
establish grounded capability.

Pooling raw and native chat would obscure the next learner decision:

| Inline renderer | Planned | Valid diagnoses | Unavailable | Strict-success bucket | Length bucket | Contradiction | Wrong commitment | Format-only | Explanation/grounding |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Raw | 128 | 84 | 44 | 0 | 82 | 0 | 0 | 2 | 0 |
| Native chat | 128 | 87 | 41 | 58 | 0 | 13 | 13 | 2 | 1 |

Thus **29 of the 87 diagnosed native-chat inline outputs fail strict scoring**:
13 contradiction, 13 wrong-commitment, two format-only, and one grounding case.
All 13 contradiction cases have a negative symbolic answer; wrong-commitment
cases include nine negative and four positive answers. This is a descriptive
subset, not a failure-rate estimate for all 128 native outputs. In the complete
machine inventory, native chat has two length stops and raw has 126; the two
native length stops lack diagnoses in this partial panel. Zero in its observed
length bucket therefore does **not** mean zero native truncation.

The observed native failures cannot all be explained by insufficient stopping.
The 82 diagnosed inline length failures all belong to raw rendering, so using
that pooled count to prioritize a native-chat EOS-only intervention would mix
different interfaces. This is a concrete refinement to the earlier partial
diagnosis, not a newly qualified instrument or evidence of an internal mechanism.

## Fixed repeat panel: unchanged, not remeasured

| Dimension | Equal / 31 valid pairs | Different |
|---|---:|---:|
| Commitment | 31 | 0 |
| Contradiction | 30 | 1 |
| Visible reasoning | 28 | 3 |
| Added facts | 26 | 5 |
| All four jointly | 25 | 6 |

Keep **25 equal, six different, one invalid** against the full denominator of
32. The continuation did not add repeats. Calibration admission used three
fields; study comparison uses four and has no post-hoc pass threshold.
Disagreements about meta-statements, hypothetical premises and truncated
explanations remain. Consistency does not prove correctness, and these labels
must not become automatic training targets.

## Verbatim illustrations, not representative examples

The first three examples are the first newly diagnosed inline ledger row in
each named bucket; the fourth retains the earlier short wrong-answer example
for contrast. This selection is post-hoc. The
[all-512-output human panel](analysis/DIAGNOSTIC_PANEL.md) retains all original
texts, facts, questions, literal evidence and unavailable judgments. Its title
uses "complete" for the output inventory, **not** judge coverage.

**Correct content, extra format:** `89f3d60346a5a601b10c3d20`, family0004,
full-chain / native chat / cue present / inline. The facts include
Joren > Aster > Kestrel > Luma and Fenn > Joren. Question: Is Joren ranked above
Luma? Symbolic answer: yes; EOS observed, whole-answer format fails.

```text
yes (transitive property: Fenn > Joren > Aster > Kestrel > Luma)
```

**Answer conflicts with its explanation:** `9db60525663ff106754b8281`,
family0001, atomic / native chat / cue absent / inline. Fact: Neris is ranked
above Aster. Question: Does Aster outrank Neris? Symbolic answer: no; EOS observed.
The visible text says yes and then denies that relation. The judge's favorable
reasoning label does not erase this conflict or establish hidden knowledge.

```text
yes (since the ranking is transitive, if Neris is ranked above Aster, then Aster is not ranked above Neris)
```

**Wrong answer with an unestablished conditional premise:**
`6cdf8806a56e76f4b6c15f97`, family0008, atomic / native chat / cue present / inline.
Fact: Ione is ranked above Aster. Question: Is Aster ranked above Ione? Symbolic
answer: no; EOS observed. A hypothetical intermediate node does not establish
the reversed relation. Mistral marked faulty reasoning but no added factual
assertion, illustrating why those axes must remain distinct.

```text
yes (assuming the ranking is transitive, if Aster was ranked above someone who was ranked above Ione, then Aster would be ranked above Ione)
```

**Short and terminated, but wrong:** `330a2cbcd94d10a9b4678dc7`, family0002,
full-chain / native chat / cue absent / inline, diagnosed in the original run.
Facts imply Eris > Joren > Fenn > Aster. Question: Is Aster ranked above Eris?
Symbolic answer: no. The case-folded whole-answer form is accepted, but its
truth value is wrong; lowercase compliance is separately false.

```text
Yes
```

## Usage and verification

| Receipt scope | Responses with usage | Input tokens | Output tokens | Frozen undiscounted estimate, USD |
|---|---:|---:|---:|---:|
| Original Mistral, including calibration | 236 | 257,581 | 1,024,652 | 4.63335552 |
| Continuation Mistral only | 155 | 169,266 | 652,234 | 2.95653988 |
| **Combined Mistral** | **391** | **426,847** | **1,676,886** | **7.58989540** |
| OpenAI calibration only | 16 | 15,034 | 7,145 | 0.1447600 |
| **Combined across providers** | **407** | **441,881** | **1,684,031** | **7.73465540** |

The bold Mistral subtotal is not an additional set of calls. Rates are from the
frozen plan; these estimates are not current-price quotes or invoices. Eight
ambiguous calls have no returned usage, so their billing is UNKNOWN, not zero.
The combined reserved-request upper bound is **$32.25306116**; the original
1,120-request plan bound remains $118.173444. The continuation's full 320-request
bound was $24.13401720, of which $11.99028936 was reserved for its 159 calls.

Both bundles replayed with exact summary/ledger/panel/raw-index agreement. All
79 original source/input files, three continuation source files and 1,042
original-bundle files verified unchanged. The original cue receipt verifier
returned `VERIFIED_RECEIPTS` with gate FAIL. All **274 selected local tests**
passed in 22.59 seconds; Ruff passed. No CI workflow is present and CI was not run.

The [executed offline validation notebook](VALIDATION.ipynb) independently
reconciles 1,120 planned / 415 distinct reserved / 407 returned coordinates,
usage, strata, unchanged repeats, four exact illustrative outputs and local
links. Its [builder/replay command](../../../scripts/build_v15_5_continuation_validation.py)
uses an isolated tooling environment, without changing the learner environment
or making API calls. [Validation receipt](RESULT_VALIDATION.json).

Three trailing-whitespace lines in the verbatim panel (7024, 13765, 16279) are
preserved original text, not prose-format errors to repair. Literal panel replay
passes with those spaces intact; publication whitespace checks exclude only
that generated panel. These are mechanical/analysis-QA checks, not scientific
qualification. Overall assessment: **share with caveats**.

## Carry-forward and next decision

The [learner proposal](../../../docs/v15/NEXT_STEPS.md) now keeps **native answer
content and answer-conditioned stopping as separate factors**. First preserve
the correct answer's question/fact binding and check finite-update behavior on
both reciprocal labels. Native answer CE versus the same CE plus verified-
answer-conditioned EOS remains an isolated candidate comparison, not a proven
fix or an explanation for wrong/conflicting answers. Do not globally shorten
free text or train on the judge's preferred clause.

Preserve workspace donor direction, zero/unrelated controls, fact-order
robustness, the pinned-base correctness floor and fresh matched qualitative
behavior as independent gates. This base-only diagnostic establishes none of
their learned improvements. Evaluator revisions need separately frozen
definitions and untouched controls; the old rubric and FAIL remain immutable.

Execution is closed as partial. The **161 never-dispatched requests are not
automatically authorized for a second continuation**; all eight ambiguous
calls and the invalid repeat remain excluded. After two timeout batches, a
bounded transport diagnosis is preferable to repeated blind relaunches. A new
instrumented execution policy or further paid run needs a separate decision.
No new experiment, PR or merge is authorized by this report.
