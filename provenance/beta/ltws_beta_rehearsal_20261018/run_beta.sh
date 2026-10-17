B=/home/ryospiralarchitect/spiralreality/SpiralReality
T=$B/tmp/ltws-beta-package-rehearsal-20261018
D=$B/worktrees/latent-workspace-v20-a5-dev-20261018
PY=$B/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python
A5=$B/tmp/latent-v20-a5-stable-route-attempt02-20261018/raw
L=$B/tmp/latent-v20-a2-depth-ladder-20261016/raw
A4=$B/tmp/latent-v20-a4-gated-route-20261017/raw
cd $T
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
echo "$(date -u +%FT%TZ) export" >> TIMELINE.log
"$PY" -B "$D/scripts/export_ltws_beta.py" --a5-raw "$A5" --ladder-raw "$L" --a4-raw "$A4" --out "$T/package" > export.out 2>&1
echo "$(date -u +%FT%TZ) export exit=$?" >> TIMELINE.log
"$PY" -B "$D/scripts/check_ltws_beta_package.py" routes --package "$T/package" --a5-raw "$A5" --ladder-raw "$L" > check_routes.out 2>&1
echo "$(date -u +%FT%TZ) check routes exit=$?" >> TIMELINE.log
"$PY" -B "$D/scripts/check_ltws_beta_package.py" text --package "$T/package" --a5-raw "$A5" --ladder-raw "$L" > check_text.out 2>&1
echo "$(date -u +%FT%TZ) check text exit=$?" >> TIMELINE.log
echo done > ALL_DONE
