"""Dev check for V20 A2 (not evidence): retrieval supervision during training only.

For hop-1 questions, the answer position's step-0 attention is pulled toward the
memory line naming both question entities (cross-entropy on the attention mass of
that line), added to the answer loss. Evaluation never uses it. Train worlds
0-191 (both sides) fit; lane A's flips read on train worlds 192-255."""
import json, math, os, re, sys, time
from pathlib import Path

D, F = Path(sys.argv[1]), Path(sys.argv[2])
LR, UPDATES, LAMBDA, SEED = float(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), int(sys.argv[6])
EXTRA = Path(sys.argv[7]) if len(sys.argv) > 7 else None  # optional generated-world features
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import torch
import torch.nn.functional as Fn

torch.set_num_threads(8)
torch.use_deterministic_algorithms(True)
import run_v20_a2_flip as run
from latent_workspace import availability, composition, training

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
tokenizer = old.engine.load_tokenizer(old.engine.ModelConfig(**architecture["model"]))
NAME = re.compile(r"- (\w+) is ranked above (\w+)\.")
keys = len(run.MEMORY_KEYS)


def spans_for(rows):
    """Per memory row: {frozenset(entities): (start, end)} over its fact lines."""
    result = []
    for m in rows["memories"]:
        pieces = [tokenizer.decode([i]) for i in m["ids"]]
        lines, start, text = {}, 0, ""
        for pos, piece in enumerate(pieces):
            if "\n" in piece or pos == len(pieces) - 1:
                end = pos + 1
                found = NAME.search(tokenizer.decode(m["ids"][start:end]))
                if found:
                    lines[frozenset(found.groups())] = (start, end)
                start = end
        result.append(lines)
    return result


def load(folder):
    tensors, rows = run.load_split(folder, "train")
    return tensors, rows, spans_for(rows)


def entities(question):
    found = re.search(r"Is (\w+) ranked above (\w+)\?", question)
    return frozenset(found.groups()) if found else None


sets = [load(F)]
if EXTRA is not None:
    sets.append(load(EXTRA))
records = run.v19().load_records(plan)["train"]


def train_rows(tensors, rows, spans, worlds, source_records):
    """(question segment, memory segment, label, world, span or None) for both sides."""
    out = []
    by_world = {}
    for i, q in enumerate(rows["questions"]):
        by_world.setdefault(q["world"], []).append(i)
    for w in worlds:
        record = source_records[w]
        for side in (0, 1):
            for i in by_world[w]:
                q = rows["questions"][i]
                memory = w * keys + side
                span = None
                if q["hop"] == 1:
                    span = spans[memory].get(entities(record["queries"][q["query"]]))
                out.append((i, memory, q["labels"][side], w, span))
    return out


big_records = None
if EXTRA is not None:
    big_records = [json.loads(l) for l in (EXTRA.parent / "functional_train_big.jsonl").read_text().splitlines() if l.strip()]
train = [(0, r) for r in train_rows(*sets[0], range(0, 192), records)]
if EXTRA is not None:
    train += [(1, r) for r in train_rows(*sets[1], range(len(big_records)), big_records)]
print(json.dumps(dict(rows=len(train), supervised=sum(r[1][4] is not None for r in train))), flush=True)


def gather(states, offsets, segments):
    lengths = [int(offsets[s + 1] - offsets[s]) for s in segments]
    width = max(lengths)
    values = torch.zeros(len(segments), width, states.shape[1])
    mask = torch.zeros(len(segments), width, dtype=torch.long)
    for row, (s, n) in enumerate(zip(segments, lengths)):
        values[row, :n] = states[int(offsets[s]) : int(offsets[s]) + n].float()
        mask[row, :n] = 1
    return values, mask


def batch(items):
    hidden, mask, memory, memory_mask = [], [], [], []
    parts = {}
    for k, (source, (qi, mi, label, w, span)) in enumerate(items):
        parts.setdefault(source, []).append(k)
    order = [None] * len(items)
    hs, ms, mems, mms = [None] * len(items), [None] * len(items), [None] * len(items), [None] * len(items)
    for source, idx in parts.items():
        tensors = sets[source][0]
        h, m = gather(tensors["question_states"], tensors["question_offsets"], [items[k][1][0] for k in idx])
        mm, mmm = gather(tensors["memory_states"], tensors["memory_offsets"], [items[k][1][1] for k in idx])
        for j, k in enumerate(idx):
            hs[k], ms[k], mems[k], mms[k] = h[j], m[j], mm[j], mmm[j]
    def stack(values, masks):
        width = max(v.shape[0] for v in values)
        out = torch.zeros(len(values), width, values[0].shape[1])
        msk = torch.zeros(len(values), width, dtype=torch.long)
        for r, (v, mk) in enumerate(zip(values, masks)):
            n = int(mk.sum())
            out[r, :n] = v[:n]
            msk[r, :n] = 1
        return out, msk
    h, m = stack(hs, ms)
    mem, mm = stack(mems, mms)
    base = torch.stack([sets[s][0]["base_logits"][qi] for s, (qi, *_rest) in items])
    labels = torch.tensor([r[2] for _, r in items])
    spans = [r[4] for _, r in items]
    return h, m, mem, mm, base, labels, spans


def retrieval_loss(route, h, m, mem, mm, spans):
    packed, pmask = composition.pack_memory(mem, mm, h, m)
    lat = route.lattice
    anchor = lat.input_projection(lat.input_norm(packed))
    att_in = lat.attention_norm(anchor) + lat.step_embeddings[0].view(1, 1, -1)
    B, L, W = att_in.shape
    heads = lat.attention.heads
    qkv = lat.attention.qkv(att_in).view(B, L, 3, heads, W // heads)
    q, k = qkv[:, :, 0], qkv[:, :, 1]
    last = pmask.sum(1) - 1
    rows = torch.arange(B)
    scores = torch.einsum("bhd,blhd->bhl", q[rows, last], k) / math.sqrt(W // heads)
    scores = scores.masked_fill(~pmask.bool()[:, None, :], float("-inf"))
    logp = scores.log_softmax(-1)
    losses = []
    for r, span in enumerate(spans):
        if span is not None:
            losses.append(-torch.logsumexp(logp[r, :, span[0] : span[1]], -1).mean())
    return torch.stack(losses).mean() if losses else torch.zeros(())


spec = plan["route"]
route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(plan["candidate_ids"]), steps=spec["steps"], seed=SEED, workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
named = training.trainable(route)
opt = training.optimizer_for(named, LR, 0.01)
per_epoch = len(train) // 32
t = time.time()
curve = []
for step in range(1, UPDATES + 1):
    route.train()
    torch.manual_seed(training.component_seed(SEED, f"step{step}"))
    epoch, offset = divmod(step - 1, per_epoch)
    order = training.epoch_order(SEED, epoch, len(train))
    items = [train[i] for i in order[offset * 32 : (offset + 1) * 32]]
    h, m, mem, mm, base, labels, spans = batch(items)
    delta, _, _, _ = route(h, m, mem, mm)
    task = Fn.cross_entropy(base + delta, labels)
    aux = retrieval_loss(route, h, m, mem, mm, spans) if LAMBDA else torch.zeros(())
    total = task + LAMBDA * aux
    opt.zero_grad(set_to_none=True)
    total.backward()
    torch.nn.utils.clip_grad_norm_([p for _, p in named], 1.0)
    opt.step()
    if step % (UPDATES // 8) == 0:
        curve.append((step, round(float(task), 3), round(float(aux), 3)))
        print(json.dumps(dict(step=step, task=round(float(task), 4), aux=round(float(aux), 4), seconds=round(time.time() - t))), flush=True)
tensors, rows, _ = sets[0]
questions = rows["questions"]
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
randoms = run.random_memory(torch, tensors, {"questions": [questions[i] for i in held]}, plan["random_memory_seed"])


def condition(name):
    seg = torch.tensor(held)
    bank = training.FeatureBank(tensors["question_states"], tensors["question_offsets"], tensors["base_logits"][seg], torch.tensor([questions[i]["labels"][0] for i in held]), torch.tensor([questions[i]["world"] for i in held]), segments=seg)
    if name.startswith("random_"):
        states, bounds, position = randoms
        side = 0 if name == "random_intact" else 1
        return bank.with_memory((states, bounds, torch.tensor([2 * position[questions[i]["world"]] + side for i in held])))
    side = 0 if name == "intact" else 1
    return bank.with_memory((tensors["memory_states"], tensors["memory_offsets"], torch.tensor([questions[i]["world"] * keys + side for i in held])))


scores = {c: training.evaluate(route, condition(c)).tolist() for c in ("intact", "twin", "random_intact", "random_twin")}
held_q = [questions[i] for i in held]
d = availability.diagnose(run.contrasts_for(held_q, lambda c: scores[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
acc = {c: round(sum((s[1] > s[0]) == bool(q["labels"][0 if c in ("intact", "random_intact") else 1]) for s, q in zip(scores[c], held_q)) / len(held_q), 3) for c in scores}
print(json.dumps(dict(lr=LR, updates=UPDATES, lam=LAMBDA, seed=SEED, extra=EXTRA is not None, curve=curve, held_accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"])), flush=True)
