# V15.5 calibration: one admitted judge setting, not a two-model consensus

Client date: 2026-10-10. Paid-source commit: `59ac10623c0f088d61481e1cfbb9898c206002b5`.
This is a **post-result diagnostic**. Neither the frozen rubric nor its admission
rules were changed after paid inference. The preceding V15 expression gate
remains **FAIL**; no learner was trained or regenerated here.

## Admission result

The eight analyst-constructed fixtures were each sent twice. They are not
independent human gold, and the 16 responses are not 16 independent cases.

| Frozen check | Required | GPT-5.4 snapshot | Mistral Large 4 |
|---|---:|---:|---:|
| Valid final JSON and literal evidence | 16/16 | 16/16 | 16/16 |
| All declared expected fields match | At least 14/16 | 15/16 | 16/16 |
| Both repeats match on wrong-bare, contradiction, fabrication controls | All | All | All |
| Equal commitment/contradiction/added-facts repeat signatures | At least 7/8 | 6/8 | 8/8 |
| Admission | All checks | **FAIL** | **PASS** |

The exact settings are `gpt-5.4-2026-03-05` with medium reasoning and an
8,192-token bound, and `mistral-large-4` with temperature 0.2, fixed replicate
seeds, and a 16,384-token bound. Those settings differ on several axes; this is
not an isolated family comparison. A returned model ID does not prove that a
remote weight revision is immutable.

Receipts: [OpenAI](openai/calibration/FINISHED.json),
[Mistral](mistral/calibration/FINISHED.json),
[frozen protocol](../../../docs/v15_5/DIAGNOSTIC_JUDGE_PROTOCOL.md).

## What failed, precisely

The OpenAI admission failure came from repeatability, not from commitment or
contradiction labels on these controls. Both of those fields matched the
declared expectation in all 16 responses.

| Control response | OpenAI replicate 0 | OpenAI replicate 1 | Consequence |
|---|---|---|---|
| `I cannot determine the ranking without facts.` | Added facts: `none` | Added facts: `entailed` | One expected-field mismatch and one repeat mismatch |
| `Yes, because Alder is above` (length stop) | Added facts: `entailed`; reasoning: `supported` | Added facts: `unclear`; reasoning: `unclear` | One repeat mismatch; reasoning itself is not an admission field |

For abstention, the second response treated “without facts” as an entailed
meta-statement about the empty visible-facts list; the first treated it as no
additional ranking fact. For the truncated explanation, one response read the
visible clause as aligned with the supplied relation and the other declined to
complete its unfinished predicate. These are meaningful taxonomy/completion
boundaries, not evidence that the model reversed the visible yes/no answer.

The truncated fixture deliberately has no absolute expected `added_facts`
label, **but that field still belongs to the frozen repeat signature**. Dropping
it now would change the admission rule after observing results. We retain FAIL
and leave OpenAI's 512 study judgments plus 32 repeats undispatched.

Mistral classified the abstention's added facts as `none` and the truncated
clause as `entailed` in both repeats. Its repeatability qualifies this particular
setting for the bounded diagnostic run; it does not establish that inferring
support from an unfinished clause is universally correct. Machine-detected
length stops remain incomplete outputs regardless of a favorable model label.

## Other retained uncertainty

- On the explicit contradictory answer, OpenAI called visible reasoning `none`
  in both repeats; Mistral called it `faulty` in both. Both identified conflicting
  commitment, internal contradiction, and unsupported facts. The reasoning
  field is not in the calibration gate, so this disagreement must not be hidden
  by the admission result.
- On the fabrication control, OpenAI's reasoning label changed from `supported`
  to `faulty`; its unsupported-added-facts label was stable. Mistral called the
  reasoning `supported` in both while still flagging unsupported added facts.
  A rationale for the original answer and an unrelated invented assertion are
  not necessarily scored at the same granularity by the two settings.
- Literal quote validation verifies that evidence occurs in the output. It
  does not prove the diagnosis or its entailment judgment.

## Implications for units 1–3 and a later learner

Only Mistral proceeds to the frozen 512-response diagnostic panel and its 32
fixed repeats. The full plan remains 1,120 requests across both settings;
OpenAI's 544 missing study/repeat judgments stay in denominators. There can be
**no two-judge study agreement claim** in this run, and an admitted single-family
judge remains an interpretation aid rather than a replacement truth oracle.

All symbolic truth, whole-answer parsing, EOS/length outcomes, and previous
failures remain unchanged. Content diagnoses may identify candidate format-only
failures, but cannot rescue the old strict gate or prove latent-state learning.

For a future, separately frozen evaluator revision, clarify meta-statements
versus additional world facts, incomplete predicates versus recoverable context,
and the granularity of “reasoning.” Confirm those definitions on untouched
controls before collecting new study judgments. Do not retry these controls
until they pass, revise the current seal, promote the admitted model to human
gold, or launch training from this calibration result.
