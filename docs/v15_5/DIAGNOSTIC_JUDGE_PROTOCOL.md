# V15.5 units 1–3: diagnostic judging, not a new learner

Client date: 2026-10-10. Freeze before paid inference. The preceding V15 strict
expression gate remains **FAIL**. This protocol neither relaxes it nor qualifies
a decoder, a learned workspace, or the pinned-base correctness floor.

## Units and inputs

1. Freeze and reuse all 512 stored generations at parent `5983acb`. Independently
   solve the 64 fact graphs and reproduce exact whole-answer/EOS accounting.
2. Separate machine facts (truth, strict parsing, stop reason, lengths) from
   unary model diagnoses (expressed commitment, internal contradiction, visible
   reasoning, additional unsupported facts). A correct clause in a contradictory
   answer is not a rescued strict success. No unseen continuation is inferred.
3. Calibrate two judge settings, then diagnose all responses and a balanced
   fixed repeat panel. No learner alteration, training, answer regeneration,
   online answer rewriting, human-gold creation, or checkpoint deletion.

The main stratum is all 256 inline outputs. The 256 query-only outputs are
separate prior/format controls; their respondents did not receive facts. A
truth-relative label match there is not evidence of grounded capability.
All are exposed development diagnostics, not new independent confirmation data.
There are 16 world clusters, not 512 independent tasks.

## Blinded unary task

Each stateless request contains exactly one unmodified response, its observed
stop reason, a canonical question, the common one-word task instruction, and
only facts the respondent actually received. The `Answer:` cue and envelope
are omitted from the judge view; the original renderings stay in the parent.
This deliberately measures response content on a common view, not judge
reconstruction of the native token interface. Model/condition names, gold
labels, existing scores, opaque record IDs, and calibration expectations are
not sent. Wording/style may still reveal clues; blinding is not perfect.

The fixed schema records commitment (`yes/no/conflicting/abstain/no_answer/unclear`),
contradiction (`present/absent/unclear`), visible reasoning
(`supported/faulty/none/unclear`), and added facts
(`entailed/unsupported/none/unclear`). Evidence must be exact substrings of the
response. Local validation supplies all matching code-point offsets; judges do
not count offsets or words. Literal evidence validates attribution, not whether
the judge interpreted it correctly. Reasoning is visible explanation, not hidden
chain of thought or a mechanistic localization.

No best-answer vote is requested. Unary requests avoid paired A/B placement but
do not establish freedom from order, style, length, or model-family bias.
Synthetic data is marked untrusted in the fixed instructions. All malformed,
truncated, refused, missing, and unclear judgments remain distinct and visible.
There is no quote repair, response rewriting, automatic retry, or majority gold.

## Calibration and repeatability

Eight constructed controls cover bare correct positive/negative answers, a
verbose correct negative, a bare wrong answer, an explicit unresolved
contradiction, an invented fact, justified abstention without facts, and
truncation. Each is sent twice with the same payload. Expectations are a frozen
analyst-constructed calibration fixture, not independently collected human gold.
They are neither study rows nor learned-target examples.

Each provider must have 16/16 valid schema/evidence responses, at least 14/16
matching all declared expected fields, both repeats correct on contradiction,
fabrication, and bare-wrong critical controls, and at least 7/8 repeated control
signatures equal. Signatures use commitment, contradiction, and added facts;
visible-reasoning judgments are retained but do not silently expand calibration
acceptance. Failure prevents that provider's study dispatch. The other provider
can proceed independently; all unfilled planned rows remain in denominators.

For the main run, one response is preselected by lowest opaque SHA-256 ID in
each renderer × cue × information × view × gold-label stratum: 32 extra
evaluations. Selection does not inspect generated text, strict success, or judge
outputs. Full four-field signatures are compared, with invalid/missing repeats
reported separately. These are repeated measurements, not independent examples.

## Settings, bounded execution, and provenance

The machine plan pins GPT-5.4 `gpt-5.4-2026-03-05`, medium reasoning, 8,192
output tokens; and `mistral-large-4`, temperature 0.2, 16,384 output tokens.
Both are larger-model judge settings, not the Mistral-7B learner. The prior
Mistral capacity experience motivates the 16k bound; this is still a distinct
new unary rubric. Only final assistant content is scored, not thinking chunks.
Provider/model, reasoning, decoding, and output budgets differ together, so no
pure model-family effect is identified. Returned IDs do not prove immutable
remote weights, particularly for the Mistral public preview.

Per provider: 16 calibration + 512 primary observations (256 inline, 256
query-only) + 32 repeats = **560**, or **1,120 planned paid requests** in total.
Concurrency is at most four per provider with at least two seconds between
starts. At the first HTTP/transport failure, stop new dispatch for that provider
and retain already-in-flight outcomes. A reserved request is never retransmitted.
An already-started cell cannot be launched again by this runner. Interruption
or a terminal stop requires an explicit recovery/scope decision; saved outcomes
remain replayable without a new API call.

Requests, raw responses, usage, response IDs, source/dataset hashes, statuses,
and literal-span checks are retained. Output reservations are exclusive.
No plaintext credentials, headers, provider error bodies, or exception strings
are recorded. Only the two official HTTPS endpoints are allowed and redirects
are rejected. Keys stay in the local environment; Furnace/GPU is not needed.

Pricing references checked on the client date:
[OpenAI model](https://developers.openai.com/api/docs/models/gpt-5.4),
[OpenAI standard pricing](https://developers.openai.com/api/docs/pricing), and
[Mistral model/pricing](https://docs.mistral.ai/models/mistral-large).
Bounds use undiscounted $2.50/$15 input/output per million for OpenAI and
conservative original $1.36/$4.18 for Mistral, ignoring the displayed launch
discount and cached-input discounts. UTF-8 request bytes bound the request's
text token volume; service-added/internal accounting is not observable. API
usage and bound exceedances are retained. Actual invoice cost is UNKNOWN.

## Analysis and ceiling

Publish all machine outcomes and every judge diagnosis, including disagreement.
Report denominators by information condition, envelope, cue, view, label, and
world. Commitment matches joined to symbolic truth are not new strict accuracy.
An EOS-terminated strict failure with a correct unambiguous commitment, no
internal contradiction, supported/absent reasoning, and no unsupported added
fact is a **format-only candidate according to that judge**, not a rescued pass.
Contradiction, wrong commitment, incomplete output, abstention, and unresolved
cases stay visible; full component axes take precedence over a summary bucket.

After both settings, agreement can nominate failure modes for a later controlled
intervention; it cannot establish their internal cause. Preserve uncertainty
and human review targets. Do not feed these selected responses or judge prose
straight into training. A future V15.5 learner needs a separate frozen single-
factor experiment and untouched confirmation families. Natural-generation
quality, content direction, and the base correctness floor remain separate
requirements. No learner experiment is authorized by a calibration pass.
