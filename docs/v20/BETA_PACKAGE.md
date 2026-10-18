# The LTWS β package

2026-10-18. **PUBLIC:
[RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta](https://huggingface.co/RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta)
(revision `2a55dc3e`).** It was uploaded privately and verified from fresh
downloads, then made public on Ryō's request. After A5, Ryō chose to start packaging the β alongside the
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

## Decisions

**Taken by Ryō on 2026-10-18** ("うん、これでいこう!!"):

- **Members:** the β reads the **mean of the three routes**. A5's
  pre-registered rule named seed 1 alone, and only if every seed passed. The
  mean was descriptive in A5, so choosing it here, after A5, is a release
  choice, not an evaluation result. The card says so.
- **License:** **Apache-2.0** for the new code and the route weights, as for
  the upstream model.
- **Merges:** A5 (#26) and the rehearsal (#27) were merged into `main`.

**The release candidate** follows from these:
- **Contents:** the routes, the descriptor with the mean as the default
  reading, the engine's `latent_workspace` package copied unchanged from a
  clean commit, an example, the card, `LICENSE` and `NOTICE`.
- **Sources:** the folder is built by
  [build_ltws_beta_release.py](../../scripts/build_ltws_beta_release.py) from
  [release/ltws_beta/](../../release/ltws_beta/).
- **Check:** [check_ltws_beta_release.py](../../scripts/check_ltws_beta_release.py)
  loads the folder as a user would. It runs isolated, with only the folder's
  own code and transformers' loader, and recomputes lane A from the release's
  readings. Record:
  [release candidate](../../provenance/beta/ltws_beta_release_candidate_20261018/README.md).

**Taken by Ryō later the same day** ("うん、そのアカウントであってる!
名前はRyo Higa / RyoSpiralArchitect でゆこう! やり方もそれで良きだよ"):

- **Repository:** `RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta`.
- **Copyright holder:** Ryo Higa / RyoSpiralArchitect, in `NOTICE` and the
  card.
- **Procedure:** a private repository first, the same check on a fresh
  download, then public.
- **The source repository** became AGPL-3.0-or-later (#29). The β release stays
  Apache-2.0: its copy of the loader is licensed so by the copyright holder, as
  `NOTICE` states.

**Done:** release candidate rc3 passed the check, was uploaded to the private
repository (Hub commit `eb370d71`), and passed the full check again from a
fresh download ([record](../../provenance/beta/ltws_beta_hub_private_20261018/README.md)).

**Then (Ryō, "さらに技術詳細や意図に踏み込んで初見にわかりやすいふうに書き換えて …
open repoにしてGitHub Repoからもリンクを貼ってみよう"):**
- **Card:** rewritten for first-time readers.
- **Benchmarks:** simple ones against the base model were added
  ([record](../../provenance/beta/ltws_beta_benchmarks_20261018/README.md)).
- **Release:** the second revision (rc4) was checked from a fresh download, and
  the repository was made public.
- **Links:** the GitHub README links the model.
