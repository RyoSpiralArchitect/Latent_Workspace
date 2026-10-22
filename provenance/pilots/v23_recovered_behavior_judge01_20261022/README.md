# V23 recovered answer-bank blind judge 01 — terminal, mixed validity

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

## Terminal denominators and preference view

The run ended at **2026-10-22T02:41:47.113175+00:00** (11:41 JST).
All **174/174** requests returned: **170 VALID, four INVALID**, no undispatched
requests or unknown remote execution. All four invalid responses ended normally
but failed the unchanged exact-substring quote check. They are not repaired,
retried or counted as preferences. Offline replay matches the terminal analysis,
every response hash, frozen request body, calibration and source binding.

Each row below retains its full **24 prompt/seed case** denominator. A preference
requires both r0 orders to be valid and to agree after arm normalization; valid
JSON alone is insufficient. A/B mean the listed reference/candidate arms, not
the displayed order. There are 12 prompts × two seeds, not 174 independent tasks.

| Comparison | Reference preferred | Candidate preferred | Tie | Order conflict | Unjudged | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base → off | 4 | 12 | 2 | 5 | 1 | 24 |
| Base → on | 8 | 12 | 1 | 3 | 0 | 24 |
| Off → on | 9 | 5 | 4 | 5 | 1 | 24 |

Across 72 main pairs, **57** have an order-stable r0 outcome, **13** conflict and
**two** are unjudged. These are not a pooled win rate or a selected new default.
The three identical-answer controls are ties in both orders: **6/6 requests**.

Repeated pairs agree in **8/12 cases**: off/base 4/4, on/base 1/4, on/off 3/4.
This measures equality of both normalized preference vectors, not equality of
the whole judgment, its correctness labels or its explanation. In particular,
stable preference can coexist with changed correctness labels. Conversely, a
repeat can reproduce an order conflict; agreement does not make it valid.
The four repeat disagreements are:

- `code-01:2026102101:base:on`
- `reasoning-02:2026102101:base:on`
- `writing-01:2026102101:base:on`
- `reasoning-02:2026102101:off:on`

As a **descriptive sensitivity only**, excluding observed repeat disagreements
from otherwise order-stable r0 pairs leaves base/off 4:12:2 (18 cases), base/on
8:11:1 (20), off/on 9:4:4 (17), in reference:candidate:tie order. Untested pairs
are not repeat-qualified. This does not replace the frozen r0 result or tune
the acceptance gate after observing answers.

### Invalid response ledger

All four are r0; the missing quote is in the **presented** side below.
The [analysis](analysis/ANALYSIS.json) binds full response hashes and case IDs.

| Request ID | Case | Order | Quote absent from presented answer |
| --- | --- | --- | --- |
| `fd659c74f1a1907cc976610b` | reasoning-02, seed 2026102102, base/off | AB | B |
| `1bb7cf42c17199a54ceba225` | reasoning-02, seed 2026102102, base/off | BA | A |
| `6e7f89885e319c746b8c9f63` | reasoning-02, seed 2026102102, off/on | AB | A and B |
| `fb7670cb2ca947597d0357a1` | reasoning-02, seed 2026102102, off/on | BA | B |

### Domain view and illustrative observations

Each cell below gives reference/candidate/tie/order-conflict/unjudged, out of
**eight units per domain** (four prompts × two seeds). Domains are descriptive.

| Domain | Base → off | Base → on | Off → on |
| --- | --- | --- | --- |
| Code | 2 / 3 / 0 / 3 / 0 | 5 / 2 / 0 / 1 / 0 | 4 / 3 / 0 / 1 / 0 |
| Reasoning | 2 / 4 / 0 / 1 / 1 | 3 / 4 / 0 / 1 / 0 | 4 / 1 / 0 / 2 / 1 |
| Writing | 0 / 5 / 2 / 1 / 0 | 0 / 6 / 1 / 1 / 0 | 1 / 1 / 4 / 2 / 0 |

These examples explain the texture of the judgments, not additional test data.
Every final judgment (all orders, repeats, controls and invalid responses) is
preserved verbatim in [JUDGMENT_BANK.md](analysis/JUDGMENT_BANK.md), with raw
response/receipt links. All learner text is in the
[72-answer bank](../v23_comparison_recovery02_20261022/analysis/ANSWER_BANK.md).

- **Retain useful constraint following.** For `writing-02`, seed 2026102101,
  off is preferred to base in both r0 orders. The judge contrasts base's
  `To ensure we meet our project timeline` with off's more faithful urgency:
  `If there is any possibility that this deadline may not be met, I would greatly appreciate an update today.`
  Its reasons emphasize the deadline, brevity and avoiding invented context.
  This is a judge interpretation, not independent human gold.
- **Preference is not full correctness.** For `reasoning-01`, seed 2026102101,
  off is consistently preferred to base in both orders and both repeats. Off
  includes `The exact fraction is 2/5`; base uses the wrong remaining-ball
  count. Yet off's later explanation contains errors and the answer is capped.
  On is also consistently preferred to base while containing a final arithmetic
  error. The weaker of two answers can lose without the preferred answer passing.
- **Preserve code explanations, not just familiar fixes.** For `code-02`,
  seed 2026102101, base is preferred to both FT arms in both r0 orders. The
  judge flags the FT explanation of a mutable default as a global-variable
  issue even though the shown replacement uses a `None` sentinel. For `code-04`,
  the same seed, base is preferred to on; on begins
  `The provided SQL query is correct and will return the department, the name of the employee with the highest salary within each department, and the highest salary.`
  The judge identifies the misleading grouped-name claim and invalid replacement
  SQL. No generated code was executed as part of this study.
- **Keep ambiguity visible.** `writing-01`, seed 2026102101, base/off gives off
  in AB but tie in BA; the repeat reproduces that conflict. Base/on changes its
  preference vector across repeats. These do not become writing wins despite
  persuasive individual explanations. The `code-01` base/on r0 preference for
  on also fails repeatability; it must not be advertised as a stable repair.

## Usage, provenance and claim ceiling

Provider-reported usage, including invalid outputs: **153,602 prompt + 730,335
completion = 883,937 total tokens**. Actual invoice cost is **UNKNOWN**. The
fixed model string was returned; the provider's underlying weight revision is
not independently known. Raw response bytes and usage are retained, not inferred
from final-text lengths. No calls were made during local publication.

The [terminal receipt](study/run/FINISHED.json), [study seal](study/SEAL.json),
[adapter binding](study/ADAPTER_BINDING.json), [analysis](analysis/ANALYSIS.json)
and [analysis manifest](analysis/MANIFEST.json) distinguish generation sources
from the paid judge source. Prior incomplete runs are not relabeled successful.
Calibration PASS remains an engineering control, not broad evaluator authority:
the study itself reveals order/repeat sensitivity and same-family bias remains.

Offline verification, from the repository root:

```sh
CUDA_VISIBLE_DEVICES='' PYTHONPATH=src:scripts python3 -B \
  provenance/pilots/v23_recovered_behavior_judge01_20261022/analyze.py verify
```

The generation bank is already complete; do not call `run`, retry a cell or
change the rubric. See the [terminal handoff](EXECUTION_HANDOFF.md).
Old expression gate **FAIL**, winner **none**, non-regression
**NOT_ESTABLISHED**. No training, model weight save/deletion, export or release.
