"""Answer yes/no questions from facts held as latent memory (mistral-7b-instruct-v0.3-LTWS β).

Run from this folder, with the packages in requirements.txt. The first run downloads the
pinned upstream model (about 14.5 GB). The facts below are a new world in the format the
routes were trained on; they are not from any training or evaluation split.
"""

import sys
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from latent_workspace import DecoderHost, package  # noqa: E402

descriptor, routes = package.load(HERE)
host = descriptor["host"]
tokenizer = AutoTokenizer.from_pretrained(host["repository"], revision=host["revision"])
options = dict(revision=host["revision"], attn_implementation="sdpa")
try:
    model = AutoModelForCausalLM.from_pretrained(
        host["repository"], dtype=torch.bfloat16, **options
    )
except TypeError:  # transformers 4.x names it torch_dtype
    model = AutoModelForCausalLM.from_pretrained(
        host["repository"], torch_dtype=torch.bfloat16, **options
    )
model.config.use_cache = False
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.eval().requires_grad_(False).to(device)
reader = package.LatentMemory(DecoderHost(model), tokenizer, descriptor, routes)

facts = (
    "World facts. The ranking is transitive.\n"
    "- Luma is ranked above Aster.\n"
    "- Aster is ranked above Joren.\n"
    "- Joren is ranked above Cyra.\n"
    "- Cyra is ranked above Eris.\n"
    "- Eris is ranked above Doran."
)
swapped = facts.replace(
    "- Luma is ranked above Aster.\n- Aster is ranked above Joren.\n- Joren is ranked above Cyra.",
    "- Luma is ranked above Joren.\n- Joren is ranked above Aster.\n- Aster is ranked above Cyra.",
)
memories = {"facts": reader.write(facts), "swapped": reader.write(swapped), "none": None}
questions = (
    "Is Aster ranked above Joren? Answer:",  # yes with the facts, no with the swap
    "Is Luma ranked above Doran? Answer:",  # yes with either
    "Does Cyra outrank Aster? Answer:",  # no with either
)
for question in questions:
    for name, memory in memories.items():
        result = reader.read(question, memory)
        gap = float(result["mean"][1] - result["mean"][0])
        print(
            f"{question:40s} memory={name:8s} answer={result['answer']:3s} (yes - no = {gap:+.2f})"
        )
