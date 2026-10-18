#!/usr/bin/env python3
"""Simple benchmarks of the LTWS β against its base model, Mistral-7B-Instruct-v0.3.

Run it isolated (``python -I``) on a release folder: its only project code is that folder's
own ``latent_workspace``. Mistral comes from transformers at the pinned revision, loaded as
``example.py`` loads it; the datasets are local JSONL files, read as data.

1. **Standard benchmarks:** the β leaves Mistral's own computation unchanged. Every item is
   scored twice, by the plain transformers forward and through the β's host wrapper
   (``DecoderHost``); the logits must be equal, bitwise. The score is the letter with the
   highest next-token logit at the answer position:
   - MMLU: the repository's 570-question subset, 5-shot, V16's protocol;
   - ARC-Challenge: test, 0-shot;
   - HellaSwag: validation, a fixed 1,000-item sample, 0-shot.
2. **BoolQ** (validation, yes/no): the passage as the β would hold it, against the usual ways.
   - closed book: the question alone;
   - the passage in the prompt (Mistral as usual);
   - the passage as latent memory at layer 4, read by Mistral alone;
   - the same, plus the β's routes (their mean). The routes were trained only on synthetic
     rankings, so this is out of their domain.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

LETTERS = "ABCDE"
BOOLQ_CLOSED = "Answer the question with one word: no or yes."
BOOLQ_OPEN = "Use the passage to answer the question with one word: no or yes."
BOOLQ_LATENT = "Use the passage you were given to answer the question with one word: no or yes."


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def hellaswag_text(text):
    """lm-evaluation-harness's HellaSwag cleanup."""
    text = text.strip().replace(" [title]", ". ")
    text = re.sub(r"\[.*?\]", "", text)
    return text.replace("  ", " ")


def letter_prompt(header, stem, options):
    lines = [f"{LETTERS[i]}. {option}" for i, option in enumerate(options)]
    return f"{header}\n\n{stem}\n" + "\n".join(lines) + "\nAnswer:"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--mmlu", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--hellaswag-sample", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--limit", type=int, default=None, help="items per benchmark (smoke)")
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    sys.path.insert(0, str(args.release.resolve()))
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    import latent_workspace
    from latent_workspace import DecoderHost, composition, package

    code = Path(latent_workspace.__file__).resolve()
    if not code.is_relative_to(args.release.resolve()):
        raise SystemExit(f"latent_workspace came from outside the release: {code}")
    descriptor, routes = package.load(args.release)
    spec = descriptor["host"]
    tokenizer = AutoTokenizer.from_pretrained(spec["repository"], revision=spec["revision"])
    options = dict(revision=spec["revision"], attn_implementation="sdpa")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            spec["repository"], dtype=torch.bfloat16, **options
        )
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            spec["repository"], torch_dtype=torch.bfloat16, **options
        )
    model.config.use_cache = False
    model = model.eval().requires_grad_(False).to("cuda")
    host = DecoderHost(model)
    cut = int(descriptor["memory"]["cut"])
    prefix = composition.CutPrefixRoute(host, cut)
    yes_no = list(descriptor["candidate_ids"])

    def ids_of(text, special):
        return torch.tensor([tokenizer.encode(text, add_special_tokens=special)], device="cuda")

    @torch.no_grad()
    def both(ids, candidates):
        """Candidate logits by the plain forward and through the β's host wrapper."""
        mask = torch.ones_like(ids)
        native = model(input_ids=ids, attention_mask=mask, use_cache=False).logits[0, -1]
        wrapped = host.logits(ids, mask)[0, -1]
        return native[candidates].float().cpu(), wrapped[candidates].float().cpu()

    def letter_ids(prompt, count):
        base = tokenizer.encode(prompt, add_special_tokens=True)
        out = []
        for letter in LETTERS[:count]:
            full = tokenizer.encode(prompt + " " + letter, add_special_tokens=True)
            if full[:-1] != base or len(full) != len(base) + 1:
                raise SystemExit("A letter candidate is not one prefix-compatible token")
            out.append(full[-1])
        return out

    def multiple_choice(name, items):
        right = equal = 0
        worst = 0.0
        for prompt, count, target in items:
            candidates = letter_ids(prompt, count)
            native, wrapped = both(ids_of(prompt, True), candidates)
            equal += torch.equal(native, wrapped)
            worst = max(worst, float((native - wrapped).abs().max()))
            right += int(native.argmax()) == target
        n = len(items)
        return dict(name=name, n=n, accuracy=right / n, identical=equal, max_abs_difference=worst)

    started = time.monotonic()
    results = {}
    mmlu = json.loads(args.mmlu.read_text())[: args.limit]
    results["mmlu"] = multiple_choice(
        "MMLU (570-question subset, 5-shot)",
        [(row["prompt"], 4, row["target"]) for row in mmlu],
    )
    arc = read_jsonl(args.data / "arc_challenge_test.jsonl")[: args.limit]
    items = []
    for row in arc:
        labels = list(row["choices"]["label"])
        prompt = letter_prompt(
            "The following is a multiple choice question (with answer) about science.",
            row["question"],
            row["choices"]["text"],
        )
        items.append((prompt, len(labels), labels.index(row["answerKey"])))
    results["arc_challenge"] = multiple_choice("ARC-Challenge (test, 0-shot)", items)
    hellaswag = read_jsonl(args.data / "hellaswag_validation.jsonl")
    sample = sorted(random.Random(args.seed).sample(range(len(hellaswag)), args.hellaswag_sample))
    sample = sample[: args.limit]
    items = []
    for index in sample:
        row = hellaswag[index]
        stem = hellaswag_text(row["activity_label"] + ": " + row["ctx"])
        endings = [hellaswag_text(ending) for ending in row["endings"]]
        prompt = letter_prompt(
            "The following is a multiple choice question (with answer): which ending is most "
            "plausible?",
            stem,
            endings,
        )
        items.append((prompt, 4, int(row["label"])))
    results["hellaswag"] = multiple_choice(
        f"HellaSwag (validation, {len(sample)}-item sample, 0-shot)", items
    )
    results["hellaswag"]["sample_seed"] = args.seed

    def chat(content):
        messages = [{"role": "user", "content": content}]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return tokenizer.encode(text, add_special_tokens=False)

    boolq = read_jsonl(args.data / "boolq_validation.jsonl")[: args.limit]
    counts = dict(closed=0, open=0, latent=0, latent_routes=0, identical=0)
    with torch.no_grad():
        for row in boolq:
            question = row["question"].strip()
            question = question[0].upper() + question[1:] + "?"
            label = int(bool(row["answer"]))
            closed = chat(f"{BOOLQ_CLOSED}\n\nQuestion: {question} Answer:")
            opened = chat(
                f"{BOOLQ_OPEN}\n\nPassage: {row['passage']}\n\nQuestion: {question} Answer:"
            )
            asked = chat(f"{BOOLQ_LATENT}\n\nQuestion: {question} Answer:")
            for key, ids in (("closed", closed), ("open", opened)):
                tensor = torch.tensor([ids], device="cuda")
                native, wrapped = both(tensor, yes_no)
                counts["identical"] += torch.equal(native, wrapped)
                counts[key] += int(native[1] > native[0]) == label
            memory_ids = tokenizer.encode(f"Passage: {row['passage']}", add_special_tokens=False)
            memory_tensor = torch.tensor([memory_ids], device="cuda")
            memory = host.to_cut(memory_tensor, torch.ones_like(memory_tensor), cut)
            query = torch.tensor([asked], device="cuda")
            states = host.to_cut(query, torch.ones_like(query), cut)
            final, logits, _ = prefix(
                states,
                torch.ones_like(query),
                memory,
                torch.ones(1, memory.shape[1], dtype=torch.long, device="cuda"),
            )
            scores = logits[0, -1, yes_no].float().cpu()
            counts["latent"] += int(scores[1] > scores[0]) == label
            hidden = final[0, memory.shape[1] :].float().cpu()[None]
            mask = torch.ones(1, hidden.shape[1], dtype=torch.long)
            residual = sum(route(hidden, mask)[0][0] for route in routes.values()) / len(routes)
            routed = scores + residual
            counts["latent_routes"] += int(routed[1] > routed[0]) == label
    n = len(boolq)
    results["boolq"] = dict(
        name="BoolQ (validation, yes/no)",
        n=n,
        majority_yes=sum(int(bool(r["answer"])) for r in boolq) / n,
        closed_book=counts["closed"] / n,
        passage_in_prompt=counts["open"] / n,
        latent_memory_layer4=counts["latent"] / n,
        latent_memory_layer4_with_routes=counts["latent_routes"] / n,
        identical=counts["identical"],
        identical_of=2 * n,
    )
    report = dict(
        loader=str(code.parent),
        model=f"{spec['repository']}@{spec['revision']}",
        results=results,
        seconds=round(time.monotonic() - started, 1),
    )
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
