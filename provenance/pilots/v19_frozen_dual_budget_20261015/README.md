# V19 frozen dual-budget diagnostic — attempt 01 (stopped)

2026-10-15. **STOPPED BY THE GPU CONTENTION GUARD; `INCOMPLETE_NO_RETRY`.**
The pure decoupling arm `ordered_cap025` completed and is **`NOT_ESTABLISHED`**:
0/256 held-out donor-directed flips. `final_cap025` trained all 512 windows but
stopped during its held-out step-512 evaluation when another project's process
appeared on the GPU; its endpoint is **missing, not zero**. `ordered_cap100` and
the replay were never dispatched, so neither paired comparison is computable.
Nothing was relaunched. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

The separate budget did what it was built to do: the workspace route now
carries its full 0.25 for every real memory (V18: about 0.0004). But it spends
that budget on a shift that is the same for intact, twin, reversed and
unrelated facts, so memory content still does not reach native answers.

## Source and dispatch

Execution commit `097d8dd13856ed1611f9b1c0ab41f9f069773606`, bound by the
[613-file seal](furnace/SOURCE_SEAL.json) (SHA-256 `f33307b2…0f537dad`), byte-
identical on Furnace and locally. Design and endpoints were frozen before launch
in [DUAL_BUDGET.md](../../../docs/v19/DUAL_BUDGET.md); the
[handoff](EXECUTION_HANDOFF.md) records the dev checks. One detached
[dispatch](furnace/launch_v19_frozen_diagnostic.sh) (UTC,
[timeline](furnace/LAUNCH_TIMELINE.log)): tiny CPU qualification 02:39:49Z,
CUDA 02:40:19Z, diagnostic 02:40:54Z → `diagnostic exit=1` at 05:47:27Z.

| Process | Status | Elapsed | Peak CUDA allocated | Peak RSS |
| --- | --- | ---: | ---: | ---: |
| Tiny CPU qualification | 47/47 PASS | 28.99 s | — | — |
| Tiny CUDA qualification | 47/47 PASS | 34.27 s | 67,536,896 | — |
| `ordered_cap025` (PID 1922959) | `V19_FROZEN_ARM_COMPLETE` | 5,600.3 s | 15,369,354,752 | 5,950,521,344 |
| `final_cap025` (PID 1938320) | `INCOMPLETE_NO_RETRY` | 5,590.3 s | 15,369,190,912 | 5,949,906,944 |
| `ordered_cap100`, replay | not dispatched | — | — | — |

Bytes. The [dispatch receipt](furnace/raw/FINISHED.json) is
`INCOMPLETE_NO_RETRY` (11,192 s), completed roles `["ordered_cap025"]`, error
`final_cap025 exited 1; no later role or retry dispatched`. The frozen backbone
hash was `9db998af…` at the start of both arms and at the end of
`ordered_cap025`, equal to the pinned original; every one of the 1,024 window
receipts records no base change. Checkpoints stay on Furnace under the task
root's `checkpoints/`: `ordered_cap025` steps 256 and 512, `final_cap025` step
256 only (79.7 MB each). The step-512 checkpoint of `final_cap025` is written
after its evaluations and therefore does not exist. No weight was deleted.

## What stopped `final_cap025`

The run's resource guard samples the GPU's compute clients and stops **its own**
job if another one appears; it never touches the other workload. Its
[last sample](furnace/raw/final_cap025/RESOURCES.jsonl) (1,097th, phase
`evaluation:512:104:0`, inside the held-out step-512 evaluation) showed a second
client, PID 1959382 with 7,291,797,504 bytes, from the same shared Furnace
interpreter; the 1,096 earlier samples showed only the run itself. The arm
recorded `Another GPU client; stop own job only` and exited 1; the dispatcher
then refused to start any later role, as designed.

At 05:48Z PID 1959382 had exited and the GPU had no compute client. Processes
starting on Furnace at that time belonged to another project's job series
(`aether_loop_escape_v1_20261015`); the guard does not record ownership, so the
attribution of PID 1959382 is likely, not proven. No process was stopped or
modified.

## Pre-registered endpoint (final split, update 512)

| Arm | Verdict | Actual flips /256 | Random-pair flips | Margin | Worlds +/−/0 | Sign-test p | Unaffected changes /768 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| `ordered_cap025` | `NOT_ESTABLISHED` | 0 | 0 | 0 | 2/6/120 | 0.965 | 7 |
| `final_cap025` | **missing** (stopped) | — | — | — | — | — | — |
| `ordered_cap100` | not run | — | — | — | — | — | — |

Selection (`ordered_cap025` vs `final_cap025`) and budget dose
(`ordered_cap100` vs `ordered_cap025`): **not computable**. Every zero-memory
row equalled the frozen direct base exactly. Reversed, equal-slot and
same-memory factors produced zero flips at every saved evaluation of both arms.
Accuracy with memory stayed at the frozen base: on final "ranked above"
questions intact 272/512 versus the direct base's 274/512; on "outrank"
questions 261/512 versus 261/512, with 17 instead of 20 exact ties.

The descriptive dev curve (64 worlds, 128 affected questions) never left zero
actual flips in either arm:

| Arm | Dev update | Random-pair flips | Worlds +/− | Sign-test p | Unaffected changes |
| --- | ---: | ---: | --- | ---: | ---: |
| `ordered_cap025` | 128 / 256 / 384 / 512 | 0 / 0 / 0 / 0 | 5/9, 3/0, 3/1, 5/0 | 0.910, 0.125, 0.313, 0.031 | 2 / 0 / 0 / 0 |
| `final_cap025` | 128 / 256 / 384 / 512 | 1 / 0 / 1 / 1 | 6/8, 2/1, 2/0, 4/4 | 0.788, 0.500, 0.250, 0.637 | 4 / 0 / 0 / 2 |

The ordered arm's dev-512 5/0 did not hold on the held-out split (2/6). Dev is
descriptive only; there was no dev selection, early stopping or threshold change.

## The freed route learned a content-independent shift (post-hoc, descriptive)

[`posthoc_routes.py`](posthoc_routes.py) reads only the saved records and
writes [POSTHOC.json](POSTHOC.json). Run on the V18 bundle
([reference output](POSTHOC_V18_REFERENCE.json)), it reproduces V18's
published route norms and transport counts exactly. Mean residual norms
(common cap 1.0, workspace cap 0.25):

| Run | Memory | Total | Common | Workspace |
| --- | --- | ---: | ---: | ---: |
| V18 ordered, final 512 | intact | 0.9987 | 0.9984 | 0.0004 |
| V19 `ordered_cap025`, final 512 | intact, twin, reversed | 1.2203–1.2225 | 0.9988–0.9989 | 0.2499–0.2500 |
| V19 `ordered_cap025`, final 512 | unrelated | 1.1154 | 0.9973 | 0.2487 |
| V19 `ordered_cap025`, final 512 | norm-matched random | 0.6891–0.7185 | 0.6658–0.6804 | 0.2109–0.2119 |
| V19 `ordered_cap025`, final 512 | common-only control | 0.9991–0.9992 | 0.9991–0.9992 | 0 |
| V19 `final_cap025`, dev 512 | intact, twin, reversed | 1.2423–1.2444 | 0.9985–0.9986 | 0.2500 |

The workspace route sits at its own cap from update 128 on for every real
memory, whichever facts it holds. The part that depends on content is tiny and
undirected. For the 256 affected held-out questions of `ordered_cap025`, the
FP64 intended change in the answer gap between intact and twin memory has
median magnitude **0.0032**, donor-directed for 129 versus 127 questions; only
14 published bf16 gaps changed at all (bf16 quanta here are 0.125). On dev the
same median *fell* during training, 0.0132 at update 128 to 0.0035 at update
512 (`final_cap025`: 0.0137 to 0.0038). The dev donor-directed counts at update
512 (75/53 ordered, 81/47 final) are FP64 signs of these tiny changes, not
answer changes.

Training gave the content term almost nothing to follow. In every epoch of
both arms about 510 of 2,048 pairs have a positive donor hinge, and 484–498 of
them sit at the hinge maximum (no donor-directed movement), the same as V18
(489–503). Mean answer CE moved slightly, 0.1121 to 0.1108 (V18 0.1141 to
0.1129). Both runs are consistent with the objective rewarding a
memory-independent shift that lowers answer CE while the content contrast
stays far below the resolution of the bf16 gap the hinge sees. This analysis
was chosen after seeing the results and is not a pre-registered test.

## Verification, and a defect in the sealed verifier

All 64 pulled receipt files are byte-identical to Furnace. The sealed
[verifier](../../../scripts/verify_v19_frozen_diagnostic.py) accepts only a
complete dispatch, so an additive
[attempt-01 check](verify_attempt01.py) loads it from a clean checkout of
`097d8dd` and reuses its functions: sealed sources (613), both qualification
bundles, dispatch and role manifests, every window journal entry, and every
saved summary and diagnosis recomputed from the gzip records, plus the matched
selection-arm contracts and initial states. It also requires that only the
step-512 held-out evaluation is missing and that no endpoint, final state or
step-512 checkpoint is claimed for `final_cap025`.
[Local](OFFLINE_VERIFY_LOCAL.json) and [Furnace](OFFLINE_VERIFY_FURNACE.json)
(clean dev checkout at `097d8dd`, all three checkpoint bodies rehashed) both
report `OFFLINE_V19_FROZEN_ATTEMPT01_STOPPED_RECEIPT_PASS`.

Running it exposed a defect: the sealed verifier compared checkpoint receipts
with the **V18** owner's format string, which no V19 checkpoint carries, so it
would have rejected even a complete V19 run (`ValueError: Checkpoint 256`). The
attempt-01 check therefore replaces only that comparison, using the sealed V19
window owner's own `FORMAT`. The branch now fixes the verifier and adds
[regression tests](../../../tests/test_v19_frozen_verifier.py), kept outside
the plan's 47 qualification cases; the fixed `verify_arm` accepts the real
`ordered_cap025` bundle including both receipts. The run itself did not use the
verifier, so no executed result changes.

## What is open

The decoupling question has its answer: an independent workspace budget is
used in full, yet memory content still does not reach answers, because the
route's output is dominated by a memory-independent shift. The selection and
budget-dose comparisons remain unanswered. The unexecuted `ordered_cap100` arm
is the only remaining test here of whether a four-times larger content budget
lifts the contrast above bf16 resolution.

**Closed by decision.** On 2026-10-15 Ryō decided not to run an attempt 02 (a
full re-dispatch of the unchanged plan) and to direct the resources to V20.
Attempt 01's bytes stay as they are, and the missing and unrun parts stay
missing. What V19 settled and what V20 inherits are collected in the
[closeout](../../../docs/v19/CLOSEOUT.md).
