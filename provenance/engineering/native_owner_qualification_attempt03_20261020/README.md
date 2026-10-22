# Native owner qualification — attempt 03

2026-10-20. **`TINY_NATIVE_OWNER_AND_REPLAY_PASS_NOT_7B` on CPU and CUDA.**
The native-memory graph now has a qualified small-model CPU-master optimizer,
ordered token-weighted update windows, guarded checkpoints and exact
fresh-process replay. This is an engineering milestone, **not a 7B training,
semantic-quality or non-regression result**.

## Frozen source and results

Execution commit: **`92d80664e2cbce2defde35a21dd1e626ecd145da`**.
The complete [source seal](attempt03/SOURCE_SEAL.json) contains **681 files**.
Runtime: Furnace Linux, Python **3.12.14**, PyTorch **2.13.0+cu132**,
Transformers **5.15.0**, RTX 5090. An isolated detached checkout used the
existing Aether CUDA interpreter; a fresh pre-import cache and exact source
checks prevented editable-install redirection.

| Device qualification | Passed / selected | Failed / errors / skipped | Pytest seconds | Receipt seconds |
| --- | ---: | --- | ---: | ---: |
| CPU | **203 / 203** | 0 / 0 / 0 | 45.29 | 48.516699018888175 |
| CUDA | **203 / 203** | 0 / 0 / 0 | 49.72 | 53.20769331790507 |

Both stayed within the **900-second** bound. The CUDA parent process's peak
allocated tensor memory was **67,276,800 bytes (64.16015625 MiB)**, under its
4-GiB allocation cap. Fresh-process owner children also set their own 4-GiB
cap. This parent peak excludes child-process peaks and is **not** whole-GPU
usage or a 7B memory forecast. Some graph-only tests run on CPU even in the
CUDA suite; the device-selecting owner/transport and fresh-process tests
actually exercise CUDA. Do not call all 203 cases CUDA kernels.

Local development also passed 218 selected cases: 203 engineering cases plus
15 offline-verifier regressions. That local run was development evidence,
not a replacement for these sealed Linux results. This is a selected suite,
not the entire repository or CI.

## What passed

- Four tiny hosts: Mistral, OLMo2, GPT-2 and scratch; FP32 and BF16.
- Whole native parameter ownership, physical tied-weight deduplication,
  token-count-weighted answer loss, finite complete-window gradients,
  CPU FP32 Adafactor state and realized native cast-change receipts.
- Verbatim promoted transport/checkpoint primitives, plus bitwise comparison
  of two native-family updates against the frozen historical arithmetic.
- Native no-memory parity, memory/query gradients, causal full-vocabulary
  labels, empty/padded cases and activation-checkpoint backward.
- Independent snapshots, incomplete-window rejection, invalid restores
  rejected before target/RNG writes, and exact next-window replay in fresh
  processes in both FP32 and BF16.
- Explicit backend policy selection/inheritance and rejection of live or
  restored model/SDPA/oneDNN policy drift. Frozen history and the 303-file
  legacy source seal still pass their guards.

All test parameters are small, newly initialized models. Pretrained-model
updates, new learner generation sequences, judge calls and weight deletions
are **0**. Generic receipt fields `native_weight_updates=0` and
`real_model_updates=0` mean no **pretrained/experiment** updates; the tiny
tests intentionally update their initialized parameters.

## Retained failures and the actual correction

| Attempt | Source | CPU outcome | CUDA |
| --- | --- | --- | --- |
| [01](../native_owner_qualification_20261020/README.md) | `238df7a` | 187/189; scratch BF16 oneDNN backward failed | Undispatched |
| [02](../native_owner_qualification_attempt02_20261020/README.md) | `e405106` | 196/199; math SDPA alone did not remove the failure | Undispatched |
| 03 | `92d8066` | 203/203 with declared CPU oneDNN-off policy | 203/203 |

No failed bundle was edited, retried in place, relabeled PASS or removed.
The repaired condition retains every old case and BF16 dtype, adds guards,
and explicitly selects native CPU math SDPA plus **CPU oneDNN disabled**.
The setting is applied before tests, inherited by child fixtures, stored in
the owner execution contract and checked after tests. CUDA tensor dispatch
and the HF eager-attention choices are not replaced. The evidence supports
that this declared backend condition works, not an unmeasured assertion of
bitwise equality with oneDNN. The exact failing non-attention primitive was
not isolated; do not turn the fix into a more specific causal claim.

## Reproducible evidence

- [CPU STARTED](attempt03/cpu/STARTED.json), [CPU FINISHED](attempt03/cpu/FINISHED.json), [CPU XML](attempt03/cpu/TESTS.xml)
- [CUDA STARTED](attempt03/cuda/STARTED.json), [CUDA FINISHED](attempt03/cuda/FINISHED.json), [CUDA XML](attempt03/cuda/TESTS.xml)
- [offline verification](OFFLINE_VERIFY.json)
- [post-run resource check](RESOURCE_RECHECK.json)

Offline replay (standard library only; **no** model/provider calls):

```sh
python -I scripts/verify_native_owner_qualification.py \
  --bundle provenance/engineering/native_owner_qualification_attempt03_20261020/attempt03 \
  --repo .
```

It verifies the full execution-commit source set and hashes, original
STARTED plans, both device manifests, literal XML denominators, backend,
time/memory bounds and unchanged claim ceilings. The complete verifier
returns `OFFLINE_NATIVE_OWNER_QUALIFICATION_VERIFIED_NOT_7B`.

Remote checkout ends in `worktrees/latent-workspace-native-owner-attempt03-20261020`;
output ends in `tmp/latent-native-owner-qualification-20261020/attempt03` under
`/home/ryospiralarchitect/spiralreality/SpiralReality`. Both are retained. No
monitor, PR, merge, pretrained weight download or Hub upload was created.

## Next gate: storage, then a new bounded 7B canary

At **06:35:44 UTC**, the GPU had no compute process and used 10 MiB. Available
filesystem space was **88,280,412,160 bytes (~82.22 GiB)**. The previous
two-checkpoint-plus-50-GiB-floor estimate is **104.17 GiB**, leaving ~21.95 GiB
of planning shortfall. These are point-in-time observations, not reservations;
the actual new graph still needs its own memory/storage measurement.

The [read-only candidate inventory](../../inventory/native_ft_candidates_20261020/README.md)
lists V16 common's pair (~54.12 GiB) first and matched-control's pair
(~54.17 GiB) second. Each is already its condition's latest-plus-previous;
retirement needs an explicit whole-condition decision. V18, original Mistral,
beta and relevant feature banks remain protected. **Nothing was deleted.**

Only after that decision and a frozen bounded 7B plan should a new canary be
admitted. The full-FT population/recipe, preservation mixture and held-out
evaluation remain unset. Old expression gate **`FAIL`**, winner **`none`**,
non-regression **`NOT_ESTABLISHED`** remain unchanged.
