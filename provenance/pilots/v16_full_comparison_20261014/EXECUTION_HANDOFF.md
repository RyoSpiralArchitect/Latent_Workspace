# V16 three-arm full-update pilot — follow the existing attempt

2026-10-14. Human authorization: “よっしゃ!! これで回しにゆこう!!”, following
the V14-only recorded cleanup and the request for V16 full updates/evaluation.
No retry, new judge, new generation, threshold change or weight deletion is
authorized by this handoff. Do not restart merely because transport is quiet.

## Exact identities

- Local publication checkout:
  `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`
- Branch: `SpiralReality/v16-slot-contrast`; remote:
  `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`
- Execution source: `59f0c15965db7c22f6362825bb8873a7aede391a`
- Furnace detached execution checkout:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v16-full-comparison-20261014`
- Furnace task root:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-full-comparison-20261014`
- Qualified interpreter:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`

The task root contains the immutable `SOURCE_SEAL.json`, completed
`qualification/cpu` and `qualification/cuda`, ongoing `raw`, separate
`checkpoints`, and the outer `dispatch.log`. Raw arm paths are
`raw/common`, `raw/raw_matched_control`, `raw/slot_contrast`.
Two full `.pt` files per condition belong only under `checkpoints/<arm>`;
do not transfer them into the repository or delete them during this run.

Local `launch/` holds **immutable launch and common step-zero copies only**:
STARTED/dispatch, CONTEXT, INITIAL and evaluation_step0, not a replica of the
growing raw output. Step zero passes offline arithmetic replay and 160/160
full-vocabulary parity; the first backward window is in progress. Do not confuse
this snapshot with a terminal run bundle or a completed update.
Initial dispatcher PID 1714013; outer launcher 1713998; first arm 1714045.
Always check exact process arguments and the latest per-arm STARTED receipt:
later arms intentionally have different PIDs. The shell detachment is not a
second dispatch or an automation. No heartbeat was created/re-enabled.

## What is already running

`scripts/run_v16_full_comparison.py dispatch` runs the three source-isolated
arms sequentially, each in a fresh process. Both source-isolated qualification
suites passed 12/12 before dispatch; selected local regression passed 279/279.
The source seal covers 535 files. Never edit the live checkout or its source.

Each arm loads fresh pinned original Mistral-7B-Instruct-v0.3, prepares the
qualified owned native checkpoint hook, trains two complete 16-pair full-update
windows, evaluates at 0/1/2, saves steps 1/2 and exactly replays step 2 from
step 1. Common/raw/candidate use identical seed/data/loss/optimizer/native
arithmetic. Extra interaction initialization is matched between raw/candidate.
No label, target answer or donor flag is an inference input.

Admission retains 31-GiB GPU free, 30.5-GiB allocator cap, 0.75-GiB sampled
device-free floor, 100/24-GiB host floors, 50-GiB disk floor, two CPU threads
and 7,200 seconds per arm. Disk reserves 64 GiB per remaining arm.
SIGALRM and phase guards apply only to this attempt's own process.
No other workload may be killed or changed to recover capacity.

## Read-only progress and terminal handling

Use the Furnace skill and `spiral status/run/pull`; never reconstruct SSH.
Inspect STARTED/FINISHED, per-arm `step*_pairs.jsonl`, `step*.json`,
`evaluation_step*.json`, checkpoint receipts, `REPLAY.json`, `RESOURCES.jsonl`
and `HOST_RESOURCES.jsonl`. Active logs are `raw/<arm>.log`; preserve them.
Count pair receipts separately from complete windows and replay windows.
Do not invoke `run-arm`, `dispatch`, `qualify`, resume or retry again.

On any arm failure, the existing dispatcher stops later arms and records
`INCOMPLETE_NO_RETRY`. Preserve exact error, missing evaluations/windows,
checkpoints and source. If a process disappears without FINISHED, that is an
incomplete attempt, not success and not permission to rerun. Request a bounded
recovery decision after diagnosis. Do not relax criteria or silently replace
source. Partial active files are not a terminal sealed bundle.

After the **dispatcher** `raw/FINISHED.json` exists and all its children have
ended, copy `raw` into this publication bundle without changing any bytes.
Use the offline verifier (no model load/calls):

```sh
.venv/bin/python scripts/verify_v16_full_comparison.py \
  --bundle provenance/pilots/v16_full_comparison_20261014/raw \
  --seal provenance/pilots/v16_full_comparison_20261014/SOURCE_SEAL.json \
  --qualification provenance/pilots/v16_full_comparison_20261014/qualification \
  --output provenance/pilots/v16_full_comparison_20261014/OFFLINE_VERIFY.json
```

The verifier output is exclusive. If it already exists, replay without
`--output` and compare; never overwrite it to make a new result look old.
For incomplete outcomes, retain missingness and publish a bounded failure
handoff rather than calling the completion-only verifier successful.

For completed work, inspect all per-query results, reciprocal-question signs,
common/random/reversal controls, post-update interaction-query gradients,
original-base regressions/repairs and measured resources. Check every denominator.
Update this results README and the root/next-steps documents with bounded English
conclusions, not a semantic promotion. Preserve the old **FAIL / winner:none /
non_regression NOT_ESTABLISHED**. No held-out evaluation, free generation or
preservation supervision was selected here.

Before publication, verify all 535 source hashes and unchanged prior seals,
literal receipts, manifests, planned/completed counts, relevant tests and links.
Check the exact branch, remote and staged paths before commit/push. Preserve
unrelated untracked `provenance/research/`. Do not merge or start a new PR as a
side effect. No recurring-monitor changes are needed.
