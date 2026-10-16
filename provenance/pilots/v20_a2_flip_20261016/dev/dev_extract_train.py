"""Dev check for V20 A2 (not evidence): real train-split features only, in a dev checkout."""
import json, os, sys, time
from pathlib import Path

D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
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
guard("admission", admission=True, forecast_bytes=4 * 2**30)
torch.cuda.set_per_process_memory_fraction(plan["resources"]["allocator_cap_gib"] * 2**30 / torch.cuda.get_device_properties(0).total_memory)
old = core.legacy.old
_, _, architecture, _ = core.legacy.validate()
config = old.engine.ModelConfig(**architecture["model"])
tokenizer = old.engine.load_tokenizer(config)
t = time.time()
base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
assert core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"]
host = DecoderHost(base)
records = run.v19().load_records(plan)
run.v19().validate_data(old, records)
load_s = time.time() - t
questions, memories = run.render(old, tokenizer, records["train"], plan)
throttle = run.v19().throttled(guard, 64)
t = time.time()
with torch.no_grad():
    tensors = run.extract_split(torch, host, host.readout(), questions, memories, plan["memory_boundary"], plan["candidate_ids"], lambda p: throttle(f"dev:{p}"))
extract_s = time.time() - t
save_file({k: v.contiguous() for k, v in tensors.items()}, str(OUT / "FEATURES_train.safetensors"))
run.ex.write_gz(OUT / "ROWS_train.json.gz", dict(questions=questions, memories=memories))
receipt = run.split_receipt(questions, memories, tensors["base_logits"], str(tensors["question_states"].dtype))
print(json.dumps(dict(load_seconds=round(load_s, 1), extract_seconds=round(extract_s, 1), receipt=receipt, peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2), shapes={k: list(v.shape) for k, v in tensors.items()})))
