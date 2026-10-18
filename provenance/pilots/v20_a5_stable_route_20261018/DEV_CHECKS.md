# V20 A5 — a stable end of training for the gated route (development, not evidence)

2026-10-18. After [A4](../v20_a4_gated_route_20261017/README.md), Ryō asked to
merge and keep moving toward the LTWS β. A4's gated route met lane A's
endpoint in two seeds of three. The third was scored at update 512 right after
a late loss spike, under a constant learning rate. These checks ask how much
the last updates move the result, and which end of training removes that.

**Setup** (scripts in [dev/](dev/), Furnace dev checkout at A4's `6bf97c2`):
- [dev_capture.py](dev/dev_capture.py) extracts A4's development rows once:
  - memory at cut 4, rows in the ladder's train order;
  - train worlds 0–191 give each row's own facts and its mismatch memory, the
    first world stepping by 97 through 0–191 that does not name both
    entities;
  - train worlds 192–255 give the held-out conditions.
- All 4,096 own rows equal the sealed ladder's stored features bitwise.
- [dev_stable.py](dev/dev_stable.py) trains A4's gated route with the engine's
  `training.update(mismatch=...)` and weight 0.3, with D1's settings otherwise.
- **Seeds:** the three sealed seeds 2026101711–13 and three more, 2026101714–16.
- **Rule:** lane A's, as written. Its thresholds were set for twice this size
  (64 held-out worlds, 128 affected questions). Raw output is in
  [OUTPUT.jsonl](dev/OUTPUT.jsonl).

## How much the last updates move a constant-rate route

The same constant-rate trajectory, read on the held-out worlds at five
updates:

| Seed | Flips at 448 / 480 / 496 / 504 / 512 | Accuracy (intact) at the same updates |
| --- | --- | --- |
| 2026101711 | 33 / 9 / 19 / 25 / 20 | 0.877 / 0.705 / 0.855 / 0.863 / 0.859 |
| 2026101712 | 32 / 27 / 24 / 20 / 18 | 0.891 / 0.875 / 0.832 / 0.867 / 0.855 |
| 2026101713 | 24 / 17 / 31 / 31 / 20 | 0.875 / 0.854 / 0.877 / 0.893 / 0.830 |
| 2026101714 | 16 / 29 / 35 / 26 / 20 | 0.834 / 0.865 / 0.885 / 0.857 / 0.828 |
| 2026101715 | 34 / 13 / 27 / 28 / 17 | 0.883 / 0.842 / 0.887 / 0.875 / 0.834 |
| 2026101716 | 23 / 26 / 27 / 30 / 30 | 0.863 / 0.877 / 0.881 / 0.883 / 0.879 |

Within 64 updates, one seed's flips range from 9 to 33 and its accuracy from
0.71 to 0.88. Random-pair flips stay at 2 throughout. Under a constant rate,
where training stops decides much of the score. That is A4's seed 1 in
miniature.

## Three ways to end training

| End of training | Flips (6 seeds) | Random | Accuracy intact / twin | Training-row accuracy | Worlds + of 64 | Answer moved by random memory |
| --- | --- | ---: | --- | --- | --- | --- |
| constant, update 512 (A4) | 17–30 (mean 20.8) | 2 | 0.828–0.879 / 0.787–0.871 | 0.825–0.877 | 42–45 | 0.013–0.317 |
| exponential average of the weights (0.99) | 27–35 (mean 29.5) | 2 | 0.881–0.887 / 0.850–0.861 | 0.871–0.884 | 41–42 | 0.017–0.057 |
| uniform average of updates 385–512 | 24–36 (mean 30.0) | 2 | 0.881–0.898 / 0.848–0.865 | 0.873–0.888 | 42–43 | 0.015–0.052 |
| **linear decay of the learning rate after update 256** | **29–36 (mean 32.3)** | 2 | **0.887–0.896 / 0.852–0.867** | 0.877–0.887 | 42–46 | 0.023–0.078 |

- **All three remove the swing.** Every seed lands at 0.88–0.90 accuracy.
- **Decay is best and simplest:**
  - It gives the most flips and the highest, tightest accuracy.
  - Over its last 32 updates the training loss is lowest (0.25–0.28, against
    0.30–0.37 constant), and so is its peak over the last 64 (0.47–0.60,
    against 0.61–1.08).
  - It needs no extra state, so a checkpoint and a fresh-process replay stay
    as they are.
- **At this size,** two decay seeds already meet the full-size rule as
  written: 33 flips with p = 8e-4, and 34 flips with p = 3e-4.
- **Choice for the sealed design:** A4's gated route, unchanged except for the
  learning rate. It stays at 3e-4 to update 256, then falls linearly:
  3e-4 × (513 − step) / 257, reaching 1.2e-6 at update 512.
