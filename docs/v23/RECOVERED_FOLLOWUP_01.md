# V23 recovered-bank follow-up 01

This is an explicit **input-provenance amendment**, not a new learner recipe,
new judge rubric or a relabeling of the stopped original dispatcher.

| Arm | Whole execution selected | Source |
|---|---|---|
| base | Original comparison 01 | `84073310cd7b2c56b5e3de046fb3bdc99e461bfb` |
| P-off | Original comparison 01 | same original source |
| P-on | Whole recovery 02 only | `af9cd1a727d98d942df1845c35a14628f8f7481b` |

The original 79 P-on MMLU rows and the CPU-only failed recovery 01 are never
spliced into this bank. The original dispatcher remains `INCOMPLETE_NO_RETRY`.
Every selected role must have complete 570/192/24 journals, unique and matched
IDs, successful immutable terminal manifests, and unchanged native weights.
Both source seals are replayed against their exact Git trees. Every originally
sealed source file must be unchanged in recovery; added orchestration/isolation
files are recorded separately. Recovery's CPU/CUDA qualification and CPU
visibility audit are mandatory. No complete bank means no new judge/model call.

## Blind judge

Keep the already calibrated `mistral-large-4` core unchanged, including its
rubric, JSON schema/parser, prompt/body construction, seed 2026102201,
temperature 0.2, 16,384 output-token cap and 1,200-second timeout. The exact
32-control terminal must replay PASS. No recalibration calls or provider
substitution. Controls are analyst fixtures, not independent human gold.

Use all 24 answers from each arm, including unchanged/capped answers: 72 pairs
in AB/BA order (144 requests), 24 same-body repeat requests and 6 identical-answer
controls: **174 planned study requests**. The legacy generation-source/status
reference in the judge plan is explicitly superseded **only for bank lookup**
by `ADAPTER_BINDING.json` and the combined origins in the study seal. All judge
policy/source hashes remain identical to calibration. The new adapter source
and its committed identity are bound additionally; both sets are checked before
dispatch. No fabricated successful original run is written.

Frozen cases, requests and blind handoff retain exact visible answer text,
finish reasons and opaque IDs. No changed-only selection, retries, completion
imputation, or post-result prompt edits. Invalidities and unknown execution stay
visible. Report order conflicts and repeated disagreements, not only preference
wins. There are 12 independent prompts, not 174 independent observations;
same-family judge bias and partial/capped learner outputs remain limitations.

## MMLU-Pro

Keep the existing dataset revision, 280 selected direct items, nested 28
reasoning items, original tokenized inputs and all scorer/decoding settings.
The old runner gains only an optional explicit predecessor-receipt callback;
its default still blocks on the original incomplete dispatcher. The new entry
passes the original numerical plan unchanged and the verified combined-bank
receipt. CPU isolation uses the repaired pre-import boundary, with sequential
CPU→CUDA→base→off→on, no other GPU client and unchanged 4-GiB/900-second
qualification limits and 7B resource floors. No train/update/save/delete.

Report all paired base-wrong/FT-correct **and reverse** IDs, margins, ties,
unparsed/capped answers and denominators. "Base wrong under this protocol" is
not "base inherently cannot solve it". This is a 14-category balanced diagnostic,
not the full official leaderboard; pretraining contamination remains UNKNOWN.
The original expression gate remains **FAIL**, winner **none**, and
non-regression **NOT_ESTABLISHED** until separately supported, not by definition.
