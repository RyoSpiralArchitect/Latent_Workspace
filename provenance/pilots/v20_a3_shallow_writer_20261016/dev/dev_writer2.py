"""Dev check for V20 A3 (not evidence): writer objectives that a content-free shift
cannot satisfy. PAIR: answer loss plus a pairwise term asking the gap under intact
memory minus the gap under twin memory to point to the intact answer (affected
questions). AE (ICAE-style): first train the writer so that the frozen host, reading
the slots, reproduces the fact text (teacher-forced next-token loss), on training worlds
plus generated training worlds; then the PAIR objective. Train worlds 0-191 (and the
generated ones for AE) fit; lane A's flips are read on train worlds 192-255."""
import json, math, os, sys, time
from pathlib import Path

D, MODE, READ, WRITE, SLOTS, LR, EPOCHS, AE_STEPS = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6]), int(sys.argv[7]), int(sys.argv[8])
BIG = Path(sys.argv[9]) if len(sys.argv) > 9 else None
SEED = 2026101731
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, availability, composition

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
nn = torch.nn
F = torch.nn.functional
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
config = old.engine.ModelConfig(**architecture["model"])
tokenizer = old.engine.load_tokenizer(config)
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
host = DecoderHost(base)
prefix = composition.CutPrefixRoute(host, WRITE)
records = run.v19().load_records(plan)["train"]
questions, memories = run.render(old, tokenizer, records, plan)
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]


def encode(ids, cut):
    x = torch.tensor([ids], device="cuda")
    with torch.no_grad():
        return host.to_cut(x, torch.ones_like(x), cut)[0]


memory_ids = [m["ids"] for m in memories]
if BIG is not None and MODE == "ae":
    big = [json.loads(l) for l in BIG.read_text().splitlines() if l.strip()]
    _, big_memories = run.render(old, tokenizer, big, plan)
    ae_ids = [m["ids"] for k, m in enumerate(memories) if m["world"] < 192 and m["key"] in ("intact", "twin")]
    ae_ids += [m["ids"] for m in big_memories if m["key"] in ("intact", "twin")]
else:
    ae_ids = [m["ids"] for m in memories if m["world"] < 192 and m["key"] in ("intact", "twin")]
memory_states = [encode(ids, READ) for ids in memory_ids]
question_states = [encode(q["prompt_ids"], WRITE) for q in questions]
reference = torch.cat([encode(ids, WRITE).float()[1:] for ids in memory_ids[:64]])
target_norm = float(reference.norm(dim=-1).median())


class SlotWriter(nn.Module):
    def __init__(self, host_dim, slots, width=256, heads=8):
        super().__init__()
        self.norm = nn.LayerNorm(host_dim)
        self.inp = nn.Linear(host_dim, width)
        self.queries = nn.Parameter(torch.randn(slots, width) * 0.02)
        self.attn = nn.MultiheadAttention(width, heads, batch_first=True)
        self.ff = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, 2 * width), nn.GELU(), nn.Linear(2 * width, width))
        self.out = nn.Linear(width, host_dim)
        self.scale = nn.Parameter(torch.tensor(target_norm))

    def forward(self, memory, mask):
        x = self.inp(self.norm(memory))
        q = self.queries.expand(memory.shape[0], -1, -1)
        attended, _ = self.attn(q, x, x, key_padding_mask=~mask.bool())
        h = q + attended
        h = h + self.ff(h)
        slots = self.out(h)
        return slots / slots.norm(dim=-1, keepdim=True).clamp_min(1e-6) * self.scale


torch.manual_seed(SEED)
writer = SlotWriter(host.hidden_size, SLOTS).to("cuda")
optimizer = torch.optim.AdamW(writer.parameters(), lr=LR, weight_decay=0.01)


def batch_states(states_list):
    width = max(s.shape[0] for s in states_list)
    out = torch.zeros(len(states_list), width, states_list[0].shape[1], device="cuda")
    mask = torch.zeros(len(states_list), width, dtype=torch.long, device="cuda")
    for r, s in enumerate(states_list):
        out[r, : s.shape[0]] = s.float(); mask[r, : s.shape[0]] = 1
    return out, mask


def write(states_list):
    mem, mmask = batch_states(states_list)
    return writer(mem, mmask)


def answer(qi, slots):
    smask = torch.ones(slots.shape[:2], dtype=torch.long, device="cuda")
    qs, qmask = batch_states([question_states[i] for i in qi])
    _, logits, packed = prefix(qs.to(torch.bfloat16), qmask, slots.to(torch.bfloat16), smask)
    last = packed.sum(1) - 1
    return logits[torch.arange(len(qi), device="cuda"), last][:, cands].float()


t = time.time()
log = []
g = torch.Generator().manual_seed(SEED)
if MODE == "ae":
    ae_states = None  # encoded lazily per batch at READ
    for step in range(1, AE_STEPS + 1):
        idx = torch.randint(0, len(ae_ids), (8,), generator=g).tolist()
        ids_list = [ae_ids[k] for k in idx]
        reads = [encode(ids, READ) for ids in ids_list]
        slots = write(reads)
        text = [encode(ids, WRITE) for ids in ids_list]
        tq, tmask = batch_states(text)
        smask = torch.ones(slots.shape[:2], dtype=torch.long, device="cuda")
        _, logits, packed = prefix(tq.to(torch.bfloat16), tmask, slots.to(torch.bfloat16), smask)
        losses = []
        for r, ids in enumerate(ids_list):
            n = len(ids)
            pred = logits[r, SLOTS - 1 : SLOTS + n - 1].float()  # last slot predicts token 0, ...
            losses.append(F.cross_entropy(pred, torch.tensor(ids, device="cuda")))
        loss = torch.stack(losses).mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0)
        optimizer.step()
        if step % 200 == 0:
            log.append(("ae", step, round(float(loss), 4)))
            print(json.dumps(dict(ae_step=step, loss=round(float(loss), 4), seconds=round(time.time() - t))), flush=True)
pairs = [(i, q["world"]) for i, q in enumerate(questions) if q["world"] < 192]
step = 0
for epoch in range(EPOCHS):
    order = torch.randperm(len(pairs), generator=g).tolist()
    for start in range(0, len(order) - 3, 4):
        chosen = [pairs[k] for k in order[start : start + 4]]
        qi = [i for i, _ in chosen] * 2
        segs = [w * keys + 0 for _, w in chosen] + [w * keys + 1 for _, w in chosen]
        labels = [questions[i]["labels"][0] for i, _ in chosen] + [questions[i]["labels"][1] for i, _ in chosen]
        slots = write([memory_states[s] for s in segs])
        out = answer(qi, slots)
        ce = F.cross_entropy(out, torch.tensor(labels, device="cuda"))
        gaps = out[:, 1] - out[:, 0]
        pair_terms = []
        for k, (i, _) in enumerate(chosen):
            q = questions[i]
            if q["affected"]:
                sign = 2 * q["labels"][0] - 1
                pair_terms.append(F.softplus(-sign * (gaps[k] - gaps[k + 4])))
        loss = ce + (torch.stack(pair_terms).mean() if pair_terms else 0.0)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0)
        optimizer.step()
        step += 1
        if step % 256 == 0:
            print(json.dumps(dict(step=step, ce=round(float(ce), 4), seconds=round(time.time() - t))), flush=True)
writer.eval()
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
held_q = [questions[i] for i in held]
scores = {}
gen = torch.Generator().manual_seed(470016)
with torch.no_grad():
    for name in ("intact", "twin", "random_intact", "random_twin"):
        side = 1 if name.endswith("twin") else 0
        out = []
        for start in range(0, len(held), 16):
            chunk = held[start : start + 16]
            slots = write([memory_states[questions[i]["world"] * keys + side] for i in chunk])
            if name.startswith("random_"):
                noise = torch.randn(slots.shape, generator=gen).to("cuda")
                slots = noise / noise.norm(dim=-1, keepdim=True) * slots.norm(dim=-1, keepdim=True)
            out.append(answer(chunk, slots))
        scores[name] = torch.cat(out).cpu().tolist()
d = availability.diagnose(availability.contrasts(held_q, lambda c: scores[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(scores[c], held_q)) / len(held_q), 3) for c in scores}
print(json.dumps(dict(mode=MODE, read=READ, write=WRITE, slots=SLOTS, lr=LR, epochs=EPOCHS, ae_steps=AE_STEPS, ae_data=len(ae_ids), steps=step, seconds=round(time.time() - t), accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected=d["unaffected_prediction_changes"], peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2))), flush=True)
