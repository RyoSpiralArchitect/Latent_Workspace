"""Dev check for V20 A2 option 2 (not evidence): can the host's upper half learn to read
a cut-16 memory prefix? LoRA on attention q/k/v/o of the layers after the cut; memory
states packed before the question's; trained on train worlds 0-191 (both sides);
lane A's flips read on train worlds 192-255. Dev and final are never touched."""
import json, math, os, sys, time
from pathlib import Path

D, F = Path(sys.argv[1]), Path(sys.argv[2])
RANK, LR, EPOCHS, SEED = int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_flip as run
from latent_workspace import DecoderHost, availability, composition

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
nn = torch.nn
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
base = old.engine._load_hf_model(old.engine.ModelConfig(**architecture["model"])).eval().requires_grad_(False).to("cuda")
torch.manual_seed(SEED)
gen = torch.Generator(device="cuda").manual_seed(SEED)


class LoRALinear(nn.Module):
    def __init__(self, inner, rank):
        super().__init__()
        self.inner = inner
        self.A = nn.Parameter(torch.randn(rank, inner.in_features, device="cuda", generator=gen) / math.sqrt(inner.in_features))
        self.B = nn.Parameter(torch.zeros(inner.out_features, rank, device="cuda"))
        self.scale = 2.0

    def forward(self, x):
        y = self.inner(x)
        return y + ((x.float() @ self.A.T) @ self.B.T * self.scale).to(y.dtype)


boundary = plan["memory_boundary"]
for layer in base.model.layers[boundary:]:
    for name in ("q_proj", "k_proj", "v_proj", "o_proj"):
        setattr(layer.self_attn, name, LoRALinear(getattr(layer.self_attn, name), RANK))
params = [p for n, p in base.named_parameters() if p.requires_grad]
print(json.dumps(dict(lora_parameters=sum(p.numel() for p in params))), flush=True)
host = DecoderHost(base)
tensors, rows = run.load_split(F, "train")
questions = rows["questions"]
keys = len(run.MEMORY_KEYS)
qo, mo = tensors["question_offsets"], tensors["memory_offsets"]
cands = plan["candidate_ids"]


def segment(states, offsets, s):
    return states[int(offsets[s]) : int(offsets[s + 1])]


def logits_for(items, memory_source=None):
    """items: (question index, memory segment or None); returns candidate logits [B, 2]."""
    qs = [segment(tensors["question_states"], qo, i) for i, _ in items]
    if memory_source is None:
        ms = [segment(tensors["memory_states"], mo, m) if m is not None else qs[0][:0] for _, m in items]
    else:
        ms = [memory_source(m) for _, m in items]
    width_q, width_m = max(q.shape[0] for q in qs), max(m.shape[0] for m in ms)
    H = qs[0].shape[1]
    hq = torch.zeros(len(items), width_q, H); mq = torch.zeros(len(items), width_q, dtype=torch.long)
    hm = torch.zeros(len(items), width_m, H); mm = torch.zeros(len(items), width_m, dtype=torch.long)
    for r, (q, m) in enumerate(zip(qs, ms)):
        hq[r, : q.shape[0]] = q.float(); mq[r, : q.shape[0]] = 1
        hm[r, : m.shape[0]] = m.float(); mm[r, : m.shape[0]] = 1
    packed, pmask = composition.pack_memory(hm, mm, hq, mq)
    packed, pmask = packed.to("cuda", torch.bfloat16), pmask.to("cuda")
    logits = host.from_cut(packed, pmask, boundary)
    last = pmask.sum(1) - 1
    return logits[torch.arange(len(items), device="cuda"), last][:, cands].float()


train = []
for i, q in enumerate(questions):
    if q["world"] < 192:
        for side in (0, 1):
            train.append((i, q["world"] * keys + side, q["labels"][side]))
optimizer = torch.optim.AdamW(params, lr=LR, weight_decay=0.0)
g = torch.Generator().manual_seed(SEED)
t = time.time()
step = 0
for epoch in range(EPOCHS):
    order = torch.randperm(len(train), generator=g).tolist()
    for start in range(0, len(order) - 15, 16):
        batch = [train[k] for k in order[start : start + 16]]
        out = logits_for([(i, m) for i, m, _ in batch])
        loss = torch.nn.functional.cross_entropy(out, torch.tensor([y for *_, y in batch], device="cuda"))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        optimizer.step()
        step += 1
        if step % 64 == 0:
            print(json.dumps(dict(step=step, loss=round(float(loss), 4), seconds=round(time.time() - t))), flush=True)
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
randoms = run.random_memory(torch, tensors, {"questions": [questions[i] for i in held]}, plan["random_memory_seed"])
states, bounds, position = randoms
scores = {}
with torch.no_grad():
    for name in ("intact", "twin", "random_intact", "random_twin", "none"):
        out = []
        for start in range(0, len(held), 32):
            chunk = held[start : start + 32]
            if name == "none":
                out.append(logits_for([(i, None) for i in chunk]))
            elif name.startswith("random_"):
                side = 0 if name == "random_intact" else 1
                src = lambda m: states[int(bounds[m]) : int(bounds[m + 1])]
                out.append(logits_for([(i, 2 * position[questions[i]["world"]] + side) for i in chunk], src))
            else:
                side = 0 if name == "intact" else 1
                out.append(logits_for([(i, questions[i]["world"] * keys + side) for i in chunk]))
        scores[name] = torch.cat(out).cpu().tolist()
held_q = [questions[i] for i in held]
d = availability.diagnose(run.contrasts_for(held_q, lambda c: scores[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
acc = {c: round(sum((s[1] > s[0]) == bool(q["labels"][1 if c in ("twin", "random_twin") else 0]) for s, q in zip(scores[c], held_q)) / len(held_q), 3) for c in scores}
print(json.dumps(dict(rank=RANK, lr=LR, epochs=EPOCHS, steps=step, seconds=round(time.time() - t), held_accuracy=acc, flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"], peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2))), flush=True)
