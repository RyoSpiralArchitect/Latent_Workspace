# LTWS β on the Hub — private upload record

2026-10-18. **Uploaded to a private repository and verified from a fresh
download, twice. Ryō then asked to make it public.**

## Ryō's decisions (2026-10-18)

The account, the name and the procedure ("うん、そのアカウントであってる!
名前はRyo Higa / RyoSpiralArchitect でゆこう! やり方もそれで良きだよ"):

- **Repository:** `RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta`.
- **Copyright holder:** Ryo Higa / RyoSpiralArchitect.
- **Procedure:** a private repository first, then the same check on a fresh
  download, then public on Ryō's final OK.

The β release itself stays Apache-2.0. The source repository became
AGPL-3.0-or-later the same day (#29).

## What was uploaded

- **The folder:** release candidate **rc3**, built at
  `3e55594a3dce2bec06536e20a3177e7fd4f4cfa9`; its manifest's SHA-256 is
  `343ee4c4dc43bfc155859714419377c09f134ad223ea6434dbd4672aaf43d714`.
- **Checked first:** before the upload, rc3 passed the full user-path check
  ([record](../ltws_beta_release_candidate_20261018/README.md),
  [rc3](../ltws_beta_release_candidate_20261018/rc3/)).
- **Where it was uploaded from:** Furnace, whose `hf` CLI (1.27.0) is logged in
  as `RyoSpiralArchitect`. The token was never read or printed.
- **How:**
  - `hf repos create … --type model --private` (the repository did not exist
    before);
  - `hf upload …`, Hub commit `eb370d716662a8c46085a87072a754dbb14f7dbc`.
- **On the Hub** ([state](HUB_STATE.json)): private; 27 files, which are
  rc3's 26 plus the Hub's `.gitattributes`. The routes' LFS SHA-256 values and
  sizes equal the manifest's.

## Verified from a fresh download

1. **Download:** `hf download … --revision eb370d71… --local-dir` into a new
   folder, `tmp/ltws-beta-hub-download-20261018` on Furnace. `MANIFEST.json`
   is byte-identical, and `package.load` passes on the download: every file's
   hash, both routes' fingerprints.
2. **The full user-path check:**
   [check_ltws_beta_release.py](../../../scripts/check_ltws_beta_release.py),
   isolated, with only the downloaded copy's own `latent_workspace` (the
   import path is confirmed). [Output](check_release.out),
   [timeline](TIMELINE.log), [script](run_hub.sh):
   - 1,024 / 1,024 prompts;
   - 6,144 / 6,144 host logits and final states, bitwise;
   - 6,144 / 6,144 answers (largest score difference 1.9e-6);
   - lane A's verdicts equal A5's for every route and for their mean: 65 / 4,
     85 of 128 worlds, `CONTENT_REACHES_ANSWERS`.
3. **`example.py`:** run from the download. Its [output](example.out) is
   identical to the card's, including the wrong third answer.
4. **Afterwards:** the copy still loads, and no cache files were written
   ([output](reload.out)).

## Second revision: the rewritten card and the benchmarks

Ryō then asked for a card that first-time readers can follow, simple benchmarks
against the base model, and an open repository linked from GitHub ("さらに技術詳細
や意図に踏み込んで初見にわかりやすいふうに書き換えて … open repoにしてGitHub
Repoからもリンクを貼ってみよう").

- **rc4:** built at `06053d80f2c15a3322649075d739524ccddeedc1` with the
  rewritten card ([rc4](../ltws_beta_release_candidate_20261018/rc4/), manifest
  `a2bdba37…34e14c`). It passed the same user-path check with the same numbers.
  - The routes and the loader are unchanged.
  - The [benchmarks](../ltws_beta_benchmarks_20261018/README.md) in the card
    were run with the first revision, `eb370d71`.
- **Upload:** rc4 went to the still-private repository as Hub commit
  `2a55dc3e56e6f07aa4977bd21f5ee893a157b18c`. No LFS file changed.
- **Check from a fresh download:** that revision was downloaded into
  `tmp/ltws-beta-hub-download2-20261018` and checked in full
  ([download2/](download2/), [Hub state](download2/HUB_STATE.json)):
  - the manifest is byte-identical;
  - 1,024 / 1,024 prompts;
  - 6,144 / 6,144 host logits, final states and answers;
  - lane A's verdicts equal A5's for every route and for their mean;
  - `example.py` gives the card's output, and nothing was written into the
    folder.

## Remaining

The repository goes public after #28 is merged, so that the card's links to the
source repository resolve.
