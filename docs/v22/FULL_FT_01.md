# V22: English-only native full-parameter pilot

2026-10-21. **Frozen execution plan; not a completed training or quality claim.**
Ryō requested Japanese exclusion, update/save/fresh-process-resume checks and
then V22 training. This is a bounded first pilot, not an epoch over all data,
a release candidate, or a replacement for the frozen-host beta.

## Fixed mechanism and data

The native memory graph/optimizer owner are unchanged: Mistral-7B-Instruct-v0.3
revision `c170c708c41dac9275d15a8fff4eca08d52bab71`, cut 4, all
7,248,023,552 native parameter elements trainable, BF16 eager attention,
non-reentrant activation checkpointing and FP32 CPU Adafactor masters.
Learning rate remains `2e-7`, weight decay zero, clip norm 1, seed 47.
There are no adapter parameters, detached writer caches or frozen native layers.

[Data record](../../provenance/data/v22_english_mixture01_20261021/README.md),
[data recipe](../../configs/v22/DATA_01.json), and
[execution plan](../../configs/v22/FULL_FT_01.json) are separate from the
unchanged original world/preservation banks. No quarantined teacher prose,
old judge labels, public benchmark examples, test or OOD rows enter training.
Existing source rights claims support this user-authorized private research
pilot; jurisdiction-specific and redistribution review are not claimed done.
No raw-data or weight publication is authorized by this plan.

The complete-row schedule has **32 updates, 723 unique row occurrences and
20,860 supervised target tokens**. Token targets (world/instruction/prose/code)
are 20/40/25/15%; realized shares are 19.640/40.340/24.962/15.058%.
These are exposure shares, not an extra role-weighted loss. The unchanged owner
divides each row's summed NLL by that update window's total target tokens.
Mean per-window objective shares are 19.947/41.676/25.511/12.866%.
Whole answers are retained; there is no truncation or sequence packing.
Code has only nine training examples in this small schedule. Neither this nor
the general instruction sample establishes broad capability preservation.

## Ordered, stop-on-first-failure execution

1. Run all **290 selected tests on CPU, then CUDA**, from one committed source
   seal. Maximum 4 GiB CUDA allocation / 900 seconds per qualification;
   explicit CPU oneDNN-off, math SDPA for the scratch CPU model, BF16 retained.
2. `canary`: load and independently hash the pinned original model with both
   named historical schemes. Perform two native update windows (4 + 5 rows):
   the longest 1,024-token instruction, 993-token code answer, world memory
   up to 78 tokens, intact/twin and absent/unrelated controls, and prose.
   Save only step 1. Hash the independent step-2 payload without saving a
   second canary weight body.
3. `replay`: a fresh process restores canary step 1 and repeats its five-row
   step 2. Require exact losses, ordered cumulative gradient hashes, update
   changes, native/master/optimizer/buffer/RNG/execution state and payload hash.
   No tolerance adjustment or retry. A failure prevents all training roles.
4. `train_a`: a fresh **original** model, not the canary-updated condition,
   evaluates a fixed 40-row development NLL panel and executes training
   updates 1–16. Save step 16 with full state and a source/data/stream contract.
5. `train_b`: another fresh original host restores training step 16, verifies
   the exact state and full frozen schedule/token cursor, executes updates
   17–32, saves step 32 and evaluates the same development panel.

The same native owner handles ordinary no-memory prose/instruction/code and
query-deferred world examples. Training omits expensive per-row gradient hashes;
the canary retains them. A tiny parity test checks this is an observation-only
difference, not altered update arithmetic. Development forwards do not change
weights or RNG and do not select checkpoints or change this recipe.

If successful: 32 learned training updates + 2 separate engineering updates +
1 replay execution = **35 physical updates**, not 35 training steps; 723 + 9 +
5 = **737 backward row occurrences**. The three checkpoint bodies remain on
Furnace: canary step 1 and training steps 16/32. No automatic deletion.

## Resources and stop rules

At preparation Furnace was idle (10 MiB GPU use, no compute client), with about
149 GiB disk free and 119 GiB host RAM available. These are snapshots, not
reservations. Three 28-GiB upper-bound checkpoint bodies plus a 50-GiB disk
floor require 134 GiB. The source/data artifacts are small compared with that
forecast. Prior short checkpoints were about 27.013 GiB each; this run must
still measure its own sizes and peaks.

Native roles require 31 GiB free GPU and 100 GiB available host at admission.
CUDA allocator cap is 30.5 GiB; abort below 0.75 GiB sampled GPU free or 24 GiB
host available, or below the 50-GiB disk floor including pending-save forecasts.
Each role is bounded to 14,400 seconds and two CPU threads. Other GPU clients
cause this run to stop; no other workload is killed. Save/restore uses an
additional host-memory forecast. No automatic retry, optimizer substitution,
dtype fallback, input truncation or enlarged resource ceiling follows failure.

The earlier 128+128 backward-only probe and short exact canary remain separate
historical evidence. V22's canary tests its actual longest candidate rows, not
every combination of the declared 128-memory/1,024-query limits.

## Validation and interpretation

Local new tests: **46/46 pass**, including tiny FP32/BF16 long-window replay.
The combined local suite reached **288/290**: both pre-existing isolated-process
owner replay tests failed because macOS Python 3.13's isolated environment
cannot import `typing_extensions`. No test is removed, and no model result is
inferred from this dependency failure. The dispatch gate is the complete CPU
and CUDA run in the pinned Furnace runtime, each requiring 290/290.

Original-base and updated-model development NLL are diagnostics, not a frozen
public benchmark or a non-inferiority test. No generation, judge, HF upload,
beta replacement or PR merge is part of this run. Historical **FAIL /
winner:none / non_regression NOT_ESTABLISHED** remains unchanged, even if
engineering and training complete. Broad benchmark and same-seed generation
evaluation require a separately specified comparison before release.
