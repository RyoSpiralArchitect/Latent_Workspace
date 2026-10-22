# V23 gradient audit 01 — complete, no training

Both roles completed under source `66467502064b08b1ea8e246edc6696bd9d35a60e`:
[`FINISHED.json`](furnace/raw/FINISHED.json) reports
`V23_TRAIN_ONLY_GRADIENT_AUDIT_COMPLETE_NOT_TRAINING`, with no error.
Parent elapsed time is 9,102.471 seconds; base 168.752 seconds and V22 8,929.009
seconds. Both recorded workers are absent. Offline terminal replay passed on
Furnace and locally before any new owner changes.

The [publication manifest](furnace/PUBLICATION_MANIFEST.json) binds 71 public
files / 5,022,431 bytes, plus the manifest itself. The 122,160,008-byte private
teacher safetensors body remains on Furnace; private source token arrays were
not copied. The transfer archive SHA256 is
`743437fc843dea3445e026ee33052b05936544fbb56653a3ba8068049db72872`.
The older `interim_furnace/` snapshot remains unchanged. All 761 frozen source
files and all role manifests replay. Future replay after engine changes must
use the original execution checkout, not claim current-source equivalence.

## Complete denominators and engineering results

- CPU and CUDA qualification: 338/338 each, no failures/errors/skips.
- Both real-7B W+Q+R canaries: 291/291 tensors within the frozen
  `1e-4 + 0.03 * full_gradient_max_abs` bound. This is not bitwise gradient-sum
  equality. Trace/no-trace and detached-reader logits/losses are exact.
- World panel: 84 unique train rows, **14 group-level units**, 532 targets:
  identity 256, copy 100, format 176, mixed 0. Affected/unaffected/absent/unrelated
  row counts are 28/28/14/14. These are not 84 independent worlds.
- Preservation: 12 complete English train rows, four instruction/prose/code
  each, 932 targets. All 12 base targets cover the full 32,768-entry vocabulary,
  FP32 log probabilities at temperature one. Not a retention benchmark.
- Parameter backwards: CE 12, KL 12, world total 84, identity 84, copy 24,
  format 84, mixed 0. The copy term explicitly retains 60 zero-component rows;
  mixed retains 84 zero rows. No hidden missing rows or retries.
- All 70 nonempty-memory rows have cut-state component VJPs; 14 absent controls
  use the native bypass. Their state counts are identity 228, copy 100, format
  148, mixed 0. Parameter W/Q/R separation is only one canary per model, not
  an all-panel path decomposition.
- Both native hashes remain unchanged. Base:
  `9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189`;
  V22: `d2a6e4f2a9861a211289f3300b98fa9e2877b23a79f254661dd2305912bf2f70`.
  Peak CUDA allocation is 19,091,351,552 bytes (17.7802 GiB) in each role.
- Two owned scratch gradient sums were hashed and retired by the frozen runner;
  they were not model checkpoints. Native updates, checkpoint saves, generated
  sequences, provider calls and weight deletions are all zero.

## What the completed diagnostic says

The exclusive [descriptive analysis](ANALYSIS.json), produced by [analyze.py](analyze.py),
uses whole-panel denominators for parameter gradients. Cut-state statistics
retain their separate per-row total-token denominator.

| World term | Loss contribution / 532 targets | Parameter L2 | Cosine with preservation CE | Cosine with preservation KL |
| --- | ---: | ---: | ---: | ---: |
| Total | 0.1616391504 | 131.086924 | +0.007890 | -0.020744 |
| Identity | 0.1600518533 | 130.706069 | +0.008385 | -0.020014 |
| Later copy | 0.0005102418 | 4.573467 | +0.012215 | -0.030390 |
| Format / stopping | 0.0010770540 | 1.453501 | -0.083035 | +0.041436 |
| Mixed | 0 | 0 | null | null |

Preservation CE is 2.010581580 (gradient L2 72.343881); forward KL is
0.0322628534 (L2 24.985453), each divided by 932 targets. Identity accounts for
99.0180% of remaining world CE in this panel, not 99% of generation errors or
of the earlier factorial's repairs. Independently rounded BF16 gradients and
floating reductions need not sum exactly across separately evaluated terms.

World-total versus KL has negative dots in 238/291 tensors. The total cosine
is small in magnitude; it is -0.021132 in the canary-reachable lower-only block
(37 tensors) and -0.021714 in the reader-only block (254 tensors). W and Q share
the lower parameters. These are local, unpreconditioned gradients at V22, not
Adafactor updates, a catastrophic conflict, or proof that KL will improve quality.

For total loss, pooled row-normalized cut-state RMS values are memory 0.0427254,
question 0.0312162 and continuation 0.0400998. The median **per-row** question /
memory RMS ratio is 1.234979 (70 nonzero-memory-gradient rows); for identity it
is 1.145509. The ratio of pooled RMS values is a different statistic. This
instrument does not support assuming universally negligible Q-state gradients.
It measures neither parameter update visibility nor useful latent deliberation.

## Consequence for the next experiment

Keep Q amplification and extra copy/geometry losses out of the first comparison.
Test ordinary-host preservation as a separate P factor, using the native shared
owner and an explicitly versioned CE+KL objective. Ordinary CE and logit
preservation have different local directions here; neither is a substitute for
an untouched base-retention evaluation. Use equal initialization/data/budgets
and qualify exact update/save/fresh-process replay before comparing full FT.

The expanded world bank remains available for a later matched data factor.
Do not simultaneously change P, data, LR, precision and recurrence, and do not
fit the exposed MMLU or late-copy errors. The 12-row target bank is diagnostic,
not automatic coverage of a future training schedule. See the
[objective-owner contract](../../../docs/v23/OBJECTIVE_OWNER_CONTRACT.md).

No new winner or release: **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
