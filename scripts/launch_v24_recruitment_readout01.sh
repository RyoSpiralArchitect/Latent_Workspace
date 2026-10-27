#!/usr/bin/env bash
# New no-retry read-only experiment; old FT source/outputs and all weights stay untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
task_source_commit=${1:?Pass the exact committed source}
[[ "$task_source_commit" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$task_source_commit"
test -z "$(git status --porcelain --untracked-files=all)"
task_python=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-readout01-20261027
task_entry=scripts/run_v24_recruitment_readout.py
task_tokenizer=/home/ryospiralarchitect/.cache/huggingface/hub/models--mistralai--Mistral-7B-Instruct-v0.3/snapshots/c170c708c41dac9275d15a8fff4eca08d52bab71
test ! -e "$task_output"
# Additional metadata headroom, not a reduction of the historical 50 GiB floor.
"$task_python" -I -B -c 'import shutil; assert shutil.disk_usage(".").free >= 50.25 * 2**30, "50 GiB plus 256 MiB metadata reserve required"'
mkdir "$task_output"
cp "$0" "$task_output/DISPATCH_SCRIPT.sh"
exec > "$task_output/LAUNCH.log" 2>&1
"$task_python" -I -B "$task_entry" prepare-seal --output "$task_output/SOURCE_SEAL.json"
env CUDA_VISIBLE_DEVICES= "$task_python" -I -B "$task_entry" verify-inputs \
  "$task_tokenizer" "$task_output/INPUT_REPLAY.json"
env CUDA_VISIBLE_DEVICES= "$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  qualify --device cpu --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/qualification/cpu"
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  qualify --device cuda --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/qualification/cuda"
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_output/SOURCE_SEAL.json" --entry "$task_entry" -- \
  dispatch --seal "$task_output/SOURCE_SEAL.json" --output "$task_output/raw" \
  --checkpoints "$task_output/checkpoints" --qualification "$task_output/qualification"
