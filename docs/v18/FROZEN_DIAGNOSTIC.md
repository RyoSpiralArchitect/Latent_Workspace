# V18 frozen-backbone selection diagnostic

2026-10-15. **FROZEN BEFORE LAUNCH.** After the [native pilot](NATIVE_PILOT.md)
showed exact 7B engineering integration but no memory-dependent answer change,
Ryō chose option B: freeze the backbone, train only the workspace for longer,
and test cheaply whether memory content can reach native answers at all before
spending full-update compute. The old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** is unchanged.

## Question and design

With pinned Mistral-7B frozen (`requires_grad=False`, eval mode, no native
update, no masters), do the 32 workspace tensors (writer 20 / common 6 /
interaction 6) learn, within 512 complete-window updates, to make intact versus
twin facts change native answers in the donor direction on held-out worlds?
And does the ordered operand-difference interaction query differ from the
final-state query?

Two matched arms run in sequence: **centered-ordered** and **centered-final**.
Both use the same reader initialization (seed 47 after construction), data
order, objective (the V15.5 terms used by every earlier V16/V18 run), bridge
AdamW 1e-4, per-family clip 1.0 and budget. Their run contracts differ only in
the declared condition and selection policy.

| Split | Source | World pairs | Questions | Affected | Use |
| --- | --- | ---: | ---: | ---: | --- |
| Train | `data/v10/functional_train.jsonl` | 256 | 2,048 | 512 | updates |
| Dev | `data/v10/functional_eval.jsonl` | 64 | 512 | 128 | descriptive curve only |
| Final | V16 population `functional.json` | 128 | 1,024 | 256 | pre-registered endpoint |

All 7,168 labels across the splits agree with the independent symbolic oracle,
including reversed fact order; every record has the fixed 2-affected / 6-
unaffected pattern and 4/4 label balance; the three splits share no pair ID,
order, twin set or context. Training uses only the "ranked above" wording;
dev/final also contain "outrank" questions (all unaffected). The final split
was evaluated before, on V16 checkpoints, but has never been trained on.

Schedule: four epochs, each a fixed `numpy` permutation (seeds 4701–4704) of
the 256 training worlds in consecutive pairs: 512 windows of 16 occurrences
(4 affected / 12 unaffected), the qualified historical denominators. Dev is
evaluated at updates 0/128/256/384/512 and final at 0/512, with the V16/V18
10-condition, 5-factor evaluation through the selection pipeline. Checkpoints
(about 50 MB each) are saved at 256 and 512. A fresh interpreter restores the
ordered arm's step-256 checkpoint and must replay window 257 exactly.

## Pre-registered endpoint (final split, update 512, fixed last step)

On the 256 affected final questions under actual intact/twin memory:

- **Flip**: intact prediction equals the intact label *and* twin prediction
  equals the twin label.
- **World sign test**: per world, sum the donor-directed gap change over its two
  reciprocal affected questions; exact one-sided binomial over worlds with a
  nonzero sum. Passes at p ≤ 0.001.
- **Chance control**: the same flip count under norm-matched random memories
  (`random_pair`).

| Verdict | Rule |
| --- | --- |
| `CONTENT_REACHES_ANSWERS` | sign test passes, at least 26/256 flips, and at least 20 more flips than random |
| `DIRECTIONAL_ONLY` | sign test passes without both flip criteria |
| `NOT_ESTABLISHED` | otherwise |

Selection comparison (paired on the same 256 questions): ordered minus final
flips ≥ 13 (5 pp) with exact one-sided McNemar p ≤ 0.01 is labelled
`ORDERED_SELECTION_ADVANTAGE_DIAGNOSTIC`; otherwise
`NO_SELECTION_ADVANTAGE_ESTABLISHED`. Validity requires every zero-memory row
to equal the frozen direct base exactly. No dev-based selection, no early
stopping and no threshold change after results. Accuracy by wording,
unaffected stability, the reversed/equal-slot/same-memory factors and the dev
curve are reported descriptively.

## Engineering and limits

Each arm and the replay are separate fresh processes behind the sealed source
launcher; the dispatcher stops at the first failure and never retries. Tiny CPU
and CUDA qualification (16 tests per device) must pass first. Every process
checks the 594 Furnace-qualified owner sources, the pilot plan, all three data
files and the canonical hash of this plan before importing project code. The
frozen 7B is hashed in full at the start and end of each arm; per window only
the trainable state, optimizer and RNG are fingerprinted. Evaluation records
are stored as deterministic gzip JSON.

Limits per process: 4 h, 2 CPU threads, a 30.5-GiB allocator cap and V16's
GPU/host/disk floors. A V16 frozen run measured about 0.3 s per backward pair;
the estimate here is roughly 45 min of updates and 30 min of evaluation per arm.

This diagnostic can show whether the memory pathway can carry facts into
answers with a frozen backbone, and whether the query factor matters there. It
does not establish a full-update result, base non-regression (the backbone is
unchanged by construction), language quality, a benchmark or release
readiness. No sequences, judge calls, native updates or deletions occur.

Runner: [run_v18_frozen_diagnostic.py](../../scripts/run_v18_frozen_diagnostic.py);
plan: [FROZEN_DIAGNOSTIC_PLAN.json](../../configs/v18/FROZEN_DIAGNOSTIC_PLAN.json);
tests: [test_v18_frozen_diagnostic.py](../../tests/test_v18_frozen_diagnostic.py);
offline verifier: [verify_v18_frozen_diagnostic.py](../../scripts/verify_v18_frozen_diagnostic.py).
