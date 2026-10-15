# V16 bounded full-update comparison: terminal result

Verified 2026-10-15 from the completed Furnace artifacts, execution source
`59f0c15965db7c22f6362825bb8873a7aede391a`. The original launch snapshot remains
unchanged. [Terminal receipt](raw/FINISHED.json) and
[offline replay](OFFLINE_VERIFY.json) establish completion, not semantic success.

- Completed **6/6 unique update windows, 3/3 exact next-update replays, 144/144
  backward pairs**. Replay pairs are not independent training samples.
- Completed **1,440 workspace rows, 144 direct-base rows, 720 factor rows** across
  steps 0/1/2. All share only two exposed worlds and one training seed (47).
- Original base: 8/16 correct for either memory world's labels.

| Final step-2 arm | Intact correct | Twin correct | Intact/twin ties | Original-correct regressions, intact/twin | Repairs, intact/twin |
| --- | --- | --- | --- | --- | --- |
| common | 10/16 | 8/16 | 1 / 1 | 0 / 1 | 2 / 1 |
| raw matched control | 8/16 | 8/16 | 1 / 1 | 1 / 1 | 1 / 1 |
| slot contrast | 9/16 | 8/16 | 2 / 2 | 0 / 1 | 1 / 1 |

At step 1, all arms reached 11/16 intact and 9/16 twin, identical to their current
trained base without workspace. The final slot-contrast choices likewise match
its current trained base (9/16, 8/16). These are training-exposed observations,
not evidence of held-out gain or base non-regression.

All three arms have **0/4 changed native affected answer margins and 0/4
donor-directed flips** at step 2. Internal residuals and some other vocabulary
logits change, but affected greedy next tokens do not. Intended FP64 projected
direction is donor-aligned only 2/4 in each arm; numerical visibility is not the
only unresolved factor. No free sequences or external judge calls were made.

Slot interaction-query gradients are nonzero: accumulated step-2 L2
`5.254306384978488e-05`. Across final intact/twin queries, mean interaction norm
is `0.00013222036841398221`, compared with common-route `0.7299620825797319`.
Raw-control interaction mean is `0.050975797697901726`. This is a live but small
interaction contribution, not proof that slot collapse is its cause. Decompose
slot variation, attention selection, output mapping and native visibility next.

The summed arm wall time is 4,067.20 seconds (about 68 minutes). Maximum CUDA
allocation is 29,835,256,320 bytes; maximum reserved is 30,454,841,344 bytes.
Two checkpoints per condition remain on Furnace. No weights were deleted.

**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.
The next [population diagnostic](../../../docs/v16/POPULATION_DIAGNOSTICS.md)
is a separately scoped evaluation of these existing checkpoints, not a rerun
of this completed training pilot or a new training-seed replication.
