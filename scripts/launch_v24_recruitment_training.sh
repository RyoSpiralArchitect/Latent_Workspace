#!/usr/bin/env bash
# Same frozen source, after the separately verified spent-canary retirement.
set -euo pipefail
cd "$(dirname "$0")/.."
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft01-20261023
task_entry=scripts/run_v24_recruitment_ft.py
test -f "$task_output/checks/FINISHED.json"
test -f "$task_output/CANARY_RETIREMENT.json"
test ! -e "$task_output/training"
test ! -e "$task_output/TRAINING_LAUNCH.log"
exec > "$task_output/TRAINING_LAUNCH.log" 2>&1
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  dispatch-training --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/raw" \
  --checkpoints "$task_output/checkpoints" --qualification "$task_output/qualification"
