# V14 matched answer bank — frozen qualitative protocol

2026-10-09. Purpose: retain the existing failed-weight checkpoints and inspect
how their unrestricted text responses differ from the independently loaded original
Mistral. This assay does not retrain, change gains, select a winning checkpoint,
or treat a judge preference as a measurement of latent intelligence.

## Frozen generation grid

16 prompts: eight reversed relation prompts across four new synthetic worlds,
and eight self-contained general tasks. Thus there are **12 world/task units**,
not 16 independent worlds. All case text and reference rubrics are fixed before
generation. The novel relation entities, five-entity worlds and instruct chat
format differ from the narrow bridge-training distribution.

Each prompt is run with greedy decoding and sampled seeds 211/212 (temperature
0.7, no top-p truncation), maximum 128 new tokens, full native BF16 vocabulary.
The seven conditions are original base, inline-facts base, old semantic bridge,
centered semantic bridge, centered zero memory, centered unrelated memory and
centered twin memory: **336 answers**, including unchanged, incorrect, refused,
malformed or length-limited answers.

Except for the explicitly separate inline-facts control, initial user prompts
and tokens are identical. Common random uniforms are deterministic functions
of case, seed and token position, and sampling uses a token-ID-ordered inverse
CDF. Same seed does not imply equal future histories after an answer diverges.

Each step recomputes its complete prefix; only exactly identical prefixes share
a forward at that step. There is no carried KV cache or cache-specific MI claim.
The production path checks ordinary original-model logits on every prompt and
zero-memory logits/tokens throughout generation. Existing model/bridge and file
hashes are checked before and after. No checkpoint is created or removed.

The writer sees only the memory text, encoded to layer 16. It sees no query,
reference answer, rubric, scenario label or judge output. The retained reader
applies its bounded correction after the original final norm, then the full
native head generates text. This is an evaluation expansion, not a claim that
the checkpoint was trained for arbitrary instruction-following tasks.

## Separate questions, not one universal score

- **General tasks:** all necessary facts are visible to base and workspace alike.
  This is the bounded no-regression panel, with only eight distinct tasks.
- **Relation tasks:** query-only base does not receive world facts. Any advantage
  can reflect information access, not increased intelligence. The inline base is
  a different-prompt information control, not the identical-token baseline.
- **Memory controls:** unrelated memory tests interference; twin memory tests
  changed-world responses for relations and conflicting-memory sensitivity for
  general tasks. In general tasks the visible user's facts remain authoritative.

Do not aggregate these questions into a single headline win rate. A few better
answers or zero observed regressions are not a statistical non-inferiority proof.
Token-limit termination is exposed beside each answer and is not quietly retried.

## LLM judge and human assessment

Primary pairs: base versus old semantic, and base versus centered semantic,
for every prompt/regime (96 pairs). Model names, training condition and expected
winner are hidden from the judge. Changed answers receive both A/B and B/A
presentations; order disagreement remains unresolved, not majority-voted away.
Exact text matches are classified mechanically, with up to four real identical
pairs also judged twice as calibration. No synthetic answer is substituted.

The pinned judge is `gpt-5.4-2026-03-05`, Responses API, low reasoning effort,
strict structured output, `store: false`, standard service tier and at most
4,000 output tokens per call. It describes correctness, instruction-following,
grounding, coherence, usefulness and calibration, and must cite actual answer
substrings. Candidate text is data, never an instruction to the judge.
Refusals, API failures, invalid quotes, incomplete JSON and missing evaluations
stay explicit. Requests are reserved before dispatch; ambiguous sends are not
silently repeated. There are at most 192 calls in this fixed grid.

The user explicitly approved reuse of the existing local shell API key and
subsequently removed the proposed dollar ceiling. The key is neither printed,
written into the repository nor sent to Furnace. Only synthetic case/answer
texts are sent to OpenAI. Usage and actual estimated cost are retained.
The implementation uses a verified certificate bundle, never disabled TLS.

Official model/schema/pricing references checked on 2026-10-09:

- [Pinned model](https://developers.openai.com/api/docs/models/gpt-5.4)
- [Structured output contract](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Standard pricing](https://developers.openai.com/api/docs/pricing): input $2.50,
  output $15 per million tokens for the short-prompt tier; cached-input discounts
  may make conservative estimates exceed the actual invoice.

Human review has a separate blinded comparison book and blank score CSV.
LLM scores never fill human fields. Unblinding and judge prose are separate files
so the user can read and label responses before viewing them. All raw answers,
not just favorable examples, are available in the public answer bank.

## Claim ceiling

The deliverable is a reproducible qualitative observation bank and a source of
new improvement hypotheses. Neither mechanistic interpretability, intelligence
amplification, broad quality preservation nor deployment readiness is established
by completing it. No semantic winner is promoted automatically.
