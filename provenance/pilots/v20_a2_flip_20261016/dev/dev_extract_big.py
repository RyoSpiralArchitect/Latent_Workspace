"""Dev check for V20 A2 (not evidence): features for generated training worlds only."""
import json, os, sys, time
from pathlib import Path

D, RECORDS, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a2_flip as run
from latent_workspace import DecoderHost
from safetensors.torch import save_file

plan = run.ex.read(D / run.PLAN)
core = run.load("run_v16_adapter_migration")
core.load_runtime()
torch = core.torch
OUT.mkdir(parents=True, exist_ok=False)
guard = core.legacy.Guard(plan["resources"], OUT)
guard("admission", admission=True, forecast_bytes=16 * 2**30)
torch.cuda.set_per_process_memory_fraction(plan["resources"]["allocator_cap_gib"] * 2**30 / torch.cuda.get_device_properties(0).total_memory)
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
config = old.engine.ModelConfig(**architecture["model"])
tokenizer = old.engine.load_tokenizer(config)
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
assert core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"]
host = DecoderHost(base)
records = [json.loads(l) for l in RECORDS.read_text().splitlines() if l.strip()]
questions, memories = run.render(old, tokenizer, records, plan)
throttle = run.v19().throttled(guard, 256)
t = time.time()
states, offsets, base_rows = [], [0], []
cands = plan["candidate_ids"]
with torch.no_grad():
    for i, row in enumerate(questions):
        throttle(f"q:{i}")
        ids = torch.tensor([row["prompt_ids"]], device="cuda")
        mask = torch.ones_like(ids)
        cut = host.to_cut(ids, mask, plan["memory_boundary"])
        logits = host.from_cut(cut, mask, plan["memory_boundary"])
        if i % 256 == 0:
            assert torch.equal(logits, host.logits(ids, mask)), "cut parity"
        states.append(cut[0].cpu()); offsets.append(offsets[-1] + cut.shape[1])
        base_rows.append(logits[0, -1, cands].float().cpu())
    m_states, m_offsets = [], [0]
    for i, row in enumerate(memories):
        throttle(f"m:{i}")
        ids = torch.tensor([row["ids"]], device="cuda")
        cut = host.to_cut(ids, torch.ones_like(ids), plan["memory_boundary"])
        m_states.append(cut[0].cpu()); m_offsets.append(m_offsets[-1] + cut.shape[1])
tensors = {"question_states": torch.cat(states), "question_offsets": torch.tensor(offsets), "base_logits": torch.stack(base_rows), "memory_states": torch.cat(m_states), "memory_offsets": torch.tensor(m_offsets)}
save_file({k: v.contiguous() for k, v in tensors.items()}, str(OUT / "FEATURES_train.safetensors"))
run.ex.write_gz(OUT / "ROWS_train.json.gz", dict(questions=questions, memories=memories))
print(json.dumps(dict(seconds=round(time.time() - t), worlds=len(records), questions=len(questions), memories=len(memories), peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2), bytes=(OUT / "FEATURES_train.safetensors").stat().st_size)))
