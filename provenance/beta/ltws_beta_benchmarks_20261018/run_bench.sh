B=/home/ryospiralarchitect/spiralreality/SpiralReality
T=$B/tmp/ltws-beta-bench-20261018
D=$B/worktrees/latent-workspace-v20-a5-dev-20261018
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
REL=$B/tmp/ltws-beta-hub-download-20261018/mistral-7b-instruct-v0.3-LTWS-beta
cd $T
echo "$(date -u +%FT%TZ) bench" >> TIMELINE.log
env -u PYTHONPATH "$PY" -I -B "$D/scripts/bench_ltws_beta.py" --release "$REL" --mmlu "$D/configs/v16/population_20261015/mmlu.json" --data "$T/data" > bench.out 2>&1
echo "$(date -u +%FT%TZ) bench exit=$?" >> TIMELINE.log
echo done > ALL_DONE
