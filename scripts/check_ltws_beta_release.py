#!/usr/bin/env python3
"""Check the LTWS β release candidate as a user would load it; no upload.

Run it isolated (``python -I``). Its only project code is the release folder's own
``latent_workspace`` package; it imports nothing from this repository. Mistral comes from
transformers at the pinned revision, loaded as ``example.py`` loads it. The sealed records
(the depth ladder's final split, A5's scores and verdicts, the final data, the plans) are
read as data.

For every final question, under the intact, twin, reversed and random memories (the
random memories are V16's norm-matched control, made as the ladder made them), the release
must:

- render the stored prompt;
- give the stored host logits and question-position final states, bitwise;
- give each route's sealed answer, within float rounding of A5's batched scores.

Lane A's verdicts, recomputed with the release's own availability module from its
readings, must equal A5's for every route and for their mean.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

CONDITIONS = (
    ("intact", 0, "own"),
    ("twin", 1, "own"),
    ("reverse_intact", 0, "reverse"),
    ("reverse_twin", 1, "reverse"),
    ("random_intact", 0, "random"),
    ("random_twin", 1, "random"),
)


def read_gz(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--ladder-raw", type=Path, required=True)
    parser.add_argument("--a5-raw", type=Path, required=True)
    parser.add_argument("--final-data", type=Path, required=True)
    parser.add_argument("--ladder-plan", type=Path, required=True)
    parser.add_argument("--a5-plan", type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    sys.path.insert(0, str(args.release.resolve()))
    import torch
    from safetensors.torch import load_file
    from transformers import AutoModelForCausalLM, AutoTokenizer

    import latent_workspace
    from latent_workspace import DecoderHost, availability, package

    code = Path(latent_workspace.__file__).resolve()
    if not code.is_relative_to(args.release.resolve()):
        raise SystemExit(f"latent_workspace came from outside the release: {code}")
    descriptor, routes = package.load(args.release)
    host_spec = descriptor["host"]
    tokenizer = AutoTokenizer.from_pretrained(
        host_spec["repository"], revision=host_spec["revision"]
    )
    options = dict(revision=host_spec["revision"], attn_implementation="sdpa")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            host_spec["repository"], dtype=torch.bfloat16, **options
        )
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            host_spec["repository"], torch_dtype=torch.bfloat16, **options
        )
    model.config.use_cache = False
    model = model.eval().requires_grad_(False).to("cuda")
    reader = package.LatentMemory(DecoderHost(model), tokenizer, descriptor, routes)

    folder = args.ladder_raw / "extract_cut4"
    questions = read_gz(folder / "QUESTIONS_final.json.gz")
    meta = read_gz(folder / "ROWS_final.json.gz")
    host_scores = read_gz(folder / "HOST_SCORES_final.json.gz")
    features = load_file(str(folder / "FEATURES_final.safetensors"))
    records = json.loads(args.final_data.read_text())
    seed = json.loads(args.ladder_plan.read_text())["random_memory_seed"]
    rule = json.loads(args.a5_plan.read_text())["endpoints"]["rule"]
    names = list(routes)
    sealed = {
        name: read_gz(args.a5_raw / f"stable_{name}" / "eval_stable_final_step512.json.gz")[
            "adapted_logits"
        ]
        for name in names
    }
    index = {(m["question"], m["condition"]): n for n, m in enumerate(meta)}
    readings = {name: {c: [] for c, _, _ in CONDITIONS} for name in [*names, "mean"]}
    counts = dict(prompts=0, rows=0, host=0, states=0, answers=0)
    worst = 0.0
    started = time.monotonic()
    memories = {}
    for i, question in enumerate(questions):
        world = question["world"]
        record = records[world]
        query = record["queries"][question["query"]]
        counts["prompts"] += package.render_question(tokenizer, query) == question["prompt_ids"]
        if world not in memories:
            own = [reader.write(record["contexts"][side]) for side in (0, 1)]
            reverse = [
                reader.write_ids(
                    tokenizer.encode(
                        package.canonical_facts(record["contexts"][side], reverse=True),
                        add_special_tokens=False,
                    )
                )
                for side in (0, 1)
            ]
            generator = torch.Generator().manual_seed(seed + world)
            random = []
            for values in own:
                mask = torch.ones(1, values.shape[0], dtype=torch.long)
                noise = availability.norm_matched_random(
                    values[None].float().cpu(), mask, generator
                )
                random.append(noise[0].to(values.device, values.dtype))
            memories = {world: dict(own=own, reverse=reverse, random=random)}
        for condition, side, kind in CONDITIONS:
            result = reader.read(query, memories[world][kind][side])
            n = index[i, condition]
            start, end = features["offsets"][n : n + 2].tolist()
            counts["rows"] += 1
            counts["host"] += result["host"].tolist() == host_scores[n]
            counts["states"] += torch.equal(
                result["question_states"], features["question_states"][start:end]
            )
            agree = True
            for name in names:
                scores = result["members"][name]
                stored = torch.tensor(sealed[name][n])
                worst = max(worst, float((scores - stored).abs().max()))
                agree &= bool((scores[1] > scores[0]) == (stored[1] > stored[0]))
                readings[name][condition].append(scores.tolist())
            readings["mean"][condition].append(result["mean"].tolist())
            counts["answers"] += agree
    verdicts = {}
    for name, by_condition in readings.items():
        contrasts = availability.contrasts(
            questions, lambda c, b=by_condition: b[c], availability.FACTORS
        )
        result = availability.diagnose(contrasts, rule)
        verdicts[name] = dict(
            verdict=result["verdict"],
            flips=result["flips"],
            world_sign=result["world_sign"],
            sign_test_p=result["sign_test_p"],
        )
    recorded = json.loads((args.a5_raw / "endpoints" / "ENDPOINTS.json").read_text())
    expected = {f"s{i}": recorded["stable"]["per_seed"][i - 1] for i in range(1, 4)}
    expected["mean"] = recorded["ensemble"]
    agreement = {
        name: verdicts[name]["verdict"] == expected[name]["verdict"]
        and verdicts[name]["flips"]["actual"] == expected[name]["flips"]["actual"]
        and verdicts[name]["flips"]["random_pair"] == expected[name]["flips"]["random_pair"]
        and verdicts[name]["world_sign"] == expected[name]["world_sign"]
        for name in verdicts
    }
    report = dict(
        loader=str(code.parent),
        questions=len(questions),
        counts=counts,
        max_abs_difference_from_sealed_scores=worst,
        verdicts=verdicts,
        verdicts_equal_to_a5=agreement,
        seconds=round(time.monotonic() - started, 1),
    )
    report["exact"] = (
        counts["prompts"] == len(questions)
        and all(counts[k] == counts["rows"] for k in ("host", "states", "answers"))
        and all(agreement.values())
    )
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if report["exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
