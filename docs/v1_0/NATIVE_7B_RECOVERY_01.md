# Native 7B canary — identity repair, recovery 01

2026-10-20. Ryō explicitly authorized this **separate** attempt after the
[failed original-model identity check](../../provenance/engineering/native_7b_canary_20261020/README.md).
The [completed result](../../provenance/engineering/native_7b_identity_recovery01_20261020/README.md)
passes the short 7B update/restart gate: two native updates, two checkpoints,
exact step-1 restore and exact step-2 replay in a fresh process. CPU/CUDA each
passed 244/244; both original-model hash schemes matched in both roles.
No full training population, generation, judge, further
deletion, automatic retry, PR merge or Hub publication is selected.

The old plan, source commit `59188535516eb32d57a42fb23fa4a7cc91585511` and all
its terminal artifacts remain historical and unchanged. The living runner
now selects [a new plan](../../configs/v1_0/NATIVE_7B_CANARY_RECOVERY_01.json),
canonical SHA-256
`6f692b785185c60f294925a25fa22e3ee2774a86c85e0372240cc159a8657526`.
It executes only from a new sealed commit and fresh output/checkpoint paths.

## Repair, not a weaker identity test

The original plan paired a tree-hash digest with the legacy hashing function.
The repair names and independently checks **both** schemes:

| Scheme | Expected original-model digest |
| --- | --- |
| `legacy_state_v1_sha256` | `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312` |
| `state_tree_v1_sha256` | `9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189` |

These expected values predate this recovery and are bound to the complete
historical V18 `CONTEXT.json` digest. They are not learned from a new run.
Before rejecting any mismatch, the runner writes `ORIGINAL_IDENTITY.json`
with expected values, actual values and per-scheme match flags. The tree-hash
measurement also supplies the original-base identity in the training contract.
The offline verifier binds these measurements to the plan and run contract,
and still verifies the old, failed bundle using its own sealed source/plan.

Fifteen new regression cases cover both actual hashing algorithms on tiny
BF16 tensors, cross-scheme swaps, individual digest failures, changed weights,
missing/extra scheme names, exclusive receipt creation, damaged evidence and
the unchanged execution recipe. No old test is removed: **244 cases per
device** (CPU then CUDA), plus the existing 20 local verifier cases.
Every selected case must pass without skips before a 7B dispatch.

## Unchanged experiment and limits

All training rows, rendering, ordering, seed, optimizer, arithmetic, cut,
checkpoint/replay endpoints, resource thresholds and stop rules are identical
to the failed attempt. A regression compares the old/new plans field by field
and permits only identity, recovery provenance, schema and qualification
additions. The native graph, optimizer owner and transport are not modified.

- Local-only pinned Mistral-7B-Instruct-v0.3; native BF16, cut 4, eager
  attention, non-reentrant checkpointing, CPU FP32 Adafactor, learning rate
  `2e-7`, seed 47.
- Four fixed synthetic inputs; two unique updates, checkpoint steps 1/2,
  then exact step-2 replay from step 1 in a fresh process. Six backward-row
  occurrences planned. No replay weight file.
- Qualification: 4 GiB allocation / 900 seconds per device; CPU oneDNN off.
- Real model: 31-GiB free-GPU admission, 30.5-GiB allocator cap, 0.75-GiB
  free-GPU floor, 100-GiB available-host admission, 24-GiB available-host
  floor, 50-GiB free-disk floor, 7,200 seconds per role, two CPU threads.
- Snapshot/load requires 32 GiB additional available host memory above the
  floor. The two-checkpoint forecast remains 64 GiB.

Stop at the first source, identity, gradient, resource, update or replay
failure. Preserve the partial result without retrying or relaxing any limit.
Only a successful exact replay establishes this short real-7B engineering
gate. It does not establish useful memory learning, longer-sequence fit,
full-FT feasibility at scale, base non-regression or release readiness.
Historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
