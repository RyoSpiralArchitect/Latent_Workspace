# F0 eight-step CUDA pilots

## Question

Can an eight-step BF16 F0 pilot verify full-scope optimization attempts for
every base-model tensor, does every tensor retain an exact persisted element
delta, and can a step-four checkpoint reproduce the uninterrupted result
bitwise under a fixed eight-step schedule?

## Frozen design

Mistral-7B-Instruct-v0.3 at revision
`c170c708c41dac9275d15a8fff4eca08d52bab71`; CUDA/BF16/SDPA;
full-parameter Adafactor; seed 42; eight optimizer steps.

## v1 result: failed strict persisted-delta hypothesis

Training and final-bundle serialization completed. Optimizer membership
covered all 291 base tensors exactly and without duplicates. Exact persisted
comparison found changed elements in 240 tensors and zero net stored delta in
51 tensors. All 51 were one-dimensional BF16 RMSNorm scales of shape `[4096]`.
The runner state is `invalid_final` because this run predates the dynamic
per-tensor update receipt.

### Failed hypothesis

The strict hypothesis that all 291 persisted base tensors would change after
eight steps failed.

### Interpretation

Optimizer membership and final stored-value change are different assertions.
The v1 artifacts do not contain name-bound dynamic evidence sufficient to
decide whether the 51 tensors had finite nonzero gradients and were processed
by the optimizer before ending at their original BF16 value.

### Claim boundary

This is a completed engineering pilot and a useful negative result. It is not
a verified matrix run, a training-quality result, evidence of causal memory,
or a positive scientific result.

Compact v1 evidence is under
[`provenance/pilots/F0_8step_all_tensor_gate_failed/`](../provenance/pilots/F0_8step_all_tensor_gate_failed/).

## v2 result: verified optimization attempts

A fresh run under the replacement contract completed eight optimizer steps
and reached `verified_completed`. It bound all 291 base tensors by name to
exact, duplicate-free optimizer membership. At the first positive-learning-rate
full-update step, every base tensor had a present, finite, nonzero gradient, a
positive base learning rate, an unskipped optimizer step, and optimizer state
advanced to at least step one.

The independent persisted-value assay again found exact changes in 240 of 291
tensors. The same 51 BF16 RMSNorm scale tensors had zero net stored delta and
are classified as `verified_update_attempt_zero_persisted_net_delta`. Thus the
v2 engineering gate passes while the stricter claim that every persisted
tensor changed remains false.

Final F0 functional query accuracy and held-out query accuracy were both 0.5;
the amputated evaluation was also 0.5. This is not a positive functional
result.

Compact, byte-verified v2 evidence is under
[`provenance/pilots/F0_8step_v2_verified/`](../provenance/pilots/F0_8step_v2_verified/).

## Historical pre-spill fixed-engine result

The pre-spill pilot was rerun under engine SHA-256
`3139c6edea71575310a2e6f245999e504318fedede202786fe2c949861ad2e1c`.
Its `RUN_VERIFICATION.json` SHA-256 is
`ba5d5a524565a9e59e6bfc207b861d786ea9e21514008318db63e1f6d8ed1191`.
It completed eight optimizer steps and reproduced the v2 mechanical result:
all 291 base tensors had exact, duplicate-free optimizer membership and
name-bound dynamic update evidence; 240 retained an exact persisted change and
51 BF16 RMSNorm scales retained zero net stored delta.

Required held-out and amputation execution passed under assay receipt SHA-256
`410b295534e25f7d24faa1fd988cf86ef85bef06d2b77dff210572571ef2480a`.
Held-out accuracy was 0.5, amputated accuracy was 0.5, and the amputation task-
loss delta was 0.0. This is an integrity PASS with neutral scientific direction,
not a positive functional result.

## Historical resume failure, cause, and fixed rerun

An earlier strict resume comparison failed despite exact RNG, sampler,
scheduler, scaler, RunState, and optimizer step counters. PyTorch's standard
`Optimizer.load_state_dict` path cast saved FP32 Adafactor state tensors to the
BF16 parameter dtype. That lossy moment reload produced mismatch in all 291
optimizer-state entries and 14,519,381 differing final base elements.

The engine now validates the exact name/group/index optimizer mapping and then
replaces optimizer tensor state from the checkpoint without changing its saved
dtype or value. The fixed equivalence harness used an eight-step uninterrupted
control and resumed from the step-four checkpoint for four more steps: 12
optimizer steps were executed across those two branches. Receipt SHA-256
`5e5b4178005a89beacfb5742edd307e15401a49d1af33543da5f36374330a645`
records PASS with:

- zero changed tensors and zero changed elements across all 291 tensors /
  7,248,023,552 elements;
- exact workspace state and exact trainer state, including optimizer,
  scheduler, scaler, sampler, RNG, and RunState;
- exact stable train and final metrics after excluding only declared runtime
  telemetry fields.

This verifies one fixed-schedule, single-GPU F0 seed. It does not verify signal
preemption, schedule extension, multi-GPU or cross-runtime reproduction, or the
active stochastic workspace route; F0 bypasses that route.

After the corrected successor passed, the obsolete failed attempt received a
separate bounded cleanup. Sixteen safetensors totaling 57,984,323,680 bytes were
deleted; compact diagnostic evidence, trainer/workspace states, metrics, and
manifests were retained. The intent and receipt are under
[`provenance/pruning/F0_resume_attempt2_failed_optimizer_dtype_weights/`](../provenance/pruning/F0_resume_attempt2_failed_optimizer_dtype_weights/).
This one explicit transaction does not authorize automatic failed-run pruning.

## Retention state

After run, assay, and resume receipts passed, the F0 run was exported to a
rehashed compact evidence bundle and transitioned to `verified_pruned`.
Exactly 14,496,105,708 bytes of the final trained base-model bundle were
removed from the baseline run's `final/base_model`. The retained hashes prove
identity and history but cannot reconstruct that deleted bundle. The successful
resume-equivalence pilot originally left exact experimental copies, but they
were never declared or managed as a durable backup. Current retention state is
reported by the newer CUDA smoke evidence and bounded cleanup receipts.

The path-free publication record is
[`PUBLIC_EVIDENCE.json`](../provenance/pilots/F0_fixed_engine_verified_pruned/PUBLIC_EVIDENCE.json),
SHA-256
`d787e5ac95fc355c1397d4bff2e6bcda95e41065b722ac2ac482447d35686fcb`.

## Current spill-engine F0

The active CPU-spill F0 rerun uses engine SHA-256
`755ddaee835cd6cf0d30269212226250a5aeed14e5457385ceca60db0f39aa3c`.
It again verified optimizer membership and dynamic update attempts for all 291
base tensors / 7,248,023,552 elements; 240 tensors retained a persisted change
and 51 retained zero net BF16 change. Its held-out and amputated accuracies were
both 0.5, so assay execution passed with neutral direction.

The current-source CPU-spill and native CUDA bundles are byte exact for all base
tensors, all 81 workspace tensors / 74,379,022 elements, all 810 trainer tensors
/ 2,966,771 elements under declared identity exclusions, and stable metrics
under declared telemetry exclusions. The exact step-four resume comparison also
passes. Mean eight-step throughput was 5.895 supervised tokens/s for spill and
83.950 for native, an observed 14.24x slowdown for this matched pilot.

Current evidence is under
[`provenance/pilots/v10_cuda_smoke_current/`](../provenance/pilots/v10_cuda_smoke_current/).
The current-source native oracle file SHA-256 is
`90ec14d5dee00750e25c5f93f5af33d31f7fae188266dfe2e7bfd1a4bb1c8a02`;
the current resume receipt file SHA-256 is
`0e4d066223783be0b7a272f9eb8e76dbda9f8efdf092ccbddcf95bd680d2cbe8`.

The later bounded duplicate cleanup removed the current native shadow, retained
d5 oracle body, and resume checkpoint/final weight copies after their receipts
were preserved. Independent postflight found no trained safetensors outside the
pinned initial-model cache. No loadable trained F0 copy is declared or remains
in the scoped Furnace worktree; hashes and comparison receipts are not backups.

## Current handoff

The four-condition seed-42 smoke profile is engineering-complete and retained
as compact evidence. n=3 and n=10 have not run. F0 has current-source native
equivalence; B native multi-microbatch equivalence remains capacity-blocked.
The GitHub repository URL and remote are still pending.
