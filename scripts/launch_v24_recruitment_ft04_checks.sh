#!/usr/bin/env bash
# New immutable source/output; CPU audit failure still prevents all CUDA/7B work.
set -euo pipefail
cd "$(dirname "$0")/.."
task_source_commit=${1:?Pass the published exact source commit}
[[ "$task_source_commit" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$task_source_commit"
test -z "$(git status --porcelain --untracked-files=all)"
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft04-20261023
task_entry=scripts/run_v24_recruitment_ft04.py
test ! -e "$task_output"
mkdir "$task_output"
cp "$0" "$task_output/CHECKS_DISPATCH_SCRIPT.sh"
exec > "$task_output/CHECKS_LAUNCH.log" 2>&1
"$task_python" -I -B "$task_entry" prepare-seal --output "$task_output/SOURCE_SEAL.json"
env CUDA_VISIBLE_DEVICES= "$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  qualify --device cpu --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/qualification/cpu"
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  qualify --device cuda --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/qualification/cuda"
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  dispatch-checks --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/raw" \
  --checkpoints "$task_output/checkpoints" --qualification "$task_output/qualification"
