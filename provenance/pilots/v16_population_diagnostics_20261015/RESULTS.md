# V16 population diagnostic: complete, not qualified

2026-10-15. All four arms completed and the frozen
[offline verifier](../../../scripts/verify_v16_population_eval.py) replayed
the [terminal raw bundle](raw/FINISHED.json) successfully:
[OFFLINE_VERIFY.json](OFFLINE_VERIFY.json). Execution source remains
`de0f14c7378abf7d92f582b6b22d31bdf688526b`; all 546 source hashes are unchanged.
The original launch README and partial receipts remain historical records.

## Completion and sample units

- Four arms × 570 MMLU questions = **2,280/2,280 scored rows**; no missing arm.
- **128/128 distinct new world pairs**, evaluated for all four arms, with
  1,024 queries per arm; 256 affected and 768 unaffected. This is not 512
  independent worlds. Entities and templates remain shared with earlier work.
- Three trained arms × ten memory conditions × 1,024 = **30,720 workspace
  rows**, plus **4,096 direct-base rows** and **15,360 transport-factor rows**.
- 6,144 observer records, of which 4,096 contain interaction traces (raw/slot).
  The common-only arm records no interaction. These are correlated observations.
- All four arms replayed the old evaluation exactly and preserved their complete
  learner/optimizer/RNG fingerprints. All manifests and frozen input identities
  passed. This evaluation made **zero new updates, sequences, judge calls or
  weight deletions**. The saved training exposure is still one model seed,
  two worlds and two updates per trained arm.

## MMLU: small ordinary declines, larger strict-tie declines

Each arm has the same 57 subjects × 10 questions, five-shot plain-text prefix,
native candidate scores, and no workspace. Regressions/repairs below compare
with the pinned original, not another trained arm.

| Arm | Ordinary correct / 570 | Strict correct / 570 | Ties / 570 | Ordinary regressions / repairs | Strict regressions / repairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| original | 356 | 355 | 14 | — | — |
| common | 356 | 352 | 15 | 0 / 0 | 4 / 1 |
| raw matched control | 355 | 352 | 14 | 2 / 1 | 5 / 2 |
| slot contrast | 354 | 348 | 17 | 2 / 0 | 7 / 0 |

Slot contrast is **−0.351 percentage points ordinary**, **−1.228 points
strict**. Ordinary paired 95% descriptive bootstrap intervals, resampling
questions within subject, are common [0, 0], raw [−0.702, +0.351] and slot
[−0.877, 0] percentage points. These are **not strict-score intervals**, not
training-seed uncertainty and not a preregistered noninferiority gate. The
common ordinary correctness vector is identical to original; a degenerate
bootstrap interval does not prove population equivalence.

Post-result inspection of the saved score journals finds every strict
regression becomes a tied candidate maximum; each original top-two candidate
gap was 0.125. Slot's seven strict losses are in electrical engineering,
high-school chemistry, high-school macroeconomics, moral disputes, professional
accounting, professional law and world religions, one each. The latter ordinary
losses are moral disputes and world religions; five other tied cases retain
the correct first-index ordinary choice. **None is rescued:** the frozen
strict and ordinary rules are unchanged. This describes score fragility, not
its causal origin. Full per-subject ordinary deltas remain in the replay JSON.

## Functional correctness: distinguish backbone drift from workspace effect

Counts are intact-label / twin-label correctness out of the **same 1,024
queries**; ties are incorrect. Original has 20 direct-choice ties. The trained
direct backbones have common 38, raw 30, slot 24 ties; intact/twin workspace
ties are common 19/19, raw 34/34, slot 19/19.

| Arm | Direct backbone | With workspace intact / twin | Workspace minus own backbone | Workspace regressions / repairs versus original, intact; twin |
| --- | ---: | ---: | ---: | --- |
| original | 535 / 525 | — | — | — |
| common | 523 / 510 | 531 / 520 | +8 / +10 | 31/27; 34/29 |
| raw matched control | 531 / 513 | 528 / 510 | −3 / −3 | 30/23; 33/18 |
| slot contrast | 527 / 513 | 528 / 519 | +1 / +6 | 29/22; 28/22 |

Workspace versus its own updated backbone gives regressions/repairs of common
2/10 intact and 2/12 twin; raw 6/3 and 6/3; slot 2/3 and 2/8. These are not
the original-base transitions used by the verifier's world-cluster intervals.
All three workspace arms remain below original on both labelings. For example,
slot's original-relative intact interval is [−1.953, +0.586] percentage points,
twin [−1.953, +0.781], with 128 worlds resampled within four data-seed strata.
Raw twin is [−2.832, −0.098]. These are descriptive, not multiplicity-adjusted
qualification tests. All condition summaries/intervals remain in the replay.

Most importantly, **intact/twin binary predictions are identical on all
1,024 queries in every arm**. No arm achieves a donor-directed flip (0/256).
The small improvement relative to an arm's own backbone therefore does not
establish selective use of the counterfactual memory.

## Native transport and internal readout

For actual intact/twin comparisons, affected native donor-margin signs are:

| Arm | Positive / zero / negative, out of 256 | Intended FP64 positive / negative | Donor flips |
| --- | ---: | ---: | ---: |
| common | 1 / 254 / 1 | 126 / 130 | 0 / 256 |
| raw matched control | 0 / 256 / 0 | 128 / 128 | 0 / 256 |
| slot contrast | 2 / 253 / 1 | 127 / 129 | 0 / 256 |

All 1,024 actual comparisons per arm change some full-vocabulary logits, but
none changes the full-vocabulary greedy next token. No free sequence was
generated. The intended FP64 projection is diagnostic-only; its approximately
balanced directions prevent an explanation based solely on numerical visibility.
All five factors, including reversed/common-slot/random/same-memory controls,
are retained in the offline replay. Common-slot controls match the actual
positive/zero/negative *counts* in common and slot; this is not a rowwise
equivalence claim or positive evidence of differentiated fact selection.

Readout means pool 2,048 intact/twin query observations per interaction arm:

| Measurement | Raw control | Slot contrast |
| --- | ---: | ---: |
| Centered / normalized slot norm | 0.063041865 | 0.062272799 |
| Centered slot norm | 2.0173070 | 1.9926980 |
| Attention L1 distance from uniform (shadow) | 0.025997570 | 0.035864962 |
| Production read norm | 7.0845615 | 0.015220141 |
| Uniform-query read norm | 7.0835971 | 2.7703684e−8 |
| Output norm before cap | 0.77067779 | 0.0014358950 |
| Remaining common-route budget fraction | 0.34146276 | 0.27243359 |
| Final interaction norm | 0.052088449 | 9.7781403e−5 |

Slot variation is not exactly collapsed: centered fractions range
0.055529669–0.067783386. The cap is not exhausted: remaining fractions range
0.25867450–0.29107195, and pre-/post-cap output means are 0.00143589499 versus
0.00143589342. The deliberate remaining-budget multiplier still attenuates the
output; this does not prove all budget effects irrelevant. Attention entropy is
1.38488045 versus ln(4)=1.38629436. Near-uniform selection of centered values
is a plausible cancellation bottleneck. Shadow attention weights are not
production activations, and the trace is not an intervention. Modest slot
variation does not itself prove useful factual content.

## Bounded consequence and resources

The observed aggregate changes support **continuing engineering preparation**,
not promotion or automatic long training. Preserve the proposed zero-loss floor
and freeze its still-pending benchmark/slice/statistical manifest before V18.
The [V18 preparation](../../../docs/v18/PREPARATION.md) therefore prioritizes
general complete-window reductions, an independently owned original-base
reference, and a selection-only relational-query hypothesis tested separately
from preservation. Do not simply enlarge the residual or stack more losses.

Summed arm elapsed time is **2,191.847 seconds (36.53 minutes)**; this is not a
single-process duration. Peak reserved CUDA memory is **15,365,832,704 bytes**
(14.311 GiB). Local post-run regression is **29/29**, and Ruff passes; the
seven receipt tests cover bootstrap helpers, not independent verification of
every receipt invariant. The separate full artifact replay is the terminal
evidence. All original weights/checkpoints remain unchanged. No recurring
monitor was created or resumed.

**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.
