"""Dev probe (not evidence): how deep can a separately encoded memory be injected and still
be read by the frozen host? For cut k, memory and question are each run alone through
layers below k; their states are packed (memory first) and the host continues from k.
No training. Train-split worlds 192-255 only; dev and final are never touched."""
import json, os, sys, time
from pathlib import Path

D, F = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_flip as run
from latent_workspace import DecoderHost, availability

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
base = old.engine._load_hf_model(old.engine.ModelConfig(**architecture["model"])).eval().requires_grad_(False).to("cuda")
host = DecoderHost(base)
rows = run.ex.read_gz(F / "ROWS_train.json.gz")
questions, memories = rows["questions"], rows["memories"]
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
held_q = [questions[i] for i in held]
results = {}
t = time.time()
with torch.no_grad():
    for cut in (0, 4, 8, 12, 16):
        def encode(ids):
            x = torch.tensor([ids], device="cuda")
            return host.to_cut(x, torch.ones_like(x), cut)[0]
        cache = {}
        def memory(segment):
            if segment not in cache:
                cache[segment] = encode(memories[segment]["ids"])
            return cache[segment]
        scores = {}
        for name in ("intact", "twin", "random_intact", "random_twin"):
            out = []
            for i in held:
                q = questions[i]
                side = 1 if name.endswith("twin") else 0
                m = memory(q["world"] * keys + side)
                if name.startswith("random_"):
                    g = torch.Generator().manual_seed(470016 + q["world"] * 2 + side)
                    r = torch.randn(m.shape, generator=g).to(m.device, m.dtype)
                    m = r * (m.float().norm() / r.float().norm()).to(m.dtype)
                x = torch.cat([m, encode(q["prompt_ids"])])[None]
                logits = host.from_cut(x, torch.ones(x.shape[:2], dtype=torch.long, device="cuda"), cut)
                out.append(logits[0, -1, cands].float().cpu().tolist())
            scores[name] = out
        d = availability.diagnose(run.contrasts_for(held_q, lambda c: scores[c], ("actual", "random_pair")), plan["endpoints"]["rule"])
        acc = {c: round(sum((s[1] > s[0]) == bool(q["labels"][1 if c.endswith("twin") else 0]) for s, q in zip(scores[c], held_q)) / len(held_q), 3) for c in scores}
        aff = [k for k, q in enumerate(held_q) if q["affected"]]
        results[cut] = dict(accuracy=acc, affected_accuracy_intact=round(sum((scores["intact"][k][1] > scores["intact"][k][0]) == bool(held_q[k]["labels"][0]) for k in aff) / len(aff), 3), flips=d["flips"], world_sign=d["world_sign"], p=d["sign_test_p"], verdict=d["verdict"], unaffected_changes=d["unaffected_prediction_changes"])
        print(json.dumps({"cut": cut, **results[cut], "seconds": round(time.time() - t)}), flush=True)
