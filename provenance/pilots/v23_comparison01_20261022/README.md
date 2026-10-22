# V23 base/off/on comparison 01 — incomplete, stopped by our CPU qualification

## Terminal result, 2026-10-22

**INCOMPLETE_NO_RETRY.** Base and P-off finished. P-on retained only the first
79/570 MMLU scores, with no world/free-generation journal. Its terminal
`new_sequences` remains **null**, not an invented measured zero. The whole
three-arm comparison is incomplete; no winner, non-regression pass or release.

This was an **operator isolation error**, not evidence of a learner failure.
The concurrently launched MMLU-Pro **CPU qualification** process PID `3785302`
also became a GPU client (522,190,848 bytes in the evaluation's resource row).
P-on PID `3784672` observed it at `mmlu:79` and its existing exclusive-GPU
guard stopped correctly. The exact first CUDA-initializing API call is not
isolated; no unsupported claim about its origin is made. "CPU tests" had been
incorrectly assumed to mean "cannot initialize CUDA." We should have hidden
CUDA before importing the test runtime, or waited for the GPU job to end.
Do not weaken the guard, edit the frozen source, or relabel this as a pass.

The competing CPU suite passed 245/245 arithmetic/restore checks, but that
does not validate GPU isolation. It and the evaluation have exited; no task
was killed or automatically restarted. No MMLU-Pro model call, study judge,
weight update/save/deletion, PR or release was started afterward.

| Available endpoint | Base | P-off | P-on |
| --- | ---: | ---: | ---: |
| MMLU rows | 570/570 | 570/570 | 79/570, incomplete |
| World rows/sequences | 192/192 | 192/192 | 0 recorded / 192 |
| Free-generation answers | 24/24 | 24/24 | 0 recorded / 24 |

Complete-arm observations only: base/off MMLU is **356/570 vs 354/570**,
with two base-only correct and zero off-only correct items. Tie-free counts
are 351 vs 349; 15 vs 18 rows have tied top option logits. This reproduces
the exposed retention concern, not a fresh non-inferiority test. World exact
match is **47/96 vs 83/96 latent**, **75/96 vs 87/96 inline**. Free answers
end at EOS in 14/24 vs 15/24; the other 10/24 vs 9/24 hit the 256-token cap.
There is **no full P-on score** and no P-on-versus-off conclusion.

All raw terminal manifests, original source/qualification seals, available
scores, IDs, generation limits and native before/after hashes for the two
complete arms replay. A tokenizer-only check rebuilt the original inputs
exactly and decoded all **432 recorded sequences out of 648 planned**;
[decoding output](OFFLINE_DECODING.json) is retained. No model call was made
by this replay. [Terminal analysis](TERMINAL_ANALYSIS.json) preserves missingness:

```sh
python3 -B provenance/pilots/v23_comparison01_20261022/verify_terminal.py --verify-publication
```

Recovery is **not authorized/dispatched by this record**. Proposed: isolate
CPU qualification with `CUDA_VISIBLE_DEVICES=""` before imports, check that it
cannot create a CUDA context, and collect P-on from the start as a separately
identified attempt with the exact original settings. Preserve the old 79 rows
as an incomplete prefix, not part of a new full-arm score. Any combined view
must name the two source/attempt provenances explicitly. Existing base/off
results stay immutable. The judge's 32/32 calibration remains valid for its
frozen body/rubric, while its 174-call study is blocked on the complete bank.
MMLU-Pro's GPU qualification and all model calls remain undispatched until an
approved recovery updates the predecessor gate through a separate plan.

## Historical qualification and launch record

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
is separate from this evaluation. The [handoff](EXECUTION_HANDOFF.md) records
the terminal failure; do not launch another copy or create a monitor.
Private bodies/weights remain on Furnace and are not included in this bundle.
