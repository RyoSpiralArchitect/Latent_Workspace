# V14 additive three-family judge panel

Prospective extension, 2026-10-09 JST. This does not rewrite the sealed original
panel, generate new model answers, train a learner, or delete weights.

## Fixed study and changed provider selection

Reuse the original 140 OpenAI judgments exactly once, by reference to the sealed
`v14_judge_panel_20261009` bundle. Add Mistral Large 4 and Gemini 3.7 Flash, each
with the same 10 changed pairs and four identical-answer controls, both orders,
and five repetitions: 140 new requests per provider, 280 new / 420 total.
The original selection, rubric, strict schema, literal-quotation validator, and
blinding stay unchanged. No score-dependent sampling, quote repair, replacement
judges, or majority-vote gold labels. Selected generations remain evaluation
data, not learner-training examples. Seven prompts / six task-world clusters
underlie the ten changed pairs; repetitions do not increase that denominator.

The user explicitly selected `gemini-3.7-flash` before any new study request.
An earlier `gemini-3.1-pro-preview` connection canary is retained separately,
not pooled. Model availability and API-contract canaries are not study evidence.
The subsequent 3.7 canary returned `modelVersion: gemini-3.8-flash`, so Gemini
study dispatch is BLOCKED on model identity. The cause is UNKNOWN, not evidence
that 3.7 was retired or equals 3.8. No accepted-ID list is widened. A user-approved
model change would require a separately recorded prospective amendment before
Gemini study calls; Mistral may execute independently.

## Prospective provider settings

- Mistral: explicit `mistral-large-4`, temperature 0.2, seeds 1001–1005,
  `standard_only`, 4,000 maximum output tokens. Exact frozen parent request
  bodies are reused, including omission of `reasoning_effort`. The server's
  default reasoning behavior is not a controlled reasoning-budget intervention.
- Gemini: explicit `gemini-3.7-flash`, temperature 1.0, seeds 1001–1005,
  `thinkingLevel: LOW`, `includeThoughts: false`, one candidate, 4,000 maximum
  output tokens. No tools, grounding, cached-content object, or batch service.
  Thinking usage is still included in output-token accounting.
  This is a blocked proposal, not an executed setting. Newer official 3.6+
  guidance says temperature is ignored and candidate-count is unsupported;
  canary acceptance does not prove their effective control. They would be
  omitted in any future approved Gemini amendment.

Each exact returned model ID must match its requested ID. A stable product ID
does not expose immutable weights. OpenAI snapshot, Mistral preview and Gemini
stable ID have different identity ceilings. Provider settings and compute are
not matched; seeds do not guarantee deterministic results or matched randomness.

## Compatibility preflight, not judgment repair

The identical-answer Mistral canary returned a successful API response with a
`message.content` list containing thinking and final-text chunks. The old
string-only parser failed. Both raw response and original failure receipt stay
untouched. A new, separately hashed Mistral adapter extracts final text only,
then applies the unchanged strict JSON/schema/exact-quotation checks. No verdict
or evidence string is edited. This correction precedes all Mistral study calls.
The adapter allows a 600-second transport deadline; it does not change model
parameters. A separate offline qualification binds the existing canary response.

The first two canary source hashes bind `preflight/PROBE_EXECUTED.py`, preserved
before formatting-only edits. The later Gemini 3.7 canary binds the current
probe source. Three canaries are excluded from all study denominators and
reported study costs. API model-list observations are operator-recorded metadata,
not a byte-for-byte archived model-list response.

## Receipts and stopping

Freeze plans, source hashes and this protocol before paid study calls. Reserve
request coordinates and bodies exclusively; retain raw responses, usage and
hashes. Ambiguous transport/reservation outcomes are never automatically resent.
Transport, identity or usage-bound failure stops the remaining requests in that
cell. Schema, quotation, refusal and truncation failures remain observations;
they do not trigger replacement calls. All planned denominators remain visible.
Provider keys come only from their named environment variables, never artifacts.
TLS verification and redirect refusal remain enabled.

Cost estimates use Mistral's conservative undiscounted parent rates $1.36/$4.18
and Gemini's published current standard text rates $0.75/$3.75 per million
input/output tokens. Gemini output includes thinking; missing usage stays
UNKNOWN. Cache, launch, free-tier and account-specific effects are not inferred.
Actual invoice remains UNKNOWN. The user removed a dollar cap; call/token bounds
and exclusive reservations remain finite.

## Interpretation

Report every provider separately: missing/invalid/refused/incomplete counts,
AB/BA conflicts, and each five-repeat pattern. A stable result requires all five
repetitions to be valid, order-consistent and share one normalized preference.
Cross-family agreement is not truth; disagreement is not an isolated family-bias
test. Mechanical constraint checks annotate explanations without altering votes.
Human labels remain pending, `winner: none`, non-regression NOT_ESTABLISHED.
No claim of latent intelligence, donor direction or memory-content causality is
licensed by attractive text alone. The next learner gate remains matched legacy
memory-content controls and genuinely held-out cases before training changes.

## Official references checked 2026-10-09 JST

- [Mistral reasoning response chunks](https://docs.mistral.ai/studio/conversations/reasoning)
- [Mistral chat parameters](https://docs.mistral.ai/api/endpoint/chat)
- [Gemini 3.7 Flash: stable ID, structured output and LOW support](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash)
- [Gemini 3 temperature guidance](https://ai.google.dev/gemini-api/docs/generate-content/gemini-3)
- [Newer Gemini 3.6+ API parameter changes](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.6#api-changes-and-parameter-updates)
- [Gemini API generation contract](https://ai.google.dev/api/generate-content)
- [Gemini standard pricing](https://ai.google.dev/gemini-api/docs/pricing)
