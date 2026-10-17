"""Dev check for V20 A3 (not evidence): is a compact, untrained memory read at cut 4?

The facts' cut-4 states are pooled to one slot per line (mean, or the line's last
token), injected as prefix positions at cut 4, and read by the frozen host alone and
with D1's route over the question-position final states. Full per-token memory is the
reference. Train worlds 0-191 fit the route; lane A's flips are read on 192-255."""
import json, os, sys, time
from pathlib import Path

D, CUT = Path(sys.argv[1]), int(sys.argv[2])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, availability, composition, training

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
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


def line_ends(ids):
    pieces = [tokenizer.decode([i]) for i in ids]
    ends = [p for p, piece in enumerate(pieces) if "\n" in piece]
    return ends + [len(ids) - 1]


def encode(ids):
    x = torch.tensor([ids], device="cuda")
    return host.to_cut(x, torch.ones_like(x), CUT)[0]


def compact(states, ids, mode):
    if mode == "full":
        return states
    ends, start, slots = line_ends(ids), 0, []
    for end in ends:
        slots.append(states[start : end + 1].float().mean(0) if mode == "mean" else states[end].float())
        start = end + 1
    return torch.stack(slots).to(states.dtype)


t = time.time()
results = {}
with torch.no_grad():
    states_cache = [encode(m["ids"]) for m in memories]
    for mode in ("full", "mean", "last"):
        mem = [compact(s, m["ids"], mode) for s, m in zip(states_cache, memories)]
        worlds = sorted({q["world"] for q in questions})
        randoms = run.random_memories(torch, mem, worlds, plan["random_memory_seed"])
        rows = []  # (question index, condition, side)
        for i, q in enumerate(questions):
            for side in (0, 1):
                rows.append((i, ("intact", "twin")[side], side))
            if q["world"] >= 192:
                rows += [(i, "random_intact", 0), (i, "random_twin", 1)]
        states, offsets, scores, meta = [], [0], [], []
        cache = {}
        for i, cond, side in rows:
            q = questions[i]
            if i not in cache:
                cache.clear(); cache[i] = encode(q["prompt_ids"])
            qs = cache[i]
            m = randoms[q["world"], side] if cond.startswith("random_") else mem[q["world"] * keys + side]
            ones = torch.ones(1, qs.shape[0], dtype=torch.long, device="cuda")
            final, logits, _ = prefix(qs[None], ones, m[None], torch.ones(1, m.shape[0], dtype=torch.long, device="cuda"))
            states.append(final[0, m.shape[0]:].cpu()); offsets.append(offsets[-1] + qs.shape[0])
            scores.append(logits[0, -1, cands].float().cpu())
            meta.append(dict(question=i, world=q["world"], query=q["query"], cond=cond, side=side, label=q["labels"][side], labels=q["labels"], affected=q["affected"]))
        hidden, offsets, base_logits = torch.cat(states), torch.tensor(offsets), torch.stack(scores)
        held = {(m["question"], m["cond"]): k for k, m in enumerate(meta) if m["world"] >= 192}
        qs_held = sorted({k[0] for k in held})
        held_q = [questions[i] for i in qs_held]
        def diag(score_rows):
            sc = {c: [score_rows[held[(i, c)]] for i in qs_held] for c in ("intact", "twin", "random_intact", "random_twin")}
            d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
            acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in sc}
            return dict(accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"])
        host_only = diag(base_logits.tolist())
        # D1's route on CPU over the question-position final states
        train_idx = [k for k, m in enumerate(meta) if m["world"] < 192 and not m["cond"].startswith("random_")]
        def bank(idx):
            seg = torch.tensor(idx)
            return training.FeatureBank(hidden, offsets, base_logits[seg], torch.tensor([meta[k]["label"] for k in idx]), torch.tensor([meta[k]["world"] for k in idx]), segments=seg)
        spec = plan["route"]
        route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(cands), steps=4, seed=plan["seeds"][0], workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
        cfg = training.TrainConfig(seed=plan["seeds"][0], updates=512, batch_size=32, learning_rate=3e-4, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
        named = training.trainable(route)
        opt = training.optimizer_for(named, 3e-4, 0.01)
        tb = bank(train_idx)
        with torch.enable_grad():
            for step in range(1, 513):
                training.update(route, None, opt, tb, cfg, step)
        all_idx = list(range(len(meta)))
        routed = training.evaluate(route, bank(all_idx)).tolist()
        results[mode] = dict(slots=int(mem[0].shape[0]), host=host_only, route=diag(routed), seconds=round(time.time() - t))
        print(json.dumps({mode: results[mode]}), flush=True)
