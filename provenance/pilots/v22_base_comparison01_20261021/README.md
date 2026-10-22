# V22 versus original Mistral — comparison 01

**Completed, descriptive, not release-qualified.** Native latent-memory
generation improved substantially on the selected held-out worlds. The reused
MMLU panel lost two correct answers, and free generation retains reasoning and
completion problems. Thus **base non-regression is not established**.

The [summary](SUMMARY.json) is replayable from frozen raw results. The
[answer bank](ANSWER_BANK.md) shows **all 24 free-generation pairs**, including
truncated replies, without outcome-based pair selection or a paid judge.
See the [pre-scoring design](../../../docs/v22/BASE_COMPARISON_01.md),
[plan](../../../configs/v22/BASE_COMPARISON_01.json) and
[terminal handoff](EXECUTION_HANDOFF.md).

## What was compared

- Original Mistral-7B-Instruct-v0.3, pinned revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- V22 **step 32**, from training execution
  `13c1192fc2727d8ca61ee215a927c0cd77f75b16`, not a best-checkpoint search.
  The 29,004,418,636-byte checkpoint SHA-256 is
  `cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.
  Its complete owner state (native weights, FP32 masters, optimizer, history,
  buffers and RNG) matched the saved receipt before inference.
- Comparison execution `5bd6f5cca45ec25d57c37b14b410b9297abe67d5`:
  **730 sealed source files**. The training engine was unchanged; only an
  additive evaluation helper entered `src/`.
- Same BF16/eager native full-vocabulary graph, cut 4, no gradients and no
  KV cache. Each token recomputes memory/query. No candidate restriction in
  generation; A/B/C/D restriction is only the MMLU scoring rule.
- Plans and exact token inputs were frozen before these scores, but **after
  training**. This is not a pre-training preregistration. The earlier 40-row
  development panel is not reused as fresh confirmation.

## 1. Ordinary-host preservation: reused MMLU panel

570 questions, 10 in each of 57 subjects, canonical five-shot plain-text
prompts, no workspace. This is the earlier V16 panel, **not fresh/unseen
confirmation or a full MMLU score**. Maximum prompt length: 3,295 tokens;
no input was truncated.

| Scorer | Original | V22 | Difference | Base-only / V22-only correct |
| --- | ---: | ---: | ---: | ---: |
| A/B/C/D argmax | 356/570 (62.456%) | 354/570 (62.105%) | −0.351 pp | 2 / 0 |
| Strict unique maximum | 351/570 (61.579%) | 349/570 (61.228%) | −0.351 pp | 5 / 3 |

There are 354 both-correct and 214 both-wrong argmax pairs. Candidate ties
occur on **15 base / 18 V22** items; they are not hidden or silently resolved
in favor of the gold label. Per-subject results remain in SUMMARY.json.

Both argmax regressions collapse a 0.125 B-versus-D margin into a tie:

| Source test index | Subject | Gold | Base B / D logits | V22 B / D logits |
| --- | --- | --- | --- | --- |
| 9596 | nutrition | D | 17.250 / 17.375 | 17.125 / 17.125 |
| 13900 | world_religions | D | 17.750 / 17.875 | 17.625 / 17.625 |

At these magnitudes 0.125 is one BF16 spacing. The frozen first-maximum
argmax chooses B on the ties. This is evidence of **fragile native readout
margins**, not evidence that all underlying knowledge disappeared; neither
does it excuse the measured regressions. Strict scoring still loses two net
answers. No tolerance, tie-break or arithmetic was changed after observing
this. [Base scores](furnace/raw/base/mmlu.jsonl),
[V22 scores](furnace/raw/v22/mmlu.jsonl).

## 2. Held-out world generation: latent versus inline

Hash-selected **16 twin groups**: two test groups from each of six trained
families, plus four OOD linked-location groups. There are 128 raw control rows,
**96 unique memory/query/answer combinations**, and zero overlap with V22
train/dev groups. Redundant absent/unrelated controls remain as aliases.
These are correlated within-group probes, not 384 independent tasks.
OOD means one held-out family, not general unseen-task coverage.

Every input is evaluated in both routes with each weight arm: memory as
cut-4 states, or the same facts in the inline prompt. The question adds a fixed
short-answer instruction. Greedy generation uses the full vocabulary and a
24-token cap. Exact match ignores only case, whitespace and final periods;
it does not accept an otherwise correct answer followed by an explanation.

| Split / route | Original exact | V22 exact | Base-only / V22-only | Target-token NLL, base → V22 |
| --- | ---: | ---: | ---: | ---: |
| Test / latent | 32/72 | 64/72 | 1 / 33 | 1.297195 → 0.056716 |
| Test / inline | 57/72 | 65/72 | 1 / 9 | 1.223528 → 0.095355 |
| OOD / latent | 15/24 | 19/24 | 1 / 5 | 0.814358 → 0.073268 |
| OOD / inline | 18/24 | 22/24 | 0 / 4 | 1.189333 → 0.085218 |

Each route/split NLL has **467 test / 156 OOD** target tokens, including EOS.
There are 384 teacher-forced rows / 2,492 target-token scoring occurrences
across both routes and arms. Teacher-forced NLL and autoregressive exact match
are different endpoints; a low NLL is not a guarantee of correct generation.

### Mode detail, exact matches

| Split / route | Affected | Unaffected | Absent | Unrelated |
| --- | ---: | ---: | ---: | ---: |
| Test / latent, base → V22 | 10→22 /24 | 12→20 /24 | 7→10 /12 | 3→12 /12 |
| Test / inline, base → V22 | 23→23 /24 | 18→20 /24 | 7→10 /12 | 9→12 /12 |
| OOD / latent, base → V22 | 5→6 /8 | 2→5 /8 | 4→4 /4 | 4→4 /4 |
| OOD / inline, base → V22 | 5→6 /8 | 5→8 /8 | 4→4 /4 | 4→4 /4 |

For affected counterfactual twins, both sides are exactly correct in
**4→12/16 groups** with latent memory and **13→14/16** inline.
Simply changing the answer is insufficient: latent text changes across twins
in 15 base versus 14 V22 groups, while joint correctness improves.
Both routes have identical generated tokens and teacher NLL on all 16
empty-memory controls in each arm.

The test latent/inline exact-match gap narrows from **25 answers to one**.
The OOD gap remains **three answers**. This suggests stronger use of the
native-memory path within the trained-family task distribution, not complete
transfer to the held-out compositional family.

### Formatting gains and remaining failures

Manual, unblinded inspection of the **12 affected test/latent repairs** finds
four base replies already contain the correct value but add explanatory
text: event-order 0006/s0; order 0002/s0, 0002/s1 and 0007/s1.
The other eight change an incorrect/unspecified literal answer to the target.
Do not describe all 12 as newly acquired reasoning successes.

Exact illustrative outputs (all remain in the raw journals):

| Input / route | Target | Original output | V22 output |
| --- | --- | --- | --- |
| inventory-test-0009/s0/affected, latent | `20.` | `21` | `20.` |
| order-test-0002/s0/affected, latent | `Njhxbkoglo.` | `Njhxbkoglo is ranked higher.` | `Njhxbkoglo.` |
| event_order-test-0015/s0/absent, latent | `Not specified.` | `Not specified` | `Nfzyxfrnok.` |
| linked_location-ood-0058/s1/affected, latent | `Nymszrcrff.` | `Nymszrcrff` | `Nymszrcrk.` |
| Same OOD input, inline | `Nymszrcrff.` | `Nymszrcrff` | `Nymszrcrff` |

IDs in the table omit only the common `wb01-` prefix.
The last two rows isolate an exact-symbol-copy error in the latent route;
the absent-memory regression remains an important negative control.
These examples illustrate value repair, format repair and regressions, not
a curated quality score. [Base world outputs](furnace/raw/base/worlds.jsonl),
[V22 world outputs](furnace/raw/v22/worlds.jsonl).

## 3. Free generation: all 24 pairs, not a quality verdict

12 fixed English prompts, four each in reasoning/writing/code; seeds
2026102101 and 2026102102; temperature 0.7, top-p 0.9, 256 new tokens.
Fresh CPU FP32 sampling RNG per answer; identical prompt/seed across arms.
**All 24 texts differ.** That is sensitivity to the weight change, not proof
that all 24 improved.

| Category (8 replies/arm) | Base EOS / capped | V22 EOS / capped | Base / V22 tokens |
| --- | ---: | ---: | ---: |
| Reasoning | 5 / 3 | 3 / 5 | 1,731 / 1,701 |
| Writing | 8 / 0 | 8 / 0 | 1,144 / 1,051 |
| Code | 1 / 7 | 4 / 4 | 2,012 / 1,939 |
| Total | 14 / 10 | 15 / 9 | 4,887 / 4,691 |

Some useful but **unblinded, non-exhaustive** observations at seed 2026102101:

- Writing-02: base softens the required same-day feasibility response to
  “at your earliest convenience”; V22 explicitly asks for “an update today”.
  This is an observable instruction-faithfulness difference, not a judge score.
- Reasoning-01: V22 reaches the correct probability **2/5**, then adds an
  inconsistent explanation about the remaining balls. Both replies hit the
  cap. A correct visible answer does not certify the explanation.
- Reasoning-02: V22 attempts a counterexample but says “G1 are also daxes,
  and G2 are not”, violating the given premise that every glimmer is a dax.
  Its reply is also capped.
- Code-01: base emits the invalid import `from hashlib import hashlib`.
  V22 removes it and uses a simpler insertion-ordered dictionary, but its
  set-based assertion does not check first-seen ordering. Both full replies
  are capped. These generated programs were inspected, **not executed**.

The [complete bank](ANSWER_BANK.md) retains every literal answer and stop
reason. No blind judge, paid API, aggregate quality preference or release
claim is made. Longer generation would be a new frozen trial; these truncated
outputs were not extended or replaced.

## Completion, resources and verification

| Item | Planned | Completed |
| --- | ---: | ---: |
| Weight arms | 2 | 2 |
| MMLU scoring rows | 1,140 | 1,140 finite |
| World teacher-forced rows | 384 | 384 finite |
| World generation sequences | 384 | 384 (15 base capped, zero V22 capped) |
| Free generation sequences | 48 | 48 (10 base capped, 9 V22 capped) |
| All generation sequences | 432 | 432: **398 EOS / 34 capped** |
| Generation tokens | cap-bounded, not a fixed total | 12,392 |
| Real-model training updates / saves / deletions / judge calls | 0 | 0 |

Base took **503.63 s**, V22 **589.65 s**, including identity checks and
V22's strict owner restore. Both peaked at **16.955 GiB CUDA allocated /
25.879 GiB reserved**. Peak host RSS was 5.541 GiB for base and 55.758 GiB for
V22, whose full CPU optimizer owner was restored for verification then discarded.
No compute worker remained after terminal completion.

- [CPU](furnace/qualification/cpu/FINISHED.json) and
  [CUDA](furnace/qualification/cuda/FINISHED.json) invocations each passed
  **138/138**, zero failures/errors/skips, in 43.18 / 47.47 seconds.
  Not every fixture executes on GPU: the device-aware owner tests exercise
  CUDA; the new small generation fixtures are CPU fixtures. See the design's
  explicit coverage caveat. Actual 7B generation here runs on CUDA.
- Mac development checks: new tests 17/17; combined suite 136/138, with two
  isolated subprocesses unable to import local `typing_extensions`.
  Neither was excluded from the passing Furnace invocations. No dependency
  installation or runtime modification was made.
- Managed TRT-LLM doctor passed, with its existing modelopt/transformers
  warning preserved. The custom cut graph/checkpoint required the matched
  native PyTorch backend. The initial incorrectly quoted read-only doctor
  command did not execute; the documented invocation succeeded.
- [Offline replay](furnace/OFFLINE_REPLAY.json) regenerated the exact input
  bank, verified all five training-bank files unchanged, and decoded all
  432 token sequences to their literal saved text without a model call.
- The [visible-fact oracle replay](WORLD_ORACLE_REPLAY.json) independently
  recomputed all 96 selected answers/evidence from their fact atoms and
  checked the exact memory/question renderings, without a model call.
- `summarize.py --verify` checks committed source hashes, exact input bytes,
  XML test counts, terminal manifests, every choice/exact-match denominator,
  unchanged weight fingerprints, paired summary and the literal answer bank.
  No source seal, old failure, training record or retained checkpoint was edited.
  The literal answer bank intentionally retains two generated trailing spaces
  (including capped final lines); its default Git whitespace check reports
  these two lines. They match the raw text and must not be stripped. Other
  staged source/document changes pass the ordinary whitespace check.

## Bounded next questions — not new training authorization

1. Preserve the observed native-memory gains; do not mistake concise formatting
   or lower teacher NLL for complete reasoning improvement.
2. Diagnose near-tied native logits separately from knowledge retention.
   Keep this run's ties and losses intact; any FP32-head/precision comparison
   must be a separately frozen condition, not a retrospective scoring fix.
3. Probe absent-memory abstention, event/rank reasoning, and exact-symbol
   copying in the held-out composition. Inline controls help locate which
   failures remain specific to latent input.
4. Examine reasoning consistency and instruction fidelity in a blinded,
   completion-aware answer comparison before selecting another learner update.
   Keep the two MMLU regressions as diagnostic test evidence, **not training
   examples**, and use a new unexposed panel for stronger retention claims.

**Historical gate unchanged: FAIL / winner:none /
non_regression NOT_ESTABLISHED. No beta replacement or Hub release.**
