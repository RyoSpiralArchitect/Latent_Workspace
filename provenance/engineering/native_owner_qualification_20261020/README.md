# Native owner qualification — attempt 01

2026-10-20. **`INCOMPLETE_NO_RETRY`; not a qualification PASS.**

The engine-owned native optimizer/restore implementation is complete, but its
first source-sealed Furnace qualification stopped at the CPU gate. This record
is immutable evidence of that attempt; a separately authorized correction must
use a different source and output tree, never overwrite or relabel this one.

## Exact scope and denominators

- Source: `238df7aaf28b6cfd5bcab4e1dd4113ba0c0259fe`; 681 sealed files.
- Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0 on Furnace Linux.
  The interpreter was the existing qualified Aether CUDA environment, not
  the unrelated editable-install checkout. A fresh detached source checkout
  and isolated pre-import launcher were used.
- CPU: **187 passed / 189 selected; 2 failed, 0 errors, 0 skipped**.
  Pytest took 45.42 seconds; the terminal receipt elapsed time is
  **48.683628301136196 seconds**, below the 900-second cap.
- CUDA: **undispatched**, because CPU did not pass. The planned per-process
  allocation ceiling was 4 GiB; there is no measured CUDA peak for this attempt.
- Pretrained-model updates, new generation sequences, judge calls and weight
  deletions: **0**. Randomly initialized tiny tests do perform parameter updates.
- Local macOS development had 204 selected passes before the final source
  freeze (189 engineering cases plus 15 offline-verifier tests). The 15
  [offline-verifier regressions](LOCAL_OFFLINE_TESTS.xml) were rerun at the
  frozen commit and passed. Local success does not supersede this Linux failure.

## Literal failures and what they establish

Both failed in BF16 backward with the literal error:

```text
RuntimeError: DNNL does not support bf16/f16 backward on the platform with avx2_vnni_2
```

1. `tests/test_native_memory.py::test_bfloat16_full_graph_has_finite_loss_and_gradients[scratch]`
2. `tests/test_native_owner.py::test_native_owner_updates_every_partition_with_cpu_state[dtype1-scratch]`

The other 187 cases passed, including Mistral/OLMo2/GPT-2 CPU owner updates,
historical native-family arithmetic parity, checkpoint rejection and
fresh-process FP32/BF16 owner replay. The failures identify a CPU backend
compatibility boundary in the scratch BF16 path, not evidence about 7B training
quality. `ScratchDecoder` calls native SDPA with automatic backend selection;
the three HF fixtures use eager attention. An explicit CPU math-SDPA policy is
the proposed correction, **not an observed successful correction in this record**.
No dtype change, skip, tolerance relaxation or in-place retry was applied.

## Retained evidence and verification

- [SOURCE_SEAL.json](attempt01/SOURCE_SEAL.json)
- [CPU STARTED.json](attempt01/cpu/STARTED.json)
- [CPU FINISHED.json](attempt01/cpu/FINISHED.json)
- [literal TESTS.xml](attempt01/cpu/TESTS.xml)
- [offline incomplete-receipt verification](OFFLINE_INCOMPLETE_VERIFY.json)

Offline verification compared the complete sealed source set and all 681
hashes to the execution commit's Git blobs, rehashed the retained CPU artifact
manifest, parsed literal XML denominators and failure identities, checked
the unchanged claim ceilings and confirmed that no CUDA directory exists.
This is verification of **an incomplete outcome**, not the complete-run
verifier's PASS. Both the remote attempt and copied local artifacts remain.

Remote checkout: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-native-owner-20261020`.
Remote output: `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-native-owner-qualification-20261020/attempt01`.
No unattended monitor was created. The old expression gate is still `FAIL`,
winner `none`, non-regression `NOT_ESTABLISHED`; no 7B canary or FT was dispatched.

Ryō subsequently authorized a **new source/new attempt** with the same
4-GiB/900-second limits, retaining BF16 and all tests, and still excluding
7B execution and weight deletion. Its outcome must be reported separately.
