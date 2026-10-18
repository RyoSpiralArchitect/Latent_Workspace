B=/home/ryospiralarchitect/spiralreality/SpiralReality
T=$B/tmp/ltws-beta-generation-20261018
D=$B/worktrees/latent-workspace-v20-a5-dev-20261018
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
REL=$B/tmp/ltws-beta-hub-download2-20261018/mistral-7b-instruct-v0.3-LTWS-beta
cd $T
echo "$(date -u +%FT%TZ) generate at $(git -C $D rev-parse HEAD)" >> TIMELINE.log
env -u PYTHONPATH "$PY" -I -B "$D/scripts/generate_ltws_beta_examples.py" --release "$REL" --boolq "$B/tmp/ltws-beta-bench-20261018/data/boolq_validation.jsonl" --out "$T/out" > generate.out 2>&1
echo "$(date -u +%FT%TZ) generate exit=$?" >> TIMELINE.log
echo done > ALL_DONE
