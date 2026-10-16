"""Dev check (not evidence): D1's lattice readout on final states with shallow-cut memory.
Fit on worlds 0-191 (both sides, own memory), read lane A's flips on worlds 192-255."""
import json, os, sys, time
from pathlib import Path

D, F, LR, UPDATES, STEPS, SEED = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
torch.set_num_threads(8)
torch.use_deterministic_algorithms(True)
import run_v20_a2_flip as run
from latent_workspace import availability, composition, training
from safetensors.torch import load_file

plan = run.ex.read(D / run.PLAN)
tensors = load_file(str(F / "FEATURES.safetensors"))
meta = run.ex.read_gz(F / "ROWS.json.gz")
def bank(indices):
    seg = torch.tensor(indices)
    return training.FeatureBank(tensors["hidden"], tensors["offsets"], tensors["base_logits"][seg], torch.tensor([meta[i]["label"] for i in indices]), torch.tensor([meta[i]["world"] for i in indices]), segments=seg)
train = [i for i, m in enumerate(meta) if m["kind"] == "own" and m["world"] < 192]
spec = plan["route"]
route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(plan["candidate_ids"]), steps=STEPS, seed=SEED, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
config = training.TrainConfig(seed=SEED, updates=UPDATES, batch_size=32, learning_rate=LR, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
named = training.trainable(route)
opt = training.optimizer_for(named, LR, 0.01)
train_bank = bank(train)
t = time.time()
for step in range(1, UPDATES + 1):
    r = training.update(route, None, opt, train_bank, config, step)
    if step % (UPDATES // 4) == 0:
        print(json.dumps(dict(step=step, loss=round(r["task_loss"], 4), seconds=round(time.time() - t))), flush=True)
held = {}
for i, m in enumerate(meta):
    if m["world"] >= 192:
        held[(m["question"], m["side"], m["kind"])] = i
questions = sorted({m["question"] for m in meta if m["world"] >= 192})
held_q = [dict(world=meta[held[(q, 0, "own")]]["world"], query=meta[held[(q, 0, "own")]]["query"], labels=meta[held[(q, 0, "own")]]["labels"], affected=meta[held[(q, 0, "own")]]["affected"]) for q in questions]
scores, base_scores = {}, {}
for name, side, kind in (("intact", 0, "own"), ("twin", 1, "own"), ("random_intact", 0, "random"), ("random_twin", 1, "random")):
    idx = [held[(q, side, kind)] for q in questions]
    scores[name] = training.evaluate(route, bank(idx)).tolist()
    base_scores[name] = tensors["base_logits"][torch.tensor(idx)].tolist()
rule = plan["endpoints"]["rule"]
out = {}
for label, s in (("host_only", base_scores), ("host_plus_route", scores)):
    d = availability.diagnose(run.contrasts_for(held_q, lambda c, s=s: s[c], ("actual", "random_pair")), rule)
    acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(s[c], held_q)) / len(held_q), 3) for c in s}
    out[label] = dict(accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"])
print(json.dumps(dict(lr=LR, updates=UPDATES, steps=STEPS, seed=SEED, seconds=round(time.time() - t), **out)), flush=True)
