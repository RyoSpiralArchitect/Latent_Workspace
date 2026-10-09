# V14 enlarged-output Mistral and Sonnet 5: prospective protocol

2026-10-09. The user authorized a larger Mistral output budget and a Claude Sonnet-5 judge.
This is a new method bundle, not a repair of the sealed 4,000-token Mistral result.
All old bundles, source files, votes and failed reservations stay unchanged.

## Before study dispatch

- Reuse exactly the selected 10 changed pairs and 4 identical controls, 5 repeats,
  both AB and BA: 140 study requests per new method. No new model answers or training.
- Capacity ladder: 16,384, then 32,768, then 65,536 only if needed. Six fixed non-study
  canaries (three new synthetic pairs in both orders) must all satisfy the unchanged
  strict schema and literal-quote checks, with tie for the identical pair. The
  maximum reported total output must use at most 75% of the candidate cap.
  No preference on the two non-identical canaries is a selection criterion.
- Each attempted cap gets a distinct directory and preserved receipts. No API retry
  after an ambiguous reservation. A new cap is a separate method; no selective
  repair of study outcomes, invalid quotes, JSON or inconvenient votes.
- Freeze a provider plan after qualifying, before any study call. Bind source,
  selected data, qualification and this protocol by hash. Keep API-reported IDs exact.
  API names cannot establish immutable remote weights.
- Mistral uses `mistral-large-4`, temperature 0.2, seeds 1001–1005, unchanged schema,
  `standard_only`, and omits reasoning_effort exactly as before. Only `max_tokens`
  changes in its API request. Timeout becomes 1,200 seconds for the larger budget.
- Claude uses `claude-sonnet-5`, explicit adaptive thinking and medium effort,
  the same rubric and JSON schema, no tools or provider sampling/seed parameters.
  Repeat numbers are repeated calls, not matched random seeds across providers.
- Metadata GET and all capacity probes are non-study. Network calls need explicit
  execution flags. Credentials are process-memory/environment only, never artifacts.

## Execution and interpretation

Reserve each exact request before sending and retain each raw response. Durable
response recovery may reconcile a pending receipt without resending. Transport,
model-identity and usage-contract failures stop that cell. Unknown costs remain
unknown; no billing claim from a posted price. No vote-dependent stopping.

Do not merge the old Mistral4k failed trial and new enlarged-cap method into one
denominator. Reuse the old OpenAI and Gemini results without paying for duplicates.
Completion, strict validity, equality-control ties, order agreement, five-repeat
stability and qualitative correctness are different claims. No majority vote is
gold, no quality winner is declared, and non-regression remains unestablished.

The representative fixtures stress longer explanations, a causal comparison and
hidden-fact grounding. They do not prove performance for every future input.
Posthoc mechanical word counts annotate answers without rewriting judge votes.

## Official references checked before dispatch

- [Mistral Large 4](https://docs.mistral.ai/models/mistral-large)
- [Mistral max_tokens and request contract](https://docs.mistral.ai/api/endpoint/chat)
- [Mistral thinking chunks](https://docs.mistral.ai/studio/conversations/reasoning)
- [Sonnet 5 specifications](https://platform.claude.com/docs/en/models/sonnet-5/overview)
- [Sonnet 5 thinking/sampling migration](https://platform.claude.com/docs/en/docs/about-claude/models/whats-new-sonnet-5)
- [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create)

Conservative Mistral rates remain $1.36/$4.18 per million input/output tokens,
ignoring launch discounts, to preserve prior accounting. Claude rates $2/$10 per
million. Cache creation is not requested; unexpected cache-write accounting fails
closed. No actual invoice or account discount is inferred.
