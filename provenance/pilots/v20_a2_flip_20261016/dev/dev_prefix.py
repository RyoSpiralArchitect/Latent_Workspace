"""Dev probe (not evidence): does the frozen host read facts injected as a cut-16 prefix?
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
config = old.engine.ModelConfig(**architecture["model"])
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
host = DecoderHost(base)
tensors, rows = run.load_split(F, "train")
questions = rows["questions"]
qo, mo = tensors["question_offsets"], tensors["memory_offsets"]
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]
held = [i for i, q in enumerate(questions) if q["world"] >= 192]
results = {}
t = time.time()
with torch.no_grad():
    for layout in ("memory_first", "bos_first"):
        scores = {}
        for cond in ("intact", "twin", "reverse_intact", "unrelated"):
            k = run.key_index(cond)
            out = []
            for i in held:
                w = questions[i]["world"]
                q = tensors["question_states"][qo[i] : qo[i + 1]]
                m = tensors["memory_states"][mo[w * keys + k] : mo[w * keys + k + 1]]
                x = torch.cat([m, q]) if layout == "memory_first" else torch.cat([q[:1], m, q[1:]])
                x = x[None].to("cuda")
                logits = host.from_cut(x, torch.ones(x.shape[:2], dtype=torch.long, device="cuda"), plan["memory_boundary"])
                out.append(logits[0, -1, cands].float().cpu().tolist())
            scores[cond] = out
        base = [tensors["base_logits"][i].tolist() for i in held]
        held_q = [questions[i] for i in held]
        def acc(s, side):
            return sum((x[1] > x[0]) == bool(q["labels"][side]) for x, q in zip(s, held_q)) / len(held_q)
        flips = sum(1 for k, q in enumerate(held_q) if q["affected"] and (scores["intact"][k][1] > scores["intact"][k][0]) == bool(q["labels"][0]) and (scores["twin"][k][1] > scores["twin"][k][0]) == bool(q["labels"][1]))
        changes = sum(1 for k, q in enumerate(held_q) if (scores["intact"][k][1] > scores["intact"][k][0]) != (scores["twin"][k][1] > scores["twin"][k][0]))
        contrasts = run.contrasts_for(held_q, lambda c: scores[c] if c in scores else None, ("actual",))
        sums = {}
        for c in contrasts:
            if c["affected"]:
                sums[c["world"]] = sums.get(c["world"], 0.0) + c["donor_directed_gap_change"]
        pos = sum(v > 0 for v in sums.values()); neg = sum(v < 0 for v in sums.values())
        results[layout] = dict(acc_intact=acc(scores["intact"], 0), acc_twin=acc(scores["twin"], 1), acc_reverse=acc(scores["reverse_intact"], 0), acc_unrelated=acc(scores["unrelated"], 0), base_acc_intact=acc(base, 0), affected=sum(q["affected"] for q in held_q), flips=flips, prediction_changes=changes, donor_world_sign=[pos, neg])
print(json.dumps(dict(seconds=round(time.time() - t), results=results)))
