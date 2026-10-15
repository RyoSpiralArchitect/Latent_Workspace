# Gemini 3.8 prospective amendment

2026-10-09 JST, before any Gemini study request. The user explicitly approved
changing the additional Gemini judge to 3.8 Flash after the 3.7 canary returned
a 3.8 model ID. The original 3.7 plan, source and mismatch receipt stay intact.
That canary is not relabeled as a 3.8 study observation. The reason for the
requested/returned mismatch remains UNKNOWN.

## Method fixed for this addition

- Request `gemini-3.8-flash` explicitly, accept only exactly that returned ID.
- `thinkingLevel: LOW`, `includeThoughts: false`, seeds 1001–1005,
  maximum 4,000 output tokens, no tools or grounding.
- Omit temperature, top-p, top-k and candidate count. Newer Gemini 3.6+
  guidance deprecates/ignores sampling controls and does not support candidate
  count. A supplied seed remains recorded but does not prove determinism.
- Retain the exact same original selection, blinded evaluator payload,
  rubric, JSON schema and literal-quotation validator. No vote or quote repair.
- Reuse 140 sealed OpenAI calls. Add the same 140 Gemini coordinates once;
  3.7 dispatched zero study calls, so this is not an extra 140-call study arm.
- Provider settings and compute are not matched. Identity is the requested and
  returned product ID, not an observable immutable weights revision.

The explicit 3.8 non-study identical-answer canary must pass returned identity,
strict schema/quotation, tie calibration and reported-usage bounds before
study dispatch. Source hashes and this amendment are bound in the new plan.
Execution uses the explicit local Python 3.13 binary. An initial unqualified
`python3` invocation resolved to Python 3.9 in interactive zsh and failed during
module import (`datetime.UTC`) before output reservation or any API request;
the canary output directory was confirmed absent before the corrected launch.
Four non-study canaries in total (Mistral, 3.1 Pro, 3.7 request, explicit 3.8)
remain outside all study denominators and study cost totals.

## Cost, stopping and interpretation

Current published standard text estimates use input $0.75 / output $3.75 per
million tokens through 2026-12-31. Output accounting includes thinking even
though thought summaries are not requested. Account/free-tier/cache discounts
are not inferred; actual invoice stays UNKNOWN. The finite grid and token bounds
remain fixed despite the user's absence of a dollar cap.

Keep existing reservation, no-redirect TLS, no-secret-artifact, exact model
identity, no automatic retry and stop-on-transport/usage-contract failure rules.
Missing/invalid/refused/incomplete judgments remain missing from valid preference
comparisons; never silently replace them. All-five stability still requires all
five AB/BA repetitions valid and directionally consistent.

The Mistral 4,000-token method has now finished with 95 reserved requests, 93
raw responses, 92 incomplete responses, one valid identical-control judgment,
two HTTP 500s, and 45 unsubmitted coordinates. Those results stay unchanged.
The new Gemini method does not cure that missing comparison or establish a
three-family quality conclusion. Any future Mistral output-budget intervention
requires a distinct prospective method and must not overwrite this attempt.

## Primary references checked 2026-10-09

- [Gemini 3.8 Flash model and LOW support](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Gemini 3.6+ parameter changes](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.6)
- [Current 3.8 migration checklist](https://ai.google.dev/gemini-api/docs/latest-model#migration-checklist)
- [Gemini API generation contract](https://ai.google.dev/api/generate-content)
- [Current standard text pricing](https://ai.google.dev/gemini-api/docs/pricing)
