"""Dev power check for V20 A2 (not evidence): train on train worlds 0-191 with both sides,
then read lane A's flips on train worlds 192-255. Dev and final splits are never touched."""
import json, os, sys, time
from pathlib import Path

D, F = Path(sys.argv[1]), Path(sys.argv[2])
LR, UPDATES, VARIANT, SEED = float(sys.argv[3]), int(sys.argv[4]), sys.argv[5], int(sys.argv[6])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch

torch.set_num_threads(8)
torch.use_deterministic_algorithms(True)
import run_v20_a2_flip as run
from latent_workspace import availability, composition, training

plan = run.ex.read(D / run.PLAN)
tensors, rows = run.load_split(F, "train")
questions = rows["questions"]
keys = len(run.MEMORY_KEYS)
TRAIN, HELD = range(0, 192), range(192, 256)


def own_bank(worlds, memory=True):
    seg, tgt, wor, mem = [], [], [], []
    for i, q in enumerate(questions):
        pass
    by_world = {}
    for i, q in enumerate(questions):
        by_world.setdefault(q["world"], []).append(i)
    for w in worlds:
        for side in (0, 1):
            for i in by_world[w]:
                seg.append(i); tgt.append(questions[i]["labels"][side]); wor.append(w); mem.append(w * keys + side)
    seg = torch.tensor(seg)
    bank = training.FeatureBank(tensors["question_states"], tensors["question_offsets"], tensors["base_logits"][seg], torch.tensor(tgt), torch.tensor(wor), segments=seg)
    return bank.with_memory((tensors["memory_states"], tensors["memory_offsets"], torch.tensor(mem))) if memory else bank


held_rows = [i for i, q in enumerate(questions) if q["world"] in HELD]
randoms = run.random_memory(torch, tensors, {"questions": [questions[i] for i in held_rows]}, plan["random_memory_seed"])


def condition_bank(name):
    seg = torch.tensor(held_rows)
    bank = training.FeatureBank(tensors["question_states"], tensors["question_offsets"], tensors["base_logits"][seg], torch.tensor([questions[i]["labels"][0] for i in held_rows]), torch.tensor([questions[i]["world"] for i in held_rows]), segments=seg)
    if name.startswith("random_"):
        states, bounds, position = randoms
        side = 0 if name == "random_intact" else 1
        return bank.with_memory((states, bounds, torch.tensor([2 * position[questions[i]["world"]] + side for i in held_rows])))
    side = 0 if name == "intact" else 1
    return bank.with_memory((tensors["memory_states"], tensors["memory_offsets"], torch.tensor([questions[i]["world"] * keys + side for i in held_rows])))


spec = plan["route"]
route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(plan["candidate_ids"]), steps=spec["steps"], seed=SEED, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
if "open" in VARIANT:
    g = torch.Generator().manual_seed(SEED)
    with torch.no_grad():
        route.lattice.attention.out.weight.copy_(0.02 * torch.randn(route.lattice.attention.out.weight.shape, generator=g))
config = training.TrainConfig(seed=SEED, updates=UPDATES, batch_size=32, learning_rate=LR, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
opt = training.optimizer_for(training.trainable(route), LR, 0.01)
bank = own_bank(TRAIN, memory="nomem" not in VARIANT)
t = time.time()
losses = []
curve = []
for step in range(1, UPDATES + 1):
    r = training.update(route, None, opt, bank, config, step)
    losses.append(r["task_loss"])
    if step % (UPDATES // 4) == 0:
        curve.append((step, round(sum(losses[-32:]) / 32, 4), round(r["gate_mean"], 3)))
train_s = time.time() - t
if "nomem" in VARIANT:
    print(json.dumps(dict(variant=VARIANT, lr=LR, updates=UPDATES, seed=SEED, train_seconds=round(train_s), curve=curve)))
    sys.exit(0)
scores = {name: training.evaluate(route, condition_bank(name)).tolist() for name in ("intact", "twin", "random_intact", "random_twin")}
held_q = [questions[i] for i in held_rows]
contrasts = run.contrasts_for(held_q, lambda c: scores[c], ("actual", "random_pair"))
d = availability.diagnose(contrasts, plan["endpoints"]["rule"])
acc = {c: sum((s[1] > s[0]) == bool(q["labels"][0 if c in ("intact", "random_intact") else 1]) for s, q in zip(scores[c], held_q)) / len(held_q) for c in scores}
aff = [k for k, q in enumerate(held_q) if q["affected"]]
acc_aff = {c: sum((scores[c][k][1] > scores[c][k][0]) == bool(held_q[k]["labels"][0 if c == "intact" else 1]) for k in aff) / len(aff) for c in ("intact", "twin")}
print(json.dumps(dict(variant=VARIANT, lr=LR, updates=UPDATES, seed=SEED, train_seconds=round(train_s), curve=curve, held_accuracy=acc, held_affected_accuracy=acc_aff, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"])))
