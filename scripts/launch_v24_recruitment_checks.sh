#!/usr/bin/env bash
# Only qualification/canary/replay. Training is a separate post-retirement phase.
set -euo pipefail
cd "$(dirname "$0")/.."
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft01-20261023
task_entry=scripts/run_v24_recruitment_ft.py
test ! -e "$task_output"
mkdir "$task_output"
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
