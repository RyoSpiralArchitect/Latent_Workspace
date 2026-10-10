# V15 native learner: full updates and exact resume qualified; usable binding remains open

2026-10-10. Both bounded phases completed on Furnace. This is the first complete
native full-update learner qualification, **not a winning semantic model or an
FT-beta quality release**. The frozen-native milestone remains conceptually
V14.5; historical paths and negative results have not been renamed or replaced.

The key distinction is now executable: internal differences, usable
question/content binding, full-update mechanics and original-base preservation
are separate milestones. **Old expression FAIL / winner: none / non-regression
NOT_ESTABLISHED remain unchanged.**

## What was installed

The [learner state owner](../../../src/latent_workspace_ft_v10/v15_native_learner.py)
connects live current-parameter question/context features, a query-independent
writer, the explicitly named question-modulated reader, native residual
composition and the native full-vocabulary head. Normalization and layer
boundaries remain architecture-owned; only pinned Mistral-7B-Instruct-v0.3 is
qualified here. The historical engine and frozen reader were not edited.

Updates require every declared pair in its exact order. The native-dtype CPU
accumulation is consumed without restoring a full gradient volume to GPU.
Bridge AdamW is matched across conditions and clipped separately from the base;
full updates additionally own all **291 physical base tensors / 7,248,023,552
elements** through CPU FP32 masters and factored Adafactor. Each completed
update casts those masters back to native BF16 once. No diagnostic factor,
answer label or factual-side identifier enters an inference forward.

Checkpoint ownership includes reader class/strength, parameter aliases/schema,
masters, bridge, both optimizers, RNG and source/plan metadata. Only a completed
hash receipt admits a checkpoint. A resumed next update must reproduce exact
state and native weights; a merely successful load is insufficient.

## Frozen plan and denominators

The [prospective contract](../../../docs/v15/NATIVE_LEARNER.md),
[plan](../../../configs/v15/NATIVE_LEARNER_PLAN.json) and [source seal](SOURCE_SEAL.json)
bind execution to `3ee78fbd157174059cc3bbd52f05ea02938ec754`.
All arms start from original base hash
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`
and fresh seed-47 bridge tensors. This is not reuse of a trained candidate.

- Reader phase: legacy and query-modulated, eight bridge-only updates each.
- Full phase: fresh query-modulated frozen/full pair, two updates each. Each
  arm also replays update 2 from its step-1 checkpoint once, without generating
  or saving another checkpoint.
- Total: **20 distinct progression updates / 22 executed complete windows**;
  **320 progression pair-backwards + 32 replay pair-backwards = 352**.
  Every window has two worlds × eight questions. Reductions stay 32 answer/EOS,
  4 affected, 12 unaffected, 16 unrelated and 48 residual terms. EOS weight is zero.
- **1,152 evaluation rows**, **256 four-corner blocks / 1,024 corners**, and
  **160 greedy sequences**. Each phase contributes 576 evaluation rows and 80
  sequences. Generation uses four exposed queries × five conditions × two
  checkpoints × two arms, at most 16 new tokens per sequence.
- Only **two already-exposed worlds** were used. These correlated measurements
  are not 1,152 independent tests or a fresh held-out base-floor qualification.
  No paid judges, additional data selection or adaptive training extension ran.

## Outcome: transport and updates are real, but content binding is not qualified

The [derived comparison table](COMPARISON_TABLE.md), [machine-readable publication](PUBLICATION.json)
and [full scalar replay](SUMMARY.json) retain all denominators:

| Final comparison | Native correct | Positive donor / correct flips | Workspace strict | Same intact/twin tokens |
|---|---:|---:|---:|---:|
| Legacy reader, step 8 | 16/32 | 0/4 / 0/4 | 0/4 | 4/4 |
| Modulated reader, step 8 | 16/32 | 0/4 / 0/4 | 0/4 | 4/4 |
| Modulated frozen, step 2 | 16/32 | 0/4 / 0/4 | 0/4 | 4/4 |
| Modulated full, step 2 | 18/32 | 0/4 / 0/4 | 0/4 | 4/4 |

The new CPU-window legacy run reproduces the historical retained step-8 bridge
hash exactly: `3287de6087668cb55c0f2d9cc9de8a8ba48e8f79580dbd7b0c157622756dd33e`.
That is one observed weight-level reproduction, not universal CPU/GPU arithmetic
equivalence. Fresh modulated training strengthens the question route, but the
step-8 common correction remains dominant and both affected projected binding
inequalities still fail. Larger question gradients or interaction norms are not
evidence of useful factual selection. Mean-slot, same-memory, random-memory,
reverse-order, zero and unrelated controls remain in the raw records.

The full arm's 18/32 must not be reported as unconditional base preservation.
Relative to the pinned original, workspace predictions have **3 repaired errors
and 1 new error** on the 32 truth-bearing exposed rows. The updated backbone
without workspace is **15/32**, with **2 repairs and 3 new errors**. Current-theta
zero identity remains exact, but its reference itself moved. The unrelated
target in this pilot is stop-gradient **current** base, not an immutable original
teacher. This is a concrete reason to make the preservation reference explicit
in the next learner factor; the net exposed-set accuracy gain is not a base-floor gate.

Workspace generation is 0/4 strict-correct with 4/4 length stops at each final
checkpoint. Native-chat inline base yields 2/4 strict-correct and 4/4 valid EOS
there. Intact and twin tokens remain identical in all four final comparisons.
The two step-8 readers change text relative to original base on 2/4 queries;
the frozen step-2 control changes 1/4. In the full step-2 arm, workspace tokens
equal its **updated** base on 4/4 queries, even though that backbone can differ
from the original. None of these comparisons establishes the first usable-
content milestone.

## Exact generation examples

All **160** outputs, token IDs, conditions and sources are preserved in the
[literal bank](GENERATION_BANK.md) and [JSON bank](GENERATION_BANK.json).
The JSON-escaped strings below are exact, including truncation; they are not
completed, corrected or scored by their first word.

World 0, query 0, reader phase / original base / step 8:

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

Same coordinate, modulated reader / workspace **and** twin / step 8:

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

World 1, query 0, full phase / full-update workspace / step 2:

```json
"yes (based on the data from World Facts, Kestrel is a"
```

All three examples stop at the token ceiling, not EOS. Changed prose, including
an assertion that it is using facts, cannot substitute for counterfactual use.

## Full update, precision and resume receipts

| Progression step | Changed FP32 base tensors | Changed native base tensors | Changed native elements | Changed FP32 RMSNorm tensors | Changed native RMSNorm elements |
|---|---:|---:|---:|---:|---:|
| 1 | 291/291 | 237/291 | 123,205,237 | 65/65 | 1,803 |
| 2 | 291/291 | 237/291 | 174,891,214 | 65/65 | 1,831 |

At both steps, only 11/65 RMSNorm tensors have any native changed element.
Master updates and BF16-visible updates must therefore remain separate counts;
“full update” means all physical parameters are owned and eligible, not that
every native element changes each time. CPU FP32 masters retain sub-grid changes
for later steps; this does not remove quantization from inference.

The [frozen resume](raw/full/frozen_RESUME.json) and [full resume](raw/full/full_RESUME.json)
are exact for state, native weights, objective totals and update receipts.
The full resumed step-2 state hash is
`37d3391cb12a5b2003086756aefaed80cde55b817a99b9449b418cb50e7c01d6`;
its native base hash is
`112ff51664bd7c16cc36d9adcc6047553002d566919dd7342a0bcbc9cbda7678`.
These qualify this pinned-runtime next-update replay, not arbitrary restart
hardware, longer training or another model architecture.

A [separate read-only checkpoint audit](raw/CHECKPOINT_AUDIT.json) rehashed all
eight retained files and reconstructed the final native BF16 base directly
from the saved FP32 masters, matching the actual final model. It also verifies
that first-update bridge **and AdamW state** are exactly equal in the matched
frozen/full pair. No model forward or update was used for this file audit.

## Resources, retention and verification

| Phase | Seconds | Peak Torch allocated GiB | Peak Torch reserved GiB | Minimum sampled free device GiB |
|---|---:|---:|---:|---:|
| Reader pair | 140.846 | 14.204 | 14.389 | 16.227 |
| Full pair, including both replays | 815.791 | 27.751 | 28.354 | 2.203 |

The full process's minimum sampled available host memory was 59.880 GiB.
These are sampled availability counters, not a continuously observed host
peak or an allocator-free global VRAM budget. Full raw resource logs and
checkpoint-write forecasts are retained. Both jobs exited; Furnace had no GPU
compute client after completion.

All eight checkpoint files are retained on Furnace: **58,412,456,846 bytes**
total, latest two per comparison condition. Full checkpoints store masters,
not a redundant second native base. [The handoff](EXECUTION_HANDOFF.md) locates
them. Only receipts and compact analysis were pulled into Git; no old weights
were deleted and no monitoring automation was restarted.

280 selected source tests passed locally and on Furnace. The additional
post-result publication tests validate missingness, malformed factor panels,
literal escaping and terminal replay. [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json)
seals the raw files. Verification is offline:

```sh
python scripts/verify_v15_native_learner.py --bundle provenance/pilots/v15_native_learner_20261010
python provenance/pilots/v15_native_learner_20261010/publish_receipts.py
pytest -q provenance/pilots/v15_native_learner_20261010/test_publication.py
```

The original cue, native-answer, reader-factor and closed judge bundles were
also reverified. Judge main coverage stays **343/512**, with eight ambiguous
timeouts, 161 never-dispatched coordinates and blocked OpenAI calibration;
`INCOMPLETE_OR_CALIBRATION_BLOCKED` is unchanged. Those are historical judge
missingness, not missing outputs from this complete learner pilot.

## Next bounded design, not another run

Keep the demonstrated native path, exact zero identity, query-independent
writer, common-response capability and explicit state ownership. Do not
silently delete the dominant projection direction or duplicate the donor loss.
The next one-factor hypothesis is an explicitly separated common-response and
question/content interaction path, with an update/norm budget that does not
let a shared common output consume the entire useful change. A query-role
antisymmetric relation route is a candidate design, **not an established fix**;
it must use query-only information, never donor labels or diagnostic corners.

Independently, make pinned-original teacher/reference ownership explicit for
preservation controls. Keep it distinct from the current-theta zero check and
from the semantic objective; do not turn judge explanations into gold targets.
Only after a matched prospective test should either factor advance to a fresh
original-base floor and a qualitative answer bank. No longer run, new judge
budget, relaxed threshold or model selection is authorized by these results.
