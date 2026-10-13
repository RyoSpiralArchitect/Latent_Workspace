"""CPU construction-only failure diagnosis; no forward/backward/update or model load.

Uses the existing sealed source after its pre-import check. This additive
diagnostic script is separately hashed, not part of the original run's seal.
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import platform
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", required=True, type=Path)
parser.add_argument("--seal", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
assert sys.flags.isolated
root = args.root.resolve()
spec = importlib.util.spec_from_file_location("source_guard", root / "scripts/run_source_sealed.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
source_check = guard.verify(
    root, json.loads(args.seal.read_text()), "scripts/continue_v16_adapter_full.py"
)
sys.path[:0] = [str(root / "src")]

import torch  # noqa: E402
import transformers  # noqa: E402
from transformers import MistralConfig, MistralForCausalLM, PreTrainedModel  # noqa: E402

from latent_workspace_ft_v10.engine import enable_gradient_checkpointing  # noqa: E402
from latent_workspace_ft_v10.hf_training_readout import (  # noqa: E402
    HFTrainingReadoutAdapter,
    native_input_grad_hook,
)

rows = []
for mode in ("direct_hf_checkpointing", "historical_engine_helper"):
    config = MistralConfig(
        vocab_size=32,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=64,
        attention_dropout=0.0,
    )
    config._attn_implementation = "sdpa"
    base = MistralForCausalLM(config).to(dtype=torch.bfloat16).train()
    if mode == "direct_hf_checkpointing":
        base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        enable_gradient_checkpointing(base)
    tracked = {h.id for h in base._require_grads_hooks}
    hooks = []
    for name, module in base.named_modules():
        for key, hook in module._forward_hooks.items():
            hooks.append(
                {
                    "module": name,
                    "tracked_handle": key in tracked,
                    "qualname": hook.__qualname__,
                    "accepted_by_native_input_grad_hook": native_input_grad_hook(
                        base, module, key, hook
                    ),
                }
            )
    try:
        HFTrainingReadoutAdapter(base)
        admission = "ACCEPTED"
    except ValueError as exc:
        admission = f"ValueError: {exc}"
    rows.append(
        {
            "mode": mode,
            "registered_forward_hooks": hooks,
            "tracked_handles": len(tracked),
            "adapter_construction": admission,
        }
    )

assert len(rows[0]["registered_forward_hooks"]) == 1
assert rows[0]["adapter_construction"] == "ACCEPTED"
assert len(rows[1]["registered_forward_hooks"]) == 2
assert [h["tracked_handle"] for h in rows[1]["registered_forward_hooks"]] == [False, True]
assert (
    rows[1]["adapter_construction"]
    == "ValueError: Training adapter rejects unqualified native hooks"
)
assert not torch.cuda.is_initialized()
result = {
    "schema": "v16-full-hook-construction-diagnosis-v1",
    "source_check": source_check,
    "diagnostic_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "runtime": {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "device": "cpu",
    },
    "method_hashes": {
        name: hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()
        for name, fn in {
            "hf_gradient_checkpointing_enable": PreTrainedModel.gradient_checkpointing_enable,
            "hf_enable_input_require_grads": PreTrainedModel.enable_input_require_grads,
            "engine_enable_gradient_checkpointing": enable_gradient_checkpointing,
            "native_input_grad_hook": native_input_grad_hook,
        }.items()
    },
    "cases": rows,
    "tiny_model_constructions": 2,
    "forward_calls": 0,
    "backward_pairs": 0,
    "optimizer_updates": 0,
    "checkpoint_writes": 0,
    "model_downloads": 0,
    "new_sequences": 0,
    "judge_calls": 0,
    "cuda_initialized": False,
    "fix_applied": False,
    "status": "DUPLICATE_HF_INPUT_GRAD_HOOK_REPRODUCED_NOT_REPAIRED",
}
with args.output.open("x") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps(result, indent=2, sort_keys=True))
