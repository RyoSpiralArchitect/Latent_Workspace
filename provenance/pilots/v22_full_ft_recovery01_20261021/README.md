# V22 recovery 01: native full-parameter training completed

**Terminal: 32/32 training updates, 723/723 unique training rows, and
20,860/20,860 supervised tokens completed.** The
[trial receipt](furnace/raw/FINISHED.json) and
[training phase](furnace/training/FINISHED.json) report
`V22_NATIVE_TRAINING_32_STEPS_COMPLETE_NOT_QUALITY`.
The fixed development panel has lower teacher-forced NLL on **40/40 rows**;
this is a diagnostic observation, not a non-regression or release gate.

Execution source: `13c1192fc2727d8ca61ee215a927c0cd77f75b16`, **724 sealed files**.
The [frozen design](../../../docs/v22/FULL_FT_RECOVERY_01.md),
[terminal handoff](EXECUTION_HANDOFF.md),
[replayable summary](SUMMARY.json), and [verification record](VERIFICATION.json)
separate execution, later offline publication, and model-quality claims.

## What ran, and what stayed fixed

This is a one-seed native full-parameter pilot of
`NativeMemoryCausalLM` on pinned Mistral-7B-Instruct-v0.3: **7,248,023,552
native parameters / 291 physical tensors**, no added adapter parameters.
Seed 47, learning rate `2e-7`, query-token-weighted causal NLL, BF16 native
weights, FP32 CPU Adafactor masters, cut 4, eager attention, and the resource
limits were unchanged. Train A starts from the original model, not the canary.

The [English-only projection](../../data/v22_english_mixture01_20261021/README.md)
is selected by existing language metadata, not a new sentence-level language
classifier. Original banks and the quarantined teacher outputs were not changed;
the teacher outputs were not admitted. Actual training exposure is:

| Training role | Unique rows | Supervised tokens | Token share |
|---|---:|---:|---:|
| world | 636 | 4,097 | 19.6405% |
| instruction | 37 | 8,415 | 40.3404% |
| prose | 41 | 5,207 | 24.9616% |
| code | 9 | 3,141 | 15.0575% |

The token target was 20/40/25/15%, not a row-uniform mixture. Only nine code
training rows were used; this is not broad code-retention evidence.

## Qualification, numerical parity, and actual activity

CPU and CUDA each passed **318/318**, with zero errors, failures or skips.
These are tiny-host engineering checks, not 318 real-7B tasks.
Pytest wall times were 214.27 / 195.99 seconds; wrappers 217.553 / 199.756
seconds. Local targeted regression tests passed 67/67.

| Real-7B role | Physical updates | Backward rows | Wall seconds |
|---|---:|---:|---:|
| Canary | 2 | 9 | 526.615 |
| Fresh step-2 replay | 1 | 5 | 351.125 |
| Train A, steps 1–16 | 16 | 325 | 2,537.432 |
| Train B, steps 17–32 | 16 | 398 | 2,749.391 |
| Total | 35 | 737 | — |

Training itself is **32 updates / 723 rows**, not 35 independent training
updates. Its two-process phase took **5,297.645 seconds / 88.294 minutes**.
Both new canary step records exactly match the corresponding old trial's
numerical records, including all nine row loss/gradient records and the update
fingerprints. Different source contracts mean that complete checkpoint
payload/file hashes are **not** asserted equal across the two trials.

[Fresh step-2 replay](furnace/raw/replay/REPLAY.json) matches all five row
losses/gradients and the entire step-2 state/payload. Separately,
[Train B's restore](furnace/raw/train_b/RESTORE.json) exactly restores the
step-16 checkpoint state, optimizer, RNG and cursor before continuing to 32.
There was **no separate uninterrupted 32-step reference run**, so the latter
is an exact restore proof, not a measured whole-trajectory comparison against
such a reference.

Every training update changed all **291 FP32 master tensors**. At least one
native BF16 element changed in **235–239 tensors per update**; 239 tensors
changed at least once across the 32 updates. The other 52 are Norm tensors,
listed in [SUMMARY.json](SUMMARY.json), with no observed native-value change.
Trainability, master updates, and realized BF16 movement are distinct facts;
these counts do not identify a quality mechanism.

## Fixed development result

The “before” condition is pinned original Mistral through the **same
native-memory graph**, not a separate vanilla direct-text generation baseline.
The exact same 40 development rows / 4,694 target tokens were scored before
training and after step 32: **80/80 finite row evaluations**, no missing rows,
no new generated sequences, no prompt/threshold changes or checkpoint selection.

Lower NLL is better. All numbers below are token-weighted within the named
panel; row lower/higher counts use the exact stored loss differences.

| Panel | Rows | Target tokens | Before NLL | Step-32 NLL | Change | Rows lower / higher |
|---|---:|---:|---:|---:|---:|---:|
| world/affected | 6 | 47 | 3.310362 | 0.200979 | -3.109383 | 6 / 0 |
| world/unaffected | 6 | 46 | 3.566308 | 0.035684 | -3.530624 | 6 / 0 |
| world/absent | 6 | 24 | 2.894054 | 0.001289 | -2.892765 | 6 / 0 |
| world/unrelated | 6 | 24 | 2.855213 | 0.022620 | -2.832593 | 6 / 0 |
| instruction | 8 | 1,957 | 1.273324 | 1.117111 | -0.156213 | 8 / 0 |
| prose | 4 | 508 | 3.031372 | 3.004748 | -0.026624 | 4 / 0 |
| code | 4 | 2,088 | 0.698288 | 0.596449 | -0.101839 | 4 / 0 |
| ALL | 40 | 4,694 | 1.267038 | 1.058723 | -0.208315 | 40 / 0 |

The total changed by **−0.208315 NLL / −16.4411%**. Instruction, prose and code
panel means fell by 12.2681%, 0.8783% and 14.5840%, respectively. All 40 paired
rows have lower NLL; none are equal or higher. This is **not 100% task accuracy**,
a significance test, a public benchmark, or proof of better free generation.

The world panels have only six rows per mode; code and prose have four each.
The aggregate contains only 141 world target tokens versus 4,553 other target
tokens, so it must not replace the separate panels. Stronger target likelihood
also does not isolate causal memory use, donor-directed counterfactual behavior,
or broad reasoning/generalization.

Literal inputs are [DEV_BASE.json](furnace/raw/train_a/DEV_BASE.json) and
[DEV_STEP32.json](furnace/raw/train_b/DEV_STEP32.json); all 40 paired deltas are
preserved in the offline summary.

## Resource correction and retained weights

At the previously failing [first replay spill](furnace/raw/replay/CACHE_step2_row0.json),
CUDA-reported free bytes rose from **460,652,544 to 18,114,478,080** after unused
cache release; live allocated bytes stayed **14,563,156,992**. The numerical
and resource criteria were not relaxed.

Across all roles there are **739 cache-boundary receipts**: 737 completed
gradient spills and two completed restores. All preserve live allocated bytes.
The recorded cache operations total **23.800 seconds**, already included in
role wall times; this is not an independent speed benchmark.
Peak CUDA allocation/reservation was **27.751 / 30.219 GiB** and peak host RSS
**86.883 GiB**. The minimum free GPU memory at resource-guard samples was
16.367 GiB, host available 47.742 GiB, and disk available 63.425 GiB.
These are boundary samples, **not continuous minima**; pre-cleanup allocator
samples can be lower, as the replay example shows. The 768-MiB GPU and 50-GiB
disk floors remain unchanged.

All three retained checkpoint bodies were re-read and fully hashed on Furnace;
each matched its save receipt. They remain under:

```text
/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft-recovery01-20261021/checkpoints/
```

- [canary_step1.pt receipt](furnace/raw/canary/CHECKPOINT_canary_step1.pt.json):
  29,004,378,380 bytes, SHA-256
  `795b96b53811f5b886f071f72203d01db4afe79489b724e481c10549d88d86e6`.
- [training_step16.pt receipt](furnace/raw/train_a/CHECKPOINT_training_step16.pt.json):
  29,004,396,428 bytes, SHA-256
  `49a5e6721963c3581a5c471556d1196f329c12868d496148066d65aa21386de2`.
- [training_step32.pt receipt](furnace/raw/train_b/CHECKPOINT_training_step32.pt.json):
  29,004,418,636 bytes, SHA-256
  `cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.

After the new replay passed and its evidence/ledger were published, exactly
the separately authorized **old failed trial's one canary body** was retired:
29,004,378,380 bytes / 27.0124 GiB. The
[retirement ledger and terminal receipt](../../inventory/v22_failed_canary_retirement_20261021/README.md)
record the hash, pre-delete publication and completed one-file removal.
There is no backup of that old body; Git metadata cannot reconstruct it.
Original Mistral, the new canary and every other weight were untouched.

The original failed Furnace evidence bundle remains byte-for-byte unchanged:
**42 files / 842,396 bytes**, including **35 raw files / 460,595 bytes**.
“42 raw files” in the earlier recovery design was a counting-label error;
42 is the whole copied Furnace bundle. No original historical record was edited.
Training roles deleted zero files; the overall recovery workflow deleted **one**.

## Verification and claim ceiling

The old 717-file execution tree and new 724-file tree both pass clean,
pre-import source checks at their own frozen commits. The offline verifier
passes `OFFLINE_V22_COMPLETE_NOT_QUALITY`; its Furnace invocation also checks
the actual raw data and all three checkpoint bodies. Local replay deliberately
reports `checkpoint_bodies_checked: false`, because weight bytes stay on Furnace.

```bash
python3 scripts/verify_v22_full_ft.py \
  --bundle provenance/pilots/v22_full_ft_recovery01_20261021/furnace \
  --repo . \
  --data provenance/data/v22_english_mixture01_20261021/furnace
python3 provenance/pilots/v22_full_ft_recovery01_20261021/summarize.py \
  --verify provenance/pilots/v22_full_ft_recovery01_20261021/SUMMARY.json
```

The publication helper is later read-only analysis, not part of the training
source. It refuses a partial run as a completed publication.

**FAIL / winner:none / non_regression NOT_ESTABLISHED remains unchanged.**
The next separate gates are unseen original-base non-regression, paired
counterfactual memory-use evaluation, and fixed-prompt/seed generation review.
No extra training, generation, teacher/judge call, public benchmark, threshold
change, beta replacement, PR/merge, or Hub upload was performed. This pilot
retains the private-research data/weight scope; it is not a release package.
