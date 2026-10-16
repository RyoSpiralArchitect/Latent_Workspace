"""Dev check (not evidence): memory injected at a shallow cut, host final states captured.
For every train-split row (world, side, question): memory and question each run alone to
cut k, are packed (memory first), and the host continues; the states entering the frozen
head and the two candidate logits are stored. Worlds 192-255 also with random memory.
Dev and final are never touched."""
import json, os, sys, time
from pathlib import Path

D, F, OUT, CUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_flip as run
from latent_workspace import DecoderHost
from safetensors.torch import save_file

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
OUT.mkdir(parents=True, exist_ok=False)
t = time.time()
states, offsets, base_rows, meta = [], [0], [], []
with torch.no_grad():
    def encode(ids):
        x = torch.tensor([ids], device="cuda")
        return host.to_cut(x, torch.ones_like(x), CUT)[0]
    mem_cache = {}
    def memory(segment):
        if segment not in mem_cache:
            mem_cache[segment] = encode(memories[segment]["ids"])
        return mem_cache[segment]
    q_cache = {}
    plan_rows = []
    for i, q in enumerate(questions):
        for side in (0, 1):
            plan_rows.append((i, side, "own"))
        if q["world"] >= 192:
            for side in (0, 1):
                plan_rows.append((i, side, "random"))
    for n, (i, side, kind) in enumerate(plan_rows):
        q = questions[i]
        m = memory(q["world"] * keys + side)
        if kind == "random":
            g = torch.Generator().manual_seed(470016 + q["world"] * 2 + side)
            r = torch.randn(m.shape, generator=g).to(m.device, m.dtype)
            m = r * (m.float().norm() / r.float().norm()).to(m.dtype)
        if i not in q_cache:
            q_cache.clear()
            q_cache[i] = encode(q["prompt_ids"])
        x = torch.cat([m, q_cache[i]])[None]
        logits = host.from_cut(x, torch.ones(x.shape[:2], dtype=torch.long, device="cuda"), CUT)
        states.append(captured["final"][0].cpu())
        offsets.append(offsets[-1] + x.shape[1])
        base_rows.append(logits[0, -1, cands].float().cpu())
        meta.append(dict(question=i, world=q["world"], query=q["query"], side=side, kind=kind, label=q["labels"][side], labels=q["labels"], affected=q["affected"], memory_length=int(m.shape[0])))
        if n % 1024 == 0:
            print(json.dumps(dict(row=n, of=len(plan_rows), seconds=round(time.time() - t))), flush=True)
save_file({"hidden": torch.cat(states).contiguous(), "offsets": torch.tensor(offsets), "base_logits": torch.stack(base_rows)}, str(OUT / "FEATURES.safetensors"))
run.ex.write_gz(OUT / "ROWS.json.gz", meta)
print(json.dumps(dict(cut=CUT, rows=len(meta), seconds=round(time.time() - t), bytes=(OUT / "FEATURES.safetensors").stat().st_size)), flush=True)
