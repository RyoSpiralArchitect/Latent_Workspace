# LTWS β on the Hub — upload record

2026-10-18. **PUBLIC:
[RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta](https://huggingface.co/RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta)
at revision `58f5203d`, the card's fourth revision.** It was first uploaded
privately and verified from a fresh download, twice, then made public at
revision `2a55dc3e` on Ryō's request. The third and fourth revisions were
verified from fresh downloads too
([third](#third-revision-free-generation-and-llm-judges),
[fourth](#fourth-revision-v10-is-planned-as-a-full-fine-tune)).

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

## Public

- **Before the switch:** #28 was merged first (`main` at `47d64c8`). All six
  links from the card to the source repository resolve there.
- **The switch:** the repository was set public with `huggingface_hub`'s
  `update_repo_settings(private=False)`, from Furnace's logged-in CLI
  environment. Its revision stayed `2a55dc3e56e6f07aa4977bd21f5ee893a157b18c`.
- **Checked without a token:**
  - `model_info` reports `private = False`, with 27 files;
  - `MANIFEST.json`, downloaded anonymously, has SHA-256
    `a2bdba37fb52ade5367d167a0c6b8879afa044d8f40797ec57654d45de34e14c`
    (rc4's);
  - the model page answers HTTP 200.
- **Links to the model:** the source repository's README and its V20 index
  (#28).

## Third revision: free generation and LLM judges

Ryō asked for the card to frame the benchmarks as a non-degradation check, to
show same-seed free generation from latent memory with LLM-judged quality, and
to lead readers to the source repository ("まずβのhf記述を整えて、元Repoにも辿り
着けるようにもしながら").

- **rc5:** built at `e29ccad` (manifest `46a47c39…6406b`) and checked
  ([record](../ltws_beta_release_candidate_20261018/README.md)). The card's new
  results are in the [generation record](../ltws_beta_generation_20261018/README.md).
- **Before the upload:** #31 was merged first (`main` at `a4760cc`). All eight
  links from the card to the source repository exist on `main` and answered
  HTTP 200 without a login.
- **Upload:** `hf upload` from Furnace's logged-in CLI (the token was never read
  or printed), Hub commit `d6a607905d53f454eafbd073dbf2af2eb3fff11f`
  ([output](download3/upload.out), [timeline](download3/UPLOAD_TIMELINE.log)).
  No LFS file was uploaded: the routes were already on the Hub, byte for byte.
- **On the Hub** ([state](download3/HUB_STATE.json)): public, 27 files. The
  routes' LFS SHA-256 values and sizes equal rc5's manifest.
- **Checked from a fresh download** of that revision, into
  `tmp/ltws-beta-hub-download3-20261018` on Furnace ([script](download3/run_hub3.sh),
  [timeline](download3/TIMELINE.log)):
  - `MANIFEST.json` and the card are byte-identical to rc5's;
  - the full user-path check passed with the download's own loader
    ([output](download3/check_release.out)): 1,024 / 1,024 prompts; 6,144 /
    6,144 host logits, final states and answers (largest score difference
    1.9e-6); lane A's verdicts equal A5's for every route and for their mean;
  - `example.py` printed the card's output ([output](download3/example.out)),
    and the folder still loaded afterwards with no cache files written
    ([output](download3/reload.out)).
- **Checked without a token, from the Mac:** the model page answers HTTP 200;
  the API reports revision `d6a60790`, public, 27 files; the card served from
  `main` equals [the repository's](../../../release/ltws_beta/README.md).

## Fourth revision: v1.0 is planned as a full fine-tune

Ryō's direction: the β is an adapter only to learn what a full fine-tune needs,
and the card should say that the next release is not an adapter ("hf repoのβの
記述にも次はadapterではないことも明記しておこう"). See
[BETA_PACKAGE.md](../../../docs/v20/BETA_PACKAGE.md).

- **rc6:** built at `02b2d3c` (manifest `2ea022c2…9693`) and checked
  ([record](../ltws_beta_release_candidate_20261018/README.md)). Only the card
  changed, with the descriptor and `NOTICE` naming the new source commit.
- **Before the upload:** #33 was merged (`main` at `fd26ea7`).
- **Upload:** Hub commit `58f5203da9d2c7e365daf1626e629f160de225a1`
  ([output](download4/upload.out), [timeline](download4/UPLOAD_TIMELINE.log)),
  from the same logged-in CLI. No LFS file was uploaded.
- **On the Hub** ([state](download4/HUB_STATE.json)): public, 27 files; the
  routes' LFS SHA-256 values equal rc6's manifest.
- **Checked from a fresh download** into `tmp/ltws-beta-hub-download4-20261018`
  ([script](download4/run_hub4.sh), [timeline](download4/TIMELINE.log)):
  - `MANIFEST.json` and the card are byte-identical to rc6's;
  - the full user-path check passed with the download's own loader
    ([output](download4/check_release.out)), with the same numbers;
  - `example.py` printed the card's output, and the folder still loaded
    afterwards with no cache files written.
- **Without a token:** the page answers HTTP 200; the API reports revision
  `58f5203d`, public, 27 files; the card served from `main` equals
  [the repository's](../../../release/ltws_beta/README.md).
