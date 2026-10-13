# Next gate: adapter-owned real-Mistral update equivalence

2026-10-13 design; 2026-10-14 execution update: the
[new sealed run](../../provenance/pilots/v16_adapter_migration_20261014/README.md)
passes frozen exact updates and replay (80/160 total pairs). Full stopped at
admission before any work. The original remains **INCOMPLETE_NO_RETRY**;
[full-only continuation 01](../v16/ADAPTER_FULL_CONTINUATION_01.md) is separately
authorized with unchanged criteria. It passed cold-start admission and completed
two legacy full updates, then rejected a duplicate/unowned HF input-gradient
hook during adapter construction. [The terminal diagnosis](../../provenance/pilots/v16_adapter_full_continuation_01_20261014/README.md)
records the production-helper/test-path mismatch. No adapter full update or
replay has run; the complete gate is not satisfied. Do not weaken hook ownership
or treat 112/160 observed pairs as matched full-mode evidence.

The [new owner](ADAPTER_STATE_OWNER.md) is an algorithm-preserving integration,
not the next semantic learner factor. Its [tiny qualification](../../provenance/pilots/v15_adapter_owner_20261013/README.md)
must not be promoted into a 7B memory, update or resume claim. In particular,
the conservative native adapter deliberately recomputes some forwards; the
historical runner's resource measurements do not bound this new path.

## Required admission before replacing the old runner

1. The [independently receipted tiny CUDA recovery](../../provenance/pilots/v15_adapter_owner_cuda_02_20261013/README.md)
   passed the unchanged 71-case suite; the first failed import remains visible.
   The [reviewed checkpoint gaps](ADAPTER_OWNER_REVIEW_20261014.md) are now repaired
   in [v2](ADAPTER_CHECKPOINT_V2.md), with [164/164 CPU/CUDA cases](../../provenance/pilots/v15_adapter_owner_v2_20261014/README.md),
   including independent snapshots, unchanged targets/RNG on rejection and
   renewed update/resume checks. Old v1 sources/receipts remain unchanged.
   Use the new format; this synthetic repair does not satisfy the real-model
   comparison and resource admission below.
2. Freeze the real-model runner, complete ordered windows, runtime, source
   manifest and resource forecast in a separate execution contract. Use the
   pinned original `Mistral-7B-Instruct-v0.3` revision
   `c170c708c41dac9275d15a8fff4eca08d52bab71`, the same exposed two-world/eight-query
   protocol, native BF16 and the unchanged six-term objective. This is a
   migration comparison, not new held-out model-quality evidence.
3. Stage old-reference and adapter arms **sequentially**, never two 7B backward
   graphs on the GPU. From matched original state and RNG, compare two complete
   16-pair windows in each frozen/full condition. Compare loss components and
   all ordered gradient/update receipts, native weights, bridge, FP32 masters,
   optimizer state and RNG. Then replay adapter window 2 from its saved window
   1. No tolerance widening or selecting only changed tensors after results.
4. Keep original-base identity distinct from the updated current base. A
   loaded adapter checkpoint must pass source/runtime/binding/run-contract
   compatibility before the resume test; a new format is not compatible merely
   because parameter names match. Do not change the sealed historical runner.
5. Recompute peak host/GPU and disk envelopes for the adapter's graph policy.
   Full-window admission and checkpoint writes must fail closed independently.

## Disk admission history and current boundary

The 2026-10-13 Furnace preflight reported about **44 GB disk free**. The
[historical resource contract](../../configs/v15/NATIVE_LEARNER_PLAN.json)
requires **50 GiB remaining including forecast checkpoint writes**, before
considering the new adapter's overhead. Each retained full checkpoint is about
29 GB (27 GiB), so two new full checkpoints plus that floor need roughly
**104 GiB free before writes**, plus any other forecast artifacts. The exact
forecast must use recorded byte counts, not rounded prose.

This proposal itself authorized no deletion. On 2026-10-14 JST, Ryō separately
authorized [all V12 experiment weights to be removed](../../provenance/inventory/v12_weight_prune_20261014/README.md)
after hash/metadata recording. Available persistent space is now 249.571 GiB;
V14/V15 and the original model cache remain unchanged. This clears the initial
capacity obstacle, not the exact new-run admission check. Neither idle GPU nor
tiny-test success bounds the new adapter's host/GPU peaks. Do not reduce the
floor or drop replay. Until the new comparison passes, the sealed 7B runner
and its old result remain authoritative.

## After migration, keep scientific factors separate

Only after real-model update/resume equivalence is observed should the next
controlled learner factors be added: (a) useful question/content interaction
with matched common-response capacity, (b) an explicitly non-native precision
intervention with its own direct-base control, and (c) an immutable-original
preservation target. The current reference hash adds ownership, **not** the
preservation loss or a correctness guarantee. No new factor, generation,
judge call, long run or merge is authorized by this document.

Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** and all judge
missingness remain unchanged.
