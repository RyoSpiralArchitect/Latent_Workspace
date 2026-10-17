"""Dev capture for V20 A5 (not evidence): the A4 development rows, saved once for CPU runs.

As A4's dev_refine2.py: memory at cut 4, rows in the ladder's train order. Train worlds
0-191 give each row's own facts and its mismatch memory (the first world, stepping by 97
through 0-191, that does not name both of the question's entities). Train worlds 192-255
give the held-out conditions: intact, twin, random_intact, random_twin, the other held-out
world's facts on each side, and the complement-entity memory. Own rows are checked against
the sealed ladder's stored features, bitwise. Dev and final are never touched."""
import json, os, sys, time
from pathlib import Path

D, LADDER, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_depth_ladder as run
from latent_workspace import DecoderHost, composition
from safetensors.torch import load_file, save_file

CUT, TRAIN, HELD = 4, 192, 64
plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
config = old.engine.ModelConfig(**architecture["model"])
tokenizer = old.engine.load_tokenizer(config)
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
assert core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"]
host = DecoderHost(base)
prefix = composition.CutPrefixRoute(host, CUT)
records = run.v19().load_records(plan)["train"]
questions, memories = run.render(old, tokenizer, records, plan)
keys = len(run.MEMORY_KEYS)
cands = plan["candidate_ids"]
names = [set(r["metadata"]["orders"][0]) for r in records]


def mismatch_world(w, q):
    a, b = records[w]["metadata"]["query_pairs"][q]
    assert a in records[w]["queries"][q] and b in records[w]["queries"][q]
    for k in range(1, TRAIN):
        o = (w + 97 * k) % TRAIN
        if not (a in names[o] and b in names[o]):
            return o
    raise ValueError("no mismatch world")


def encode(ids):
    x = torch.tensor([ids], device="cuda")
    return host.to_cut(x, torch.ones_like(x), CUT)[0]


rows = []
for i, _, side in run.split_rows(questions, "train"):
    w = questions[i]["world"]
    if w < TRAIN:
        rows.append((i, "own", side, w * keys + side))
        rows.append((i, "mismatch", side, mismatch_world(w, questions[i]["query"]) * keys + side))
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
equal = 0
own = [k for k, m in enumerate(meta) if m["kind"] in ("own", "intact", "twin")]
for k in own:
    s = where[meta[k]["question"], meta[k]["side"]]
    equal += torch.equal(stored["question_states"][stored["offsets"][s] : stored["offsets"][s + 1]], states[k]) and torch.equal(stored["host_logits"][s], scores[k])
OUT.mkdir(parents=True, exist_ok=False)
save_file({"question_states": torch.cat(states).contiguous(), "offsets": torch.tensor(offsets), "host_logits": torch.stack(scores)}, str(OUT / "FEATURES.safetensors"))
run.ex.write_gz(OUT / "ROWS.json.gz", dict(rows=meta, questions=questions))
print(json.dumps(dict(rows=len(meta), own_rows_equal_to_ladder=f"{equal}/{len(own)}", capture_seconds=capture, bytes=(OUT / "FEATURES.safetensors").stat().st_size)), flush=True)
