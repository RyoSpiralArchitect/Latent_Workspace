# V20 A2 — power checks before freezing (development, not evidence)

2026-10-16. A1's lesson was to check, before launch, that a plan's own settings
can detect planted content at real scale. The A2 draft failed that check, so
A2 was not frozen, sealed or launched. These development checks decide the
design; they are recorded here with their scripts in [dev/](dev/). Nothing here
touched the dev or final splits. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

## The draft that was checked

- **Memory:** V19's writer input. That is the host residual stream at cut 16
  of the canonical facts text, encoded on its own, so the host never sees the
  facts with the question.
- **Question:** the cut-16 states of the question-only prompt.
- **Workspace:** D1's lattice route from the engine
  (`composition.DeliberationRoute`) over the packed [memory; question] states,
  into v4's gated logit residual.
- **Training:** cross-entropy on both sides of every training world, with D1's
  settings (learning rate 3e-4, 512 updates, batch 32).
- **Endpoint:** lane A's flip endpoint, unchanged (`availability.diagnose`).

## Checks

1. **Planted relational memory at real width**
   ([planted_binding.py](dev/planted_binding.py), local, synthetic).
   - *Setup:* each fact's second entity carries the first (`B + 0.7·R·A`), so
     an answer needs the question's order matched against the memory. 256
     training worlds × 16 rows, 128 held-out worlds.
   - *Result:* nothing learned. The training loss stayed at ln 2 for every
     combination tried (learning rate 3e-4 / 1e-3 / 3e-3; 512–2,048 updates;
     zero, opened-attention, tied query-key and stronger attention-step
     initializations). No setting produced a flip.
2. **Planted direct memory at real width**
   ([planted_direct.py](dev/planted_direct.py)).
   - *Setup:* one memory token carries ± a fixed direction for the answer.
   - *Result:* the route as drafted, with D1's settings, reaches 0.996 on
     held-out rows by update 128. The plumbing works; relational retrieval is
     what never starts.
3. **Real features, train split only, on Furnace**
   ([dev_extract_train.py](dev/dev_extract_train.py), dev checkout `1fe66c8`).
   - *Extraction:* passed native and cut-16 parity bitwise on every question
     row. 2,048 questions (≤ 57 tokens) and 1,280 memories (≤ 63 tokens) took
     89 s, with a 14.1 GiB CUDA peak. The question-only base is at chance:
     999 / 2,048 for the intact answers.
   - *Within-train power check* ([dev_power.py](dev/dev_power.py)): fitted on
     worlds 0–191 (both sides); lane A's flips read on worlds 192–255 (128
     affected questions).

   | Initialization | Learning rate | Updates | Last training loss | Held-out accuracy (intact / twin) | Flips (actual / random) | Unaffected predictions changed |
   | --- | ---: | ---: | ---: | --- | --- | ---: |
   | as drafted (zero output paths) | 3e-4 | 512 | 0.696 | 0.54 / 0.52 | 0 / 4 | 0 |
   | as drafted | 1e-3 | 1,024 | 0.678 | 0.51 / 0.50 | 0 / 0 | 0 |
   | opened attention output | 1e-3 | 1,024 | 0.688 | 0.48 / 0.51 | 0 / 0 | 0 |
   | opened attention output | 3e-4 | 2,048 | 0.627 | 0.54 / 0.52 | 4 / 13 | 9 |

   In the first three rows, every held-out prediction was the same for
   intact and twin memory: the route ignored the memory. With 2,048 updates it
   began to use memory to fit its training worlds (loss 0.627) without
   generalizing: 4 held-out flips against 13 for random memory.
4. **A logit map on V19's read output**
   ([dev_v19_transport.py](dev/dev_v19_transport.py)). A1's update-256 train
   features, the same within-train split.
   - *Setup:* an L2 logistic map from a single memory's read output to the
     answer (not a difference of two).
   - *Result:* 0.52–0.57 even on its own training rows. Held out it was at
     about 0.5, with 2–12 of 128 affected questions flipped (random memory:
     0). The content A1 found in V19's read output shows only as an
     intact-minus-twin difference, too weak to carry an answer alone.
5. **The frozen host reading a cut-16 memory prefix**
   ([dev_prefix.py](dev/dev_prefix.py)), with no training.
   - *Setup:* the facts' cut-16 states were placed before the question's
     (memory first, or after the question's BOS), and the decoder continued
     from cut 16.
   - *Result:* accuracy 0.48, against 0.49 for the base without facts, and
     2–3 of 128 affected questions flipped. The upper half does not use facts
     the lower half never saw.

## What it means

Launched as drafted, A2 would almost surely end `NOT_LEARNED`. The v4 lattice
route behaves as a readout. It learns quickly when the answer is already in a
host state (D1, facts inline) or sits directly in a memory token (check 2).
Within these budgets it does not begin to learn relational retrieval from a
memory encoded apart from the question. The answer-residual readers of
V16–V19 (0 flips) and the V19 read output (check 4) meet the same wall. A2 now
needs a design decision.
