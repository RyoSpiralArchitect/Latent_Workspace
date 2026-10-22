# V22 full-FT recovery 01: allocator boundaries, unchanged arithmetic

Ryō explicitly authorized the cache-boundary correction, regression tests and a
fresh canary/replay → 32-update training trial. Separately, only after the new
exact replay passes, the **old failed trial's one canary step-1 body** may be
retired after an exact hash and published ledger. Neither original Mistral nor
any other checkpoint is in that deletion authorization.

The [old terminal failure](../../provenance/pilots/v22_full_ft01_20261021/README.md)
and its 42-file Furnace evidence bundle (35 raw files) remain byte-for-byte
unchanged. The old execution source
is `3c6da4218526cbaaf4690efe6910a2dc493d004b`; the new trial uses a new committed
source seal and a separate worktree/output directory. No old run is resumed.

## Fixed and changed factors

The new [plan](../../configs/v22/FULL_FT_RECOVERY_01.json) retains the exact
English data, canary/dev/training row order, seed 47, query-token-weighted NLL,
BF16 native weights, FP32 CPU Adafactor masters, learning rate `2e-7`, clipping,
runtime, attention, checkpointing, and all resource/quality limits. The same
32 training updates cover 723 unique rows and 20,860 supervised tokens.

The sole execution change is opt-in allocator maintenance **after** a complete
synchronous CPU gradient spill has returned, and **after** an exact checkpoint
restore has returned. It validates host gradient ownership and no native/master
live gradients, synchronizes CUDA, records allocated/reserved/free memory,
releases unused cache, synchronizes again and records the result. Live allocated
bytes must stay identical. There is no tensor detach/cast/merge, gradient clear,
optimizer step, RNG operation, `gc.collect` addition, threshold relaxation or
peak-stat reset in this helper. CPU is a no-op. The original call paths default
to no maintenance. Per-boundary receipts are separate from numerical receipts.

PyTorch describes [`empty_cache`](https://docs.pytorch.org/docs/2.14/generated/torch.cuda.memory.empty_cache.html)
as releasing unused allocator blocks, not live tensors or increasing capacity
for a model that actually needs more live memory. Consequently this is a
testable allocator-lifetime hypothesis, not a promise that the 7B trial fits.

## Qualification and phase gates

The original 290 CPU/CUDA tests remain, with 28 new cases (318 total per device).
New cases compare cache-on/off complete losses, CPU gradient hashes, native
parameters, FP32 masters, optimizer state, RNG and payloads, including actual
long tiny-model windows and save/restore. CPU/CUDA use the same prior 4-GiB /
900-second envelopes; CUDA cannot silently skip. Local targeted testing passed
67/67. An initial local collection error from missing script import roots was
fixed before sealing; no Furnace trial was dispatched from that development
state. No packages or shared runtime environments were changed.

`dispatch-checks` exclusively runs canary then fresh-process replay, and stops
at the first failure. It forecasts only its one 28-GiB checkpoint allowance.
Successful completion is `V22_RECOVERY_CHECKS_COMPLETE_NOT_TRAINING`; it is not
full training or a quality result. The raw trial remains nonterminal at this
explicit phase boundary.

After verifying that terminal, copy/publish the successful check receipts and
the old checkpoint's exact deletion ledger **before deleting its body**. The
authorized old path is:

```
/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft01-20261021/checkpoints/canary_step1.pt
```

It has 29,004,378,380 bytes and SHA-256
`278466e8a5c2b763f4ebae94ae05577e7d8ffae459bf81692c21615078bb2aaf`.
Git metadata is not a restorable backup of this body. No deletion is implemented
in a training role or automatic dispatcher.

`dispatch-training` is also exclusive. It verifies the same-source successful
checks phase and exact role manifests before starting. Train A independently
admits its two 28-GiB saves plus the unchanged 50-GiB disk floor; train B admits
one remaining save plus that floor. Train A starts from original Mistral, not
the canary weights. It saves at 16; a fresh Train B process restores exactly and
continues the fixed cursor through 32, then saves and repeats the fixed 40-row
development NLL panel. No role, phase or process is automatically retried.

Training processes still report zero weight deletion. The separate old-body
retirement is disclosed in the storage ledger and overall publication; it must
not be misreported as zero deletions across the whole recovery workflow.

All existing **FAIL / winner:none / non_regression NOT_ESTABLISHED** ceilings
remain. No new generation, paid judge, public benchmark or HF release occurs.

## Observed terminal outcome (2026-10-21; added after execution)

The [separate recovery completed](../../provenance/pilots/v22_full_ft_recovery01_20261021/README.md)
at execution commit `13c1192fc2727d8ca61ee215a927c0cd77f75b16`: 318/318
qualifications on each device, exact fresh step-2 replay, exact step-16 state
restore, and all 32 training updates / 723 unique rows / 20,860 target tokens.
The 40-row fixed development panel has lower NLL on every row; aggregate NLL
is 1.267038 before and 1.058723 after. This does not establish public-benchmark
non-regression, causal memory dependence or generation quality. No separate
uninterrupted 32-step reference trajectory was run.

All three new checkpoint bodies were rehashed successfully. Only the separately
approved old failed canary body was retired after the successful replay and
pre-published ledger. The original failed evidence is unchanged. The 42-file
count is for the whole original Furnace evidence bundle, not just its raw
subdirectory; the earlier wording incorrectly called all 42 files raw.
No frozen JSON recipe, numerical criterion or resource floor was changed after
launch. The next gates are unseen non-regression, counterfactual memory-use
evaluation, and paired fixed-prompt/seed generation; none was launched here.
