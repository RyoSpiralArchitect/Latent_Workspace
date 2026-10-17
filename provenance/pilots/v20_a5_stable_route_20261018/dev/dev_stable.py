"""Dev check for V20 A5 (not evidence): where does the gated route's training stop?

A4's gated route (cut 4, content gating 0.3, D1's settings) was scored at update 512 under
a constant learning rate; one seed of three was scored right after a loss spike. On the A5
development rows (dev_capture.py: fit train worlds 0-191, read 192-255), per seed:

- const: A4's schedule. Held-out readings at updates 448, 480, 496, 504 and 512 show how
  much the last updates move the result. The same trajectory also gives an exponential
  average of the weights (decay 0.99) and a uniform average of updates 385-512.
- decay: constant to update 256, then linear decay of the learning rate to near zero.

Lane A's rule is applied as written (its thresholds were set for twice this size)."""
import copy, json, os, sys, time
from pathlib import Path

D, FEATURES = Path(sys.argv[1]), Path(sys.argv[2])
SEEDS = [int(s) for s in sys.argv[3].split(",")]
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run

plan = run.ex.read(D / run.PLAN)
torch = run.cpu_runtime(plan)
run.load("run_v16_adapter_migration").load_runtime()
from latent_workspace import availability, composition, training
from safetensors.torch import load_file

TRAIN, UPDATES, WEIGHT, EMA = 192, 512, 0.3, 0.99
READ_AT = (448, 480, 496, 504, 512)
tensors = load_file(str(FEATURES / "FEATURES.safetensors"))
saved = run.ex.read_gz(FEATURES / "ROWS.json.gz")
meta, questions = saved["rows"], saved["questions"]
hidden, offsets, host_logits = tensors["question_states"], tensors["offsets"], tensors["host_logits"]


def bank(idx):
    seg = torch.tensor(idx)
    return training.FeatureBank(hidden, offsets, host_logits[seg], torch.tensor([meta[k]["label"] for k in idx]), torch.tensor([meta[k]["world"] for k in idx]), segments=seg)


own = [k for k, m in enumerate(meta) if m["kind"] == "own"]
mismatch = [k for k, m in enumerate(meta) if m["kind"] == "mismatch"]
assert [(meta[k]["question"], meta[k]["side"]) for k in own] == [(meta[k]["question"], meta[k]["side"]) for k in mismatch]
own_bank, mismatch_bank = bank(own), bank(mismatch)
held = {(m["question"], m["kind"]): k for k, m in enumerate(meta) if m["world"] >= TRAIN}
held_rows = sorted(held.values())
position = {k: j for j, k in enumerate(held_rows)}
held_bank = bank(held_rows)
qs_held = sorted({k[0] for k in held})
held_q = [questions[i] for i in qs_held]
CONDITIONS = ("intact", "twin", "random_intact", "random_twin", "other_intact", "other_twin", "complement")
host_scores = {c: [host_logits[held[i, c]].tolist() for i in qs_held] for c in CONDITIONS}
own_labels = [meta[k]["label"] for k in own]


def report(route):
    evals = training.evaluate(route, held_bank).tolist()
    sc = {c: [evals[position[held[i, c]]] for i in qs_held] for c in CONDITIONS}
    d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
    acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in ("intact", "twin")}
    moved = {c: round(sum(abs((x[1] - x[0]) - (h[1] - h[0])) for x, h in zip(sc[c], host_scores[c])) / len(held_q), 3) for c in ("intact", "random_intact", "other_intact", "complement")}
    train = training.evaluate(route, own_bank)
    train_acc = round(float(((train[:, 1] > train[:, 0]).long() == torch.tensor(own_labels)).float().mean()), 3)
    return dict(accuracy=acc, train_accuracy=train_acc, flips=[d["flips"]["actual"], d["flips"]["random_pair"]], worlds=[d["world_sign"]["positive"], d["world_sign"]["negative"]], p=float(f"{d['sign_test_p']:.2e}"), verdict=d["verdict"], gap_moved=moved)


def averaged(route, state):
    other = copy.deepcopy(route)
    other.load_state_dict({k: v.to(route.state_dict()[k].dtype) for k, v in state.items()})
    return other


spec = plan["route"]
t = time.time()
for seed in SEEDS:
    for schedule in ("const", "decay"):
        route, optimizer, config, named = run.build(plan, seed, spec["steps"])
        config = training.TrainConfig(**{**config.__dict__, "mismatch_weight": WEIGHT})
        base_lr = config.learning_rate
        ema = swa = None
        swa_count = 0
        readings = {}
        losses = []
        for step in range(1, UPDATES + 1):
            lr = base_lr if schedule == "const" or step <= 256 else base_lr * (UPDATES - step + 1) / (UPDATES - 256 + 1)
            for group in optimizer.param_groups:
                group["lr"] = lr
            receipt = training.update(route, None, optimizer, own_bank, config, step, mismatch_bank)
            losses.append(receipt["task_loss"])
            if schedule == "const":
                current = {k: v.detach().clone().float() for k, v in route.state_dict().items()}
                ema = current if ema is None else {k: EMA * ema[k] + (1 - EMA) * current[k] for k in current}
                if step > UPDATES - 128:
                    swa_count += 1
                    swa = current if swa is None else {k: swa[k] + (current[k] - swa[k]) / swa_count for k in current}
                if step in READ_AT:
                    readings[step] = report(route)
        tail = losses[-32:]
        if schedule == "const":
            for step in READ_AT:
                print(json.dumps(dict(seed=seed, variant=f"const@{step}", **readings[step])), flush=True)
            print(json.dumps(dict(seed=seed, variant="ema", **report(averaged(route, ema)))), flush=True)
            print(json.dumps(dict(seed=seed, variant="swa", **report(averaged(route, swa)))), flush=True)
        else:
            print(json.dumps(dict(seed=seed, variant="decay", **report(route))), flush=True)
        print(json.dumps(dict(seed=seed, schedule=schedule, loss_last32=round(sum(tail) / 32, 3), loss_max_last64=round(max(losses[-64:]), 3), seconds=round(time.time() - t))), flush=True)
