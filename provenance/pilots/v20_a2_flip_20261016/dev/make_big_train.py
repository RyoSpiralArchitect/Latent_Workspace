"""Dev data for the A2 scale check: more training worlds with the canonical train settings."""
import hashlib, json, sys
from pathlib import Path

sys.path.insert(0, "src")
from latent_workspace_ft_v10.engine import make_functional_relation_pair_records

def remap(record):
    assert record["choices"] == [" 0", " 1"]
    return {**record, "choices": [" no", " yes"]}

def canonical(record):
    return json.dumps(record, ensure_ascii=False, separators=(", ", ": "))

original = [json.loads(l) for l in open("data/v10/functional_train.jsonl") if l.strip()]
regen = [remap(r) for r in make_functional_relation_pair_records(worlds=256, seed=90_071, width=6, queries_per_world=8)]
print("generator reproduces the canonical train split:", regen == original)
dev = [json.loads(l) for l in open("data/v10/functional_eval.jsonl") if l.strip()]
final = json.load(open("configs/v16/population_20261015/functional.json"))
taken = {tuple(o) for r in original + dev + final for o in r["metadata"]["orders"]}
contexts = {c for r in original + dev + final for c in r["contexts"]}
seed, worlds = int(sys.argv[1]), int(sys.argv[2])
fresh, dropped = [], 0
for r in make_functional_relation_pair_records(worlds=worlds, seed=seed, width=6, queries_per_world=8):
    r = remap(r)
    if any(tuple(o) in taken for o in r["metadata"]["orders"]) or any(c in contexts for c in r["contexts"]):
        dropped += 1
        continue
    fresh.append(r)
out = Path(sys.argv[3])
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fresh))
print(json.dumps(dict(seed=seed, generated=worlds, kept=len(fresh), dropped_for_overlap=dropped, bytes=out.stat().st_size, sha256=hashlib.sha256(out.read_bytes()).hexdigest())))
