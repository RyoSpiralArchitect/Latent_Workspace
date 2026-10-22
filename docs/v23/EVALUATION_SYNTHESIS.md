# V23 integrated readout: useful changes, no release winner

**2026-10-22.** The native full-FT/P-only comparison, recovered readout bank,
MMLU-Pro and blind judge have terminal records. This closes the authorized
evaluation/publication phase; it does not start another experiment or promote
the full-FT weights to the existing frozen-host beta release.

## What changed

The matched off/on arms each started from the original Mistral-7B-Instruct-v0.3
and used 32 updates, 723 rows and 20,860 supervised targets. The sole intended
training factor is original-host full-vocabulary preservation KL at coefficient
zero versus one. Off reproduces V22. Exact native update/fresh-process restart
and target ownership qualify the engineering path, not general retention.
See [training terminal](../../provenance/engineering/v23_preservation_ft01_20261022/TERMINAL.md).

| Endpoint | Base | P-off | P-on | Scope |
| --- | ---: | ---: | ---: | --- |
| Fixed-dev target-weighted NLL | 1.267038 | 1.058723 | 1.069616 | 40 exposed rows / 4,694 targets |
| MMLU direct correct | 356 | 354 | 355 | 570 selected items |
| MMLU tie-free correct | 351 | 349 | 349 | Same 570 items |
| Latent-world exact | 47 | 83 | 83 | 96 rows, 16 groups |
| Inline-world exact | 75 | 87 | 86 | Same 96 rows |
| MMLU-Pro direct correct | 92 | 101 | 100 | 280 selected items |
| MMLU-Pro tie-free correct | 90 | 100 | 99 | Same 280 items |
| MMLU-Pro strict reasoning correct | 11 | 9 | 8 | 28 nested IDs, five-shot |
| Free-generation EOS | 14 | 15 | 14 | 24 prompt/seed units per arm |
| Free-generation cap reached | 10 | 9 | 10 | Same units, 256-token cap |

Sources: [training](../../provenance/engineering/v23_preservation_ft01_20261022/TERMINAL.md),
[complete comparison](../../provenance/pilots/v23_comparison_recovery02_20261022/README.md),
[MMLU-Pro](../../provenance/pilots/v23_recovered_mmlu_pro02_20261022/README.md).
These are distinct, protocol-specific denominators, not a combined benchmark.
The selected panels are now exposed development evidence, not future confirmation.

On MMLU-Pro, base→off repairs 16 direct items and loses seven; base→on repairs
14 and loses six. This is the desired observation of some base-wrong/FT-correct
decisions, **not** a demonstration of abilities inaccessible to the base model.
The old MMLU panel has no such repairs (off loses two; on loses one). P-on is
not a uniformly better preservation setting. Off/on latent-world exact outcomes
are identical item-by-item, while both differ substantially from base.

The 28 reasoning IDs have direct base/off/on correctness **12/10/11**. Therefore
the contrast between all-280 direct gains and 28 reasoning losses cannot itself
identify a generation bottleneck. Zero-shot scoring and five-shot generation
also condition on different prefixes. A matched-state experiment is still needed.

## What the judge can and cannot add

The [blind study](../../provenance/pilots/v23_recovered_behavior_judge01_20261022/README.md)
includes every free answer: 12 prompts × two seeds × three arms = 72 outputs,
not a changed-only or uncapped-only subset. It returned 174/174 responses:
170 valid, four invalid literal-quote failures, no missing calls. AB/BA r0 results:

| Reference → candidate | Reference / candidate / tie | Order conflict / unjudged | Total cases |
| --- | --- | --- | ---: |
| Base → off | 4 / 12 / 2 | 5 / 1 | 24 |
| Base → on | 8 / 12 / 1 | 3 / 0 | 24 |
| Off → on | 9 / 5 / 4 | 5 / 1 | 24 |

Preference-vector repeats disagree in 4/12 selected cases despite the earlier
32/32 calibration PASS; identical-answer controls pass 6/6. Neither the 174
requests nor the three pairings are independent samples. Same-family judging,
small prompts, cap effects and evaluator instability limit generalization.
The descriptive preference for FT is strongest in writing/constraint following;
code remains mixed and P-on is preferred to base in only 2/8 code units versus
5/8 preferring base (one order conflict). Preserve both gains and regressions.

The [all-72 learner bank](../../provenance/pilots/v23_comparison_recovery02_20261022/analysis/ANSWER_BANK.md),
[all-174 final judgments](../../provenance/pilots/v23_recovered_behavior_judge01_20261022/analysis/JUDGMENT_BANK.md)
and [all-84 reasoning bank](../../provenance/pilots/v23_recovered_mmlu_pro02_20261022/analysis/REASONING_BANK.md)
allow human inspection. Judged preference is not ground-truth correctness:
even a reproducibly preferred answer can contain arithmetic mistakes, invalid
tests or a truncated explanation. No post-hoc invalid-response repair was used.

## Failure modes to carry into the learner design

These are **hypotheses for the next finite study**, not trained fixes or new
acceptance rules. Keep the original workspace objective: useful computation
through query-conditioned latent state, with the native host learning end to end.

1. **Preserve useful behavior, independently of correctness.** Keep the observed
   concise writing, deadline/constraint fidelity and world exactness gains as
   separate endpoints. Do not replace them with a single binary task score or
   use the judge to waive wrong answers. Code explanation truthfulness needs
   preservation alongside familiar code patterns and executable behavior.
2. **Disentangle semantic answer, label binding, format and stopping.** In the
   three shared strict-reasoning losses, `biology:3462` is a missing required
   answer marker; `other:5622` has the right explanation but the opposite option
   letter; `math:9037` contains incorrect math and, for on, capped zero repetition.
   `chemistry:4250` independently separates a calculated quantity from its
   scientific-notation option. Do not recode these old scores. A future
   train-only oracle can mark identity/option/format/EOS spans separately before
   any forward pass; a separate frozen diagnostic can inspect all endpoints.
3. **Test transport at matched prefixes before adding more loss.** Compare
   teacher-forced choice margins and self-generated continuations on the same
   predeclared questions/contexts. Locate where a correct semantic quantity or
   direction becomes a wrong label; use W/Q/R interventions only if the assay
   actually exercises memory. Existing empty-memory MMLU/Pro/free generation
   says nothing by itself about workspace-mediated improvement.
4. **Keep P and binding/identity factors separate.** P=1 has not removed the
   observed errors or established ordinary-host non-regression. The matched
   gradient audit and this readout justify investigating train-only coverage,
   label consistency and state compatibility, not blindly increasing KL or
   question gain. Preserve exact owner/no-op/restart gates and freeze a fresh
   confirmation panel before selecting a coefficient, checkpoint or data mixture.

Do not train on these exposed benchmark labels, example failures or judged
answers. No larger teacher, provider substitution, repeat judge call, new
generation, checkpoint deletion or new training is authorized by this analysis.
The existing [P/B/I factor plan](NEXT_FACTORS.md) and
[workspace revival](WORKSPACE_REVIVAL.md) remain the design context.

## Integrity and release boundary

Original stopped trials remain immutable. The comparison combines whole
original base/off with whole recovered on under explicit source seals; the
original partial 79 on scores are excluded. MMLU-Pro 02 reevaluates all three
arms in one new authorized attempt, not a merge of partial journals. Judge
source binds that complete answer bank and its original calibration.

Current local publication uses no GPU, model/API calls, dependency changes or
weight deletion. Historical Furnace qualification and real-model results are
reported as historical, not rerun alongside Aether. The review guide provides
replay commands and negative-trial pointers.

**Share as an auditable research comparison with caveats. Do not claim general
non-regression, a P winner, causal workspace reasoning, 1.0 or a new HF release.**
Old expression gate **FAIL**, winner **none**, non-regression **NOT_ESTABLISHED**.
