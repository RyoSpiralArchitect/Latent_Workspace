"""Dev check for the refined low-layer workspace (not evidence): content-gated reading.

Memory at cut 4 (the facts' own states after four layers, as in the depth ladder),
D1's route over the host's final states at the question positions. Baseline: the depth
ladder's training (own memory, both sides). Gated: also rows whose memory is another
training world's facts, where the route's residual is pushed to zero (it should not
move answers when the memory is not about the question). Lane A's Gaussian random-pair
control is never trained on. Fit on train worlds 0-191, read on 192-255."""
import json, os, sys, time
from pathlib import Path

D, CUT = Path(sys.argv[1]), int(sys.argv[2])
LAMBDAS = [float(x) for x in sys.argv[3].split(",")]
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, availability, composition, training

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
F = torch.nn.functional
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
config = old.engine.ModelConfig(**architecture["model"])
tokenizer = old.engine.load_tokenizer(config)
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
host = DecoderHost(base)
prefix = composition.CutPrefixRoute(host, CUT)
records = run.v19().load_records(plan)["train"]
questions, memories = run.render(old, tokenizer, records, plan)
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]


def encode(ids):
    x = torch.tensor([ids], device="cuda")
    return host.to_cut(x, torch.ones_like(x), CUT)[0]


t = time.time()
with torch.no_grad():
    memory_states = [encode(m["ids"]) for m in memories]
    randoms = run.random_memories(torch, memory_states, sorted({q["world"] for q in questions}), plan["random_memory_seed"])
    rows = []
    for i, q in enumerate(questions):
        w = q["world"]
        for side in (0, 1):
            if w < 192:
                rows.append((i, "own", side, w * keys + side))
                other = (w + 97) % 192
                rows.append((i, "mismatch", side, other * keys + side))
            else:
                rows.append((i, ("intact", "twin")[side], side, w * keys + side))
                rows.append((i, ("random_intact", "random_twin")[side], side, None))
                rows.append((i, "unrelated_" + ("intact", "twin")[side], side, ((w - 192 + 17) % 64 + 192) * keys + side))
    states, offsets, scores, meta = [], [0], [], []
    cache = {}
    for i, kind, side, seg in rows:
        q = questions[i]
        if i not in cache:
            cache.clear(); cache[i] = encode(q["prompt_ids"])
        qs = cache[i]
        m = randoms[q["world"], side] if seg is None else memory_states[seg]
        ones = torch.ones(1, qs.shape[0], dtype=torch.long, device="cuda")
        final, logits, _ = prefix(qs[None], ones, m[None], torch.ones(1, m.shape[0], dtype=torch.long, device="cuda"))
        states.append(final[0, m.shape[0]:].cpu()); offsets.append(offsets[-1] + qs.shape[0])
        scores.append(logits[0, -1, cands].float().cpu())
        meta.append(dict(question=i, world=q["world"], kind=kind, label=q["labels"][side]))
capture = round(time.time() - t)
del base, host
torch.cuda.empty_cache()
torch.set_num_threads(8)
hidden, offsets, host_logits = torch.cat(states), torch.tensor(offsets), torch.stack(scores)
own = [k for k, m in enumerate(meta) if m["kind"] == "own"]
mismatch = [k for k, m in enumerate(meta) if m["kind"] == "mismatch"]
held = {(m["question"], m["kind"]): k for k, m in enumerate(meta) if m["world"] >= 192}
qs_held = sorted({k[0] for k in held})
held_q = [questions[i] for i in qs_held]


def bank(idx):
    seg = torch.tensor(idx)
    return training.FeatureBank(hidden, offsets, host_logits[seg], torch.tensor([meta[k]["label"] for k in idx]), torch.tensor([meta[k]["world"] for k in idx]), segments=seg)


own_bank, mismatch_bank = bank(own), bank(mismatch)
spec = plan["route"]
results = []
for seed in plan["seeds"]:
    for lam in LAMBDAS:
        route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(cands), steps=4, seed=seed, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
        named = training.trainable(route)
        opt = training.optimizer_for(named, 3e-4, 0.01)
        cfg = training.TrainConfig(seed=seed, updates=512, batch_size=32, learning_rate=3e-4, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
        for step in range(1, 513):
            route.train()
            torch.manual_seed(training.component_seed(seed, f"step{step}"))
            idx = training.batch_indices(cfg, len(own_bank), step)
            h, m, b, y, _ = own_bank.batch(idx)
            delta, _, _, _ = route(h, m)
            loss = F.cross_entropy(b + delta, y)
            if lam:
                h2, m2, _, _, _ = mismatch_bank.batch(idx)
                d2, _, _, _ = route(h2, m2)
                loss = loss + lam * d2.square().mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for _, p in named], 1.0)
            opt.step()
        evals = training.evaluate(route, bank(list(range(len(meta))))).tolist()
        sc = {c: [evals[held[(i, c)]] for i in qs_held] for c in ("intact", "twin", "random_intact", "random_twin", "unrelated_intact", "unrelated_twin")}
        d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
        acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in sc}
        unrelated_flips = sum(1 for k, q in enumerate(held_q) if q["affected"] and (sc["unrelated_intact"][k][1] > sc["unrelated_intact"][k][0]) == bool(q["labels"][0]) and (sc["unrelated_twin"][k][1] > sc["unrelated_twin"][k][0]) == bool(q["labels"][1]))
        results.append(dict(seed=seed, lam=lam, accuracy=acc, flips=d["flips"], unrelated_flips=unrelated_flips, world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"]))
        print(json.dumps(results[-1]), flush=True)
host_held = {c: [host_logits[held[(i, c)]].tolist() for i in qs_held] for c in ("intact", "twin", "random_intact", "random_twin")}
dh = availability.diagnose(availability.contrasts(held_q, lambda c: host_held[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
print(json.dumps(dict(host_flips=dh["flips"], host_world_sign=dh["world_sign"], capture_seconds=capture, seconds=round(time.time() - t))), flush=True)
