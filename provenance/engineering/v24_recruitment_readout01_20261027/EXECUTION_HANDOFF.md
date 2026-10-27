# V24 recruitment readout 01 — immutable execution handoff

## Authority and scope

Ryō asked to continue after the Furnace move and safe cache cleanup. This run
evaluates the already-completed V24 FT04 checkpoints; it does not restart FT,
train a learner, delete a weight, call a paid judge, publish a PR, push to
GitHub, or shut the machine down. No recurring monitor was created.

Old ceiling: **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
Six development source groups are correlated across twins, controls and routes.
No result from this protocol establishes general ability or a release gate.

## Exact source and destinations

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
- Local branch: `SpiralReality/v24-readout-improvement`.
- Remote URL: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Execution commit: **`425f10d833b25977b09f6954ed3a34f6875e4890`**, 868 sealed source files.
- Original FT source: `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`, never rewritten.
- New Furnace checkout:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-readout01-20261027`.
- New Furnace output:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-readout01-20261027`.
- tmux: `ltws-v24-recruitment-readout01-20261027`.
- Launcher: `scripts/launch_v24_recruitment_readout01.sh`, called **once** with the execution commit.
- Pinned Python:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

Source was transported as an incremental Git bundle, SHA-256
`65f36fbdb56742932813c0b1b66bc32043b5f704f6ef718e236adc305dc24e5b`,
verified on Furnace and checked out separately. No GitHub write occurred.
Post-checkout space was **50.49264 GiB**: the 50-GiB floor plus the launcher's
additional 256-MiB metadata reserve passed. No other GPU process was present.

## Snapshot — 2026-10-27 09:25:39 JST

- Pinned-runtime tokenizer/input replay: **exact**; zero model calls.
- CPU: **441/441 PASS**, no skips; independent CPU/GPU isolation **PASS**.
  CPU qualification PID 49028; 57.14 seconds, external observation 58.06 seconds.
- CUDA: **441/441 PASS**, no skips, PID 50025; 67.51 seconds.
- The complete 868-file source seal, both closed test manifests/JUnit counts,
  and independent observer were replayed locally in
  [QUALIFICATION_REPLAY.json](QUALIFICATION_REPLAY.json). This is not a 7B result.
- Dispatcher PID 50754 and base PID 50832 started after those gates passed.
  Base journals contain **10 fixed traces and 4/72 generation rows** at this
  snapshot. Base and dispatcher terminal receipts are not present yet.
  Inline-trained and workspace-trained model roles remain pending.
- Free disk observed **54,210,904,064 bytes (about 50.49 GiB)**. Shared-disk availability is sampled again
  during execution; a new external job or floor violation stops this run only.

Mac tests remain honestly recorded as 437/441 PASS: four isolated-child tests
could not import `typing_extensions`. They were retained and all passed on the
pinned Furnace CPU. New instrument/runner/reducer tests passed 62/62 locally.
Raw JUnit trailing spaces are preserved; source/docs whitespace checks passed.
Execution is ongoing, not complete. This handoff is a dated observation, not
a promise that the process remains live after the observation time.

## Remaining execution and recovery

1. Observe this existing process only. Do **not** relaunch the shell, resume a
   role, retry a cell or mutate this source/output. On a failure, preserve
   missingness and ask for a separate recovery decision.
2. Roles are base → inline-trained → workspace-trained. Each is crossed with
   inline and workspace runtime input: 72 generation rows, 144 reference traces,
   2,320 fixed forwards per role. Maximum new generations are **216**, each at
   most 128 tokens. Real updates / new saves / judges / deletions are zero.
3. Each trained role rehashes the original step32 body, restores its original
   owner contract and whole state fingerprint, then switches explicitly to
   inference. No original checkpoint is deleted or copied into Git.
4. Wait for successful `raw/FINISHED.json` and all three role terminals before
   copying **closed metadata only** into this local `furnace/` folder. No weight
   bodies are required. No automatic off-host tensor backup is claimed.
5. Offline replay requires the exact source commit above and the pinned
   tokenizer files. Use `scripts/analyze_v24_recruitment_readout.py` with the
   recovered bundle, `--source`, `--tokenizer`, and an absent `--write` path;
   then replay using `--check`. It verifies full manifests, source, qualification,
   restore/weight identity, resource floors, literal output decoding, scores and
   all counters. It performs no model forwards or provider calls.
6. Report all six cells, answer/steps/format/mixed/EOS, before/after-gold-answer
   assistance, strict generation, cap/parse failures, paired repairs/losses and
   source-group denominators. Steps-first references remain teacher forced.
   No threshold changes or winner/non-regression promotion.

If the process disappears without a terminal, or a role fails, do not convert
the output into a complete analysis or automatically start recovery. Preserve
all partial evidence. There is no current shutdown instruction.
