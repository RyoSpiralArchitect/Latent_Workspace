"""Smoke of the sealed A5 code path in a dev checkout (not evidence): the runner's own
reproduction of A4's gated route of seed 1 from the pinned records (every receipt, the
fingerprint and the final scores). No stable route is trained and no new route reads the
final split. The output folder must sit directly under tmp/, beside the sealed task roots."""
import json, os, sys, time
from argparse import Namespace
from pathlib import Path

D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a5_stable_route as run

plan = run.ex.read(D / run.PLAN)
run.validate_plan(plan)
torch = run.LADDER.cpu_runtime(plan)
run.load("run_v16_adapter_migration").load_runtime()
args = Namespace(role="reproduce", output=OUT / "raw" / "reproduce", checkpoints=OUT / "checkpoints")
args.output.mkdir(parents=True, exist_ok=False)
t = time.time()
report = run.reproduce_run(torch, args, plan)
print(json.dumps(dict(report, seconds=round(time.time() - t))), flush=True)
