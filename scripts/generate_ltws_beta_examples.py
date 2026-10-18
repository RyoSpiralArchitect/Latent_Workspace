#!/usr/bin/env python3
"""Free generation with a passage held as latent memory, against closed book and the usual prompt.

Run it isolated (``python -I``) on a release folder, as ``bench_ltws_beta.py`` runs: its only
project code is that folder's own ``latent_workspace``. Mistral comes from transformers at the
pinned revision; BoolQ is a local JSONL file, read as data.

For a fixed sample of BoolQ validation questions, Mistral answers in free text: yes or no, then
a short explanation. Each question is answered four ways with the same sampling seed, so the
answers differ only in how the passage reached Mistral:

- ``closed``: the question alone (closed book);
- ``latent``: the passage as latent memory at layer 4, read by Mistral alone. This is the
  benchmark's path (``CutPrefixRoute``) one token at a time: each step runs the question and
  the answer so far alone through layers 1-4, enters the passage's states before them at the
  cut, and lets layers 5-32 continue;
- ``latent_empty``: the latent prompt with no memory, which separates the passage from the
  instruction that mentions it;
- ``prompt``: the passage in the prompt, as usual.

Every step recomputes the whole sequence, without a cache, in every condition. Sampling runs on
the CPU from float32 probabilities (temperature, then nucleus), with a fresh generator per
answer seeded by the question's seed.

An answer's verdict is its first word: yes, no, or unclear. Its first-token belief is the
probability of a yes-token over yes- and no-tokens at the first step, before sampling.

Representative examples are chosen by a rule fixed here, before any judging. Among questions
where the closed-book and latent-memory verdicts differ, rank them by the change in first-token
belief in the gold answer from closed book to latent memory. Take the three largest gains
(latent right, closed book not) and the largest loss (closed book right, latent not).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import sys
import time
from pathlib import Path

INSTRUCTION = "Start your answer with Yes or No, then explain in one or two sentences."
PROMPTS = {
    "closed": "Answer the question. {instruction}\n\nQuestion: {question}",
    "latent": (
        "Use the passage you were given to answer the question. {instruction}\n\n"
        "Question: {question}"
    ),
    "latent_empty": (
        "Use the passage you were given to answer the question. {instruction}\n\n"
        "Question: {question}"
    ),
    "prompt": (
        "Use the passage to answer the question. {instruction}\n\n"
        "Passage: {passage}\n\nQuestion: {question}"
    ),
}
MEMORY = "Passage: {passage}"
CONDITIONS = ("closed", "latent", "latent_empty", "prompt")
VERDICT = re.compile(r"^\W*(yes|no)\b", re.IGNORECASE)
GAINS, LOSSES = 3, 1


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def sample_token(torch, logits, generator, temperature, top_p):
    """Temperature, then nucleus, then one draw from ``generator`` (CPU, float32)."""
    probs = torch.softmax(logits / temperature, -1)
    ordered, order = torch.sort(probs, descending=True, stable=True)
    keep = (ordered.cumsum(0) - ordered) < top_p
    ordered = torch.where(keep, ordered, torch.zeros_like(ordered))
    pick = torch.multinomial(ordered / ordered.sum(), 1, generator=generator)
    return int(order[pick])


def gold_belief(answer, label):
    return answer["p_yes"] if label == "yes" else 1.0 - answer["p_yes"]


def select(records):
    """The fixed rule: largest first-token belief changes where the verdicts differ."""

    def swing(record):
        answers = record["answers"]
        return gold_belief(answers["latent"], record["label"]) - gold_belief(
            answers["closed"], record["label"]
        )

    def right(record, condition):
        return record["answers"][condition]["verdict"] == record["label"]

    gains = [r for r in records if right(r, "latent") and not right(r, "closed")]
    losses = [r for r in records if right(r, "closed") and not right(r, "latent")]
    gains.sort(key=lambda r: (-swing(r), r["index"]))
    losses.sort(key=lambda r: (swing(r), r["index"]))
    return dict(
        rule=(
            "Questions where the closed-book and latent-memory verdicts differ, ranked by "
            "the change in first-token belief in the gold answer from closed book to latent "
            f"memory: the {GAINS} largest gains and the {LOSSES} largest loss."
        ),
        gains=[dict(index=r["index"], swing=round(swing(r), 4)) for r in gains[:GAINS]],
        losses=[dict(index=r["index"], swing=round(swing(r), 4)) for r in losses[:LOSSES]],
        candidates=dict(gains=len(gains), losses=len(losses)),
    )


def summarize(records):
    n = len(records)
    out = dict(n=n, majority_yes=sum(r["label"] == "yes" for r in records) / n)
    for condition in CONDITIONS:
        answers = [r["answers"][condition] for r in records]
        out[condition] = dict(
            verdict_accuracy=sum(
                a["verdict"] == r["label"] for a, r in zip(answers, records, strict=True)
            )
            / n,
            unclear=sum(a["verdict"] == "unclear" for a in answers),
            stopped_at_length=sum(a["stop"] == "length" for a in answers),
            mean_tokens=sum(a["tokens"] for a in answers) / n,
            first_token_belief_accuracy=sum(
                (a["p_yes"] > 0.5) == (r["label"] == "yes")
                for a, r in zip(answers, records, strict=True)
            )
            / n,
        )
    out["identical_text"] = {
        f"{a}=={b}": sum(r["answers"][a]["text"] == r["answers"][b]["text"] for r in records)
        for a, b in (("closed", "latent"), ("latent", "prompt"), ("closed", "latent_empty"))
    }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--boolq", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="a new folder")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--max-new-tokens", type=int, default=160)
    parser.add_argument("--limit", type=int, default=None, help="questions (smoke)")
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"Refusing to write into an existing path: {args.out}")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    sys.path.insert(0, str(args.release.resolve()))
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    import latent_workspace
    from latent_workspace import DecoderHost, composition, package

    code = Path(latent_workspace.__file__).resolve()
    if not code.is_relative_to(args.release.resolve()):
        raise SystemExit(f"latent_workspace came from outside the release: {code}")
    descriptor, _ = package.load(args.release)
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

    words = {"yes": [], "no": []}
    for token, index in tokenizer.get_vocab().items():
        word = token.replace("▁", " ").strip().lower()
        if word in words:
            words[word].append(index)
    if not words["yes"] or not words["no"]:
        raise SystemExit("No yes- or no-token in the vocabulary")
    yes_ids, no_ids = (torch.tensor(sorted(words[w])) for w in ("yes", "no"))

    def chat(content):
        messages = [{"role": "user", "content": content}]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return tokenizer.encode(text, add_special_tokens=False)

    @torch.no_grad()
    def next_logits(ids, memory):
        tensor = torch.tensor([ids], device="cuda")
        ones = torch.ones_like(tensor)
        if memory is None:
            return host.logits(tensor, ones)[0, -1].float().cpu()
        states = host.to_cut(tensor, ones, cut)
        memory_mask = torch.ones(1, memory.shape[1], dtype=torch.long, device="cuda")
        _, logits, _ = prefix(states, ones, memory, memory_mask)
        return logits[0, -1].float().cpu()

    def generate(prompt_ids, memory, seed):
        generator = torch.Generator().manual_seed(seed)
        ids, out, stop, belief = list(prompt_ids), [], "length", None
        for step in range(args.max_new_tokens):
            logits = next_logits(ids, memory)
            if step == 0:
                probs = torch.softmax(logits, -1)
                yes, no = float(probs[yes_ids].sum()), float(probs[no_ids].sum())
                belief = dict(
                    p_yes=yes / (yes + no),
                    yes_no_mass=yes + no,
                    top_first_token=tokenizer.convert_ids_to_tokens(int(logits.argmax())),
                )
            token = sample_token(torch, logits, generator, args.temperature, args.top_p)
            if token == tokenizer.eos_token_id:
                stop = "eos"
                break
            ids.append(token)
            out.append(token)
        text = tokenizer.decode(out, skip_special_tokens=True).strip()
        match = VERDICT.match(text)
        verdict = match.group(1).lower() if match else "unclear"
        return dict(text=text, verdict=verdict, tokens=len(out), stop=stop, **belief)

    data = args.boolq.read_bytes()
    rows = read_jsonl(args.boolq)
    chosen = sorted(random.Random(args.seed).sample(range(len(rows)), args.sample))
    chosen = chosen[: args.limit]
    args.out.mkdir(parents=True)
    started = time.monotonic()
    records = []
    with (args.out / "generations.jsonl").open("w") as handle:
        for index in chosen:
            row = rows[index]
            question = row["question"].strip()
            question = question[0].upper() + question[1:] + "?"
            passage = row["passage"]
            memory_ids = tokenizer.encode(MEMORY.format(passage=passage), add_special_tokens=False)
            with torch.no_grad():
                tensor = torch.tensor([memory_ids], device="cuda")
                memory = host.to_cut(tensor, torch.ones_like(tensor), cut)
            seed = args.seed + index
            answers = {}
            for condition in CONDITIONS:
                prompt = chat(
                    PROMPTS[condition].format(
                        instruction=INSTRUCTION, question=question, passage=passage
                    )
                )
                held = memory if condition == "latent" else None
                answers[condition] = dict(prompt_tokens=len(prompt), **generate(prompt, held, seed))
            record = dict(
                index=index,
                seed=seed,
                label="yes" if row["answer"] else "no",
                question=question,
                passage_sha256=sha256(passage),
                memory_tokens=len(memory_ids),
                answers=answers,
            )
            records.append(record)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
    report = dict(
        loader=str(code.parent),
        manifest_sha256=sha256((args.release / "MANIFEST.json").read_bytes()),
        model=f"{spec['repository']}@{spec['revision']}",
        cut=cut,
        boolq=dict(path=str(args.boolq), sha256=sha256(data), rows=len(rows)),
        sample=dict(size=args.sample, seed=args.seed, limit=args.limit, indices=chosen),
        sampling=dict(
            temperature=args.temperature,
            top_p=args.top_p,
            max_new_tokens=args.max_new_tokens,
            seed_per_question="seed + BoolQ row index, the same for every condition",
        ),
        prompts=dict(PROMPTS, memory=MEMORY, instruction=INSTRUCTION),
        yes_no_token_ids=dict(yes=yes_ids.tolist(), no=no_ids.tolist()),
        summary=summarize(records),
        selection=select(records),
        environment=dict(
            python=platform.python_version(),
            torch=torch.__version__,
            transformers=transformers.__version__,
            gpu=torch.cuda.get_device_name(0),
        ),
        seconds=round(time.monotonic() - started, 1),
    )
    (args.out / "summary.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(dict(summary=report["summary"], selection=report["selection"]), indent=1))


if __name__ == "__main__":
    main()
