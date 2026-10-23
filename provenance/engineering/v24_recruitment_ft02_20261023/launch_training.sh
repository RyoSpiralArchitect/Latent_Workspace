#!/usr/bin/env bash
# No auto-delete: a separately published retirement must precede this phase.
set -euo pipefail
task_source=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft01-20261023
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft02-20261023
task_entry=scripts/run_v24_recruitment_ft.py
cd "$task_source"
test "$(git rev-parse HEAD)" = d43382833f6dc85787720bda80aec511c66f58be
test -z "$(git status --porcelain --untracked-files=all)"
test -f "$task_output/checks/FINISHED.json"
test -f "$task_output/CANARY_RETIREMENT.json"
test ! -e "$task_output/training"
test ! -e "$task_output/TRAINING_LAUNCH.log"
cp "$0" "$task_output/TRAINING_DISPATCH_SCRIPT.sh"
exec > "$task_output/TRAINING_LAUNCH.log" 2>&1
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  dispatch-training --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/raw" \
  --checkpoints "$task_output/checkpoints" --qualification "$task_output/qualification"
