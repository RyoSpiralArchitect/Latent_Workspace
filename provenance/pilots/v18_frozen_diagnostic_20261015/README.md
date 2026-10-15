# V18 frozen-backbone selection diagnostic — results

2026-10-15. **COMPLETE AND VERIFIED. Both arms `NOT_ESTABLISHED`;
`NO_SELECTION_ADVANTAGE_ESTABLISHED`.** With pinned Mistral-7B frozen and only
the 32 workspace tensors trained for 512 complete windows, intact versus twin
facts produced **0/256 donor-directed flips** on the held-out final worlds in
both the centered-ordered and centered-final arms. Post-hoc decomposition shows
why: the common route saturated the shared residual budget within the first 128
updates, leaving the interaction route about 0.0004 of norm. The old **FAIL /
winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

Execution commit `3789a4bc4329e614feb606391aad30324695322f`, bound by the
[603-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `2d9dcfa0…62c33b0`), byte-
identical on Furnace and locally. Design and endpoints were frozen before launch
in [FROZEN_DIAGNOSTIC.md](../../../docs/v18/FROZEN_DIAGNOSTIC.md); the
[handoff](EXECUTION_HANDOFF.md) records the dev checks. One detached
[dispatch](furnace/launch_frozen_diagnostic.sh): tiny CPU qualification
22:44:52Z, CUDA, then the diagnostic 22:45:25Z → all stages exited 0 at
01:54:05Z (UTC; [timeline](furnace/LAUNCH_TIMELINE.log)). No retry.

| Process | Status | Elapsed | Peak CUDA allocated | Peak RSS |
| --- | --- | ---: | ---: | ---: |
| Tiny CPU qualification | 16/16 PASS | 13.76 s | — | — |
| Tiny CUDA qualification | 16/16 PASS | 17.24 s | 67,504,128 | — |
| centered-ordered arm (PID 1882681) | `V18_FROZEN_ARM_COMPLETE` | 5,581.0 s | 15,369,354,752 | 5,945,544,704 |
| centered-final arm (PID 1897535) | `V18_FROZEN_ARM_COMPLETE` | 5,649.2 s | 15,369,190,912 | 5,948,444,672 |
| Replay (PID 1914393) | `V18_FRESH_PROCESS_EXACT_REPLAY` | 86.7 s | 14,694,357,504 | 5,960,704,000 |

Bytes. The dispatch receipt is
`V18_FROZEN_DIAGNOSTIC_COMPLETE_NOT_FULL_UPDATE_OR_RELEASE` (11,320 s). The
frozen backbone hash was `9db998af…` at the start and end of both arms, equal
to the pinned original; no native weight changed. Each arm ran 512 windows
(8,192 backward pairs), five dev and two final evaluations. Checkpoints (79,727,735
bytes each, steps 256 and 512 per arm) stay on Furnace under the task root's
`checkpoints/`; their bodies were rehashed during Furnace verification.

## Pre-registered endpoint (final split, update 512)

| Arm | Verdict | Actual flips /256 | Random-pair flips | Margin | Worlds +/−/0 | Sign-test p | Unaffected changes /768 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| centered-ordered | `NOT_ESTABLISHED` | 0 | 0 | 0 | 15/16/97 | 0.640 | 4 |
| centered-final | `NOT_ESTABLISHED` | 0 | 0 | 0 | 7/7/114 | 0.605 | 0 |

Selection comparison: 0 versus 0 flips, no discordant questions, McNemar
p = 1: `NO_SELECTION_ADVANTAGE_ESTABLISHED`. Every zero-memory row equalled the
frozen direct base exactly, so the evaluation is valid. Reversed, equal-slot and
same-memory factors also produced zero flips at every evaluation.

The descriptive dev curve (64 worlds, 128 affected) never left zero flips
(actual flips 0 at updates 0/128/256/384/512 in both arms; nonzero-sum worlds
at most 10, split evenly). Accuracy with memory stayed at the frozen base: for
example on final "ranked above" questions, intact 272/512 (ordered) and 274/512
(final) versus the direct base's 274/512; on "outrank" questions 266/512 and
265/512 versus 261/512, the difference coming from fewer exact ties.

## Why: the common route consumed the shared budget (post-hoc, descriptive)

The reader allots the interaction route `0.25 × (1 − |common|/cap)` of its
bounded output. Mean residual norms on intact/twin final rows at update 512:

| Arm | Memory | Total | Common | Interaction |
| --- | --- | ---: | ---: | ---: |
| ordered | intact, twin, reversed, unrelated | 0.9983–0.9988 | 0.9980–0.9985 | 0.00038–0.00044 |
| ordered | norm-matched random | 0.6517 | 0.6371 | 0.0770 |
| final | intact, twin, reversed, unrelated | 0.9990 | 0.9988 | 0.00030 |
| final | norm-matched random | 0.7003 | 0.6890 | 0.0699 |

On dev the common route was already at 0.997–0.998 by update 128 in both arms
and stayed there. For any real written memory it sits at the 1.0 cap, the same
for intact, twin, reversed or unrelated facts, so the interaction route is
starved; with random memory the common route stays below the cap and the
interaction route does produce 0.02–0.13. The interaction route is therefore
able to act; the budget formula prevents it. The common route itself learned a
large, content-independent shift: training answer CE fell slightly (0.119 →
0.108 per pair term) while the donor hinge stayed at its maximum on almost
every affected pair.

Content effects are small and undirected even before bf16: over the 256
affected final questions, the FP64 projection of the intact-minus-twin residual
onto the answer gap has median magnitude 0.0067 (ordered) and 0.0039 (final),
and is donor-directed for 136 versus 120 questions in both arms. Published
native gaps changed on 40 (ordered) and 14 (final) questions, by at most one or
two bf16 quanta, with random direction. This analysis was chosen after seeing
the results and is not a pre-registered test.

## Replay and verification

A fresh interpreter rebuilt the run contract, schedule and training inputs,
restored the ordered arm's step-256 checkpoint and replayed window 257 exactly
(16 pairs, update receipt and trainable-state fingerprint;
[REPLAY.json](furnace/raw/replay/REPLAY.json)). Frozen-mode exact resume on the
real 7B is qualified.

[Local verification](OFFLINE_VERIFY_LOCAL.json) from a clean clone of the
execution commit rehashed all 603 sealed sources, both qualification bundles and
every manifest; recomputed every evaluation summary and pre-registered diagnosis
from the gzip records, the schedule IDs, the arm matching, the selection
comparison and the replay. The [Furnace verification](OFFLINE_VERIFY_FURNACE.json)
repeated this from a separate clean checkout and rehashed all four checkpoint
bodies. Both report `OFFLINE_V18_FROZEN_DIAGNOSTIC_RECEIPT_PASS`.

## Consequence

In the current reader, longer workspace-only training does not make memory
content reach native answers, because the common route claims the whole
residual budget for a content-independent shift. A full-parameter run of the
same design would very likely spend its updates on the backbone without
opening that path. The narrow next factor is the one already listed in the
V18 preparation table for an exhausted budget: a separately allocated, bounded
interaction budget (or, as an ablation, a common route held at zero). Either is
an arithmetic or trainability change that needs a new versioned reader/owner,
fresh qualification and a new frozen plan before any comparison. No such change
is made here.
