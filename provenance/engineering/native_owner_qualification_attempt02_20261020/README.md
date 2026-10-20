# Native owner qualification — attempt 02

2026-10-20. **`INCOMPLETE_NO_RETRY`; not a qualification PASS.**
Source `e4051069ee73cfacad3d35a73c1bde75e0cce40f`, with 681 sealed files.
This is Ryō's authorized new-source CPU-backend correction, separate from
[attempt 01](../native_owner_qualification_20261020/README.md).

CPU: **196 passed / 199 selected; 3 failed, 0 errors, 0 skipped**. Pytest took
45.67 seconds and the terminal receipt elapsed **48.80170820560306 seconds**.
CUDA remained **undispatched** because CPU did not pass. The unchanged limits
were 900 seconds per device and 4 GiB CUDA allocation per process. Runtime:
Furnace Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0.

This source added explicit native CPU math SDPA to scratch, preserving BF16
inputs/outputs and leaving CUDA and the three eager HF fixtures unchanged.
Ten extra policy/dtype/restore guards retained every original test. The local
macOS development suite passed 214 cases; that did not predict Linux success.

The original two scratch BF16 backward failures recurred, and the added
`test_scratch_explicit_cpu_math_keeps_dtype_and_cuda_policy[dtype1]` failed
with the same literal error:

```text
RuntimeError: DNNL does not support bf16/f16 backward on the platform with avx2_vnni_2
```

**Math-SDPA selection alone was insufficient.** This narrows the remedy; it
does not identify which remaining native operation called oneDNN. Do not
claim an attention-only cause from this record. PyTorch's [upstream report](https://github.com/pytorch/pytorch/issues/148861)
describes the same ISA/backward limitation and disabling oneDNN as a way to
run backward. The next proposed condition explicitly disables **CPU oneDNN**
for the whole qualification, including child processes; it does not convert
BF16 weights or remove tests. Its result must be recorded separately.

Evidence: [source seal](attempt02/SOURCE_SEAL.json),
[CPU start](attempt02/cpu/STARTED.json),
[CPU terminal receipt](attempt02/cpu/FINISHED.json),
[literal XML](attempt02/cpu/TESTS.xml),
[offline incomplete verification](OFFLINE_INCOMPLETE_VERIFY.json).
The original attempt and this attempt are retained unchanged. No automatic
retry, 7B update, generation, judge call, weight deletion or CUDA dispatch
occurred. The old expression gate is `FAIL`, winner `none`, and non-regression
`NOT_ESTABLISHED`.

Remote checkout ends in `worktrees/latent-workspace-native-owner-attempt02-20261020`;
remote output ends in `tmp/latent-native-owner-qualification-20261020/attempt02`
under `/home/ryospiralarchitect/spiralreality/SpiralReality`.
