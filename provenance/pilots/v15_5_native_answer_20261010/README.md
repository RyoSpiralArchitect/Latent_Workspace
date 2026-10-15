# V15.5 native answer/completion learner: engineering path completed, no winner

2026-10-10. **COMPLETED_ENGINEERING_PILOT**. Both matched arms completed eight
workspace-only updates, all **576 evaluation rows** and **80 bounded greedy
sequences**. Native logits changed after finite updates; the answer-only arm
also changed generated text. Neither arm improved the measured choice accuracy,
counterfactual donor direction, or strict generation/termination outcomes.
The old expression gate remains **FAIL**, `winner: none`,
`semantic_promotion: false`, `non_regression: NOT_ESTABLISHED`.

This is an exposed two-world engineering experiment, not a held-out capability
comparison, successful instrument repair, full-backbone FT, or FT-beta release.
The additional judge-call count is **zero**. The heartbeat remains paused.

## Scope and immutable sources

The [prospective protocol](../../../docs/v15_5/NATIVE_ANSWER_LEARNER.md) and
[plan](../../../configs/v15_5/NATIVE_ANSWER_PLAN.json) were committed and pushed
before execution at `4b796ed4f3bfc157e6f46b5da5ea3e1777552b0c`.
[STARTED.json](raw/STARTED.json) binds 271 source/data files, runtime, PID and
admission state. The [terminal report](raw/REPORT.json) records unchanged source
and independently loaded pinned-base identity before and after the run.

- Base: `mistralai/Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`, frozen BF16 backbone.
- Learner: 4,200,192 FP32 bridge/writer parameters in 26 tensors; fresh seed 47,
  final-position reader, native chat with Answer cue, canonical literal fact
  order and FP32 residual cap 1.0. Both arms have the same initial state hash.
- `native_answer`: native full-vocabulary answer-token CE, EOS coefficient 0.
- `native_answer_eos`: the same answer CE with coefficient 1, **plus** EOS CE
  with coefficient 1 after the graph-verified answer. All other factors match.
- Both arms retain the same donor hinge, unaffected-gap, unrelated-gap and
  residual penalties. These are not full-vocabulary preservation losses.
- Eight AdamW updates per arm, learning rate 0.0001, weight decay 0.01,
  gradient clipping at 1.0. No continuation or hyperparameter selection followed.

There are **two previously exposed training worlds**, eight queries per world,
and both factual sides: 16 pairs / 32 answer rows per update, including four
affected and twelve unaffected pairs. Every update uses that same full set.
Both arms evaluate the completion features even when EOS has zero loss weight.
Targets come from the independently checked ranking graph, not judge prose.
No answer label enters the answer writer/reader; the teacher-forced completion
prefix is explicitly answer-conditioned. Inference never receives oracle tokens.

The user-authorized return to engineering work did not qualify the failed old
instrument. Relative to historical V14, renderer, reader and readout changed
together; the isolated comparison here is **EOS coefficient between these two
new arms**, not a one-factor improvement over V14.

## Valid diagnoses retained, not converted into training gold

The immutable [diagnostic continuation](../v15_5_diagnostic_judge_continuation_01_20261010/README.md)
remains at **343/512 valid main diagnoses**, eight ambiguous outcomes and 161
never-dispatched requests. Its 32 fixed repeats retain 31 valid and one invalid
response: 25 equal, six differing, one invalid pair. All 544 OpenAI study/repeat
requests remain calibration-blocked. Combined status remains
`INCOMPLETE_OR_CALIBRATION_BLOCKED`; there is no two-provider study consensus.
No missing call or invalid label was retried, repaired, or silently dropped.

Among 87 diagnosed native-chat inline outputs, 29 strict failures comprised
13 contradictions, 13 wrong commitments, two format-only candidates and one
grounding case. That supports keeping answer content separate from stopping;
it does not identify a causal repair. All 82 diagnosed inline length failures
were raw-rendered, while two native length stops in the complete bank remained
undiagnosed. These selected, correlated diagnoses motivate the learner factors
only. They are not human gold or prevalence estimates.

## Learning losses: components, not a cross-arm total-loss contest

[Answer training log](raw/native_answer_training.jsonl) and
[answer-plus-EOS log](raw/native_answer_eos_training.jsonl) contain every update.
The logged loss is computed **before** the named update; update-8 loss therefore
describes parameters after seven updates, not a fresh final-state evaluation.

| Component | Shared pre-update 1 | Answer CE arm, pre-update 8 | Answer + EOS arm, pre-update 8 |
|---|---:|---:|---:|
| Full-vocabulary answer CE | 1.469184 | 1.387551 | 1.432977 |
| Answer-conditioned EOS CE | 6.053280 | 6.071205 | 5.822753 |
| Donor hinge | 0.250000 | 0.250000 | 0.250000 |

EOS CE in the first arm is an unsupervised diagnostic, not part of its objective.
The total losses have different objectives and should not be ranked against
each other. Both arms updated parameters finitely; all 26 parameter tensors
had nonzero accumulated gradient norms before update 8. Initially only the
zero-initialized output projection had a nonzero gradient. This establishes
gradient reachability, not correct content-dependent learning.

## Native choice evaluation: visible transport without donor separation

Steps 0, 1 and 8 each contain 16 world/query prefixes under six memory controls:
intact, twin, reversed intact, reversed twin, written-zero and unrelated.
That is 96 rows per arm/checkpoint and **576 total**, not 576 independent tasks.
[SUMMARY.json](SUMMARY.json) retains each checkpoint and all denominators.

| Step-8 measurement | Answer CE | Answer CE + EOS |
|---|---:|---:|
| Intact choice correct | 8/16 | 8/16 |
| Twin choice correct | 8/16 | 8/16 |
| Reversed intact / reversed twin correct | 8/16 / 8/16 | 8/16 / 8/16 |
| Positive donor-signed margin changes, affected pairs | 0/4 | 0/4 |
| Both factual sides correct, affected pairs | 0/4 | 0/4 |
| Full logits changed, nonzero-memory controls | 80/80 | 80/80 |
| Written-zero full logits changed | 0/16 | 0/16 |
| Intact/twin two-choice score vectors exactly equal | 16/16 | 16/16 |
| Intact/unrelated two-choice score vectors exactly equal | 14/16 | 16/16 |
| Maximum absolute full-logit change, intact | 0.2500 | 0.1875 |

The four truth-bearing conditions also scored 8/16 at steps 0 and 1. All four
affected donor-signed changes are exactly zero at every measured checkpoint.
No new same-prefix base-correct choice errors occurred in those conditions,
but this small query-only base has no ranking facts and starts at 8/16. That is
**not** an equal-information base floor or non-regression qualification.
Zero/unrelated memory has no authoritative task truth in choice evaluation;
its correctness fields remain `null`.

At step 8 the 80 nonzero-memory FP32 residual norms range from
0.977392–0.979106 (answer) and 0.978704–0.979069 (answer + EOS), close to the
cap-one smooth bound. The BF16-applied residual norm is a different quantity:
its maxima are 1.050578 and 1.034795. The FP32 cap and selected-row bound were
never claimed as native-arithmetic bounds; this is not a widened tolerance.

Equal two-choice vectors do not prove equal full-vocabulary tensors or absent
subthreshold information. The observations are consistent with a substantial
memory-nonspecific output shift, but this experiment does not establish its
mechanism, a global memory collapse, or a failure for every future objective.

## Actual generation: retain every truncation and wrong answer

Each arm/step has four exposed reciprocal queries and five conditions:
20 sequences, at steps 0 and 8, for **80 total**. Greedy decoding is capped at
16 new tokens; validity requires the whole stripped/case-folded text to be
exactly `no` or `yes` **and observed EOS**. No first-word rescue or extra-text
deletion is permitted. This cap is a new bounded pilot budget, not a replacement
for the old 64-token failure gate.

The following table holds separately at both measured steps of both arms:

| Condition | Strict correct | Valid one-word + EOS | Length-limited |
|---|---:|---:|---:|
| Query-only base | 0/4 | 0/4 | 4/4 |
| Base with inline facts | 2/4 | 4/4 | 0/4 |
| Intact workspace | 0/4 | 0/4 | 4/4 |
| Twin workspace | 0/4 | 0/4 | 4/4 |
| Written-zero workspace | 0/4 | 0/4 | 4/4 |

The answer-only arm changed 4/20 sequences from step 0 to step 8: intact and
twin text for two of the four queries. The EOS arm changed 0/20. Within each
arm, intact/twin generated token IDs remain exactly equal for all 4/4 queries
despite opposite targets. Base/zero token IDs match throughout. Token changes
show that native updates reach generation, **not** useful semantic divergence.

For the illustrative `w0 q0` query, the intact target is `yes` and twin target
is `no`. All three snippets below stop by length at 16 tokens. These are literal
outputs, not representative samples or approved reasoning:

Base, both arms and steps; also both workspaces at step 0:

```text
No (as Galen is a historical figure, a physician, and Kest
```

Answer CE, step 8, **both intact and twin**:

```text
no (Galen was a Roman physician, and Kestrel is a fict
```

Answer CE + EOS, step 8, **both intact and twin**:

```text
No (as Galen is a historical figure, a physician, and Kest
```

The full [80-output bank](GENERATION_BANK.md), raw token IDs and per-token
readout traces are retained. A lowercase `no` at the start is not a valid whole
answer, and a world-irrelevant physician explanation is not ranking-grounded
reasoning. Correct-answer-conditioned EOS loss falling does not imply that
free generation visits the supervised answer prefix or selects EOS there.
In this example the first token also changes from `No` to `no`. Training
targets one exact lowercase alias, so redistribution among answer spellings is
an alternative contributor to the CE reduction, not proof of improved truth
selection. The complete alias-mass contribution was not measured here.

## What to keep and what to investigate next

1. **Keep the verified native path.** Loss, finite updates and actual generation
   share the full-prefix/full-vocabulary native readout. Preserve written-zero
   identity, architecture-owned arithmetic, the independently loaded base,
   exact targets and the separate answer/EOS coefficients.
2. **Investigate content selectivity before scaling update count.** A next
   separately specified train-only diagnostic should decompose each loss's
   writer/Q/K/V/output gradients, reciprocal cancellation, common versus
   intact–twin residual components, cap compression and pre-/post-BF16 donor
   margins and answer-alias redistribution. Current aggregate gradient norms
   cannot choose among these causes.
   Retain final/pooled-reader and schema/random-memory controls as isolated
   candidates; do not change reader, gain and objective together.
3. **Keep EOS as a factor, not the presumed fix.** Compare the teacher-forced
   correct-answer prefix with prefixes actually reached by greedy generation.
   Lower EOS CE without observed termination is not success. No extra judge is
   needed to establish this pilot's negative result.
4. **Protect the FT-beta goal.** The earlier
   [keep/strengthen/add plan](../../../docs/v14/FT_BETA_IMPROVEMENT_PLAN.md)
   remains: preserve concise, calibrated verification behavior, improve grounded
   content use, add missing capabilities, and qualify against an independent
   pinned-base correctness floor. Fresh matched answer banks, natural multi-turn
   behavior, random/schema controls and human review remain untested here.

These are proposals, not newly run experiments or automatic permission to
continue past the eight-update pilot. No winner, semantic promotion or release
claim follows from lower training loss or changed wording.

## Execution, validation and retained weights

Furnace RTX 5090; Python 3.14.4, Torch 2.13.0+cu132, Transformers 5.15.0,
CUDA 13.2. Both arms and all measurements took **70.012593 seconds** in the
runner. Torch peak allocation was **15,167,136,768 bytes (14.125497 GiB)**;
peak reserved memory 14.277344 GiB; sampled own-process peak 15.001953 GiB;
minimum sampled device-free memory 16.337891 GiB. These counters differ and
sampled extrema are not continuous guarantees. No other job was interrupted.

- [Local prelaunch](PRELAUNCH_VALIDATION.json): 232 selected tests passed;
  Ruff passed. Its pending remote status is historical, not rewritten.
- [Remote prelaunch](REMOTE_PRELAUNCH_VALIDATION.json): the same 232 tests
  passed on the exact execution source. Remote Ruff was unavailable; no package
  installation was attempted. Lint is a local result on identical source.
- 361 ordinary/shared-native full-logit parity forwards on 138 unique prefixes
  passed in-process. Base/source identities remained exact. Four saved bridge
  checkpoints round-tripped exactly in-process; subsequent independent remote
  `sha256sum` and byte-size checks match the terminal receipts.
- Offline frozen verifier replay passes for all 18 raw files, 576 evaluation
  rows, 80 sequences, loss-accounting tolerances and literal bank. It does not
  independently reload the full model/tensors or re-decode token strings.
- The [post-result descriptive audit](inspect_receipts.py) replays token-pair,
  gradient-count, cap and resource observations into
  [OBSERVATIONS.json](OBSERVATIONS.json). It is not part of the prospective gate.
- The old cue bundle and original/continuation diagnostic seals and analysis
  replay still pass. Original diagnostic files and failed gates remain intact.
  See [publication checks](PUBLICATION_VALIDATION.json) and
  [terminal handoff](EXECUTION_HANDOFF.md). No CI, PR or merge is claimed.

The four bridge checkpoints (steps 4 and 8 for **each** condition) remain on
Furnace, 16,808,981 bytes each, about 64.1 MiB total; no backbone copy or weight
deletion was made. Their SHA-256 values are in [REPORT.json](raw/REPORT.json).
Exact remote directory:

```text
/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v15-5-native-answer-20261010/runs/v15_5_native_answer_20261010
```

Local evidence is the Git-tracked bundle containing this README. To verify it
without training, generation, network or API calls, from the repository root:

```sh
PYTHONPATH=src:scripts .venv/bin/python scripts/verify_v15_5_native_answer.py --bundle provenance/pilots/v15_5_native_answer_20261010
.venv/bin/python provenance/pilots/v15_5_native_answer_20261010/inspect_receipts.py
```

Do not use `--write` against existing derived artifacts and do not relaunch the
completed learner run. Further FT needs a separately bounded next-step plan.
