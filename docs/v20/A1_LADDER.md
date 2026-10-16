# V20 A1: where does memory content get lost?

2026-10-16. **RESULT: `CONTENT_ABSENT_IN_MEMORY` at all three states by the
rule below, but not readable literally.** The memory probe never learned to use
memory, and at update 256 the read-output test passed (161 of 256 held-out
affected questions, p = 7e-5), which content absent from memory could not
produce. Read descriptively, the content is lost in transport. See the
[results](../../provenance/pilots/v20_a1_ladder_20261016/README.md).
Frozen before launch as follows. The first of the three experiments agreed
with Ryō (A1 → A2 → D2), on the Availability corner of the
[V20 square](SCOPE.md) and built on the [engine](../ARCHITECTURE.md). The old
**FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Question

In V19's frozen dual-budget pipeline, intact versus twin facts never moved a
native answer ([attempt 01](../../provenance/pilots/v19_frozen_dual_budget_20261015/README.md)).
At which rung is the content lost: in the written memory, in the read output,
or on the way to the native head? The answer decides A2: if the read output
still carries the content, a learned route can recover it; if the memory never
held it, the writer is the place to work.

## What is read, and how

V19 attempt 01's `ordered_cap025` state at initialization and after updates 256
and 512 (sealed `097d8dd`; checkpoint bodies stay on Furnace). Rule 6 of the
architecture applies: these historical artifacts are read with the frozen V19
code. Before any reading, the run requires:

- V19's receipts and checkpoint bodies match their pinned hashes;
- the initial state rebuilt by V19's code matches V19's recorded fingerprint;
- the store receipts (renderings, spans, contexts) equal V19's for both splits;
- each published residual equals the recomputed common and workspace parts;
- zero memory reproduces the frozen direct base exactly;
- the reader's queries do not depend on memory.

Three GPU roles record, for every train (256) and held-out final (128) world,
memory condition (intact, twin, reversed facts, unrelated, norm-matched random)
and question: the memory slots, the common and workspace route outputs, and
both reader queries. One CPU role fits the probes.

## Probes (engine: `latent_workspace.ladder`)

- **R1, written memory.** A one-head attention probe (question → memory slots →
  yes/no) is fitted on training rows and tested on held-out rows. Two controls
  are fitted identically: the same probe with zeroed memory (question only) and
  with another world's memory. Measure: content following, meaning both sides
  of an affected pair right, over the 256 held-out pairs. Three probe seeds.
- **R2, read output.** An L2 logistic contrast probe on
  `read(intact) - read(twin)` for affected questions predicts the intact
  answer: 512 training pairs, 256 held-out pairs. Workspace route (primary),
  common route and total residual. Form control: the same probe on
  `read(intact) - read(reversed facts)`.
- **R3/R4, native.** Known from V19: the FP64 intended gap change is
  donor-directed for 129 of 256 held-out questions; no published answer flips.

## Pre-registered endpoint (per state; α = 0.01)

- **R1 passes** if, in every probe seed, content following beats both the
  zeroed-memory and the shuffled-memory probe by a one-sided sign test over the
  128 held-out worlds.
- **R2 passes** if the workspace-route contrast probe beats chance by a
  one-sided sign test over held-out worlds (two affected questions each).

| Verdict | Condition |
| --- | --- |
| `CONTENT_ABSENT_IN_MEMORY` | R1 fails |
| `LOST_IN_READING` | R1 passes, R2 fails |
| `LOST_IN_TRANSPORT` | R1 and R2 pass (R3 is known to be at chance) |

Descriptive, not part of the verdict: probe accuracy on all held-out rows, the
common-route and total-residual contrast probes, the form control, and the
median ratio `|intact - twin| / |intact - reversed facts|` for memory and each
route.

## Execution, tests and limits

The run uses the engine's sealed-execution skeleton (`latent_workspace.execution`):
tiny CPU and CUDA qualification ([18 tests](../../tests/test_v20_a1_ladder.py),
plus the [ladder](../../tests/test_latent_workspace_ladder.py) and
[execution](../../tests/test_latent_workspace_execution.py) suites), roles as
fresh processes in order, no retry. The verdict is computed inside the probe
role, never in the dispatcher. The tests show the extraction keeps V19's
invariants on a tiny V19 learner (FP32 and BF16), that planted content yields
each verdict at the right rung, and that the
[offline verifier](../../scripts/verify_v20_a1_ladder.py) accepts what the
runner writes, refits the probes exactly and rejects an altered count.
[Plan](../../configs/v20/A1_LADDER_PLAN.json).

A pass means these small probes could extract the content from that rung; a
fail means they could not. Nothing here trains the workspace, changes an
answer, or says that the native model uses memory.
