# V23 additional behavior judging and MMLU-Pro diagnostic

2026-10-22. Authorized as a **separate** evaluation while comparison 01 runs.
The already-launched comparison source `84073310cd7b2c56b5e3de046fb3bdc99e461bfb`
and its zero-judge plan remain immutable. No training, weight save/deletion,
provider substitution, retry, release, or alteration of an earlier gate.

## Behavior judge 01: frozen before seeing V23 answers

Use all 12 exposed free prompts, both existing generation seeds, and all three
pairs (base/off, base/on, off/on): **72 pairs / 144 AB+BA requests**. Four named
prompts at the first seed repeat both orders for each comparison (24 additional
requests). Three identical-answer controls add six requests: **174 study calls**.
No changed-only selection and no new learner generation. Seeds, orders and
repeats do not multiply the 12 independent prompts. The full bank must finish
and pass its manifests before any study packet is constructed.

Mistral `mistral-large-4` is confirmed through the official model metadata API.
New-rubric calibration precedes study: eight analyst-written controls, AB/BA,
two identical-body repetitions, **32 requests**, all 32 valid and expected to
admit study. This is a conservative interface/control gate, not independent
human-gold validation. Historical calibration PASS/FAIL results are unchanged
and do not transfer. Total maximum: **206 requests**, one attempt each, 16,384
output tokens/request, temperature 0.2, fixed seed 2026102201. Report observed
usage; invoice cost and the service's immutable underlying model revision are
unknown. No inference request to OpenAI, Gemini or Claude is included here.

Blinded packets include task, verbatim answers, symmetric whitespace word/
character counts and finish reasons; arm mappings stay in operator files.
Prefer correctness/faithfulness/constraints before prose style. Truncation is
visible and not excused or automatically treated as incomplete. Never execute
generated code. Validate terminal envelopes, exact model identity, strict JSON
and literal quotes. Count order conflicts, repeat disagreements, cannot-assess,
invalidity, refusal, unknown transport outcomes and undispatched requests
separately, never as ties. An HTTP/transport failure stops admission, without
resending. A stopped process never authorizes resume. Manual Claude review can
use `BLIND_PACKET.json` without API access; it is not already a completed review.

## MMLU-Pro: prospective, paired evaluation rather than win mining

Pin TIGER-Lab/MMLU-Pro revision
`b189ec765aa7ed75c8acfea42df31fdae71f97be` (MIT dataset card; 12,032 test and
70 validation examples). Select by a fixed hash of category/question ID before
model answers. A balanced diagnostic is not the full benchmark's micro score.
The direct-choice endpoint and a smaller five-shot reasoning-generation panel
are separate: direct scoring alone does not establish reasoning ability.
Exact counts, contexts and resource admission are recorded in the separate
MMLU-Pro plan and input manifest before execution.

For every candidate, retain all four transitions against base: both correct,
base-only correct, candidate-only correct, both wrong. Publish candidate-only
and base-only IDs together, plus option margins, ties, unparsed/capped outputs
and literal reasoning-panel answers. Report the whole denominator and subject
counts. "Base wrong" means wrong under this fixed elicitation/decoding setting,
not inherently unsolvable by the base model. No filtering by base correctness,
random answer imputation, adaptive prompts/caps, or dataset-to-training use.

The public benchmark may overlap Mistral pretraining or exposed old MMLU items;
no decontamination claim is made. No latent memory is fabricated for a closed-book
benchmark. This measures preservation/transfer of the updated backbone, not
causal workspace use. Keep old expression **FAIL**, winner **none**, and
non-regression **NOT_ESTABLISHED** unless a separately specified gate is met.

Primary references: [official dataset](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/tree/b189ec765aa7ed75c8acfea42df31fdae71f97be),
[official evaluation implementation](https://github.com/TIGER-AI-Lab/MMLU-Pro/blob/main/evaluate_from_local.py).
The original implementation uses five-shot CoT with context-dependent shot
reduction and has random fallback for unparsed answers. Our bounded native
diagnostic must expose any deviation and must never turn an unparsed answer
into a random correct answer. It is not an official leaderboard submission.
