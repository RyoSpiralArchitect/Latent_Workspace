# The LTWS β package (rehearsal)

2026-10-18. **PACKAGING REHEARSAL: nothing uploaded, no Hub repository
created.** After A5, Ryō chose to start packaging the β alongside the
research ("2でいこう"). This builds and checks the package that a release
would ship, from V20 A5's sealed routes. Whether to release, and what, stays
Ryō's decision under the [release checklist](../v18/HF_RELEASE.md).

## What the β is in this line

The A line keeps **Mistral-7B-Instruct-v0.3 frozen**, so the β adds to the
upstream model and changes none of its weights.

- **Latent memory:** facts are run alone through the host's first four layers
  once. Their states can be cached; the facts never enter the question's
  context.
- **Reading:** a question is run alone through the same four layers. The
  memory's states enter before the question's at layer 4, and the host's own
  remaining 28 layers continue.
- **Route:** A5's stable gated route reads the host's final states at the
  question positions. It adds a gated low-rank residual to the two answer
  logits (" no" / " yes"). It was trained to leave the answer alone when the
  memory is not about the question.

With LTWS off, the model is the upstream model, unchanged.

## The package

Built by the engine's [`package`](../../src/latent_workspace/package.py)
module:

| File | Contents |
| --- | --- |
| `route_s1.safetensors`, `route_s2.safetensors`, `route_s3.safetensors` | the parameters of A5's three stable routes (seeds 2026101711–13) |
| `descriptor.json` | the host (repository, pinned revision, base hash; weights not included), the cut, the candidates, the prompt contract, the route architecture, each member's fingerprint and source, and A5's evidence |
| `MANIFEST.json` | every other file's bytes and SHA-256 |

The engine's latent-memory API:

- **`load(path)`:** rebuilds the routes from the package alone, after
  checking the manifest and every route's fingerprint.
- **`LatentMemory(host, tokenizer, descriptor, routes)`:**
  - `write(facts)` returns the latent memory of a fact text: its canonical
    lines, run alone to layer 4.
  - `read(question, memory)` returns the host's own answer logits, each
    route's, and their mean, plus the answer. The question must end with the
    answer cue " Answer:".

## How the package is built and checked

1. **Export** ([export_ltws_beta.py](../../scripts/export_ltws_beta.py)):
   - A5 saved scores and fingerprints, not final weights.
   - The script retrains each stable route exactly as A5's role did: A5's
     plan, the pinned records, deterministic CPU arithmetic.
   - It exports a route only if its fingerprint equals A5's sealed record, so
     the package holds the sealed routes, bit for bit.
2. **Route check** ([check_ltws_beta_package.py](../../scripts/check_ltws_beta_package.py)
   `routes`, CPU):
   - In a fresh process, the package alone scores the ladder's final features.
   - Every member's scores must equal A5's sealed scores bitwise.
   - Lane A's verdicts recomputed from them, and from their mean, must equal
     A5's.
3. **Text check** (the same script `text`, GPU): end to end from text, through
   the pinned host, for every final question under its intact facts, its twin
   facts and no memory.
   - Bitwise checks: the rendered prompt equals the stored prompt ids; the
     memory equals the run's memory tokens; the host's answer logits and
     final states equal the stored ones.
   - Reported: how far the API's one-question readings lie from A5's batched
     scores, and whether every answer agrees.

Results are recorded in the
[rehearsal record](../../provenance/beta/ltws_beta_rehearsal_20261018/README.md).

## What a β could and could not claim (from the sealed record)

- **Content (lane A), from A5:**
  - Two seeds of three meet the flip endpoint; seed 3 is two worlds short on
    the world sign test (80 of 128, needing 82).
  - The mean of the three meets it (descriptive).
  - By the all-seeds rule the verdict is `NOT_ESTABLISHED`, and a card must
    say so.
- **Behavior with irrelevant or absent memory:** random, unrelated or no
  memory moves the answer (the candidate gap) by 0.01–0.09, against 4.2–4.3
  with the right memory.
- **Scope:**
  - synthetic ranking worlds (six entities from a pool of twelve, five facts
    each), yes/no questions in a fixed English format;
  - not general question answering;
  - no text generation through the route;
  - no claim about reasoning, non-regression elsewhere or language quality.

## Decisions that are Ryō's

1. **Release:** whether and when. The all-seeds criterion is not met; the
   checklist leaves shipping with lane A not established to Ryō.
2. **Members:** one route (A5's pre-registered candidate is seed 1) or the
   mean of the three.
3. **Hub identity:** the namespace and repository ID. The provisional slug is
   `mistral-7b-instruct-v0.3-LTWS-beta`.
4. **License:** for the new code and the route weights. The upstream model
   is Apache-2.0.
5. **Contents:** besides the routes, which loader code (the engine's
   `package` module and what it imports), which examples, and whether to
   include the synthetic worlds.
6. **Card:** a review of the [model card draft](BETA_MODEL_CARD_DRAFT.md).
