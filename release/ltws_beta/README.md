---
license: apache-2.0
base_model: mistralai/Mistral-7B-Instruct-v0.3
base_model_relation: adapter
language:
- en
tags:
- latent-workspace
- latent-memory
- research
---

# mistral-7b-instruct-v0.3-LTWS β

A **latent workspace (LTWS)** for the unchanged
[Mistral-7B-Instruct-v0.3](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/tree/c170c708c41dac9275d15a8fff4eca08d52bab71).
It lets the model answer yes/no questions from facts held as **latent memory**
instead of text in its prompt.

**β: a research preview.** It covers one synthetic task family, and its
content claim is not fully established (see [Evidence](#evidence)). This is
not an official Mistral release, and it changes none of Mistral's weights.

## How it works

1. **Writing memory:** the facts run alone through Mistral's first four
   layers. Their states are the latent memory; they can be computed once and
   cached.
2. **Reading:** a question runs alone through the same four layers. The memory
   enters before it at layer 4, and Mistral's own remaining 28 layers continue.
3. **The routes:** three small trained routes (about 3.0M parameters each)
   read Mistral's final states at the question. Each adds a gated, low-rank
   adjustment to the two answer logits (" no" and " yes"), and the answer is
   their **mean**.
   - **Content gating:** the routes were also trained to leave the answer
     alone when the memory is not about the question.

This repository holds only the routes, their descriptor and the loader code.
Mistral is downloaded, unchanged, from its pinned revision. Without LTWS, the
model is the upstream model.

## Use

```bash
pip install -r requirements.txt
python example.py
```

[`example.py`](example.py) loads Mistral at the pinned revision (bf16, SDPA
attention), writes a new world's facts as latent memory, and asks the same
questions with the facts, with one adjacent pair swapped, and with no memory.
The core of it:

```python
from latent_workspace import DecoderHost, package

descriptor, routes = package.load(".")  # checks every file's hash and each route
reader = package.LatentMemory(DecoderHost(model), tokenizer, descriptor, routes)
memory = reader.write(facts)  # "World facts. ...\n- A is ranked above B.\n..."
result = reader.read("Is A ranked above B? Answer:", memory)
result["answer"], result["mean"]  # "yes" / "no", and the [no, yes] logits
```

- **Facts:** a header line, then one `- X is ranked above Y.` line per fact.
- **Questions:** they end with ` Answer:`, as in training ("Is X ranked above
  Y? Answer:" or "Does X outrank Y? Answer:").

## Evidence

All figures come from sealed, offline-verified runs on held-out worlds: 128
world pairs, 1,024 questions, 256 of them affected by the paired fact change.

| System | Accuracy, right memory | Accuracy, random memory | Flips / under random memory | Worlds in the memory's direction | Verdict |
| --- | --- | --- | --- | --- | --- |
| Mistral alone, facts as text in the prompt | 0.74–0.76 | 0.50 | 55 / 6 | 90 of 128 | `CONTENT_REACHES_ANSWERS` |
| Mistral alone, latent memory at layer 4 | 0.58–0.60 | 0.50 | 44 / 3 | 54 of 128 | `NOT_ESTABLISHED` |
| **LTWS β, mean of the three routes** | 0.85–0.86 | 0.50 | 65 / 4 | 85 of 128 | `CONTENT_REACHES_ANSWERS` |
| each route alone (seeds 1 / 2 / 3) | 0.84–0.85 | 0.50 | 58 / 4, 59 / 4, 60 / 4 | 83, 85, 80 of 128 | content, content, not established |

- **Flip:** a question gets the original facts' answer under the original
  facts and the swapped facts' answer under the swapped facts.
- **`CONTENT_REACHES_ANSWERS`:** at least 26 flips, 20 more than under random
  memory, and a one-sided sign test over worlds at α = 0.001 (82 of 128).
- **The pre-registered criterion was not met.** It required every route
  alone to reach the verdict, and seed 3 is two worlds short. The mean's
  reading was descriptive in that run; it was chosen as the β's default
  afterwards.
- **Memory that is not about the question** (random, other entities, or none)
  moves the answer's logit gap by 0.01–0.09. The right memory moves it by
  4.2–4.3.

The package was checked against the sealed runs: in a fresh environment it
reproduces their routes and scores, and their answers end to end from text.
Records:
- [the β package and its checks](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/docs/v20/BETA_PACKAGE.md);
- [the routes' run (V20 A5)](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/pilots/v20_a5_stable_route_20261018/README.md);
- [the depth ladder](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/pilots/v20_a2_depth_ladder_20261016/README.md).

## Intended use and limits

- **Use:** research on how a frozen language model can read memory it did not
  see in its context, and controlled evaluation.
- **Task family only:**
  - synthetic ranking worlds (six entities from a pool of twelve, five facts
    each);
  - the two question forms above, in English;
  - yes/no answers. Nothing else is evaluated.
- **Not provided:** general question answering, text generation through the
  routes, or any claim about reasoning, intelligence, safety or quality
  elsewhere.
- **Inherited:** the upstream model's limitations, including its lack of
  moderation mechanisms.
- **Memory hygiene:** memory is read as given. Conflicting or untrusted facts
  are not detected.

## Training

- **Data:** the frozen model's states on 256 synthetic world pairs (the
  original and the swapped facts). The held-out worlds above were never used.
- **Routes:**
  - three seeds, each trained on CPU in FP32: 512 updates of 32 questions,
    AdamW at 3e-4, the learning rate decaying linearly after update 256;
  - content gating at weight 0.3, using other worlds' facts that do not name
    both of a question's entities.

## License

Apache-2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). Mistral-7B-Instruct-v0.3
is Apache-2.0 by Mistral AI and is not redistributed here.
