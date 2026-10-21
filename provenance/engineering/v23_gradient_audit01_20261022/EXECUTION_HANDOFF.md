# Execution handoff — V23 gradient audit 01

**Terminal supersession:** both roles are complete; [results](TERMINAL.md),
`furnace/PUBLICATION_MANIFEST.json` and `ANALYSIS.json` are published. The
original workers are absent. Do not restart or monitor this completed job.
The earlier status entries below are historical. Offline replay passed before
new owner work; after engine changes use the original frozen source checkout.
Ryō subsequently authorized proceeding through gated comparative FT; that is
a separate source/plan/run, never a continuation of this no-update audit.

Source: `66467502064b08b1ea8e246edc6696bd9d35a60e`, 761 sealed files.
Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/latent-memory-full-ft`.
Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.

Furnace source worktree:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-gradient-audit01-20261022`.
Furnace run:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-gradient-audit01-20261022`.
tmux: `ltws-v23-gradient-audit01-20261022`.
Dispatcher PID at launch: 3653540; V22 child PID: 3654121. Verify live identity,
not just recycled PID existence. Only inspect this existing run, never relaunch.

## Last verified status: interim snapshot, not terminal publication

- CPU and CUDA qualifications: 338/338 each, no failures/errors/skips.
- Base arm complete in 168.7523 seconds. 291/291 path sums within the fixed
  1e-4 + 3%-of-full-gradient-max engineering bound, trace/no-trace exact.
- Maximum-memory canary: `wb02-20261022-inventory-train-0007/s0/unaffected`,
  105 memory / 46 query tokens. Separate 128-token preservation backward.
- All 12 base target rows / 932 supervised causal positions generated under
  the frozen full-vocabulary FP32 target contract; not external teacher prose.
- Base native tensor hash unchanged; peak CUDA allocation 19,091,351,552 bytes.
- V22 strict step32 owner restore and the same 291/291 path-sum canary pass.
  The panel audit is running, not declared complete. Its final native hash is
  still pending. No optimizer update, checkpoint save, generation or judge.
- Immutable interim snapshot at 2026-10-21 16:21:52 UTC is in
  `interim_furnace/`; 27 public files / 1,224,369 bytes plus its manifest.
  One 122,160,008-byte private teacher body is omitted. Source and public
  receipts replay locally with `publish_interim.py verify`.

## Fixed inputs and outputs

Preparation's private token body SHA256:
`9e6bd21685cfcda0a56c9fb8d4f811cc178da1c5d324cd41cfe349375ae3285b`.
84 world rows / 14 groups / 532 targets: identity 256, copy 100, format 176,
mixed 0. 70 rows have memory; 14 absent controls keep the native bypass.
12 preservation rows / 932 targets, four each instruction/prose/code.
All training-only. New confirmation/OOD and public benchmarks are not used.

Raw teacher targets and any live scratch gradient bodies remain remote only.
Do not edit or replace `interim_furnace/` when the terminal result arrives.
Publish the terminal snapshot to a new `furnace/` sibling instead.
`verify.py snapshot` is offline and requires terminal receipts and absent
recorded workers. It prepares an exclusive publication manifest, omitting
private `.safetensors` bodies. Pull only listed public files plus that manifest.
`verify.py verify` checks the published artifact and sealed source again.
`analyze.py` is an offline descriptive reduction, only for a fully successful
terminal result. It does not dispatch inference or change thresholds.

If a role fails, preserve the terminal error and all missingness. Do not retry,
resume, replace the teacher, change tolerances or modify the frozen source.
Publish bounded results and request a decision for a separate recovery trial.
No new automation, training, API call, PR, merge or release is authorized here.

The existing audit is slow but bounded: early preservation CE rows take about
25 seconds each including synchronous transport. Do not mistake low GPU
utilization during CPU aggregation/hash checks for a stopped job, and do not
change the frozen algorithm or shorten the panel to accelerate this attempt.
No recurring monitor was re-enabled. Continue by inspecting the existing
tmux/process/receipts via `spiral`, not by calling the launcher again.

## Separate completed cleanup

Three obsolete engineering canaries were retired under ledger commit
`a682a83ee115da2d5ed69ece4ec51dedadbd6381`; [receipt](../../inventory/v23_obsolete_canaries_20261022/DELETE_FINISHED.json).
87,013,134,820 bytes removed. Base, V22 step16/32, scientific V18–V20 branches,
activation banks and data remain. Git preserves fingerprints, not recoverable
weight bodies. No further weight deletion is needed for this audit.

## Additive handoff update — 2026-10-22 02:23 JST

The [later read-only progress observation](../v23_preservation_binding01_20261022/AUDIT_PROGRESS_OBSERVATION.json)
still finds the original V22 worker active, with the frozen remote worktree
unchanged. Preservation CE and KL are 12/12 each and world total is 84/84;
identity has 33/84 complete row records. Copy/format/mixed and the terminal
receipts are pending. Do not confuse these counts with completion or quality.

Independent [target-metadata preparation](../v23_preservation_binding01_20261022/README.md)
adds a new engine module and tests, without editing any of this audit's 761
sealed files. It does not change the owner or start a GPU job. Its
[proposed objective-owner contract](../../../docs/v23/OBJECTIVE_OWNER_CONTRACT.md)
leaves coefficient selection, owner wiring and new-objective restart after the
complete audit. The old source can still be replayed; do not relaunch it from
the newer local HEAD or reinterpret V22 restoration as a changed-objective resume.
