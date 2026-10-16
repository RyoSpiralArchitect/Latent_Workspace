"""Dev check for V20 A3 (not evidence): a learned writer, trained through the frozen host.

A small writer reads the facts' host states at cut READ and writes S slots into the
host's residual space; the slots enter at cut WRITE before the question, the frozen
host continues, and its own answer logits train the writer (cross-entropy on both
sides). Train worlds 0-191 fit; lane A's flips are read on 192-255."""
import json, math, os, sys, time
from pathlib import Path

D, READ, WRITE, SLOTS, LR, EPOCHS = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), int(sys.argv[6])
SEED = 2026101721
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


memory_states = [encode(m["ids"], READ) for m in memories]
question_states = [encode(q["prompt_ids"], WRITE) for q in questions]
reference = [encode(m["ids"], WRITE).float() for m in memories[:64]]
target_norm = float(torch.cat(reference).norm(dim=-1).median())


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


def batch_states(segments, states):
    width = max(states[s].shape[0] for s in segments)
    out = torch.zeros(len(segments), width, states[0].shape[1], device="cuda")
    mask = torch.zeros(len(segments), width, dtype=torch.long, device="cuda")
    for r, s in enumerate(segments):
        n = states[s].shape[0]
        out[r, :n] = states[s].float(); mask[r, :n] = 1
    return out, mask


def answer(qi, memory_segments, slots=None):
    mem, mmask = batch_states(memory_segments, memory_states)
    if slots is None:
        slots = writer(mem, mmask)
    smask = torch.ones(slots.shape[:2], dtype=torch.long, device="cuda")
    qs, qmask = batch_states(qi, question_states)
    _, logits, packed = prefix(qs.to(torch.bfloat16), qmask, slots.to(torch.bfloat16), smask)
    last = packed.sum(1) - 1
    return logits[torch.arange(len(qi), device="cuda"), last][:, cands].float()


train = [(i, q["world"] * keys + side, q["labels"][side]) for i, q in enumerate(questions) if q["world"] < 192 for side in (0, 1)]
g = torch.Generator().manual_seed(SEED)
t = time.time()
step = 0
for epoch in range(EPOCHS):
    order = torch.randperm(len(train), generator=g).tolist()
    for start in range(0, len(order) - 7, 8):
        batch = [train[k] for k in order[start : start + 8]]
        writer.train()
        out = answer([b[0] for b in batch], [b[1] for b in batch])
        loss = F.cross_entropy(out, torch.tensor([b[2] for b in batch], device="cuda"))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0)
        optimizer.step()
        step += 1
        if step % 128 == 0:
            print(json.dumps(dict(step=step, loss=round(float(loss), 4), seconds=round(time.time() - t))), flush=True)
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
            segs = [questions[i]["world"] * keys + side for i in chunk]
            if name.startswith("random_"):
                mem, mmask = batch_states(segs, memory_states)
                real = writer(mem, mmask)
                noise = torch.randn(real.shape, generator=gen).to("cuda")
                rnd = noise / noise.norm(dim=-1, keepdim=True) * real.norm(dim=-1, keepdim=True)
                out.append(answer(chunk, segs, slots=rnd))
            else:
                out.append(answer(chunk, segs))
        scores[name] = torch.cat(out).cpu().tolist()
d = availability.diagnose(availability.contrasts(held_q, lambda c: scores[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(scores[c], held_q)) / len(held_q), 3) for c in scores}
print(json.dumps(dict(read=READ, write=WRITE, slots=SLOTS, lr=LR, epochs=EPOCHS, steps=step, target_norm=round(target_norm, 2), seconds=round(time.time() - t), accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected=d["unaffected_prediction_changes"], peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2))), flush=True)
