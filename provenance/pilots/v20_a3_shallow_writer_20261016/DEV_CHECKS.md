# V20 A3 — a compact memory written into the lower layers (development, not evidence)

2026-10-16/17. Ryō's option 3 after the [depth ladder](../v20_a2_depth_ladder_20261016/README.md):
a workspace that writes a **compact** memory where the frozen host can read it.
The depth ladder showed the host reads per-token fact states at cut 0 (alone)
and cut 4 (with D1's route). These checks ask whether fewer, written slots can
take their place. All checks fit train worlds 0–191 (both sides) and read
lane A's flips on train worlds 192–255 (128 affected questions). Dev and final
are never touched. Scripts are in [dev/](dev/); they ran in the Furnace dev
checkout at `1daa358`. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

## 1. Untrained compression at cut 4 ([dev_pooled.py](dev/dev_pooled.py))

The facts' cut-4 states were pooled to one slot per line (header plus five
facts): the line mean, or the line's last token. Each version was injected at
cut 4 and read by the host alone and with D1's route (seed 2026101711).

| Memory | Slots | Host accuracy (intact / twin) | Host flips / random | Route accuracy | Route flips / random |
| --- | ---: | --- | --- | --- | --- |
| every token (the depth ladder's) | 61 | 0.57 / 0.58 | 23 / 2 | 0.87 / 0.84 | 20 / 28 |
| line mean | 6 | 0.47 / 0.49 | 0 / 17 | 0.50 / 0.50 | 0 / 5 |
| line's last token | 6 | 0.48 / 0.49 | 1 / 18 | 0.50 / 0.50 | 0 / 24 |

Pooled lines are not read at all. Compression has to be learned.

## 2. A writer trained through the frozen host by the answer ([dev_writer.py](dev/dev_writer.py))

- *Writer:* a small slot writer. Learned queries cross-attend over the
  facts' host states at cut `read`, and the output is projected to the host
  width at the median residual norm of cut `write`.
- *Training:* its slots enter at cut `write` before the question. The frozen
  host's own answer trains it, with cross-entropy on both sides and gradients
  through the host. AdamW, batch 8.

| Read | Write | Slots | Learning rate | Updates | Held-out accuracy | Flips / random |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 16 | 4 | 8 | 1e-4 | 768 | 0.51 / 0.52 | 0 / 14 |
| 4 | 4 | 8 | 1e-4 | 768 | 0.50 / 0.49 | 0 / 14 |
| 16 | 0 | 8 | 1e-3 | 1,536 | 0.50 / 0.50 | 0 / 9 |
| 4 | 4 | 8 | 1e-3 | 1,536 | 0.49 / 0.50 | 0 / 12 |
| 16 | 4 | 32 | 1e-3 | 1,536 | 0.50 / 0.50 | 0 / 22 |

The training loss went from about 0.75 to ln 2 (0.693) and stopped. The writer
found the content-free solution: it neutralizes the host's per-question bias
and makes it unsure, instead of telling it the facts. This is the same trap as
V19's memory-independent shift.

## 3. A paired content term ([dev_writer2.py](dev/dev_writer2.py), `pair`)

This adds a pairwise term to the answer loss. For each affected question, the
gap under intact memory minus the gap under twin memory should point to the
intact answer, and no content-free shift can satisfy it. Read 16, write 4,
8 slots, learning rate 1e-3, 1,536 updates of 4 questions × both sides.

Result: held-out 0.50 / 0.51, 0 flips against 13 random, worlds 15 / 23. It
did not learn either.

## 4. An autoencoding writer (ICAE-style) ([dev_writer2.py](dev/dev_writer2.py), `ae`)

- *Pretraining:* the writer reads the facts' cut-16 states and writes 8 soft
  tokens at cut 0. The frozen host, reading them before the fact text,
  reproduces that text under a teacher-forced next-token loss. 2,000 steps of
  batch 8 over 4,474 memories: train worlds 0–191 and 2,045 generated training
  worlds, both sides.
- *Then:* the paired answer objective of section 3, 1,536 updates.

| Phase | Loss |
| --- | --- |
| reproduction, step 400 → 2,000 | 0.289 → 0.120 |
| answers after pretraining (cross-entropy) | about 0.63–0.76 |

The writer learns to put the facts into 8 soft tokens the host can expand
back into the text. Answering through them still failed: held-out
0.51 / 0.51, 1 flip against 16 random.

## 5. What the autoencoding slots carry, and whether answers come through them ([dev_writer3.py](dev/dev_writer3.py))

Same writer: read 16, write 0, 8 soft tokens, 4,000 autoencoding steps
(reproduction loss 0.258 at step 500, 0.019 at step 4,000). It was then
frozen and measured on the held-out memories of train worlds 192–255, which
it never saw:

| Slots before the fact text | Reproduction loss | Entity tokens right |
| --- | ---: | ---: |
| the writer's 8 slots | **0.046** | **0.90** |
| norm-matched random slots | 2.773 | 0.17 |
| no slots | 2.595 | 0.15 |

**A compact memory works for reproduction.** Eight soft tokens at the host's
lowest layer carry an unseen world's facts well enough for the frozen host to
write them back, with nine entity names in ten right.

**It does not yet work for answers.** With the question after the slots, the
host alone scored 0.48 / 0.49 (7 flips against 29 random). D1's route, fitted
on the host's final states, scored 0.50 / 0.50 (3 against 20). The host can
unroll the facts from the slots, but cannot read "is A ranked above B?" from
them in one pass.

## 6. Context distillation from the host reading the text ([dev_writer4.py](dev/dev_writer4.py))

- *Teacher:* the frozen host reading the fact text before the question. This
  is the depth ladder's cut 0, which met lane A's endpoint.
- *Student:* the same host reading the writer's 8 soft tokens.
- *Training:* after an autoencoding warm start, the writer is trained so
  that the student matches the teacher. The loss is KL on the answer plus
  cosine distance of the final states at the question positions, on 35,792
  question rows from train worlds 0–191 and the generated worlds (no labels
  needed). 3,000 steps of batch 8.

| Run (seed) | Warm-start reproduction loss | Distillation, final | Student held-out | Teacher held-out |
| --- | --- | --- | --- | --- |
| 2026101751, 2,000 autoencoding steps | stuck at 1.08–1.13 | KL 0.45, cosine distance 0.55 | 0.50 / 0.50, 0 flips / 23 random | 0.77 / 0.79, 32 flips |
| 2026101741, 4,000 autoencoding steps | 0.184 → 0.019 | KL 0.54, cosine distance **0.09** | 0.48 / 0.51, 7 flips / 30 random | 0.77 / 0.79, 32 flips |

- **Seed sensitivity:** in one seed of two the autoencoding warm start did
  not take off.
- **States matched, answers did not:** from a good warm start, the
  student's states at the question positions came within 0.09 cosine
  distance of the teacher's, yet its answers did not follow (KL stayed near
  0.5, accuracy at chance). The part of the state that carries the answer is
  what the slots fail to supply.
