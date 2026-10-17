# mistral-7b-instruct-v0.3-LTWS β

**UNRELEASED MODEL-CARD DRAFT (packaging rehearsal, 2026-10-18).** Nothing has
been uploaded and no Hub repository exists. Hub metadata and model-index are
intentionally absent until Ryō decides on a release, and the namespace and
license are set.
See [the β package](BETA_PACKAGE.md) for the open decisions, and the
[release checklist](../v18/HF_RELEASE.md). This replaces nothing in the V18
[draft](../v18/MODEL_CARD_DRAFT.md), which describes a different, untrained
design.

## What this is

A latent workspace (LTWS) for the unchanged
[Mistral-7B-Instruct-v0.3](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/tree/c170c708c41dac9275d15a8fff4eca08d52bab71)
(revision `c170c708c41dac9275d15a8fff4eca08d52bab71`). It lets the model
answer yes/no questions from facts held as **latent memory** instead of text
in its context.

- **Writing:** the facts run alone through the model's first four layers.
  Their states are the memory and can be cached.
- **Reading:** a question runs alone through the same four layers. The memory
  enters before it at layer 4, and the model's own remaining layers continue.
- **The route:** a small trained component, about 3.0M parameters per route.
  It reads the model's final states at the question and adjusts the two
  answer logits (" no" and " yes"). It was trained to leave the answer alone
  when the memory is not about the question.

The repository would contain only the routes and their descriptor, never
Mistral's weights. Load the pinned upstream revision as it is. With LTWS off,
the model is the upstream model.

This is a research artifact, not an official Mistral release and not a
general upgrade of the model.

## Evidence

All figures come from sealed, offline-verified runs on held-out worlds:
128 world pairs and 1,024 questions, 256 of them affected by the paired fact
change.

| System | Accuracy, right memory | Accuracy, random memory | Flips / under random memory | Worlds in the memory's direction | Lane A verdict |
| --- | --- | --- | --- | --- | --- |
| Mistral alone, facts as text in the prompt (cut 0) | 0.74–0.76 | 0.50 | 55 / 6 | 90 of 128 | `CONTENT_REACHES_ANSWERS` |
| Mistral alone, latent memory at layer 4 | 0.58–0.60 | 0.50 | 44 / 3 | 54 of 128 | `NOT_ESTABLISHED` |
| **LTWS β routes, latent memory at layer 4** (seeds 1 / 2 / 3) | 0.84–0.85 | 0.50 | 58 / 4, 59 / 4, 60 / 4 | 83, 85 and 80 of 128 | `CONTENT_REACHES_ANSWERS`, `CONTENT_REACHES_ANSWERS`, `NOT_ESTABLISHED` |
| Mean of the three routes (descriptive) | 0.85–0.86 | 0.50 | 65 / 4 | 85 of 128 | `CONTENT_REACHES_ANSWERS` |

- **Flip:** both the intact and the changed fact set give their own
  (different) correct answer to the same question.
- **Verdict:** `CONTENT_REACHES_ANSWERS` needs at least 26 flips, 20 more
  than under random memory, and a world-level sign test at α = 0.001.
- **The pre-registered criterion is not met.** Every seed must reach the
  verdict, and seed 3 is two worlds short on the sign test.
- **With random, unrelated or no memory,** the routes move the answer by
  0.01–0.09 in the logit gap. With the right memory they move it by 4.2–4.3.

Records:
- [depth ladder](../../provenance/pilots/v20_a2_depth_ladder_20261016/README.md)
  (the first two rows);
- [A5](../../provenance/pilots/v20_a5_stable_route_20261018/README.md) (the
  routes);
- [package checks](../../provenance/beta/ltws_beta_rehearsal_20261018/README.md).

## Intended use and limits

- **Use:** research on how a frozen language model can read memory it did not
  see in context, and controlled evaluation.
- **Task family only:**
  - synthetic ranking worlds (six entities from a pool of twelve, five
    "ranked above" facts each);
  - questions in one English format ("Is A ranked above B? Answer:" or "Does
    A outrank B? Answer:");
  - yes/no answers;
  - nothing else is evaluated.
- **Not provided:** no general question answering, no text generation through
  the route, and no claim about reasoning, intelligence, safety or quality
  elsewhere.
- **Inherited:** the upstream model's limitations, including its lack of
  moderation mechanisms.
- **Memory hygiene:** conflicting or untrusted facts are read as given. Check
  memory provenance.

## Training

- **Data:** the frozen model's states on the train split (256 world pairs,
  both fact sets).
- **Route:** each route trains alone on CPU in FP32, 512 updates of 32
  questions, AdamW at 3e-4, with the learning rate decaying linearly after
  update 256.
- **Content gating:** every update also reads each question with another
  world's facts that do not name both of its entities. The route's residual
  there is pushed toward zero (weight 0.3).
- **Separation:** the held-out worlds above were never trained on.

## Loading

Pending a tested inference-only package from a clean environment. The engine's
[`package`](../../src/latent_workspace/package.py) module is the loader the
checks use (`load`, then `LatentMemory.write` and `.read`). No snippet is
published until a release route is chosen and tested from the export alone.

## License and provenance

- **Upstream:** the model declares Apache-2.0.
- **Pending:** the license of the new code and route weights, required
  notices and redistribution clearance.
- **Provenance:** source commits, plan hashes and every receipt are linked
  from the records above.
- No affiliation with or endorsement by Mistral AI is implied.
