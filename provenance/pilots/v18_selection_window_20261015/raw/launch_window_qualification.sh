#!/usr/bin/env bash
# One serial dispatch of the sealed V18 selection-window qualification.
# CPU first; CUDA only if the CPU coordinator exits 0. No retry, no loop.
set -u
B=/home/ryospiralarchitect/spiralreality/SpiralReality
W=$B/worktrees/latent-workspace-v18-selection-window-20261015
T=$B/tmp/latent-v18-selection-window-20261015
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
SEAL=$T/SOURCE_SEAL.json
ENTRY=scripts/qualify_v18_selection_window.py
cd "$W" || exit 90
for device in cpu cuda; do
  if [ -e "$T/$device" ] || [ -e "$T/$device-coordinator.log" ]; then
    echo "$(date -u +%FT%TZ) $device output already exists; not dispatching" >> "$T/DISPATCH.log"
    exit 91
  fi
  echo "$(date -u +%FT%TZ) dispatch $device" >> "$T/DISPATCH.log"
  "$PY" -I scripts/run_source_sealed.py --seal "$SEAL" --entry "$ENTRY" -- \
    run --source-seal "$SEAL" --device "$device" --output "$T/$device" \
    > "$T/$device-coordinator.log" 2>&1
  code=$?
  echo "$(date -u +%FT%TZ) $device exit=$code" >> "$T/DISPATCH.log"
  if [ "$code" -ne 0 ]; then
    echo "$(date -u +%FT%TZ) stop: no later device dispatched" >> "$T/DISPATCH.log"
    exit "$code"
  fi
done
echo "$(date -u +%FT%TZ) both devices exited 0" >> "$T/DISPATCH.log"
