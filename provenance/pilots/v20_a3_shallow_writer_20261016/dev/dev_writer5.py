"""Dev check for V20 A3 (not evidence): a compact memory plus a host that learns to read it.

As dev_writer4 (ICAE-style warm start, then distillation from the host reading the fact
text), but LoRA on attention q/k/v/o of every host layer is trained together with the
writer: the gisting setup, where the host learns to use compressed tokens. The teacher
is the host with LoRA switched off. The answer cross-entropy on both sides is added.

Teacher: the frozen host reading the fact text before the question (the depth ladder's
cut 0, which met lane A's endpoint). Student: the same host reading S soft tokens that
the writer wrote from the facts' cut-16 states. The writer, warm-started by ICAE-style
autoencoding, is trained so that the student's answer distribution and final states at
the question positions match the teacher's (KL plus cosine). Training uses train worlds
0-191 and generated training worlds (no labels needed); lane A's flips are read on
train worlds 192-255 for the student, the teacher and random slots."""
import json, os, sys, time
from pathlib import Path

D, SLOTS, AE_STEPS, KD_STEPS, BIG = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), Path(sys.argv[5])
STATE_WEIGHT = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0
SEED = int(sys.argv[7]) if len(sys.argv) > 7 else 2026101751
READ, WRITE, LR = 16, 0, 1e-3
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
RANK = int(sys.argv[8]) if len(sys.argv) > 8 else 16


class LoRALinear(nn.Module):
    enabled = True

    def __init__(self, inner, rank, generator):
        super().__init__()
        self.inner = inner
        self.A = nn.Parameter(torch.randn(rank, inner.in_features, device="cuda", generator=generator) / inner.in_features**0.5)
        self.B = nn.Parameter(torch.zeros(inner.out_features, rank, device="cuda"))

    def forward(self, x):
        y = self.inner(x)
        if not LoRALinear.enabled:
            return y
        return y + ((x.float() @ self.A.T) @ self.B.T * 2.0).to(y.dtype)


lora_gen = torch.Generator(device="cuda").manual_seed(7)
for layer in base.model.layers:
    for name in ("q_proj", "k_proj", "v_proj", "o_proj"):
        setattr(layer.self_attn, name, LoRALinear(getattr(layer.self_attn, name), RANK, lora_gen))
lora_params = [p for n, p in base.named_parameters() if p.requires_grad]
host = DecoderHost(base)
prefix = composition.CutPrefixRoute(host, WRITE)
records = run.v19().load_records(plan)["train"]
questions, memories = run.render(old, tokenizer, records, plan)
big = [json.loads(l) for l in BIG.read_text().splitlines() if l.strip()]
big_questions, big_memories = run.render(old, tokenizer, big, plan)
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]


def encode(ids, cut):
    x = torch.tensor([ids], device="cuda")
    with torch.no_grad():
        return host.to_cut(x, torch.ones_like(x), cut)[0]


# (question ids, memory ids, label) pools for distillation and evaluation
def pool(qs, ms, worlds):
    out = []
    for i, q in enumerate(qs):
        if q["world"] in worlds:
            for side in (0, 1):
                out.append((q["prompt_ids"], ms[q["world"] * keys + side]["ids"], q["labels"][side]))
    return out


kd_pool = pool(questions, memories, set(range(192))) + pool(big_questions, big_memories, set(range(len(big))))
ae_ids = [m["ids"] for m in memories if m["world"] < 192 and m["key"] in ("intact", "twin")]
ae_ids += [m["ids"] for m in big_memories if m["key"] in ("intact", "twin")]
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
lora_optimizer = torch.optim.AdamW(lora_params, lr=2e-4, weight_decay=0.0)


def batch_states(states_list):
    width = max(s.shape[0] for s in states_list)
    out = torch.zeros(len(states_list), width, states_list[0].shape[1], device="cuda")
    mask = torch.zeros(len(states_list), width, dtype=torch.long, device="cuda")
    for r, s in enumerate(states_list):
        out[r, : s.shape[0]] = s.float(); mask[r, : s.shape[0]] = 1
    return out, mask


def write(memory_ids_list):
    return writer(*batch_states([encode(ids, READ) for ids in memory_ids_list]))


def read(question_ids_list, memory_states, memory_mask):
    """Host final states at the question positions and candidate logits at the last one."""
    qs, qmask = batch_states([encode(ids, WRITE) for ids in question_ids_list])
    final, logits, packed = prefix(qs.to(torch.bfloat16), qmask, memory_states.to(torch.bfloat16), memory_mask)
    lengths_m = memory_mask.sum(1)
    rows = torch.arange(len(question_ids_list), device="cuda")
    last = packed.sum(1) - 1
    q_states = [final[r, int(lengths_m[r]) : int(lengths_m[r]) + int(qmask[r].sum())].float() for r in range(len(question_ids_list))]
    return q_states, logits[rows, last][:, cands].float()


t = time.time()
g = torch.Generator().manual_seed(SEED)
LoRALinear.enabled = False
for step in range(1, AE_STEPS + 1):
    idx = torch.randint(0, len(ae_ids), (8,), generator=g).tolist()
    ids_list = [ae_ids[k] for k in idx]
    slots = write(ids_list)
    tq, tmask = batch_states([encode(ids, WRITE) for ids in ids_list])
    _, logits, _ = prefix(tq.to(torch.bfloat16), tmask, slots.to(torch.bfloat16), torch.ones(slots.shape[:2], dtype=torch.long, device="cuda"))
    loss = torch.stack([F.cross_entropy(logits[r, SLOTS - 1 : SLOTS + len(ids) - 1].float(), torch.tensor(ids, device="cuda")) for r, ids in enumerate(ids_list)]).mean()
    optimizer.zero_grad(set_to_none=True); loss.backward(); torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0); optimizer.step()
    if step % 1000 == 0:
        print(json.dumps(dict(ae_step=step, loss=round(float(loss), 4), seconds=round(time.time() - t))), flush=True)
for step in range(1, KD_STEPS + 1):
    idx = torch.randint(0, len(kd_pool), (8,), generator=g).tolist()
    batch = [kd_pool[k] for k in idx]
    LoRALinear.enabled = False
    with torch.no_grad():
        text, tmask = batch_states([encode(m, WRITE) for _, m, _ in batch])
        teacher_states, teacher_logits = read([q for q, _, _ in batch], text, tmask)
    LoRALinear.enabled = True
    slots = write([m for _, m, _ in batch])
    student_states, student_logits = read([q for q, _, _ in batch], slots, torch.ones(slots.shape[:2], dtype=torch.long, device="cuda"))
    kd = F.kl_div(F.log_softmax(student_logits, -1), F.softmax(teacher_logits, -1), reduction="batchmean")
    cos = torch.stack([1 - F.cosine_similarity(s, t_, dim=-1).mean() for s, t_ in zip(student_states, teacher_states)]).mean()
    ce = F.cross_entropy(student_logits, torch.tensor([y for _, _, y in batch], device="cuda"))
    loss = kd + STATE_WEIGHT * cos + ce
    optimizer.zero_grad(set_to_none=True); lora_optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(writer.parameters(), 1.0); torch.nn.utils.clip_grad_norm_(lora_params, 1.0)
    optimizer.step(); lora_optimizer.step()
    if step % 500 == 0:
        print(json.dumps(dict(kd_step=step, kl=round(float(kd), 4), cos=round(float(cos), 4), seconds=round(time.time() - t))), flush=True)
writer.eval()
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
held_q = [questions[i] for i in held]
gen = torch.Generator().manual_seed(470016)
scores = {"student": {}, "teacher": {}}
with torch.no_grad():
    for name in ("intact", "twin", "random_intact", "random_twin"):
        side = 1 if name.endswith("twin") else 0
        s_out, t_out = [], []
        for start in range(0, len(held), 16):
            chunk = held[start : start + 16]
            mids = [memories[questions[i]["world"] * keys + side]["ids"] for i in chunk]
            qids = [questions[i]["prompt_ids"] for i in chunk]
            slots = write(mids)
            if name.startswith("random_"):
                noise = torch.randn(slots.shape, generator=gen).to("cuda")
                slots = noise / noise.norm(dim=-1, keepdim=True) * slots.norm(dim=-1, keepdim=True)
                LoRALinear.enabled = True
                s_out.append(read(qids, slots, torch.ones(slots.shape[:2], dtype=torch.long, device="cuda"))[1])
                t_out.append(s_out[-1])
            else:
                LoRALinear.enabled = True
                s_out.append(read(qids, slots, torch.ones(slots.shape[:2], dtype=torch.long, device="cuda"))[1])
                LoRALinear.enabled = False
                text, tmask = batch_states([encode(m, WRITE) for m in mids])
                t_out.append(read(qids, text, tmask)[1])
        scores["student"][name] = torch.cat(s_out).cpu().tolist()
        scores["teacher"][name] = torch.cat(t_out).cpu().tolist()
report = dict(slots=SLOTS, ae_steps=AE_STEPS, kd_steps=KD_STEPS, kd_pool=len(kd_pool), state_weight=STATE_WEIGHT, lora_rank=RANK, lora_parameters=sum(p.numel() for p in lora_params))
for who in ("student", "teacher"):
    sc = scores[who]
    d = availability.diagnose(availability.contrasts(held_q, lambda c: sc[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
    acc = {c: round(sum((x[1] > x[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for x, q in zip(sc[c], held_q)) / len(held_q), 3) for c in sc}
    report[who] = dict(accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"])
report["seconds"] = round(time.time() - t)
print(json.dumps(report), flush=True)
