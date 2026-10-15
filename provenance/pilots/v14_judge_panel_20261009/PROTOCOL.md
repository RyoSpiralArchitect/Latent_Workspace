# V14 changed-answer repeated judge panel

Prospective protocol, 2026-10-09. The source answer bank remains immutable.
This panel observes existing generations; it does not train, regenerate, delete
weights, promote a winner, or supply human labels.

## Selection and unit of analysis

The selector reconstructs the full 336-answer bank and its 96 primary
base-versus-legacy/centered pairs, then includes **all 10 text-changed pairs**.
No previous judge preference is consulted. These are five general and five
relation pairs, all legacy, covering seven prompts and six world/task clusters.
This is a change-conditioned qualitative sample, not an estimate of overall
model quality or a non-regression test. Multiple decoding regimes from one
prompt and opposite queries from one world are not independent tasks.

Four actual identical base/centered pairs calibrate spurious differentiation:
general-02-json, general-04-code, relation-02-reverse, relation-03-reverse,
all greedy. They are not changed-answer outcomes. The `base_inline` condition
is excluded because it supplies different visible information.

## Frozen grid

Each provider judges 14 pairs in both AB and BA order in five repetitions:
28 requests per provider/repetition, 140 per provider, 280 total planned.
Pair, order, provider and repetition coordinates are reserved before dispatch.
Each repetition completes its declared grid regardless of judgment quality;
transport, identity or usage-contract failures halt its remaining dispatch.
Missing credentials leave that provider explicitly unexecuted. No replacement
judge is silently substituted and ambiguous requests are never resent.

- OpenAI: `gpt-5.4-2026-03-05`, Responses, reasoning `low`, standard/default
  service tier, maximum 4,000 output tokens. No temperature or random seed.
- Mistral: explicit `mistral-large-4`, Chat Completions, temperature 0.2,
  random seeds 1001 through 1005, `standard_only`, maximum 4,000 output tokens.
  `mistral-large-latest` is not assumed to resolve to this model. Public-preview
  weight immutability remains unknown even when the returned model ID matches.

The same schema, rubric and evaluator payload are used for both providers;
provider API and sampling differences are retained as part of the comparison.
Repeated calls are not additional independent judges. Same-family Mistral
evaluation can reveal disagreement but is not independent ground truth or an
isolated test of family affinity.

## Blinding and validation

Requests include the visible prompt, evaluator reference, rubric, answers and
termination reasons. They exclude model/training-condition labels, source
pair IDs and prior verdicts. Both answer orders are evaluated and normalized
back to base/workspace only after receipt.

The old strict schema and exact-substring evidence validator are reused. A
prospective instruction clarifies that evidence strings contain literal answer
substrings, with no added quotation wrappers. There is **no automatic repair**.
The prior primary judgments and post-hoc quote-wrapper supplement remain
separate methodological versions; neither is pooled silently into this panel.

Report valid/invalid/refused/incomplete/missing counts, order-consistent
base/workspace/tie/uncertain outcomes, order conflicts, and each five-repeat
pattern. A stable preference requires all five repetitions to have two valid,
order-consistent judgments with the same normalized preference. Do not force
majority votes into gold labels. Report identical-control ties and erroneous
preferences separately. Preserve the complete raw explanations and answer text
so a human can inspect them. Human evaluation remains pending until supplied.

## Provenance, cost and security

The plan binds the selection and executable source hashes before any paid call.
Each cell preserves the prepared bodies, exclusive request reservations, raw
responses, response hashes, model IDs, status, token usage and timestamps.
Keys are read only from their provider-specific environment variables and are
never included in artifacts. TLS verification stays enabled; redirects are
refused. Existing authorized OpenAI credentials are reused; Mistral needs a
separately available credential. No API call occurs in dry-run mode.

The user removed a dollar cap; the call grid and output bounds remain finite.
Conservative estimates use OpenAI $2.50/$15 and Mistral $1.36/$4.18 per million
input/output tokens, without cache or launch discounts. Mistral currently lists
a 50% launch promotion; the higher rates are deliberate conservative estimates.
Actual billed cost is unknown. The UTF-8 request-byte input bound is checked
against reported usage rather than treated as an invoice.

## Interpretation and next learner gate

Qualitative preference is a hypothesis generator, not proof of memory-content
use, latent intelligence, semantic direction or base preservation. This bank
lacks legacy zero/unrelated/twin controls; an attractive legacy answer may
reflect a generic bias or changed sampling boundary. Centered answers were
unchanged despite nonzero native-logit effects. The next decision therefore
requires no-training memory-content controls and held-out cases before choosing
a learner update. Do not train on this selected evaluation bank or its labels.

## Official API/model references checked 2026-10-09

- [OpenAI GPT-5.4 snapshot, pricing and capabilities](https://developers.openai.com/api/docs/models/gpt-5.4)
- [OpenAI strict structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Mistral Large 4 Public Preview, October 6](https://docs.mistral.ai/models/mistral-large)
- [Mistral changelog](https://docs.mistral.ai/resources/changelogs)
- [Mistral chat parameters](https://docs.mistral.ai/api/endpoint/chat)
- [Official SDK response format](https://github.com/mistralai/client-python/blob/main/src/mistralai/client/models/responseformat.py)
- [Official SDK JSON schema serialization](https://github.com/mistralai/client-python/blob/main/src/mistralai/client/models/jsonschema.py)
