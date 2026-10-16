# V20 A2 depth ladder — results

2026-10-16. **All 18 roles complete and verified. Read depth: the frozen host
alone reads the memory at cut 0, and with v4's route the system reads it at
cut 4.**

- **Cut 0** (the facts as a text prefix): the frozen host reaches
  `CONTENT_REACHES_ANSWERS`. This is the first time lane A's endpoint has
  been met in this project. D1's route meets it in every seed, with flips
  rising from 55 to 71–118 of 256.
- **Cut 4** (a latent memory: the facts' own states after four layers,
  computed apart from the question): the host alone answers weakly, and not
  in the donor's direction. With the route, the system answers from the
  memory: 0.79–0.83 accuracy, against 0.50 with random memory. It reaches
  `CONTENT_REACHES_ANSWERS` in two of three seeds, which makes
  `DIRECTIONAL_ONLY` by the all-seeds rule.
- **Cut 8 and deeper:** nothing passes. V16–V19 wrote their memory at cut 16.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

- **Source:** execution commit `1daa358d0a745fc71baa62aefef3c9858dc1920b`,
  bound by the [654-file seal](furnace/SOURCE_SEAL.json) (SHA-256
  `caaeb0b7…5fccf6`), byte-identical on Furnace and locally.
- **Design:** the design and endpoint were frozen before launch in
  [A2_DEPTH_LADDER.md](../../../docs/v20/A2_DEPTH_LADDER.md); the
  [handoff](EXECUTION_HANDOFF.md) records the dev checks and the disk
  retirement that preceded launch.
- **Dispatch:** one detached [dispatch](furnace/launch_v20_a2_depth_ladder.sh)
  (UTC, [timeline](furnace/LAUNCH_TIMELINE.log)):
  - CPU qualification at 09:09:34Z (58/58);
  - CUDA qualification at 09:09:41Z (58/58);
  - ladder from 09:09:50Z, ending `ladder exit=0` at 09:40:29Z.

| Process | Status | Elapsed |
| --- | --- | ---: |
| `extract_cut{0,4,8,16}` (GPU; peak CUDA 15,446,395,904 bytes) | `V20_A2_DEPTH_FEATURES_EXTRACTED` | 213.0–222.5 s |
| `route_cut{k}_s{1,2,3}` ×12 (CPU, 8 threads; route then readout) | `V20_A2_DEPTH_ROUTES_COMPLETE` | 73.6–79.2 s |
| `replay` (`route` at cut 4, seed 1, update 257 from 256) | `V20_A2_DEPTH_FRESH_PROCESS_EXACT_REPLAY` | 3.1 s |
| `endpoints` | `V20_A2_DEPTH_ENDPOINTS_COMPLETE` | 2.2 s |

- **Rows per cut:** 4,096 train rows (each side's own facts) and 8,192 final
  rows (1,024 questions × 8 conditions).
- **Parity:** on 192 rows per cut, the head on the final states equaled the
  decoder continued from the cut, bitwise. At cut 0 it also equaled the
  inline forward of the memory text followed by the question.
- **Storage:** the features (about 21 GiB) and the twelve update-256
  checkpoints stay on Furnace; their hashes are in the role manifests.

## Pre-registered endpoint (final split, update 512; 256 affected questions, 128 worlds)

Lane A's rule from V19, unchanged: at least 26 flips, at least 20 more than
random memory, and the world sign test at α = 0.001. A flip is the intact
answer under the intact facts and the twin answer under the twin's.

| Cut | Arm | Flips / random | Worlds +/− | p | Verdict |
| ---: | --- | --- | --- | ---: | --- |
| 0 | host | 55 / 6 | 90 / 38 | 2.5e-6 | **`CONTENT_REACHES_ANSWERS`** |
| 0 | route s1 / s2 / s3 | 118 / 20, 75 / 10, 71 / 11 | 114/14, 109/19, 115/13 | 6e-21, 8e-17, 7e-22 | **`CONTENT_REACHES_ANSWERS`** (all seeds) |
| 4 | host | 44 / 3 | 54 / 73 | 0.96 | `NOT_ESTABLISHED` |
| 4 | route s1 / s2 / s3 | 66 / 24, 54 / 32, 21 / 46 | 84/44, 84/44, 85/43 | 3e-4, 3e-4, 1e-4 | **`DIRECTIONAL_ONLY`** (s1, s2 content; s3 directional) |
| 8 | host | 10 / 12 | 60 / 53 | 0.29 | `NOT_ESTABLISHED` |
| 8 | route s1 / s2 / s3 | 36 / 13, 14 / 0, 19 / 11 | 69/59, 81/47, 78/50 | 0.21, 0.002, 0.008 | `NOT_ESTABLISHED` |
| 16 | host | 2 / 16 | 42 / 49 | 0.80 | `NOT_ESTABLISHED` |
| 16 | route s1 / s2 / s3 | 14 / 1, 10 / 4, 0 / 0 | 58/70, 59/69, 60/68 | 0.87, 0.83, 0.79 | `NOT_ESTABLISHED` |

**Read depth (pre-registered summary):** host 0, route 4.

The readout control (descriptive) gives `DIRECTIONAL_ONLY` at cut 0 (seeds 2
and 3 content, seed 1 margin 8). It gives `NOT_ESTABLISHED` at cut 4 (seeds
directional, directional, not established) and at cuts 8 and 16.

## Descriptive (declared before launch)

Accuracy on all 1,024 final questions (host; route over its three seeds):

| Cut | Memory | Twin | Random | Reversed | Unrelated | None |
| ---: | --- | --- | --- | --- | --- | --- |
| 0 | host 0.74, route 0.85–0.90 | 0.76, 0.87–0.90 | 0.50, 0.50 | 0.73, 0.86–0.89 | 0.49, 0.51 | 0.53, 0.50–0.51 |
| 4 | host 0.58, route 0.79–0.83 | 0.60, 0.81–0.83 | 0.50, 0.49–0.51 | 0.61, 0.80–0.82 | 0.50, 0.47–0.50 | 0.53, 0.48–0.50 |
| 8 | host 0.50, route 0.52–0.65 | 0.52, 0.53–0.65 | 0.49–0.51, 0.49–0.50 | 0.49, 0.55–0.62 | 0.50, 0.48–0.50 | 0.53, 0.49–0.50 |
| 16 | host 0.53, route 0.50–0.51 | 0.52, 0.50–0.51 | 0.48–0.51, 0.49–0.50 | 0.53, 0.50–0.53 | 0.53, 0.50–0.51 | 0.53, 0.50–0.51 |

From [descriptive.py](descriptive.py) ([output](DESCRIPTIVE.json)), which
reads the receipts only:

- **Reversed-memory agreement** (the same answer under intact facts and the
  same facts in reverse order): host 0.66–0.68 at cut 0 and 0.74–0.76 at cut
  4; route 0.83–0.89 at both. The route is closer to reading content than
  surface order. At cuts 8 and 16 agreement is high only because answers
  barely depend on memory.
- **Training-split accuracy at update 512** (route): 0.90–0.92 at cut 0,
  0.82–0.87 at cut 4, 0.57–0.72 at cut 8 and 0.50–0.55 at cut 16. The host
  alone scores 0.78, 0.61, 0.51 and 0.51.
- **Unaffected predictions changed** between intact and twin (of 768): host
  122 at cut 0 and 119 at cut 4; route 30–33 at cut 0 and 41–64 at cut 4.

## What it means

1. **The depth wall is located.** The frozen Mistral reads facts it saw
   only from cut 0. Facts that ran on their own through four layers are
   still largely recoverable with a learned readout of its final states.
   From cut 8 on, its remaining layers make almost no use of them. V16–V19
   wrote memory at cut 16, past this wall, which plausibly explains their
   zero flips.
2. **Cut 0 is the positive anchor.** The frozen host with the facts as a text
   prefix meets the endpoint. The machinery and the rule can therefore show
   content use, and D1's route roughly doubles the flips (a readout gap, as
   in D1).
3. **Cut 4 is the first latent memory the system reads.** Accuracy is
   0.79–0.83 against 0.50 with random memory, and the route flips more
   content-specifically than the host. The host alone flips 44 affected
   answers, but its gap changes are not donor-directed across worlds (54
   against 73).
4. **Why cut 4 stops at directional.** Seed 3's route answers random memory
   inconsistently, producing 46 random-pair "flips" against 21 real ones.
   Lane A's margin over random memory is the guard that catches this.
5. **For the next step (Ryō's option 3, and possibly the β).** Nothing
   requires the workspace to sit high in the network. A workspace that
   writes its memory into the lower layers (cut ≤ 4) is where the host's own
   reading can meet it. The cut-4 memory here is uncompressed: one state per
   fact token. Writing a compact memory at a shallow cut, so that a route
   meets the endpoint in every seed, is the open problem.
6. **Scope.** Frozen backbone, this task family, held-out worlds. The result
   says nothing about the native head without the route, general reasoning,
   non-regression or language quality.

## Verification

- **Receipts:** all 237 pulled receipt files are byte-identical to Furnace.
- **Sealed verifier:** [verifier](../../../scripts/verify_v20_a2_depth_ladder.py),
  run from a clean clone of `1daa358`. It does the following:
  - rehashes the 654 sources, both qualification bundles, the dispatch and
    every role manifest;
  - checks every cut's row and condition counts;
  - checks that every route started exactly at the host's logits;
  - checks the replay;
  - recomputes every verdict from the saved scores with the runner's own
    function.

  The [local](OFFLINE_VERIFY_LOCAL.json) report is
  `OFFLINE_V20_A2_DEPTH_LADDER_RECEIPT_PASS`. The
  [Furnace](OFFLINE_VERIFY_FURNACE.json) report, from the sealed checkout
  with all eight feature files rehashed, is the same; only
  `features_rehashed` differs between the two.

Nothing was relaunched, no weight was deleted by the run, and nothing here
trains the backbone or generates text.
