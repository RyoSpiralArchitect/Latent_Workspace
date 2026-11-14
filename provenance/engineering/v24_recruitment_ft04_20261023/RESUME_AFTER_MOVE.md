# V24 FT04 — handoff across Furnace relocation

Recorded locally **2026-10-23 20:19 JST**.

## Current state

- Ryō explicitly reported having powered Furnace off for relocation. Power state
  is **USER_REPORTED_POWERED_OFF**; the exact shutdown time and shutdown method
  are unknown. This is human confirmation, not independent hardware telemetry.
- The agent did not issue shutdown, kill a workload, or override an inhibitor.
  No more remote calls were made after that confirmation. The earlier SSH
  connection failure is retained as a transport observation, not power evidence.
- All identified preservation targets had already been copied, rehashed and
  synchronized by **19:48:07 JST**. This covers the recorded files/screens, not
  every anonymous-memory buffer or unsubmitted interactive input.
- Paired FT is finished: **32/32 updates per arm, 64 scientific / 67 total**.
  Do **not** restart or resume the completed training dispatcher.
- Closed LTWS metadata/logs, local analysis and recovery receipts are on the Mac.
  Both final 27.01-GiB tensor bodies and the private cross-project recovery
  capsule remain on Furnace's SSD. They are **not off-host backed up**.
- No automatic reminder/restart was requested. The completed heartbeat remains
  deleted; no replacement automation was created.

## On the next explicitly requested session, approximately October 25

1. Confirm Furnace availability through the existing Spiral transport. If the
   address changed, follow the Furnace skill's pinned-identity peer-recovery
   procedure; do not guess or rewrite its address from connection failure alone.
2. Recheck the intended checkout, GPU/CPU jobs, storage and current boot. Read
   the completed receipts before doing anything that could launch work.
3. Verify both final weight files against their saved body hashes in
   [FINAL_CHECKPOINT_BODY_VERIFICATION.json](FINAL_CHECKPOINT_BODY_VERIFICATION.json).
   Confirm the private volatile capsule against
   [its copy manifest](volatile_recovery/receipts/COPY_MANIFEST.json).
   Do not rerun the one-shot snapshot helper or restore opaque SHM/units/locks.
4. Continue from [the offline analysis](offline_analysis_20261023/README.md).
   Proposed next work is separately frozen semantic-value/step scoring,
   matched route controls and base-preservation evaluation, **not automatically
   authorized model execution** by this handoff.

The unchanged scientific ceiling is **old expression gate FAIL**, **winner:
none**, **non_regression: NOT_ESTABLISHED**. New analysis is post-hoc and did not
change prompts, training, target order, thresholds, rubrics, or completed results.

All additions in this follow-up remain local and uncommitted. No GitHub push,
PR, model/provider call or weight deletion was performed.
