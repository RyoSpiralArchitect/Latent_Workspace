# V20 A1 Availability ladder — results

2026-10-16. **All four roles complete and verified. The pre-registered verdict
is `CONTENT_ABSENT_IN_MEMORY` at all three V19 states (initial, update 256,
update 512), but it cannot be read as "the memory lacks the content".** The
memory probe (R1) never learned to use memory: its training loss matched the
zero-memory control's. And at update 256 the pre-registered read-output test
(R2) passed: one linear direction told intact from twin for 63% of held-out
affected questions (p = 7e-5 over worlds). The read output is computed from
the memory and a memory-independent query, so content that reaches it was in
the memory. **A1 did not locate the loss by its own rule.** Read
descriptively, it points at transport at update 256: the content reached the
workspace read output, and V19 showed that it barely moved the answer. The
old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

Execution commit `5b5776bcceb35c55f495e1a60c9b346354bfed53`, bound by the
[646-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `dff3b071…6d246`),
byte-identical on Furnace and locally. Design and endpoint were frozen before
launch in [A1_LADDER.md](../../../docs/v20/A1_LADDER.md); the
[handoff](EXECUTION_HANDOFF.md) records the dev checks. One detached
[dispatch](furnace/launch_v20_a1_ladder.sh) (UTC,
[timeline](furnace/LAUNCH_TIMELINE.log)): CPU qualification 04:07:31Z (18/18),
CUDA 04:08:02Z (18/18), ladder 04:08:33Z → `ladder exit=0` at 04:37:15Z.

| Process | Status | Elapsed |
| --- | --- | ---: |
| `extract_initial` (GPU; peak CUDA 14,607,054,336 bytes) | `V20_A1_STATE_EXTRACTED` | 480.5 s |
| `extract_step256` (peak 14,659,534,336 bytes) | `V20_A1_STATE_EXTRACTED` | 495.6 s |
| `extract_step512` (peak 14,659,534,336 bytes) | `V20_A1_STATE_EXTRACTED` | 494.8 s |
| `probe` (CPU, 8 threads, GPU hidden) | `V20_A1_LADDER_COMPLETE` | 240.0 s |

Each extraction restored V19 `ordered_cap025` with V19's frozen code and passed
every check in the design: pinned receipt and checkpoint hashes, the rebuilt
initial state equal to V19's recorded fingerprint, store receipts equal to
V19's for both splits, each published residual equal to its common and
workspace parts, zero memory reproducing the frozen direct base, and
memory-independent queries. It read 384 worlds (256 train, 128 held-out
final), 8 questions each, under 5 memory conditions. The feature files
(1.84 GB) stay on Furnace; their hashes are in the role manifests.

## Pre-registered endpoint (per state; α = 0.01)

**R1, written memory.** Content following: both sides of an affected pair
right, of 256 held-out pairs. One-sided world sign tests against the
zero-memory and shuffled-memory probes; R1 needs every seed to beat both.

| State | Seed | Memory | Zero | Shuffled | vs zero (+/−, p) | vs shuffled (+/−, p) |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| initial | 1 | 2 | 0 | 1 | 2/0, 0.25 | 2/1, 0.50 |
| initial | 2 | 7 | 0 | 2 | 7/0, 0.0078 | 6/1, 0.063 |
| initial | 3 | 2 | 0 | 1 | 2/0, 0.25 | 2/1, 0.50 |
| step256 | 1 | 3 | 0 | 0 | 3/0, 0.125 | 3/0, 0.125 |
| step256 | 2 | 2 | 0 | 1 | 2/0, 0.25 | 2/1, 0.50 |
| step256 | 3 | 10 | 0 | 2 | 9/0, 0.002 | 9/2, 0.033 |
| step512 | 1 | 4 | 0 | 3 | 4/0, 0.063 | 4/3, 0.50 |
| step512 | 2 | 3 | 0 | 0 | 3/0, 0.125 | 3/0, 0.125 |
| step512 | 3 | 28 | 0 | 5 | 27/0, 7e-9 | 26/4, 3e-5 |

R1 fails at every state (one seed of three passes at step512).

**R2, read output** (workspace route): a logistic contrast probe on
`read(intact) − read(twin)` predicting the intact answer, 256 held-out affected
questions, sign test against chance over the 128 worlds.

| State | Correct /256 | Worlds +/−/0 | p | R2 |
| --- | ---: | --- | ---: | --- |
| initial | 128 | 0/0/128 | 1.0 | fail |
| step256 | **161** | 53/20/55 | **7.1e-5** | **pass** |
| step512 | 142 | 45/31/52 | 0.068 | fail |

| State | R1 | R2 | Verdict |
| --- | --- | --- | --- |
| initial | fail | fail | `CONTENT_ABSENT_IN_MEMORY` |
| step256 | fail | **pass** | `CONTENT_ABSENT_IN_MEMORY` |
| step512 | fail | fail | `CONTENT_ABSENT_IN_MEMORY` |

## Descriptive (declared before launch)

- **R1 probes are at chance on all held-out rows**, memory and controls alike:
  accuracy 0.482–0.509 over 2,048 rows per probe.
- **Contrast probes by route**, correct /256 (form control in brackets: the
  same probe on `read(intact) − read(reversed facts)`, same content, other
  order):

  | Route | initial | step256 | step512 |
  | --- | --- | --- | --- |
  | Workspace (primary) | 128 (128) | 161 (138) | 142 (136) |
  | Common | 128 (128) | 135 (135) | 120 (136) |
  | Total residual | 128 (128) | 144 (141) | 138 (137) |

  At initialization every route output is exactly zero for every memory, so
  there is nothing to read.
- **Distinguishability**, the median of `|intact − twin| / |intact − reversed|`:
  memory 0.65 / 0.58 / 0.57; workspace route 0.63 at both trained states;
  common route 0.55 and 0.43; total residual 0.55 and 0.46. Content changes
  move each rung about half to two thirds as much as reordering the same facts.

## What it means

1. **The verdict cannot be taken literally.** The ladder assumes a later rung
   cannot pass when an earlier one truly fails. At step256, R2 passed while R1
   failed, so R1's failure belongs to the probe. The attention probe never
   learned to use memory. In 8 of 9 runs its training loss with real memory
   (0.675–0.679) was within 0.003 of the same seed's loss with zeroed memory
   (0.678–0.679). The exception, step512 seed 3 (0.659), is the one run that
   passed both tests. The plan's probe settings (300 full-batch steps at
   learning rate 1e-3, width 64) were never power-checked at this scale. The
   tiny qualification passed with planted content at learning rate 0.01 and
   width 8. Whether a better-trained or different probe reads the memory is
   untested.
2. **The read output carried content at step256.** The two affected questions
   of a world are reciprocal ("Is Galen ranked above Kestrel?", "Is Kestrel
   ranked above Galen?"), and the twin swaps exactly that pair. One direction
   can separate both questions' contrasts only if the output relates the
   question's order to the swapped fact. The workspace route did so for 161 of
   256 held-out questions, against 138 for the same probe on a pure
   reordering. The common route carried less. By step512 the workspace route
   was at 142 (p = 0.068).
3. **Together with V19, the loss sits in transport.** At step512, V19 found
   that the content-dependent change in the answer gap was tiny and
   undirected (FP64 median 0.0032, donor-directed 129 against 127). On dev,
   that change fell during training (0.0132 at update 128, 0.0035 at 512).
   Where V19's donor hinge was active, it sat at its maximum for almost every
   pair (484–498 of about 510 per epoch), so the objective gave the content
   term nothing to follow. A1 adds that content was linearly present in the
   workspace read output at update 256 and weaker at 512. The answer-residual
   route adds that output to the last normalized state, where the frozen head
   reads it, and the content part became almost no change in the answer gap.
   This is a descriptive reading, not the verdict.
4. **For A2.** v4's logit route maps the workspace onto the answer logits with
   its own learned map. It does not add the output to the last hidden state
   under a norm budget that V19's memory-independent shift already filled.
   That is the rung A1 and V19 point at. Two lessons carry over:
   - every probe and endpoint should be power-checked at real scale, with
     planted content and the plan's exact settings, before launch;
   - the content objective must not saturate the way V19's donor hinge did.
5. **A data note.** In V19's worlds, the first question of each reciprocal
   pair is always the one true in the intact world. Labels are balanced, the
   model sees each question as its own prompt, and the zero-memory probe is at
   chance, so this gives no shortcut here. Any design that uses question
   position should still counterbalance it.

## Verification

All 44 pulled receipt files are byte-identical to Furnace. The sealed
[verifier](../../../scripts/verify_v20_a1_ladder.py), run from a clean clone of
`5b5776b`, rehashes the 646 sources, both qualification bundles, the dispatch
and every role manifest. It checks every extraction against V19's world counts
and shapes, and re-derives every state's tests and verdict from the recorded
per-world counts: [local](OFFLINE_VERIFY_LOCAL.json),
`OFFLINE_V20_A1_LADDER_RECEIPT_PASS`. On Furnace, in the sealed checkout with
the feature files present, the same verifier also refits every probe and
requires `LADDER.json` to match exactly. A small driver
([`verify_a1_refit.py`](verify_a1_refit.py)) runs it under the probe role's
arithmetic: GPU hidden, 8 threads, deterministic algorithms.
[Furnace](OFFLINE_VERIFY_FURNACE.json) also reports
`OFFLINE_V20_A1_LADDER_RECEIPT_PASS`, with every probe refitted exactly; only
`probes_refitted` differs between the two reports.

Nothing was relaunched, no weight was deleted, and nothing here trains the
workspace, changes an answer or says that the native model uses memory.
