# V23 base/off/on comparison 01 — qualified, evaluation in progress

Frozen execution source: `84073310cd7b2c56b5e3de046fb3bdc99e461bfb`,
774 sealed source files. The [plan](../../../configs/v23/COMPARISON_01.json)
and [design](../../../docs/v23/COMPARISON_01.md) define one inference-only
comparison with the same exposed V22 inputs and unchanged generation policy.
No checkpoint selection, new training, paid judge or release.

| Qualification | Tests | Failures / errors / skips | Seconds |
| --- | ---: | ---: | ---: |
| CPU | 223 | 0 / 0 / 0 | 56.879935 |
| CUDA | 223 | 0 / 0 / 0 | 64.958595 |

The eight local fresh-process exclusions **ran and passed on Furnace**.
CUDA qualification peak allocation was 67,325,952 bytes (a tiny-model
measurement, not a 7B memory estimate). Both gates were below the fixed
4-GiB / 900-second limits. No test was skipped or threshold adjusted.

The [read-only offline replay](verify_qualification.py) checks all 774
historical source bytes via Git, both plans and source seals, raw artifact
manifests, XML counts, activity ceilings and limits:

```sh
python3 -B provenance/pilots/v23_comparison01_20261022/verify_qualification.py \
  --root provenance/pilots/v23_comparison01_20261022/furnace --repo .
```

At `2026-10-21T22:48:30.838389Z`, the base role had started and loaded the
original 7B host. Its [start receipt](furnace/raw/base/STARTED.json) and the
[dispatcher start](furnace/raw/STARTED.json) establish launch only; no terminal
model evaluation receipt was present at that observation. Planned per arm:
570 MMLU items, 192 world scores/generations and 24 free generations.
Three-arm totals: 1,710 scores and 648 sequences. None of these planned
counts is asserted as completed here.

Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED**. The completed
[preceding FT result](../../engineering/v23_preservation_ft01_20261022/TERMINAL.md)
is separate from this evaluation. Follow the existing process using the
[handoff](EXECUTION_HANDOFF.md); do not launch another copy or create a monitor.
Private bodies/weights remain on Furnace and are not included in this bundle.
