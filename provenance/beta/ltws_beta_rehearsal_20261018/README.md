# LTWS β package — rehearsal record

2026-10-18. **PASS: the package reproduces A5's sealed routes and scores,
from the stored features and end to end from text. Nothing uploaded; no Hub
repository created.** Design and open decisions:
[BETA_PACKAGE.md](../../../docs/v20/BETA_PACKAGE.md). Ryō chose this step
after A5 ("2でいこう").

## Where it ran

- **Code:** commit `0de69b2d0dfe836cb3d42ec96fd3b0aa6f4fd2b1` on
  `SpiralReality/ltws-beta-package`, transferred as `beta.bundle` (SHA-256
  `2f26f344…19d9d2`).
- **Checkout:** the Furnace dev checkout
  `worktrees/latent-workspace-v20-a5-dev-20261018`, clean before and after.
  The package's tests, the architecture rules and the stack ran there first:
  54/54.
- **Records read:**
  - A5 attempt 02 (`tmp/latent-v20-a5-stable-route-attempt02-20261018/raw`);
  - the depth ladder's and A4's pinned records, rehashed by the export.
- **Steps:** [run_beta.sh](run_beta.sh) ran once
  ([timeline](TIMELINE.log), UTC):
  - export 18:30:39Z–18:34:39Z;
  - the route check, exit 0 at 18:35:02Z;
  - the text check, exit 0 at 18:37:03Z.
- **The package:** stays on Furnace at
  `tmp/ltws-beta-package-rehearsal-20261018/package`. The three route files
  are 11,931,620 bytes each. Their hashes are in [MANIFEST.json](package/MANIFEST.json);
  the [descriptor](package/descriptor.json) is copied here. The route weights
  are not in git; the export rebuilds them from the sealed records.

## Results

**Export** ([output](export.out)): each A5 stable route was retrained from
the pinned records (78–79 s each). Its parameter fingerprint equals A5's
sealed record, so the exported weights are the sealed routes:

| Member | Seed | Fingerprint (= A5's `stable_s{i}` at update 512) |
| --- | --- | --- |
| `s1` | 2026101711 | `1f1647596b6b…3eb0a9` |
| `s2` | 2026101712 | `4ced0b029f0d…d2f35a` |
| `s3` | 2026101713 | `949a1e281a90…4f904bd` |

**Route check** ([output](check_routes.out); CPU, fresh process, the package
alone):
- Every member's scores on the ladder's 8,192 final rows equal A5's sealed
  scores, bitwise.
- Lane A's verdicts recomputed from them equal A5's:
  `CONTENT_REACHES_ANSWERS`, `CONTENT_REACHES_ANSWERS`, `NOT_ESTABLISHED`.
- The members' mean gives `CONTENT_REACHES_ANSWERS` with A5's flips.

**Text check** ([output](check_text.out); GPU): the latent-memory API ran end
to end from text, through the pinned Mistral, for all 1,024 final questions.
Each question was read with its intact facts, its twin facts and no memory:
3,072 readings in 103 s.

| Check | Equal |
| --- | --- |
| rendered question = stored prompt ids | 1,024 / 1,024 |
| memory tokens = the run's memory tokens | 3,072 / 3,072 |
| host's answer logits = stored, bitwise | 3,072 / 3,072 |
| question-position final states = stored, bitwise | 3,072 / 3,072 |
| answer of every member = A5's | 3,072 / 3,072 |

- **One question at a time:** the API reads one question per call, while A5
  scored rows in batches of 64. Its route outputs lie at most 1.9e-6 from A5's
  scores (float rounding of the batched matrix products), and no answer
  changes.

## What this shows

- **Rebuildable:** the β package can be rebuilt from the sealed records alone,
  and loads from its own files.
- **Equivalent to the sealed system:** from plain fact text and plain
  questions, the package gives the sealed run's answers. It needs only the
  two texts; the host and the routes do the rest.
- **Not shown:**
  - a release decision, a namespace or a license;
  - behavior outside this task family;
  - any change to the lane A record (`NOT_ESTABLISHED` by the all-seeds rule).
