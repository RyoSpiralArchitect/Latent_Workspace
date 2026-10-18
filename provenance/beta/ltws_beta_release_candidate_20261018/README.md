# LTWS β release candidate — record

2026-10-18. **PASS: the release candidate, loaded as a user would load it,
reproduces A5's sealed readings and lane A verdicts. Not uploaded.** Ryō's
decisions ("うん、これでいこう!!"): the β reads the mean of the three
routes, under Apache-2.0. Design and remaining decisions:
[BETA_PACKAGE.md](../../../docs/v20/BETA_PACKAGE.md).

## The candidate (rc2)

- **Built by** [build_ltws_beta_release.py](../../../scripts/build_ltws_beta_release.py)
  in the Furnace dev checkout, clean before and after, at commit
  `54d82d65767b01adf3bb37988396fe80560ee23f`.
- **Inputs:** the checked rehearsal package and the templates in
  [release/ltws_beta/](../../../release/ltws_beta/).
- **Location:** Furnace,
  `tmp/ltws-beta-release-candidate-20261018/rc2/mistral-7b-instruct-v0.3-LTWS-beta`,
  35 MB, 25 files plus the manifest.
- **Manifest:** [MANIFEST.json](rc2/MANIFEST.json), SHA-256 `6552baf7…4fc017e`.

| Files | Contents |
| --- | --- |
| `route_s1/s2/s3.safetensors` | A5's three stable routes, byte-identical to the rehearsal's (`92a0bc34…`, `f3285747…`, `18e807be…`) |
| `descriptor.json` | [copy](rc2/descriptor.json): default reading the mean of `s1`–`s3`, `apache-2.0`, the loader's source commit and file hashes |
| `latent_workspace/` | the engine package (16 modules), copied unchanged from that commit |
| `README.md` | the model card ([source](../../../release/ltws_beta/README.md)) |
| `LICENSE`, `NOTICE` | the Apache-2.0 text; the [notice](rc2/NOTICE), whose copyright holder is still a placeholder |
| `example.py`, `requirements.txt` | the example; the tested versions (torch 2.13.0, transformers 5.15.0, safetensors 0.8.0) |

## The user-path check

[check_ltws_beta_release.py](../../../scripts/check_ltws_beta_release.py) ran
isolated (`python -I`, no `PYTHONPATH`; [script](rc2/run_rc2.sh),
[timeline](rc2/TIMELINE.log)).

- **Setup:**
  - its only project code was the release folder's own `latent_workspace`,
    and it confirmed the import path;
  - Mistral came from transformers at the pinned revision, loaded as
    `example.py` loads it;
  - the sealed records were read as data.
- **Scope:** every final question under its intact, twin, reversed and random
  memories. The random memories are V16's norm-matched control, made as the
  ladder made them.

| Check ([output](rc2/check_release.out)) | Result |
| --- | --- |
| rendered prompt = stored prompt ids | 1,024 / 1,024 |
| host's answer logits = stored, bitwise | 6,144 / 6,144 |
| question-position final states = stored, bitwise | 6,144 / 6,144 |
| every route's answer = A5's | 6,144 / 6,144 (largest score difference 1.9e-6) |
| lane A recomputed with the release's own `availability` module | equals A5 for every route and for their mean |

| Reading | Flips / random | Worlds +/− | p | Verdict |
| --- | --- | --- | --- | --- |
| `s1` | 58 / 4 | 83 / 45 | 5.0e-4 | `CONTENT_REACHES_ANSWERS` |
| `s2` | 59 / 4 | 85 / 43 | 1.3e-4 | `CONTENT_REACHES_ANSWERS` |
| `s3` | 60 / 4 | 80 / 48 | 3.0e-3 | `NOT_ESTABLISHED` |
| **mean (the β's default)** | 65 / 4 | 85 / 43 | 1.3e-4 | `CONTENT_REACHES_ANSWERS` |

- **`example.py`:** ran isolated from the folder
  ([output](rc2/example.out)). Its output is shown verbatim in the card,
  including the wrong third answer.
- **After both runs:** the folder still loads, and no cache files were written
  into it ([output](rc2/reload.out)).

**rc1**, built at `f248dd6` with the earlier card, passed the same check with
the same numbers ([rc1/](rc1/)). rc2 differs from it only in the card.

**rc3, the uploaded candidate**, was built at `3e55594` with Ryō's copyright
holder and repository ID ([rc3/](rc3/), manifest `343ee4c4…`). Its `NOTICE`
and card add the dual-license note. It passed the same check with the same
numbers. It was then uploaded privately and checked again from a fresh
download ([record](../ltws_beta_hub_private_20261018/README.md)).

## What the card now says about accuracy

Computed from the sealed records for the card, held-out, under the original and
the swapped facts:

- **Relations the swap leaves unchanged:** the β reads them from memory, at
  0.93 for "outrank" pairs 1–4 steps apart and 1.00 for the top and bottom of
  the ranking. Without memory these are 0.53–0.55.
- **The adjacent pair the swap reverses:** 0.55 / 0.57. Both versions are
  answered right for 65 of 256, against 55 for Mistral with the facts as text
  in its prompt and 4 under random memory.

## Before any upload (Ryō)

- **Hub repository:** furnace's `hf` CLI (1.27.0) is logged in as
  `RyoSpiralArchitect`. The repository ID is not inferred from that; it waits
  for Ryō.
- **`NOTICE`:** the copyright holder.
- **Publication:** the explicit go. Proposed order:
  1. a private repository;
  2. the upload;
  3. a download into a fresh folder, and the same check against it;
  4. public visibility only on Ryō's final OK.
