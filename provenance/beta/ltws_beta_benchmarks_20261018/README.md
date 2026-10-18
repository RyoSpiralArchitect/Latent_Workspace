# LTWS β — simple benchmarks against the base model

2026-10-18. Ryō asked for simple benchmarks on well-known datasets, comparing the
β with its base model, for the card ("いくらか簡易的なベンチを各種有名なものを
使ってbase modelと比較して"). **Descriptive, run once, not pre-registered.**

## How it ran

- **Script:** [bench_ltws_beta.py](../../../scripts/bench_ltws_beta.py) at commit
  `312e2f9efc8f36582fe3de181161df08afb657c1`, run once on Furnace
  ([script](run_bench.sh), [timeline](TIMELINE.log): 09:56:11Z–10:04:57Z, 522 s).
- **Isolation:** the run was isolated (`python -I`). Its only project code was
  the published package itself, the private Hub revision `eb370d71` as
  downloaded, and it confirmed that import path.
- **Model:** Mistral-7B-Instruct-v0.3 at `c170c708…`, bf16, SDPA attention, as
  `example.py` loads it.
- **Data:** read as local JSONL ([sources and revisions](SOURCES.json),
  [file hashes](DATA_SHA256.txt)):
  - MMLU: the repository's 570-question subset (MIT).
  - ARC-Challenge: `allenai/ai2_arc` test (CC BY-SA 4.0).
  - HellaSwag: `Rowan/hellaswag` validation. A 1,000-item sample, seed 20261018.
  - BoolQ: `google/boolq` validation (CC BY-SA 3.0).
  - The dataset files are not redistributed here.
- **Output:** [bench.out](bench.out).

## 1. Standard benchmarks: the β leaves Mistral unchanged

**Method:**
- Every item was scored twice, by the plain transformers forward and through the
  β's host wrapper (`DecoderHost`).
- The prediction is the letter with the highest next-token logit after
  "Answer:".
- MMLU used V16's 5-shot prompts. ARC-Challenge and HellaSwag used a 0-shot
  letter-choice prompt.
- HellaSwag's text was cleaned as lm-evaluation-harness cleans it.
- These protocols are not those of public leaderboards, so the numbers are not
  comparable to them.

| Benchmark | Items | Base Mistral | LTWS β | Logits identical |
| --- | ---: | --- | --- | --- |
| MMLU (570-question subset, 5-shot) | 570 | 0.625 (356) | 0.625 | 570 / 570, max difference 0.0 |
| ARC-Challenge (test, 0-shot) | 1,172 | 0.784 (919) | 0.784 | 1,172 / 1,172 |
| HellaSwag (validation sample, 0-shot) | 1,000 | 0.723 (723) | 0.723 | 1,000 / 1,000 |

The β does not touch Mistral's weights or its forward pass. Without a memory,
its answers are Mistral's, bit for bit.

## 2. BoolQ: a real passage held as latent memory

BoolQ asks yes/no questions about a Wikipedia passage. All 3,270 validation
questions were asked in Mistral's chat template, comparing " no" and " yes" at
the answer position, as the β does. The passage reached Mistral four ways:

| How Mistral gets the passage | Correct | Accuracy |
| --- | ---: | --- |
| (always "yes", the majority answer) | 2,033 | 0.622 |
| not at all (closed book) | 2,184 | 0.668 |
| in the prompt, as usual | 2,778 | 0.850 |
| **as latent memory at layer 4, read by Mistral alone** | **2,719** | **0.831** |
| as latent memory at layer 4, with the β's routes (their mean) | 2,626 | 0.803 |

- **Latent memory alone:** the passage, with a "Passage:" header, ran alone
  through layers 1–4. Its states entered before the question's, and Mistral's
  layers 5–32 read them. The question's prompt asked it to use "the passage
  you were given". No component was trained for this.
- **Close to the prompt:** frozen Mistral read a real passage held as latent
  memory at 0.831, against 0.850 from its prompt and 0.668 without it. That
  recovers 90% of the passage's benefit over closed book (535 of the 594 extra right
  answers).
- **The routes do not transfer:** they were trained only on synthetic
  rankings, and on BoolQ they lower accuracy by 2.8 points.
- **Synthetic task vs BoolQ:** on the synthetic task, Mistral alone read the
  latent memory weakly (0.58–0.60). That task needs exact relations between
  names. BoolQ passages often carry the answer as salient content. This is a
  plausible reason for the difference, not a tested one.
- **Statistics:** each accuracy here has a 95% interval of about ±1.3 points.
  Per-item answers were not saved, so no paired test was run.

## What this adds to the card

- **No degradation:** the β's absence of degradation is verified, not just
  stated.
- **Beyond the synthetic task:** latent memory written at layer 4 can carry
  natural text that frozen Mistral reads, without any training. This was
  measured once, descriptively. The packaged routes and API are specific to the
  ranking task.
