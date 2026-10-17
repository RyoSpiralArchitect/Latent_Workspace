"""Smoke of the sealed A4 code path in a dev checkout (not evidence). ``extract``: the
runner's own mismatch extraction on the first two train worlds (32 rows), every row
checked against the head and the ladder's stored features. ``reproduce``: the runner's
reproduction of the ladder's ungated route of seed 1. No gated route is trained and no
new route reads the final split. The output folder must sit directly under tmp/, beside
the ladder's task root."""
import json, os, sys, time
from argparse import Namespace
from pathlib import Path

D, MODE, OUT = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path[:0] = [str(D / "scripts"), str(D / "src")]
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import run_v20_a4_gated_route as run

plan = run.ex.read(D / run.PLAN)
run.validate_plan(plan)
args = Namespace(role=MODE, output=OUT / "raw" / MODE, checkpoints=OUT / "checkpoints")
args.output.mkdir(parents=True, exist_ok=False)
raw = run.ladder_raw(args, plan)
t = time.time()
if MODE == "reproduce":
    torch = run.LADDER.cpu_runtime(plan)
    run.load("run_v16_adapter_migration").load_runtime()
    report = run.reproduce_run(torch, args, plan)
    print(json.dumps(dict(report, seconds=round(time.time() - t))), flush=True)
else:
    from safetensors.torch import load_file
    from latent_workspace import DecoderHost

    core = run.load("run_v16_adapter_migration")
    core.load_runtime()
    torch = core.torch
    run.verify_ladder(raw, plan)
    old = core.legacy.old
    _, _, architecture, _ = core.legacy.validate()
    config = old.engine.ModelConfig(**architecture["model"])
    tokenizer = old.engine.load_tokenizer(config)
    base = old.engine._load_hf_model(config).eval().requires_grad_(False).to("cuda")
    assert core.tree_hash(base.state_dict()) == plan["backbone"]["original_base_sha256"]
    host = DecoderHost(base)
    records = run.LADDER.v19().load_records(plan)
    run.check_entities(records["train"])
    questions, memories = run.LADDER.render(old, tokenizer, records["train"], plan)
    source = raw / "extract_cut4"
    run.check_alignment(questions, run.ex.read_gz(source / "ROWS_train.json.gz"))
    stored = load_file(str(source / "FEATURES_train.safetensors"))
    smoke = dict(plan, parity_every=1)
    with torch.no_grad():
        tensors, meta, checked = run.extract_mismatch(torch, host, plan["cut"], records["train"], questions[:16], memories, stored, smoke, lambda _p: None)
    print(json.dumps(dict(rows=len(meta), checked=checked, stride_steps=sorted({m["stride_steps"] for m in meta}), worlds=sorted({m["mismatch_world"] for m in meta}), peak_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2), seconds=round(time.time() - t))), flush=True)
