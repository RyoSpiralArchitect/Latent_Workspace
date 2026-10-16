"""Dev check (not evidence): for cut k, capture host final states with memory injected at k
(in memory, nothing written to disk), then train D1's readout on CPU and read flips.
Fit on train worlds 0-191, read on 192-255; dev and final are never touched."""
import json, os, sys, time
from pathlib import Path

D, F, CUT = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_flip as run
from latent_workspace import DecoderHost, availability, composition, training

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
base = old.engine._load_hf_model(old.engine.ModelConfig(**architecture["model"])).eval().requires_grad_(False).to("cuda")
host = DecoderHost(base)
captured = {}
base.lm_head.register_forward_hook(lambda module, inputs, output: captured.__setitem__("final", inputs[0]))
rows = run.ex.read_gz(F / "ROWS_train.json.gz")
questions, memories = rows["questions"], rows["memories"]
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]
t = time.time()
states, offsets, base_rows, meta = [], [0], [], []
with torch.no_grad():
    def encode(ids):
        x = torch.tensor([ids], device="cuda")
        return host.to_cut(x, torch.ones_like(x), CUT)[0]
    mem_cache = {}
    for i, q in enumerate(questions):
        qs = encode(q["prompt_ids"])
        kinds = [(0, "own"), (1, "own")] + ([(0, "random"), (1, "random")] if q["world"] >= 192 else [])
        for side, kind in kinds:
            seg = q["world"] * keys + side
            if seg not in mem_cache:
                mem_cache[seg] = encode(memories[seg]["ids"])
            m = mem_cache[seg]
            if kind == "random":
                g = torch.Generator().manual_seed(470016 + q["world"] * 2 + side)
                r = torch.randn(m.shape, generator=g).to(m.device, m.dtype)
                m = r * (m.float().norm() / r.float().norm()).to(m.dtype)
            x = torch.cat([m, qs])[None]
            logits = host.from_cut(x, torch.ones(x.shape[:2], dtype=torch.long, device="cuda"), CUT)
            states.append(captured["final"][0].cpu())
            offsets.append(offsets[-1] + x.shape[1])
            base_rows.append(logits[0, -1, cands].float().cpu())
            meta.append(dict(question=i, world=q["world"], query=q["query"], side=side, kind=kind, label=q["labels"][side], labels=q["labels"], affected=q["affected"]))
capture_s = time.time() - t
del base, host
torch.cuda.empty_cache()
os.environ["CUDA_VISIBLE_DEVICES"] = ""
torch.set_num_threads(8)
hidden, offsets, base_logits = torch.cat(states), torch.tensor(offsets), torch.stack(base_rows)
def bank(indices):
    seg = torch.tensor(indices)
    return training.FeatureBank(hidden, offsets, base_logits[seg], torch.tensor([meta[i]["label"] for i in indices]), torch.tensor([meta[i]["world"] for i in indices]), segments=seg)
train = [i for i, m in enumerate(meta) if m["kind"] == "own" and m["world"] < 192]
spec = plan["route"]
SEED = 2026101701
route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(cands), steps=4, seed=SEED, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
config = training.TrainConfig(seed=SEED, updates=512, batch_size=32, learning_rate=3e-4, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
named = training.trainable(route)
opt = training.optimizer_for(named, 3e-4, 0.01)
train_bank = bank(train)
for step in range(1, 513):
    training.update(route, None, opt, train_bank, config, step)
held = {(m["question"], m["side"], m["kind"]): i for i, m in enumerate(meta) if m["world"] >= 192}
qs_held = sorted({k[0] for k in held})
held_q = [dict(world=meta[held[(q, 0, "own")]]["world"], query=meta[held[(q, 0, "own")]]["query"], labels=meta[held[(q, 0, "own")]]["labels"], affected=meta[held[(q, 0, "own")]]["affected"]) for q in qs_held]
scores, base_scores = {}, {}
for name, side, kind in (("intact", 0, "own"), ("twin", 1, "own"), ("random_intact", 0, "random"), ("random_twin", 1, "random")):
    idx = [held[(q, side, kind)] for q in qs_held]
    scores[name] = training.evaluate(route, bank(idx)).tolist()
    base_scores[name] = base_logits[torch.tensor(idx)].tolist()
out = {}
for label, s in (("host_only", base_scores), ("host_plus_route", scores)):
    d = availability.diagnose(run.contrasts_for(held_q, lambda c, s=s: s[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
    acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(s[c], held_q)) / len(held_q), 3) for c in s}
    out[label] = dict(accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"])
print(json.dumps(dict(cut=CUT, capture_seconds=round(capture_s), total_seconds=round(time.time() - t), **out)), flush=True)
