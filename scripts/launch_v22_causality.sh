#!/usr/bin/env bash
# One finite no-retry launch. Existing sources/results must never be reused.
set -euo pipefail
task_root=/home/ryospiralarchitect/spiralreality/SpiralReality
task_work="$task_root/worktrees/latent-v22-causality01-20261021"
task_out="$task_root/latent-v22-causality01-20261021"
task_python="$task_root/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python"
test "$#" -eq 1
test "$(git -C "$task_work" rev-parse HEAD)" = "$1"
test -z "$(git -C "$task_work" status --porcelain --untracked-files=all)"
test ! -e "$task_out"
cd "$task_work"
mkdir -p "$task_out/qualification"
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export LTWS_CPU_SDPA_BACKEND=math
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
"$task_python" scripts/run_v22_causality.py prepare-seal --output "$task_out/SOURCE_SEAL.json"
for task_device in cpu cuda; do
  "$task_python" -I scripts/run_source_sealed.py \
    --seal "$task_out/SOURCE_SEAL.json" --entry scripts/run_v22_causality.py -- \
    qualify --device "$task_device" --seal "$task_out/SOURCE_SEAL.json" \
    --output "$task_out/qualification/$task_device" > "$task_out/qualification/$task_device.log" 2>&1
done
"$task_python" -I scripts/run_source_sealed.py \
  --seal "$task_out/SOURCE_SEAL.json" --entry scripts/run_v22_causality.py -- \
  dispatch --seal "$task_out/SOURCE_SEAL.json" --output "$task_out/raw" \
  --checkpoints "$task_out/no-checkpoint-writes" --qualification "$task_out/qualification" \
  > "$task_out/dispatch.log" 2>&1
