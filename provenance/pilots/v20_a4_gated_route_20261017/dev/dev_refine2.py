"""Dev check for V20 A4 (not evidence): content gating with memories that state no answer.

As dev_refine.py, with one change and three additions.

- Change: a training row's mismatch memory is another training world's facts (same side)
  that do not name both of the question's entities: the first of (w + 97k) mod 192,
  k = 1, 2, ..., to qualify. The name pool has 12 names and a world uses 6, so 23% of
  dev_refine's mismatch memories named both entities, stated an answer, and gating pushed
  against reading them.
- Rows follow the depth ladder's train order (world, side, question).
- Added: the route's mean |change of the candidate gap| under each held-out condition; the
  complement-entity memory (the ladder's `unrelated` condition, no shared entity); and the
  own rows, extracted in this fresh process, against the sealed ladder's stored cut-4 rows.
Fit on train worlds 0-191, read on 192-255. Dev and final are never touched."""
import collections, json, os, sys, time
from pathlib import Path

D, CUT, LADDER = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
LAMBDAS = [float(x) for x in sys.argv[4].split(",")]
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, availability, composition, training
from safetensors.torch import load_file

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
names = [set(r["metadata"]["orders"][0]) for r in records]
TRAIN, HELD = 192, 64


def mismatch_world(w, q):
    a, b = records[w]["metadata"]["query_pairs"][q]
    assert a in records[w]["queries"][q] and b in records[w]["queries"][q]
    for k in range(1, TRAIN):
        o = (w + 97 * k) % TRAIN
        if not (a in names[o] and b in names[o]):
            return o, k
    raise ValueError("no mismatch world")


def encode(ids):
    x = torch.tensor([ids], device="cuda")
    return host.to_cut(x, torch.ones_like(x), CUT)[0]


rows, ks = [], []
for i, _, side in run.split_rows(questions, "train"):
    w = questions[i]["world"]
    if w < TRAIN:
        o, k = mismatch_world(w, questions[i]["query"])
        ks.append(k)
        rows.append((i, "own", side, w * keys + side))
        rows.append((i, "mismatch", side, o * keys + side))
for i, q in enumerate(questions):
    w = q["world"]
    if w >= TRAIN:
        for side in (0, 1):
            rows.append((i, ("intact", "twin")[side], side, w * keys + side))
            rows.append((i, ("random_intact", "random_twin")[side], side, None))
            other = (w - TRAIN + 17) % HELD + TRAIN
            rows.append((i, ("other_intact", "other_twin")[side], side, other * keys + side))
        rows.append((i, "complement", 0, w * keys + run.key_index("unrelated")))

t = time.time()
with torch.no_grad():
    memory_states = [encode(m["ids"]) for m in memories]
    randoms = run.random_memories(torch, memory_states, sorted({q["world"] for q in questions}), plan["random_memory_seed"])
    states, offsets, scores, meta, cache = [], [0], [], [], {}
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
        meta.append(dict(question=i, world=q["world"], kind=kind, side=side, label=q["labels"][side]))
capture = round(time.time() - t)

stored = load_file(str(LADDER / "FEATURES_train.safetensors"))
where = {(m["question"], m["side"]): k for k, m in enumerate(run.ex.read_gz(LADDER / "ROWS_train.json.gz"))}
own = [k for k, m in enumerate(meta) if m["kind"] == "own"]
mismatch = [k for k, m in enumerate(meta) if m["kind"] == "mismatch"]
equal_states = equal_logits = 0
worst = 0.0
for k in own:
    s = where[meta[k]["question"], meta[k]["side"]]
    a = stored["question_states"][stored["offsets"][s] : stored["offsets"][s + 1]]
    equal_states += torch.equal(a, states[k])
    equal_logits += torch.equal(stored["host_logits"][s], scores[k])
    worst = max(worst, float((a.float() - states[k].float()).abs().max()))
del stored
print(json.dumps(dict(reproduction=dict(rows=len(own), states_equal=equal_states, logits_equal=equal_logits, max_abs=worst), mismatch_k=dict(sorted(collections.Counter(ks).items())), capture_seconds=capture)), flush=True)

del base, host, prefix
torch.cuda.empty_cache()
torch.set_num_threads(8)
hidden, offsets, host_logits = torch.cat(states), torch.tensor(offsets), torch.stack(scores)
del states


def bank(idx):
    seg = torch.tensor(idx)
    return training.FeatureBank(hidden, offsets, host_logits[seg], torch.tensor([meta[k]["label"] for k in idx]), torch.tensor([meta[k]["world"] for k in idx]), segments=seg)


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


def label(c, q):
    return q["labels"][1 if c.endswith("twin") else 0]


def report(sc):
    d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
    acc = {c: round(sum((x[1] > x[0]) == bool(label(c, q)) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in CONDITIONS}
    moved = {c: round(sum(abs((x[1] - x[0]) - (h[1] - h[0])) for x, h in zip(sc[c], host_scores[c])) / len(held_q), 3) for c in CONDITIONS}
    other = sum(1 for k, q in enumerate(held_q) if q["affected"] and (sc["other_intact"][k][1] > sc["other_intact"][k][0]) == bool(q["labels"][0]) and (sc["other_twin"][k][1] > sc["other_twin"][k][0]) == bool(q["labels"][1]))
    return dict(accuracy=acc, gap_moved=moved, flips=d["flips"], other_flips=other, world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"])


print(json.dumps(dict(host=report(host_scores))), flush=True)
spec = plan["route"]
for seed in plan["seeds"]:
    for lam in LAMBDAS:
        route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(cands), steps=4, seed=seed, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
        named = training.trainable(route)
        opt = training.optimizer_for(named, 3e-4, 0.01)
        cfg = training.TrainConfig(seed=seed, updates=512, batch_size=32, learning_rate=3e-4, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
        penalties = []
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
                penalty = d2.square().mean()
                penalties.append(float(penalty.detach()))
                loss = loss + lam * penalty
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for _, p in named], 1.0)
            opt.step()
        evals = training.evaluate(route, held_bank).tolist()
        sc = {c: [evals[position[held[i, c]]] for i in qs_held] for c in CONDITIONS}
        tail = penalties[-64:]
        print(json.dumps(dict(seed=seed, lam=lam, **report(sc), penalty_last64=round(sum(tail) / len(tail), 4) if tail else None, seconds=round(time.time() - t))), flush=True)
