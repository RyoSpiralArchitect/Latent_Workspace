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
- **Choice for the sealed design:** λ = 0.3, from training worlds only. It
  will be run against the ungated route in the same sealed run.
