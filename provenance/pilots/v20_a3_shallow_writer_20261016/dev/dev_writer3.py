"""Dev check for V20 A3 (not evidence): what an autoencoding writer's slots carry, and
whether D1's route can read answers through them.

1. ICAE-style pretraining: the writer reads the facts' cut-16 states and writes S soft
   tokens at cut 0; the frozen host, reading them, reproduces the fact text
   (teacher-forced next-token loss), on train worlds 0-191 and generated training worlds.
2. Held-out memories (train worlds 192-255): the reproduction loss with the writer's
   slots, with norm-matched random slots and with no slots; and the accuracy of
   reproducing the entity tokens.
3. The writer frozen: the host answers questions after the slots (host alone), and D1's
   route is fitted on the host's final states at the question positions (worlds 0-191)
   and read on 192-255. Lane A's rule as written."""
import json, os, re, sys, time
from pathlib import Path

D, SLOTS, AE_STEPS, BIG = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
READ, WRITE, LR, SEED = 16, 0, 1e-3, 2026101741
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, availability, composition, training

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
big = [json.loads(l) for l in BIG.read_text().splitlines() if l.strip()]
_, big_memories = run.render(old, tokenizer, big, plan)


def encode(ids, cut):
    x = torch.tensor([ids], device="cuda")
    with torch.no_grad():
        return host.to_cut(x, torch.ones_like(x), cut)[0]


ae_ids = [m["ids"] for m in memories if m["world"] < 192 and m["key"] in ("intact", "twin")]
ae_ids += [m["ids"] for m in big_memories if m["key"] in ("intact", "twin")]
held_ids = [m["ids"] for m in memories if m["world"] >= 192 and m["key"] in ("intact", "twin")]
reference = torch.cat([encode(ids, WRITE).float()[1:] for ids in ae_ids[:64]])
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
    return writer(*batch_states(states_list))


def reproduce(ids_list, slots):
    """Per-row next-token loss on the fact text and entity-token accuracy."""
    text = [encode(ids, WRITE) for ids in ids_list]
    tq, tmask = batch_states(text)
    n_slots = 0 if slots is None else slots.shape[1]
    if slots is None:
        slots = tq[:, :0]
    smask = torch.ones(slots.shape[:2], dtype=torch.long, device="cuda")
    _, logits, _ = prefix(tq.to(torch.bfloat16), tmask, slots.to(torch.bfloat16), smask)
    losses, hits, total = [], 0, 0
    for r, ids in enumerate(ids_list):
        n = len(ids)
        if n_slots:
            pred = logits[r, n_slots - 1 : n_slots + n - 1].float()
            target = torch.tensor(ids, device="cuda")
        else:
            pred = logits[r, : n - 1].float()
            target = torch.tensor(ids[1:], device="cuda")
        losses.append(F.cross_entropy(pred, target))
        guess = pred.argmax(-1).tolist()
        offset = 0 if n_slots else 1
        for k, tok in enumerate(target.tolist()):
            piece = tokenizer.decode([tok]).strip()
            if piece[:1].isupper() and piece.isalpha() and piece not in ("World", "The"):
                hits += int(guess[k] == tok); total += 1
    return torch.stack(losses), hits, total


t = time.time()
g = torch.Generator().manual_seed(SEED)
for step in range(1, AE_STEPS + 1):
    idx = torch.randint(0, len(ae_ids), (8,), generator=g).tolist()
    ids_list = [ae_ids[k] for k in idx]
    slots = write([encode(ids, READ) for ids in ids_list])
    loss, _, _ = reproduce(ids_list, slots)
    loss = loss.mean()
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0)
    optimizer.step()
    if step % 500 == 0:
        print(json.dumps(dict(ae_step=step, loss=round(float(loss), 4), seconds=round(time.time() - t))), flush=True)
writer.eval()
report = {}
gen = torch.Generator().manual_seed(470016)
with torch.no_grad():
    for name in ("writer", "random", "none"):
        loss_sum, hits, total, count = 0.0, 0, 0, 0
        for start in range(0, len(held_ids), 16):
            chunk = held_ids[start : start + 16]
            slots = write([encode(ids, READ) for ids in chunk]) if name != "none" else None
            if name == "random":
                noise = torch.randn(slots.shape, generator=gen).to("cuda")
                slots = noise / noise.norm(dim=-1, keepdim=True) * slots.norm(dim=-1, keepdim=True)
            losses, h, n = reproduce(chunk, slots)
            loss_sum += float(losses.sum()); count += len(chunk); hits += h; total += n
        report[f"held_reproduction_{name}"] = dict(loss=round(loss_sum / count, 4), entity_accuracy=round(hits / max(total, 1), 3))
    print(json.dumps(report), flush=True)
    # questions after the slots
    captured = {}
    hook = base.lm_head.register_forward_hook(lambda module, inputs, output: captured.__setitem__("final", inputs[0]))
    q_states = {}
    rows = []
    for i, q in enumerate(questions):
        for side in (0, 1):
            rows.append((i, ("intact", "twin")[side], side))
        if q["world"] >= 192:
            rows += [(i, "random_intact", 0), (i, "random_twin", 1)]
    mem_reads = {}
    states, offsets, scores, meta = [], [0], [], []
    for i, cond, side in rows:
        q = questions[i]
        seg = q["world"] * keys + side
        if seg not in mem_reads:
            mem_reads[seg] = write([encode(memories[seg]["ids"], READ)])[0]
        slots = mem_reads[seg]
        if cond.startswith("random_"):
            noise = torch.randn(slots.shape, generator=gen).to("cuda")
            slots = noise / noise.norm(dim=-1, keepdim=True) * slots.norm(dim=-1, keepdim=True)
        if i not in q_states:
            q_states.clear(); q_states[i] = encode(q["prompt_ids"], WRITE)
        qs = q_states[i]
        ones = torch.ones(1, qs.shape[0], dtype=torch.long, device="cuda")
        final, logits, _ = prefix(qs[None], ones, slots[None].to(torch.bfloat16), torch.ones(1, slots.shape[0], dtype=torch.long, device="cuda"))
        states.append(final[0, slots.shape[0]:].cpu()); offsets.append(offsets[-1] + qs.shape[0])
        scores.append(logits[0, -1, cands].float().cpu())
        meta.append(dict(question=i, world=q["world"], cond=cond, label=q["labels"][side]))
    hook.remove()
hidden, offsets, base_logits = torch.cat(states), torch.tensor(offsets), torch.stack(scores)
held = {(m["question"], m["cond"]): k for k, m in enumerate(meta) if m["world"] >= 192}
qs_held = sorted({k[0] for k in held})
held_q = [questions[i] for i in qs_held]


def diag(score_rows):
    sc = {c: [score_rows[held[(i, c)]] for i in qs_held] for c in ("intact", "twin", "random_intact", "random_twin")}
    d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
    acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in sc}
    return dict(accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"])


report["host_after_slots"] = diag(base_logits.tolist())
train_idx = [k for k, m in enumerate(meta) if m["world"] < 192 and not m["cond"].startswith("random_")]
def bank(idx):
    seg = torch.tensor(idx)
    return training.FeatureBank(hidden, offsets, base_logits[seg], torch.tensor([meta[k]["label"] for k in idx]), torch.tensor([meta[k]["world"] for k in idx]), segments=seg)
spec = plan["route"]
route = composition.DeliberationRoute(spec["hidden_dim"], spec["vocab_size"], tuple(cands), steps=4, seed=plan["seeds"][0], workspace_dim=spec["workspace_dim"], heads=spec["attention_heads"], ff_multiplier=spec["ff_multiplier"], dropout=spec["dropout"], rank=spec["rank"], gate_init_bias=spec["gate_init_bias"])
cfg = training.TrainConfig(seed=plan["seeds"][0], updates=512, batch_size=32, learning_rate=3e-4, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
opt = training.optimizer_for(training.trainable(route), 3e-4, 0.01)
tb = bank(train_idx)
for step in range(1, 513):
    training.update(route, None, opt, tb, cfg, step)
report["route_after_slots"] = diag(training.evaluate(route, bank(list(range(len(meta))))).tolist())
report.update(slots=SLOTS, ae_steps=AE_STEPS, ae_data=len(ae_ids), seconds=round(time.time() - t))
print(json.dumps(report), flush=True)
