# V20 A4 — a content-gated workspace at cut 4 (development, not evidence)

2026-10-17. Ryō's fallback after [A3](../v20_a3_shallow_writer_20261016/DEV_CHECKS.md):
refine the low-layer workspace the [depth ladder](../v20_a2_depth_ladder_20261016/README.md)
already supports. The starting point is memory at cut 4 (the facts' own states
after four layers) read by D1's route over the host's final states. In the
sealed ladder it met lane A's endpoint in two seeds of three. The third fell
short only because random memory moved its answers: 46 random-pair flips
against 21 real ones.

**Refinement: content gating.** During training, rows whose memory is another
training world's facts are added, and the route's residual on them is pushed
to zero by a weight λ times the mean squared residual. The route should move
answers only when the memory is about the question. Lane A's Gaussian
random-pair control is never trained on. Fit on train worlds 0–191 (both
sides); read on train worlds 192–255 (128 affected questions), with lane A's
rule as written. Dev and final are never touched.
([dev_refine.py](dev/dev_refine.py), Furnace dev checkout at `1daa358`. The
first run took the weights 0 and 1.0 as fixed arguments; later runs take a
list.)

## 1. Gating at λ = 1.0 against the ungated route

| λ | Seed | Accuracy (intact / twin) | Flips / random | Worlds +/− (p) | Rule |
| ---: | --- | --- | --- | --- | --- |
| 0 | 2026101711 | 0.889 / 0.857 | 34 / 16 | 46 / 18 (3e-4) | `DIRECTIONAL_ONLY` |
| 0 | 2026101712 | 0.900 / 0.881 | 35 / 25 | 47 / 17 (1e-4) | `DIRECTIONAL_ONLY` |
| 0 | 2026101713 | 0.895 / 0.852 | 28 / 23 | 46 / 18 (3e-4) | `DIRECTIONAL_ONLY` |
| 1.0 | 2026101711 | 0.738 / 0.732 | 29 / 2 | 41 / 23 (0.016) | `NOT_ESTABLISHED` |
| 1.0 | 2026101712 | 0.748 / 0.738 | 27 / 3 | 39 / 25 (0.05) | `NOT_ESTABLISHED` |
| 1.0 | 2026101713 | 0.697 / 0.691 | 27 / 2 | 39 / 25 (0.05) | `NOT_ESTABLISHED` |

The host alone flips 23 against 2 (worlds 36 / 28). Random and unrelated
memory stay at chance accuracy in every row.

- **Gating works on the weak point:** random-pair flips fall from 16–25 to
  2–3, while real flips stay at 27–29, so the margin over random is met.
- **At λ = 1.0 it costs too much elsewhere:** the route becomes timid with
  the right memory too. Accuracy drops from about 0.88 to 0.72, and the world
  sign test weakens.

## 2. Lighter gating

| λ | Seed | Accuracy (intact / twin) | Flips / random | Worlds +/− (p) | Rule |
| ---: | --- | --- | --- | --- | --- |
| 0.1 | 2026101711 | 0.877 / 0.848 | 32 / 0 | 42 / 22 (0.008) | `NOT_ESTABLISHED` |
| 0.1 | 2026101712 | 0.871 / 0.834 | 23 / 3 | 43 / 21 (0.004) | `NOT_ESTABLISHED` |
| 0.1 | 2026101713 | 0.846 / 0.830 | 27 / 2 | 41 / 23 (0.016) | `NOT_ESTABLISHED` |
| 0.3 | 2026101711 | 0.830 / 0.814 | 28 / 2 | 44 / 20 (0.002) | `NOT_ESTABLISHED` |
| 0.3 | 2026101712 | 0.822 / 0.797 | 22 / 2 | 45 / 19 (8e-4) | `DIRECTIONAL_ONLY` |
| 0.3 | 2026101713 | 0.822 / 0.789 | 30 / 2 | 45 / 19 (8e-4) | `CONTENT_REACHES_ANSWERS` |

These checks are half the size of the final split (64 worlds, 128 affected
questions), while the rule's thresholds (26 flips, a margin of 20, α = 0.001)
were set for 128 worlds and 256 questions.

- **λ = 0.3 balances best:** random-pair flips stay at 2, accuracy at about
  0.81, and the donor direction is the strongest of the gated settings (44–45
  of 64 worlds).
- **At the final split's size** the flips and the world counts roughly
  double.
- **Choice for the sealed design:** λ = 0.3, from training worlds only.

## 3. Mismatch memories that state no answer ([dev_refine2.py](dev/dev_refine2.py))

The name pool has 12 names and a world uses 6. In 23% of the mismatch rows
above, the other world named both of the question's entities, so its facts
stated an answer. Gating pushed against reading them. This check changes three
things:

- **Mismatch memory:** the first world that does not name both entities,
  stepping by 97 through the training worlds (worlds 0–191 here). A first step
  was enough for 77% of rows, and none needed more than six.
- **Row order:** the ladder's train order (world, side, question).
- **Added measurements:**
  - the mean change of the candidate gap from the host's under each
    condition;
  - the complement-entity memory (the ladder's `unrelated` condition, no
    shared name);
  - the own rows against the sealed ladder's stored cut-4 features.

| λ | Seed | Accuracy (intact / twin) | Flips / random | Worlds +/− (p) | Gap moved: intact / random / complement | Rule |
| ---: | --- | --- | --- | --- | --- | --- |
| 0 | 2026101711 | 0.879 / 0.844 | 20 / 25 | 43 / 21 (0.004) | 4.56 / 4.67 / 2.93 | `NOT_ESTABLISHED` |
| 0 | 2026101712 | 0.891 / 0.836 | 25 / 20 | 46 / 18 (3e-4) | 4.34 / 4.34 / 2.64 | `DIRECTIONAL_ONLY` |
| 0 | 2026101713 | 0.768 / 0.766 | 7 / 9 | 43 / 21 (0.004) | 5.08 / 5.37 / 2.42 | `NOT_ESTABLISHED` |
| 0.3 | 2026101711 | 0.859 / 0.846 | 20 / 2 | 45 / 19 (8e-4) | 4.47 / 0.013 / 0.018 | `DIRECTIONAL_ONLY` |
| 0.3 | 2026101712 | 0.855 / 0.832 | 18 / 2 | 45 / 19 (8e-4) | 4.50 / 0.021 / 0.019 | `DIRECTIONAL_ONLY` |
| 0.3 | 2026101713 | 0.830 / 0.787 | 20 / 2 | 44 / 20 (0.002) | 3.71 / 0.029 / 0.019 | `NOT_ESTABLISHED` |
| 1.0 | 2026101711 | 0.830 / 0.818 | 12 / 2 | 43 / 21 (0.004) | 4.74 / 0.003 / 0.004 | `NOT_ESTABLISHED` |
| 1.0 | 2026101712 | 0.809 / 0.771 | 19 / 2 | 42 / 22 (0.008) | 3.41 / 0.076 / 0.011 | `NOT_ESTABLISHED` |
| 1.0 | 2026101713 | 0.721 / 0.732 | 7 / 2 | 43 / 21 (0.004) | 4.17 / 0.011 / 0.018 | `NOT_ESTABLISHED` |

The host alone: 0.57 / 0.58, 23 flips against 2.

- **The weak point, measured:** without gating, random memory moves the
  answer as much as the right memory (gap change 4.3–5.4 against 4.3–5.1).
- **With gating at λ = 0.3,** random memory moves it by 0.01–0.03 and the
  complement-entity memory by 0.02, while the right memory still moves it by
  3.7–4.5. This holds in every seed. Random-pair flips fall to 2, accuracy
  stays at 0.83–0.86, and 44–45 of 64 worlds point the donor's way.
- **Stability:** the ungated route's flips depend on the training trajectory
  (in this row order 7–25, in section 1's order 28–35). The gated route gave
  18–20 in every seed.
- **Mismatch definition:** accuracy at λ = 0.3 is a little higher than with
  section 2's definition (0.83–0.86 against 0.82–0.83). Flips are lower
  (18–20 against 22–30), but the row orders differ, so this is not a
  controlled comparison.
- **λ = 1.0** is too cautious again (7–19 flips). The sealed design keeps
  λ = 0.3, with this mismatch definition.
- **Reproduction:** all 3,072 own rows, extracted in this fresh process,
  equal the sealed ladder's stored cut-4 features bitwise (states and
  logits). The sealed run checks this on every 64th row.

## 4. The ladder's ungated route, retrained ([dev_reproduce.py](dev/dev_reproduce.py))

In a fresh process, the ladder's ungated cut-4 route of seed 2026101711 was
retrained from the stored features with the ladder's own code: 512 updates.
Every update receipt, the final fingerprint and the final scores on the final
split equal the ladder's records (48 s). The sealed run repeats this as its
first role, so the comparison with the ladder differs only by the gating.
