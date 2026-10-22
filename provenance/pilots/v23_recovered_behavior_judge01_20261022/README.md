# V23 recovered answer-bank blind judge 01 — running, no preference claim yet

One authorized study was frozen and launched from committed source
`b2f569740636e2cffb80e4091323d551ea7de4c2`.
The [study seal](study/SEAL.json) separately binds the unchanged calibrated
judge implementation and the explicit recovered-input adapter. The historical
original comparison remains incomplete; base/off are its whole completed arms,
and on is the whole successful recovery 02. No partial original on row is used.

The existing **32/32** Mistral calibration replays PASS (16/16 normalized order
and 16/16 repeat agreements). Controls are analyst fixtures, not human gold.
The study contains **174 requests**: 144 AB/BA requests for 72 paired cases,
24 repeat requests and 6 identical-answer controls. All 72 learner answers
remain included, including unchanged and length-capped outputs. There are
**12 independent prompts**, each with two seeds, not 174 independent samples.

Model `mistral-large-4`, seed 2026102201, temperature 0.2, maximum 16,384 output
tokens and 1,200-second timeout are unchanged. Exact metadata identity passed.
Each request is attempted at most once, sequentially. Transport/HTTP errors
halt dispatch; unknown remote execution is never relabeled failure-to-execute,
and invalid returned judgments are preserved rather than retried. No OpenAI,
Claude or Gemini requests, additional calibration, prompt edits or new rubric.

This is a launch record, not a finished preference study. See the
[handoff](EXECUTION_HANDOFF.md) before doing anything. The
[literal 72-answer bank](../v23_comparison_recovery02_20261022/analysis/ANSWER_BANK.md)
is already published independently. Old expression gate **FAIL**, winner
**none**, non-regression **NOT_ESTABLISHED**. No training, model weight save,
deletion, export or release. Same-family judge bias and capped outputs limit
any later interpretation even if all responses are structurally valid.
