# V22 base comparison 01 — terminal handoff

Execution source: `5bd6f5cca45ec25d57c37b14b410b9297abe67d5`, 730 sealed files.
Preparation source: `70beea06` (same builder/plan bytes); tokenized inputs were
committed before scoring in the execution source. Inputs:
SHA-256 `3370e6e19c82065f1593f85865b89acb863178d92eb81400ee3bdd060475d4eb`.

Both CPU and CUDA qualification invocations passed 138/138, zero
errors/failures/skips (mixed CPU fixtures and device-aware owner tests).
The one-shot dispatcher and both arms are terminal:
`V22_BASE_COMPARISON_COMPLETE_NOT_RELEASE`. No compute worker remained.
All 1,140 MMLU scores, 384 world teacher-forced rows and 432 generations
finished, with 398 EOS / 34 capped replies and 12,392 generated tokens.
No role or qualification may be rerun under this bundle.
Do not change its source, inputs, settings or raw output files.

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
- Branch: `SpiralReality/latent-memory-full-ft`.
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Furnace checkout: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-comparison01-20261021`.
- Furnace evidence: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-comparison01-20261021`.
- Read-only runtime: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
- tmux session: `ltws-v22-comparison01-20261021`.
- Launch: [LAUNCH.sh](LAUNCH.sh), one finite sequence, no recurring automation.

Use `spiral` for inspection. The role journals are
`raw/<base|v22>/{mmlu,worlds,free}.jsonl`; resource/log/STARTED and terminal
FINISHED receipts retain partial progress if stopped. Do not infer completion
from a vanished process. Preserve failed or censored results and ask before
any separately modified trial. No training, checkpoint saving/deletion,
paid judge, PR/merge, beta replacement or Hub upload is part of this comparison.

The evidence is copied under [furnace/](furnace/). The offline
[summarizer](summarize.py) and `--verify` reproduce the summary and all 24
literal pairs in [ANSWER_BANK.md](ANSWER_BANK.md). The separate tokenizer-only
[replay](furnace/OFFLINE_REPLAY.json) regenerated all inputs, verified the
five training-bank files, and decoded all 432 saved token sequences exactly.
No additional model call, real-model update, save, deletion or judge occurred.

MMLU argmax: **356→354/570**, both losses becoming BF16 B/D ties.
Test latent exact match: **32→64/72**; OOD latent: **15→19/24**.
These include formatting effects and correlated controls; some regressions,
exact-copy errors, abstention errors and inconsistent free reasoning remain.
See the [full bounded results](README.md), not this shorthand alone.
Existing training receipts, old failures and retained weights remain unchanged.
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains the ceiling.
