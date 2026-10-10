# V15 reader question/value interaction: no-update mechanism comparison

2026-10-10 · prospective protocol. Full-update optimizer work is paused by Ryō's
request to address the weak question-side gradient first.

## One factor, not a larger correction budget

The historical reader lets the question choose attention weights over memory
values. Nearly common values can give weak question sensitivity even when the
question projection varies. Earlier value centering did not recover useful
directionality; the recent backward probe established connectivity, not a useful
question gradient. Neither result proves a universal memory collapse.

The opt-in `QueryModulatedWorkspaceBridge` changes only the value entering `up`:

```
q = query_norm(query_projection(question))
r = attention(q, memory_norm(memory), memory_norm(memory))
r_new = r * (1 + 0.25 * tanh(q))
delta = existing_smooth_cap(up(r_new))
```

The writer, parameter keys/count, checkpoint bytes, final-position query, native
full-head readout, BF16/FP32 boundaries, cap 1, loss and denominators are unchanged.
There is no extra trainable parameter or direct question-only additive residual.
This supplies a question/value interaction even for common slots. It is **not**
evidence of entity/role binding: nonzero fixed carriers can support this route.
The 0.25 strength is fixed before execution, not swept or chosen from outcomes.
Channel multipliers lie in [0.75,1.25] before `up`; that is not a 25% bound after
projection/cancellation. Exact zero memory still produces zero correction, and
zero output initialization still blocks upstream gradients until `up` changes.

Historical code and sealed bundles remain untouched. Candidate checkpoint keys
are deliberately compatible; the class/strength must accompany any future
checkpoint metadata. This is not silently enabled in an old training runner.

## Frozen experiment

[Plan](../../configs/v15/READER_MODULATION_PLAN.json): pinned original
Mistral-7B-Instruct-v0.3, seed-47 initial bridge and the exact retained answer-only
step-8 bridge. Each state is loaded into both reader classes without any update.
All 291 base tensors are frozen. All 26 bridge tensors retain their exact bytes.

Two already-exposed training worlds × eight reciprocal queries × eight controls
give **128 evaluation rows per state/arm, 512 total**. There are 32 truth-bearing
intact/twin rows per state/arm, including four affected world/query pairs and
twelve unaffected pairs. These are not independent worlds or new holdouts.

Controls: intact, twin, written zero, unrelated facts, deterministic sin/cos
carrier, seeded random memory, jointly reversed slots/mask, and repeated mean
slots. Carrier/random use the intact written-memory global L2 norm, not matched
post-normalization covariance. Common slots keep the intact masked mean. The
carrier/random values do not contain task facts. No new label enters the reader.

Record full-head native choices, diagnostic FP32 choices, zero/full-logit parity,
delta norms, absolute reciprocal differences, own-norm relative differences,
unit-direction differences and radial/tangential components. Mixed differences
across reciprocal questions and intact/twin memory test whether question effects
depend on memory. A larger effect is not sufficient: affected donor sign and
unaffected/unrelated shifts are reported separately, including zeros and ties.

The gradient panel reuses the original complete 16-pair objective with unchanged
32/4/12/16/48 reductions and EOS coefficient zero. Both EOS forwards still run.
The frozen input features remain detached; the diagnostic pipeline makes an
independent FP32 leaf at each reader question. Measure the actual total gradient
at these 80 leaves per state/arm (48 answer/unrelated, 32 zero-weight EOS), plus
per-parameter gradient norms and output-projection donor cancellation. This is
a **reader-local cut graph**, not a second full-backbone backward measurement.
Finite BF16-cast surrogate gradients need not predict finite native changes.

For each state, before interpreting the intervention, an alpha-zero candidate
must exactly reproduce the legacy delta, and the legacy native scores must
equal the retained historical intact/twin records on all 16 pairs. Runtime
parameter keys/count, source seal, checkpoint and before/after tensor hashes
are checked. Tiny tests also check matched gradients, masks, memory dependence,
common-slot sensitivity, native zero identity and live full-model integration.

## Admission and stopping

No other GPU compute client, at least 20 GiB free on admission, 18 GiB allocator
cap, at least 4 GiB sampled free and 20 GiB disk, two CPU threads and a phase-
checked 900-second limit. Use one isolated Furnace checkout, a committed source
seal and an exclusive output directory. Preserve partial receipts on failure;
no retries, new hyperparameters, optimizer, training, generation, judge requests,
weight deletion or heartbeat. Source/results can be committed locally only.

Mechanical qualification means the intended route exists under the tested
contracts. It does not promote a semantic winner or establish base preservation.
The old FAIL, `winner: none`, `non_regression: NOT_ESTABLISHED`, closed judge
missingness and `INCOMPLETE_OR_CALIBRATION_BLOCKED` remain unchanged. Any future
learning comparison must start from matched initial weights and predeclare its
small reciprocal task, controls, base floor and budget; it is not part of this run.
