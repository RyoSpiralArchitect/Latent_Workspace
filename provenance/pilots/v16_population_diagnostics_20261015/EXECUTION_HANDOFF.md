# V16 population diagnostics: execution handoff

2026-10-15. Ryō authorized more samples on Furnace and a partial public benchmark
comparison with original base. This attempt evaluates existing weights only.
It does not authorize new training, a paid judge, generation, weight deletion,
threshold changes, or an automatic retry. No recurring monitor is created.

## Identities

- Publication checkout:
  `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`
- Branch `SpiralReality/v16-slot-contrast`; remote
  `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Frozen execution source: `de0f14c7378abf7d92f582b6b22d31bdf688526b`.
  [SOURCE_SEAL.json](SOURCE_SEAL.json) binds 546 files, preserving the preceding
  535-file execution source byte-for-byte.
- Furnace checkout:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v16-population-20261015`
- Furnace task root:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-population-20261015`
- Original completed training parent root:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-full-comparison-20261014`
  (source `59f0c15965db7c22f6362825bb8873a7aede391a`).
- Qualified Python:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

## Selection and qualification

[Plan](../../../configs/v16/POPULATION_EVAL_PLAN.json): original base then
common, raw matched control, slot contrast, each in a fresh sequential process.
All trained arms restore their retained step-2 checkpoints and replay the old
native evaluation exactly before using new questions. Never convert checkpoints
or bypass the qualified state owner. Two checkpoints per condition stay intact.

CPU and CUDA each passed 22/22 source-isolated tests. Their hashes and XML live
in `qualification/`. The tokenizer-only preflight covered all 570 MMLU prompts;
maximum length 3,295, cap 4,096, candidate IDs [1098,1133,1102,1152] for A/B/C/D.
It made no model forwards. Broader local prelaunch regression is recorded
separately; require its terminal passing XML before dispatch.

Inputs: 128 fresh world pairs, 1,024 queries, 256 affected; four data seeds but
only one training seed. Public screen: 570 MMLU questions (57 subjects × 10),
five dev examples, no workspace. Do not conflate these denominators, perform
post-hoc subset selection, or interpret shadow attention weights as the native
production output. The old gate remains FAIL / winner:none / non_regression
NOT_ESTABLISHED, regardless of an encouraging subset score.

## Lifecycle and results

The task-root `LAUNCHED.json`, then `raw/STARTED.json` and
`raw/DISPATCH_<arm>.json` are the dispatch authority. Check these and exact
process arguments before interpreting a PID. This handoff by itself does not
claim a dispatch has occurred. If a receipt exists, follow that existing attempt;
do not launch another copy because output is temporarily quiet.

`raw/<arm>/mmlu.jsonl` journals each scored question. `world_000.json` through
`world_127.json` hold completed worlds. RESTORE, TOKENS, BEFORE/AFTER and FINISHED
receipts carry state/provenance. Logs are `raw/<arm>.log`, outside each arm's
terminal manifest but inside the eventual dispatcher manifest. Resource samples
remain beside each arm. A failure stops later arms and keeps partial files.
Never restart/resume a failed or ambiguous attempt without a recovery decision.

When dispatcher FINISHED exists and every child is terminal, copy `raw` without
altering bytes and run the offline verifier, not a model entry:

```sh
.venv/bin/python scripts/verify_v16_population_eval.py \
  --bundle provenance/pilots/v16_population_diagnostics_20261015/raw \
  --seal provenance/pilots/v16_population_diagnostics_20261015/SOURCE_SEAL.json \
  --qualification provenance/pilots/v16_population_diagnostics_20261015/qualification \
  --output provenance/pilots/v16_population_diagnostics_20261015/OFFLINE_VERIFY.json
```

The output is exclusive. If already present, replay without `--output` and
compare; do not overwrite an earlier result. Preserve missingness if incomplete.
Report all denominators, ties, regressions/repairs, world-cluster versus
within-subject intervals, native versus FP64 direction, slot/attention/output
decomposition, and the unchanged claim ceiling. Do not infer a new training
factor has been implemented or validated from this diagnostic alone.

Check source seals, manifests, documentation numbers/links, staged diff and
remote before a scoped publication commit. Exclude unrelated untracked
`provenance/research/`. Do not create or merge a PR as a side effect.
