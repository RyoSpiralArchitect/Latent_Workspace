# V24 R1 FT04 — offline development-result decomposition

**Post-hoc analysis, 2026-10-23. No new model calls.**
The paired full-update run completed correctly, and both routes fit the frozen
development references better than their own initial state. A broad workspace
advantage is **not** established. The next useful measurement is semantic
readout and independently generated computation, not another undifferentiated
whole-answer loss.

## Evidence and denominators

- Frozen execution source: `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`.
- Both arms start independently from original pinned Mistral, not each other.
  Each completes **32 updates, 538 unique training rows, 21,112 target tokens**.
  The frozen preparation reports 403 training source groups. Training keys and
  synthetic source groups are disjoint from the observed development set.
- Development: **76 rows / 5,002 target tokens** in each of four observations.
  Ordered keys, buckets and token counts match exactly.
- Synthetic development is **60 rows but only 10 source groups**: one group for
  each of seven world families and each of three reasoning families. Twins and
  controls are not independent replicate problems. The deterministic selection
  is explicit in [preparation](../../../../scripts/prepare_v24_recruitment.py).
- No-memory retention development is **16 rows / 4,488 tokens**: 8 instruction,
  4 code, and 4 prose rows. It accounts for **89.72% of all development tokens**;
  the overall average therefore cannot stand in for workspace utility.
- All **76/76 rows improve within each arm** in teacher-forced NLL. This is a
  descriptive observation on this small, fixed panel, not an accuracy or
  base-non-regression qualification.

The unchanged offline training verifier was rerun successfully locally. Full
row-level values, input hashes, all strata, and leave-one-family-out summaries
are in [RESULTS.json](RESULTS.json); [analyze.py](analyze.py) reproduces it using
only receipts. No model, tokenizer, tensor checkpoint, raw private text, or
confirmation/OOD input is loaded.

## 1. Base-reference retention looks encouraging on the observed rows

| Panel | Rows | Tokens | Inline: base → step 32 | Workspace: base → step 32 |
|---|---:|---:|---:|---:|
| No-memory retention | 16 | 4,488 | 0.966781 → 0.874073 | 0.966781 → 0.873073 |
| Synthetic world + reasoning | 60 | 514 | 2.922317 → 0.140255 | 3.870083 → 0.159790 |
| Overall | 76 | 5,002 | 1.167729 → 0.798667 | 1.265121 → 0.799777 |

Every one of the 16 retention rows improves within both arms. Workspace has
slightly lower final NLL on 13/16 of them, but the pooled difference from inline
is only about **−0.001000 nat/token**. This is neither an independent statistical
trial nor evidence of better writing, coding, or public-benchmark accuracy.
The two synthetic baselines differ because information is supplied through
different routes; comparing their gains does not identify a causal effect.

The overall final gap is workspace minus inline **+0.001110 nat/token**.
Its loss-sum decomposition is retention **−4.487434** plus synthetic **+10.041090**,
equal to **+5.553656 nats** over all 5,002 targets. Opposing local effects nearly
cancel; a nearly equal grand mean does not mean the behaviors are identical.

## 2. Affected-world advantage is localized, not a family-wide win

The affected-world panel is 14 rows / 106 tokens / 7 groups. Final NLL is
**0.163604 inline versus 0.138985 workspace**. Eight rows favor workspace and
six favor inline, but at the paired-family level only three of seven favor
workspace.

| Affected-world family | Rows | Tokens | Inline final | Workspace final |
|---|---:|---:|---:|---:|
| event_order | 2 | 18 | 0.067171 | 0.082458 |
| inventory | 2 | 9 | 0.037087 | 0.038263 |
| linked_location | 2 | 15 | 0.736151 | 0.633589 |
| location | 2 | 16 | 0.006825 | 0.010440 |
| order | 2 | 14 | 0.054443 | 0.151440 |
| ownership | 2 | 16 | 0.073161 | 0.062822 |
| revision | 2 | 18 | 0.150831 | 0.005976 |

Removing the single revision source group leaves **12 rows / 88 tokens** with
NLL **0.166217 inline versus 0.166191 workspace**, almost tied. Revision supplies
99.91% of the *signed net* affected-world gap; other positive and negative
differences cancel. This is a sensitivity description, **not causal attribution**.
Linked-location remains a high-loss group for both routes despite workspace's
relative advantage. Revision was already easier through workspace at base
(2.990084 versus 4.257915), another reason not to attribute its final gap solely
to what FT learned.

All seven leave-one-family-out results are retained, not just this illustrative
one. No example has been removed from the reported full denominator or selected
as a new training case in this follow-up.

## 3. Multi-step state manipulation is the sharper diagnostic lead

| Reasoning family | Groups / rows / tokens | Inline final | Workspace final |
|---|---:|---:|---:|
| arithmetic | 1 / 6 / 74 | 0.298983 | 0.319683 |
| register_trace | 1 / 6 / 74 | 0.255378 | 0.349333 |
| stable_filter | 1 / 6 / 94 | 0.119795 | 0.131821 |

Both routes improve every reasoning row from their own base, but inline has
lower pooled final NLL in all three families. Register-trace contributes **72.31%**
of the signed final reasoning gap. This suggests a targeted hypothesis about
using supplied state in successive operations, **not an established mechanism**:
there is only one dev group per family and no layer/gradient intervention here.

For present-record affected reasoning, the contrast is **0.314850 versus
0.371498** over 6 rows / 122 tokens. For unrelated-record reasoning, workspace
instead has lower NLL (**0.014817 versus 0.033869**, 3 rows / 18 tokens).
The world unrelated control goes in the opposite direction, so this cannot be
generalized as a broad improvement in ignoring irrelevant memory.

## 4. The current reasoning meter is answer-first teacher forcing

This is a source-backed measurement limitation, not a claim about a generated
transcript. [The generator](../../../../src/latent_workspace/recruitment_bank.py)
constructs `answer` and `steps`, then
[canonical JSON](../../../../src/latent_workspace/execution.py) uses sorted keys.
Present-reference targets therefore serialize **`answer` before `steps`**.
[The evaluator](../../../../scripts/run_v22_full_ft.py) reports one loss sum over
the whole teacher-forced reference, including formatting and EOS.

Later step tokens consequently see earlier **gold answer tokens** in their
prefix. In arithmetic, register-trace and filtering, the answer is also related
to or repeated inside the step sequence. The observed NLL can mix first-answer
prediction, syntax learning, copying, and reference-conditioned continuation.
It does **not** establish that the model generated valid intermediate steps and
then reached its answer. The present receipts cannot split value tokens from
syntax or reconstruct a free-generation correctness rate.

The current target order, prompts, losses and gates remain unchanged. This is
not a reason to rewrite or regrade the finished experiment. A steps-first format,
if desired later, must be a separately frozen comparison, not a retrospective fix.

## Next measurements proposed, not executed

1. **Separate semantic prediction from output format.** On frozen new evaluation
   groups, score answer-value probability before any gold answer is supplied;
   record value/step/syntax/EOS likelihood separately. Generate without a gold
   answer prefix and score exact final answers and executable steps separately.
   A shorter response is not automatically better or worse.
2. **Separate trained weights from runtime access.** Cross inline-trained and
   workspace-trained checkpoints with both input routes. Within a fixed
   checkpoint, use matched intact/twin/absent/unrelated or shuffled-memory
   controls and donor-directed answer margins. Current training-route ×
   inference-route cells are diagonal only; their joint contrast is not isolated
   causal workspace utility. Supplied external information remains M, not newly
   computed internal workspace state S.
3. **Increase independent source groups, not only twin/control rows.** Freeze
   all sampling, budgets and criteria before another run; retain the full
   existing panel. Validate retention with base-matched accuracy and generation
   probes before considering more FT or a release. Register-trace, order,
   linked-location and revision are diagnostic strata, not winning-branch
   selectors or automatic new training examples.

**Unchanged ceiling:** old expression gate **FAIL**; **winner: none**;
**non_regression: NOT_ESTABLISHED**. No new training, generation, benchmark, judge,
threshold/rubric change, weight deletion, GitHub push, or PR was performed.

See [completed-run recovery](../COMPLETION_RESULTS.md) and
[cross-project volatile-data preservation](../volatile_recovery/README.md).
