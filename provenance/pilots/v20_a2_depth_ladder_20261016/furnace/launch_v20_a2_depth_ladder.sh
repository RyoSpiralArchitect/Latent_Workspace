#!/usr/bin/env bash
# One serial dispatch of the sealed V20 A2 depth ladder. Tiny CPU
# qualification, tiny CUDA qualification, then the runner's own dispatcher
# (four extraction roles -> twelve route roles -> replay -> endpoints). Each stage
# starts only if the previous exited 0. No retry.
set -u
B=/home/ryospiralarchitect/spiralreality/SpiralReality
W=$B/worktrees/latent-workspace-v20-a2-depth-ladder-20261016
T=$B/tmp/latent-v20-a2-depth-ladder-20261016
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
SEAL=$T/SOURCE_SEAL.json
ENTRY=scripts/run_v20_a2_depth_ladder.py
LOG=$T/LAUNCH_TIMELINE.log
cd "$W" || exit 90
note() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
for path in "$T/qualification" "$T/raw" "$T/checkpoints"; do
  if [ -e "$path" ]; then note "refuse: $path exists"; exit 91; fi
done
for device in cpu cuda; do
  note "dispatch qualify-$device"
  "$PY" -I scripts/run_source_sealed.py --seal "$SEAL" --entry "$ENTRY" -- \
    qualify --seal "$SEAL" --device "$device" --output "$T/qualification/$device" \
    > "$T/qualify-$device.log" 2>&1
  code=$?
  note "qualify-$device exit=$code"
  if [ "$code" -ne 0 ]; then note "stop: nothing later dispatched"; exit "$code"; fi
done
note "dispatch ladder"
"$PY" -I scripts/run_source_sealed.py --seal "$SEAL" --entry "$ENTRY" -- \
  dispatch --seal "$SEAL" --output "$T/raw" --checkpoints "$T/checkpoints" \
  --qualification "$T/qualification" > "$T/runner-stdout.log" 2>&1
code=$?
note "ladder exit=$code"
if [ "$code" -eq 0 ]; then note "all stages exited 0"; else note "stop: ladder failed"; fi
exit "$code"
