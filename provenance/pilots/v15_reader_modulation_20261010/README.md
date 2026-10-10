# Reader question/value modulation: a stronger route, not a semantic winner

2026-10-10 · **COMPLETED_READER_INTERVENTION_NO_STEP**.

The new reader makes the question influence the memory read before output
projection. At the unchanged answer-only step-8 checkpoint, mean reader-input
gradient norm rose **324.40×** and intact reciprocal-question correction distance
rose **418.13×**. Direction differences survive norm matching. However, all
**32/32 intact/twin native choice vectors remain identical to the old reader**:
both score **16/32**, with **0/4 correct donor flips**. This qualifies the tested
question route, not useful memory binding, training success or base preservation.

No optimizer, parameter update, new text generation, judge call or weight
deletion occurred. All results are on **two already-exposed training worlds**;
the retained checkpoint intervention is not a retrained candidate or holdout.

## One changed factor

The [prospective protocol](../../../docs/v15/READER_MODULATION.md) and
[plan](../../../configs/v15/READER_MODULATION_PLAN.json) were committed before
execution. The old reader only uses the question to select attention weights.
The opt-in [candidate](../../../src/latent_workspace_ft_v10/query_modulated_bridge.py)
adds `read * 0.25 * tanh(projected_question)` before the unchanged `up` projection.
Strength was fixed, not swept. There are still **26 tensors / 4,200,192 bridge
parameters**. Writer, checkpoint bytes, final-position query, native full head,
FP32 bridge, BF16 base, cap 1, losses and denominators are unchanged.

Written-zero memory still gives exactly zero correction; a nonzero carrier can
support question dependence and therefore is not evidence of semantic binding.
The old class is unmodified. Strength zero returns its exact forward. State-dict
keys are compatible, but class/strength must be recorded separately from tensor
hashes; identical tensor bytes do not mean identical algorithms.

## Denominators and provenance

- Two bridge states: exact seed-47 initialization and retained native-answer
  step 8; each evaluated with legacy and query-modulated readers: **four cells**.
- Each cell: 2 worlds × 8 questions × 8 controls = **128 evaluation rows**;
  **512 total**, including **32 truth-bearing rows per cell / 128 total**.
  A cell has **four affected and twelve unaffected world/question pairs**.
- Each control has **eight reciprocal comparisons** per cell, not eight
  independent worlds. There are eight question-by-memory mixed differences.
- Each gradient cell has 16 complete-objective pair contributions and **80
  reader leaves**: 48 answer/unrelated leaves, plus 32 zero-weight EOS leaves.
  Across all four cells: **320 observed leaves**, not missing observations.
- Controls are intact, twin, written zero, unrelated facts, sin/cos carrier,
  seeded random memory, jointly reversed slots/mask, and repeated mean slots.
  Carrier/random match the intact memory's global norm, not its normalized
  covariance. Mean slots are a common-component intervention, not a no-facts
  control; the carrier/random directions themselves do not encode task facts.

Source: `fa203409e3c2edc7e50fd774791e3b8f8d24a36f`, with a
[282-file source/data seal](SOURCE_SEAL.json). The model is pinned
`mistralai/Mistral-7B-Instruct-v0.3` at
`c170c708c41dac9275d15a8fff4eca08d52bab71`. The base tensor hash is
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312` before and after.
Bridge hashes are unchanged in all four cells, recorded in the
[terminal receipt](raw/REPORT.json). Retained checkpoint file identity is in
[STARTED](raw/STARTED.json), matching the
[parent pilot](../v15_5_native_answer_20261010/README.md).

## Question sensitivity increased, including direction changes

The gradient below is the actual original objective differentiated at separate
FP32 reader-input leaves. The frozen prefix features are unchanged; this cuts
off the backbone path solely for diagnosis. It is **not a new full-base backward
measurement**, optimizer update, or derivative of discrete BF16 rounding.
Original **32/4/12/16/48** reductions and EOS weight zero are preserved.

Retained step-8 state, matched observations:

| Measurement | Legacy | Query-modulated | Denominator |
|---|---:|---:|---|
| Mean reader-input gradient L2 | 2.712284e-09 | 8.798644e-07 | 48 answer/unrelated leaves |
| Minimum / maximum gradient L2 | 4.383368e-12 / 1.251871e-08 | 1.315461e-09 / 3.672006e-06 | same 48 leaves |
| Intact reciprocal correction absolute L2 | 1.240459e-06 | 5.186771e-04 | 8 reciprocal comparisons |
| Intact reciprocal equal-norm direction distance | 1.225337e-06 | 5.151042e-04 | same 8 comparisons |
| Question × intact/twin mixed correction L2 | 4.009316e-07 | 1.412956e-05 | 8 reciprocal comparisons |
| Mean intact correction norm | 0.9790750764 | 0.9791867156 | 16 questions |

Equal-norm direction distance is the distance between unit directions, multiplied
by mean endpoint norm. It does not recalculate native logits after a norm-matched
intervention. The mixed difference is
`delta(q1,twin)-delta(q1,intact)-delta(q0,twin)+delta(q0,intact)`; its increase
does not establish a task-correct interaction. No confidence interval or
independent-world significance claim is made.

Both retained readers have nonzero gradients at **48/48 eligible leaves**; both
initial readers have **0/48**, because zero-initialized `up` still closes upstream
gradients. All **32/32 EOS leaves per cell are zero**, as specified. The candidate
does not eliminate that initialization condition.

The output-projection donor-gradient cancellation ratio
`norm(sum(pair_gradients)) / sum(norm(pair_gradients))` changed:

| State | Legacy | Query-modulated |
|---|---:|---:|
| Initial | 0.0005175744 | 0.0163741188 |
| Retained step 8 | 0.0001705901 | 0.0064954692 |

This leaves a larger fraction after summation, even at initialization; it is a
raw surrogate-gradient observation, not proof of an effective finite update.
Most individual-gradient norm still cancels. No optimizer preconditioning or
learning trajectory was evaluated.

## Why the sensitivity result is not yet content selectivity

Mean reciprocal correction L2, eight comparisons per control at retained step 8:

| Memory control | Legacy | Query-modulated |
|---|---:|---:|
| Intact | 1.240459e-06 | 5.186771e-04 |
| Repeated mean slots | 0.000000e+00 | 5.189918e-04 |
| Unrelated facts | 1.809019e-06 | 5.015395e-04 |
| Fixed carrier | 7.952505e-03 | 6.739156e-03 |
| Seeded random | 6.153329e-03 | 6.358206e-03 |
| Written zero | 0.000000e+00 | 0.000000e+00 |

The candidate's question effect is almost unchanged when all intact slots are
replaced by their mean, and unrelated facts produce a similar effect. Carrier
and random memory already elicited larger question differences in the legacy
reader. These controls rule out equating sensitivity with understanding.
They support testing whether the new route can learn binding, not selecting it
as a semantic winner. They do not prove no information exists in written memory.

All four cells score **16/32**, with no native ties and **0/4 correct donor flips**.
At retained step 8, all four native donor-signed intact-to-twin margin changes
are exactly zero for both readers. Diagnostic selected-row FP32 margins remain
positive on only **2/4** affected pairs in each reader. Their literal values,
in `(world0 query0, world0 query1, world1 query0, world1 query1)` order:

```
legacy: [-0.0001983642578125, 0.00020599365234375, 0.0006237030029296875, -0.0006237030029296875]
candidate: [-0.00018310546875, 0.00018310546875, 0.000629425048828125, -0.0006256103515625]
```

The twelve unaffected native gap changes remain zero for both. Mean absolute
unrelated-to-base native gap shift stays **0.0703125**, maximum **0.125**, over
16 questions. Preserved choice vectors on this exposed tiny set are not a fresh
correctness floor or evidence of preserved free-generation quality.

## Engineering validation and resource use

- **199 selected tests passed locally and on Furnace**. These include tiny
  FP32/BF16 live-full-model integration, exact strength-zero forward/gradient
  parity, masks, common-slot behavior and the diagnostic cut graph. Local Ruff
  passed. Remote Ruff and CI were not run. See [local](PRELAUNCH_VALIDATION.json)
  and [remote](REMOTE_PRELAUNCH_VALIDATION.json) prelaunch receipts.
- **48/48 ordinary/shared full-head prefix parity checks** passed. All
  **64/64 historical intact/twin native score vectors** matched over the two
  legacy states. Strength-zero deltas matched **256/256** legacy control rows.
- Written-zero full logits matched **64/64**; initial full logits matched
  **256/256**. These sets overlap and must not be added as independent checks.
  All **64/64** jointly permuted slot comparisons had maximum error zero.
- Sole invocation: **37.613406 seconds**, peak Torch allocated **14.125497 GiB**,
  reserved **14.269531 GiB**, minimum sampled free GPU **16.345703 GiB**, across
  **131 phase samples**. This frozen-backbone probe does not estimate full-update
  optimizer memory or training throughput. Postflight had no GPU compute client.
- All **13 raw files / 1,164,045 bytes** were pulled and indexed. The
  [offline summary](SUMMARY.json) and [raw index](ARTIFACT_INDEX.json) replay
  exactly. Replay validates bytes, scalar receipts and denominators, not an
  independent repeat of the real-model tensor computation.

## Decision: test learning before full updating

Keep the candidate as an **opt-in mechanism hypothesis**, alongside the legacy
reader. The next proposed unit is a short, predeclared, matched bridge-only
learning comparison from the same fresh seed-47 tensors, with reciprocal
questions in each balanced window. Keep cap, native readout, AdamW, losses,
data order and budget identical; change only the reader. The retained step-8
intervention must not substitute for this retraining control.

Require useful donor direction and intact/twin separation, not simply gradient
norm or loss decrease. Retain unaffected/unrelated/carrier/random controls,
independent-original-base floor and the later generated behavior bank. If the
small task still cannot bind memory to reciprocal questions, return to the
reader/writer representation instead of escalating to full-backbone training.
Do not tune a gate on the exposed two worlds and call it held-out success.

No such learning run was started here. Full-update one-step/resume work is
deferred. The old **FAIL**, **winner: none**, and
**non_regression: NOT_ESTABLISHED** remain. The judge collection remains closed,
`INCOMPLETE_OR_CALIBRATION_BLOCKED`, and its heartbeat remains paused.
No GitHub push, PR, CI or merge is implied by the local commits.

Safe offline replay (not a new model invocation):

```sh
.venv/bin/python scripts/summarize_v15_reader_modulation.py \
  --bundle provenance/pilots/v15_reader_modulation_20261010
.venv/bin/python provenance/pilots/v15_reader_modulation_20261010/check_publication.py
```

See the [terminal handoff](EXECUTION_HANDOFF.md). Do not rerun the real-model cell
or overwrite the frozen artifacts with `--write`.
