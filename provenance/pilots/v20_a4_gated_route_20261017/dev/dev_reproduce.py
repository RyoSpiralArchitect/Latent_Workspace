"""Dev check for V20 A4 (not evidence): does the ladder's ungated cut-4 route of seed 1
reproduce bitwise in a fresh process from the stored features (512 updates: every receipt,
the final fingerprint and the final scores)? The sealed run makes this its first role."""
import json, os, sys, time
from pathlib import Path

D, RAW = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run

plan = run.ex.read(D / run.PLAN)
torch = run.cpu_runtime(plan)
run.load("run_v16_adapter_migration").load_runtime()
from latent_workspace import training

t = time.time()
bank = run.load_bank(torch, RAW / "extract_cut4", "train")
final = run.load_bank(torch, RAW / "extract_cut4", "final")
route, optimizer, config, named = run.build(plan, plan["seeds"][0], plan["route"]["steps"])
receipts = [training.update(route, None, optimizer, bank, config, s) for s in range(1, config.updates + 1)]
fingerprint = training.fingerprint(named)
adapted = training.evaluate(route, final).tolist()
recorded = [json.loads(line) for line in (RAW / "route_cut4_s1" / "updates_route.jsonl").read_text().splitlines()]
scores = run.ex.read_gz(RAW / "route_cut4_s1" / "eval_route_final_step512.json.gz")["adapted_logits"]
expected = run.ex.read(RAW / "route_cut4_s1" / "FINGERPRINTS.json")["route"]["512"]
print(json.dumps(dict(fingerprint_equal=fingerprint == expected, receipts_equal=receipts == recorded, scores_equal=adapted == scores, seconds=round(time.time() - t))), flush=True)
