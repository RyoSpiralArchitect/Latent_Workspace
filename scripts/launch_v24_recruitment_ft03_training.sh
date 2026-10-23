#!/usr/bin/env bash
# No auto-delete or auto-retry. Requires separately completed replay and retirement.
set -euo pipefail
cd "$(dirname "$0")/.."
task_source_commit=${1:?Pass the published exact source commit}
[[ "$task_source_commit" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$task_source_commit"
test -z "$(git status --porcelain --untracked-files=all)"
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft03-20261023
task_entry=scripts/run_v24_recruitment_ft03.py
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
