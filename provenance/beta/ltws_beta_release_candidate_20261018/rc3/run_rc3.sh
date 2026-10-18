B=/home/ryospiralarchitect/spiralreality/SpiralReality
T=$B/tmp/ltws-beta-release-candidate-20261018/rc3
REL=$T/mistral-7b-instruct-v0.3-LTWS-beta
D=$B/worktrees/latent-workspace-v20-a5-dev-20261018
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
cd $T
echo "$(date -u +%FT%TZ) release check" >> TIMELINE.log
env -u PYTHONPATH HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$PY" -I -B "$D/scripts/check_ltws_beta_release.py" --release "$REL" --ladder-raw "$B/tmp/latent-v20-a2-depth-ladder-20261016/raw" --a5-raw "$B/tmp/latent-v20-a5-stable-route-attempt02-20261018/raw" --final-data "$D/configs/v16/population_20261015/functional.json" --ladder-plan "$D/configs/v20/A2_DEPTH_LADDER_PLAN.json" --a5-plan "$D/configs/v20/A5_STABLE_ROUTE_PLAN.json" > check_release.out 2>&1
echo "$(date -u +%FT%TZ) release check exit=$?" >> TIMELINE.log
cd $REL
env -u PYTHONPATH HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$PY" -I -B example.py > $T/example.out 2>&1
echo "$(date -u +%FT%TZ) example exit=$?" >> $T/TIMELINE.log
cd $T
"$PY" -I -B -c "import sys; sys.path.insert(0, '$REL'); from latent_workspace import package; package.load('$REL'); print('loads after the runs')" > reload.out 2>&1
echo "$(date -u +%FT%TZ) reload exit=$?" >> TIMELINE.log
find $REL -name '__pycache__' | wc -l >> reload.out
echo done > ALL_DONE
