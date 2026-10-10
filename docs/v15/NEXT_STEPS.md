# V15 follow-up: native learner exercised; isolate content-selective learning

Client date: 2026-10-10. **POST-RESULT DESIGN; bounded learner pilot complete**.

## Current decision: return to the FT learner without further judge collection

Ryō chose to use the valid existing diagnoses and resume learner work. The
[separate eight-update engineering plan](../v15_5/NATIVE_ANSWER_LEARNER.md)
implements matched native answer CE versus the same CE plus verified-answer-
conditioned EOS, with the pinned backbone frozen. This is a bounded new scope,
not a successful qualification of the old instrument or the generalization
study below. The [completed results](../../provenance/pilots/v15_5_native_answer_20261010/README.md)
retain 576 evaluation rows and all 80 bounded greedy sequences. Do not retry any judge call or
reactivate the paused heartbeat. No preferred generated answer becomes gold.

Both native objectives produced finite parameter updates and observable native
logit changes. Answer-only training changed the generated text for 2/4 exposed
queries, but intact/twin tokens matched for all 4/4 in each arm. All four
truth-bearing choice conditions stayed at 8/16; the four affected donor-margin
changes stayed exactly zero. Both arms' workspace generation stayed 0/4 strict
correct and 4/4 length-limited at each measured step. EOS supervision reduced
teacher-forced EOS CE without improving observed termination. Lower losses or
different wording do not select a winner; the old FAIL remains unchanged.

This closes the missing finite-update/native-generation engineering path, not
the content-use problem. FP32 residual norms approached the cap-one bound while
intact/twin two-choice score vectors remained equal for 16/16 prefixes. That
is consistent with a shared output bias, not proof that all latent semantic
information is absent. All 26 bridge tensors had nonzero aggregate gradient
norms by update 8, which cannot rule out per-loss cancellation or weak content
selectivity. No full-tensor causal decomposition was performed.

### Next bounded learner priority (proposed, not executed)

1. **Keep the shared native path and sealed controls.** Preserve the graph
   oracle, independent frozen base, written-zero parity, original question
   anchor, exact generation outputs, and separate answer/EOS loss weights.
2. **Decompose content versus common output shift before more updates.** On
   train-only worlds, record per-loss writer/Q/K/V/output gradient norms and
   alignment, reciprocal-query cancellation, intact/twin residual differences,
   common components, cap compression, answer-alias redistribution, and native
   versus pre-cast donor margins.
   An aggregate gradient, saturated norm or changed top-1 token is not enough.
   Use those measurements to choose one next factor: e.g. reader binding or
   content-dependent objective/parameterization. Do not silently combine these
   with a larger cap or a longer run.
3. **Keep completion separately observable.** Compare the correct-answer
   teacher-forced prefix with prefixes actually reached in greedy generation.
   Do not turn a smaller EOS loss into a stopping-success claim or use it to
   harden a wrong first answer. No additional judge is needed for this result.
4. **Retain the original keep/strengthen/add exit contract.** Only fresh,
   matched task/world controls and answer banks can establish preservation of
   useful calibrated responses, grounded improvements and the independent
   base correctness floor. Random/schema controls, natural multi-turn behavior,
   qualitative sentinel preservation and human review remain outstanding.

The completed engineering scope does not authorize automatic longer training,
full-backbone updates, revised scoring thresholds, new judge collection, weight
deletion or release promotion. Checkpoints 4 and 8 of each arm remain on Furnace.

## Prior evidence: native answer content is not reducible to stopping

The [continuation result](../../provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010/README.md)
is terminal, **HALTED_NO_RETRY**, not a completed judge panel. Its 155 valid new
diagnoses bring main coverage to **343/512**: 171 inline and 172 query-only.
There are now eight ambiguous main calls and 161 never dispatched. The original
invalid repeat and OpenAI's calibration FAIL plus 544 undispatched study calls
remain unchanged. All original records, settings, bodies and gates are preserved;
the heartbeat is paused. At that diagnostic checkpoint no learner run was
authorized; the later explicit engineering scope is recorded above.

The renderer split materially sharpens the earlier proposal. Of 87 diagnosed
native-chat inline outputs, 58 strictly succeed and 29 fail: **13 contradiction,
13 wrong-commitment, two format-only candidates, one grounding failure**. All
13 contradiction cases have a negative symbolic answer; the wrong-commitment
cases include nine negative and four positive answers. These are descriptive
observations, not rates for all 128 native outputs or causal learner evidence.

All 82 diagnosed inline length stops are from raw rendering. The complete bank
also contains two native-chat length stops, but neither has a diagnosis here.
Pooling raw truncation with native answer/explanation conflict would therefore
overstate the case for an EOS-only native fix. A visible explanation supporting
the opposite answer is a consistency defect, not proof of hidden correct
reasoning that can simply be read out. Short EOS-terminated wrong answers
independently rule out termination as a universal content repair.

The unchanged fixed repeats remain 25 equal, six differing and one invalid pair
out of 32; commitment agrees in all 31 valid pairs, while reasoning/added-fact
interpretation is less stable. These are not training gold. Missing judgments
are not assumed random, and the old strict scores remain 84/256 inline and
1/256 query-only. No old gate is rescued.

Carry these distinctions into **proposed, separately authorized** learner work:

1. **Qualify the observable first.** Preserve free-generation FAIL. Use an
   untouched, separately frozen panel for the intended interface; if complete-
   answer choice is chosen, name and qualify it separately. Do not convert a
   favorable later clause into the answer or relax the old parser/gate.
2. **Prioritize answer content and question binding in the native path.** Check
   balanced reciprocal labels, verified graph truth and original question/fact
   binding in full-vocabulary answer-token CE. Inspect a finite-update change
   in native logits and actual tokens, not merely a nonzero gradient or a
   correct teacher-forced continuation. The observed negative-answer conflicts
   justify a targeted diagnostic, not label-conditioned rescue or automatic
   supervision from judge prose.
3. **Keep stopping as its own controlled factor.** Native answer CE versus the
   **same** CE plus verified-answer-conditioned EOS remains a candidate pair.
   Hold initialization, data, update count, readout, reader, residual cap and
   precision fixed. Old FP32 candidate CE versus native answer-plus-EOS changes
   two factors and cannot isolate EOS. Apply completion supervision only to the
   declared one-word task; it can harden a wrong answer and must not globally
   shorten free text. This is not the single established cause of native failure.
4. **Preserve independent workspace and behavior gates.** Keep matched intact/
   twin donor direction, reciprocal queries, written-zero/unrelated controls,
   fact-order robustness and a pinned-base correctness floor. Test preservation
   of the earlier concise, calibrated verification behavior on fresh, matched
   qualitative answer banks. An aligned-serialization change is a separate
   experiment, not another factor silently added to the CE/EOS comparison.
5. **Version evaluator repairs separately.** Clarify world facts versus
   meta-statements, hypothetical premises versus assertions, and incomplete
   explanations. Confirm on untouched controls. Do not repair the frozen
   evidence/rubric or treat repeatable single-family labels as human truth.

No learner factor is proven by this base-only partial diagnostic. Its
execution scope is closed; the later decision above declines further judge
collection and proceeds with a separate bounded learner test. Any future
recovery of the **161 never-dispatched requests** would need a new decision and
a separately recorded run. The eight ambiguous calls and
invalid repeat remain excluded. No new model request, source-seal change,
learner experiment, provider substitution or PR merge follows automatically.

## Earlier update: fresh cue confirmation failed; keep observables separate

The prospective cue-by-envelope comparison proposed below is now
[complete](../../provenance/pilots/v15_cue_confirmation_20261010/README.md):
16 new world families, 64 cases, and all 512 planned greedy generations.
The frozen primary, native chat / cue absent / inline, **FAILED**. Native-chat
strict correctness was 44/64 with `Answer:` and 40/64 without it; atomic
negative answers fell from 5/16 to 0/16. Raw generation failed throughout.
None of the four methods qualified. No learner run followed.

The completed-path discrepancy did recur on fresh instances: native chat with
the cue retained ranks 21/32 atomic answers correctly at the first token and
30/32 after weighting the fixed aliases by immediate EOS. Actual generation
is still 21/32. Removing the cue gives only 20/32 correct completed-path rankings
and 16/32 generated answers. Thus neither cue removal nor a universal stopping
explanation accounts for the result. Full-chain chat completed-path ranking is
25/32 under either cue setting; that is not a qualified reasoning result.

The next step is an **instrument decision**, not another unbounded prompt
search or automatic training launch:

1. Preserve free generation's failure as its own result. No first-word rescue,
   post-hoc budget increase, relaxed validity gate, or comparator promotion.
2. If completed-answer choice is the intended task observable, define it as a
   separately named instrument before another run. Freeze aliases, native
   probability/termination semantics, absolute mass coverage, acceptance rules,
   both reciprocal labels, and a new untouched confirmation panel. Keep
   natural generation validity/correctness next to it; a finite-path score
   cannot qualify the old free-generation interface. The current names and
   templates were reused, so this panel establishes no lexical/task transfer.
3. Keep answer selection, answer-conditioned completion, and multi-hop content
   reasoning as separate learner objectives to be tested. A later
   sequence-level answer-plus-EOS loss is a concrete candidate, not an
   evidence-backed fix. Select and preregister one learner factor only after
   its intended instrument is qualified; do not combine loss, serialization,
   gain, capacity, and prompt changes into a single unexplained intervention.

The earlier aligned-serialization comparison remains a proposed isolated
factor, not authorization to execute it past the failed gate. Preserve the
judge-derived keep/strengthen/add goals, base correctness floor, semantic donor
direction, and qualitative paired answer-bank evaluation as independent gates.
This base-only run says nothing about whether the favorable V14 response
qualities survive a future learner change.

The new numerical replay policy was frozen prospectively: its verifier passes
on both Mac and Furnace CPU with byte-identical receipts. That resolves
portability for this accounting contract only; the preceding completion run's
four exact Mac scalar mismatches remain in its immutable evidence. No sealed
source or raw artifact was changed to turn an old failure into a pass.

## Earlier update after the first no-training instrument checks

Unit A below was exercised in two separately frozen units:
[288-generation elicitation](../../provenance/pilots/v15_base_elicitation_20261010/README.md)
and [144-prefix completion-path scoring](../../provenance/pilots/v15_completion_mass_20261010/README.md).
The generation gate **FAILED**, and all cases were exposed before the second
diagnostic. No retrospective rescoring changes that result; no new learning or
judge run followed. The original no-training comparison and following proposed
learning factors remain separate from this update.

Three boundaries are now distinguishable on this bounded base-model panel:

1. **Answer choice.** Raw inline atomic lower-choice scores are correct 16/16,
   yet all its primary free generations fail. Candidate ranking alone does not
   qualify an answer interface. Native chat atomic lower-choice ranking is 9/16.
2. **Completed answer versus initial token.** Native chat atomic class ranking
   remains 9/16 after summing capitalization aliases, but becomes 14/16 when
   the same aliases are followed by immediate EOS. Five of seven wrong initial
   negative answers change class in this diagnostic, without a weight change.
   This is finite-path reweighting, not successful natural generation.
3. **Relation reasoning.** Native chat full-chain ranking changes only 7/16 to
   8/16 after EOS weighting. Correct termination is not sufficient to repair
   three-hop reasoning, and an unconditional stopping reward could make wrong
   answers more confidently terminal.

The next unit should still be **no-training instrument qualification**, not a
large learner run. Before execution, freeze a minimal prospective comparison
that isolates the internal `Answer:` cue from the native chat wrapper, with
the same authoritative facts, question binding, aliases and stopping policy.
The observed cases are development-only now; acceptance needs new independent
families and balanced reciprocal no/yes pairs. If fixed complete-answer scoring
or constrained decoding is included, name it as a distinct instrument and keep
free-generation validity/correctness alongside it. Grammar compliance cannot
serve as a reasoning gate. Do not select a renderer from these old scores and
retroactively call it confirmed.

Once that gate passes, carry these distinctions into the future learner as
separate measured objectives: native full-vocabulary answer selection,
answer-conditioned completion, and multi-hop/content directionality with
aligned serialization controls. A sequence-level answer-plus-EOS objective is
now a concrete **candidate experiment**, not a proven fix. Retain candidate
mass coverage, all invalid/truncated generations, and unnormalized probabilities
so a finite-path conditional score cannot conceal weak natural completion.

Preserve the earlier judge-motivated capabilities through the matched base/V14
answer-bank and blinded qualitative comparison; this base-only task did not
re-evaluate those strengths. New gain, capacity, serialization learning and
completion supervision must not be bundled into one unexplained change.
The base correctness floor, semantic donor direction, and general response
quality remain independent release gates, all unqualified here.

The completion verifier also exposed a reproducibility issue: four derived
probabilities differ by one FP64 ULP between Linux and Mac, despite identical
categorical/aggregate results. Keep the frozen failure receipt. Any future
cross-host numerical comparison policy must be specified and tested before
its run; do not widen the old exact-equality gate after seeing outputs.

## Earlier post-transport design and preserved controls

This addendum responds to the
[verified V15 summary](../../provenance/pilots/v15_readout_transport_20261010/SUMMARY.json)
and [execution report](../../provenance/pilots/v15_readout_transport_20261010/raw/REPORT.json).
It does not amend the frozen [assay plan](PLAN.md), repair historical scores,
or record a new training, generation, or judge run.

## What the assay established—and did not

The engineering path is now explicit: a workspace residual reaches native
full-vocabulary logits and can change generated tokens. The assay records
ordinary/split native parity on 16 prefixes, shared/historical native parity
on all 384 crossover rows, written-zero equality on 32 crossover cases,
and generation-path parity checks. Native loss backward reaches the loaded
bridge without an optimizer step. Base and bridge hashes remain unchanged.
The portable verifier reconstructs scalar receipts; it does not independently
reload weights, recover full logits, or redifferentiate gradients.

These are transport and engineering results, not evidence of semantic learning
or better answers. The no-training crossover sharpens the earlier diagnosis:

| Retained reader / arithmetic | Original accuracy / correct affected flips | Canonical | Canonical reverse |
|---|---:|---:|---:|
| Final / native | 24/32 · 2/4 | 22/32 · 0/4 | 21/32 · 0/4 |
| Mean / native | 24/32 · 2/4 | 22/32 · 0/4 | 23/32 · 1/4 |
| Final / diagnostic FP32 | 25/32 · 3/4 | 22/32 · 0/4 | 22/32 · 0/4 |
| Mean / diagnostic FP32 | 25/32 · 3/4 | 23/32 · 1/4 | 24/32 · 2/4 |

Historical intact and twin facts were independently shuffled. Their original
contrast therefore changes content **and** serialization; the raw summary's
`affected_content` field is not an isolated semantic causal effect. Canonical
and reverse-canonical orders align subject order for these two exposed worlds.
They are useful controls here, not a universal guarantee that sorting removes
every positional confound in new worlds. The remaining isolated successes do
not select a pooling winner or establish order-invariant fact use.

The generated-output instrument also failed its narrow contract: **all 64
sequences were unparseable as an entire yes/no answer; 63 reached the 64-token
budget and one terminated at EOS with extra text**. This includes all eight
base-with-facts-inline sequences, not just workspace outputs. Consequently,
the strict outcome is failure under this renderer/decoder/scorer; it is not a
clean measurement of the model's ability to answer the underlying relation.
More tokens or retrospective first-token scoring cannot repair that record.

## Next unit A — no-training elicitation and termination qualification

Do this before another learner change. Keep model revision, base weights,
readout binding, and source receipts pinned. Use a separately frozen protocol
to determine whether the base can express the task through the intended
interface, rather than optimizing the learner against an unqualified output
contract.

1. **Version the complete instrument.** Freeze each proposed renderer,
   tokenizer/chat-template policy, exact answer cue, BOS/EOS handling, prompt
   and target tokenization, question-span binding, decode policy, stop rule,
   output budget, scorer, and invalid/missingness handling before generation.
   If a native chat template is tested, it is a new method—not a silent fix to
   the historical `use_chat_template: false` method.
2. **Start with the pinned base at step zero.** Compare the same frozen queries
   with authoritative facts inline versus query-only. The inline condition
   tests elicitation with sufficient task information. Query-only exposes
   answer priors and formatting behavior; it is not an equal-information
   capability baseline and need not solve facts it was never given.
3. **Separate choice readout from answer realization.** Record native
   yes/no margins and ties alongside whole-output validity, correctness,
   termination, and length. A model can rank the right choice yet fail to
   obey the output format. Conversely, constraining output to a yes/no grammar
   mechanically guarantees formatting, not correct reasoning. A constrained
   decoder, if included, needs its own method label and preregistered scorer.
4. **Declare stopping before observing answers.** State whether EOS, an
   explicit delimiter, a complete answer grammar, or a fixed budget terminates
   the new method, including how partial answers and extra text are handled.
   Do not select whichever prefix of an observed answer happens to be right.
   Preserve full token/termination traces and all planned denominators.
5. **Freeze an acceptance rule and independent confirmation set.** Specify
   the required formatting/termination performance and evidence of correctness
   beyond an answer prior before running the test. Development examples used
   to choose a renderer stay development examples. Confirm the chosen method
   on predeclared independent task/world/paraphrase families, without selecting
   cases because their answers changed or happened to be correct.

Exact question-span binding must be revalidated for every new renderer.
Keep mean reduction on the declared CPU-FP32 path unless a separately tested
numerical intervention changes it. New ordinary/native and written-zero
receipts are required; old parity does not qualify new prefix geometry.

Only after this instrument passes should a locked method compare retained
workspace candidates under the same information, formatting, and termination
contracts. That comparison would measure transfer to a new interface, not
silently reproduce the old training distribution. If the base-inline control
still fails, report an unresolved instrument/capability distinction and do not
compensate with stronger workspace gains or more FT steps.

## Next unit B — one learner factor: paired serialization exposure

The first learner comparison should change the **serialization distribution
of training inputs**, not add a new consistency loss at the same time. This
narrows the alternative-orders/consistency direction proposed in the frozen
plan into a first identifiable experiment.

- Define a label-independent correspondence between facts on the two sides
  and apply the same preregistered permutation to both. Freeze this mapping
  before training; verify preservation of each side's fact multiset and the
  intended content edit. Sorting happens to align subjects in the present
  two worlds, but future edits may change the available subject inventory.
  Such cases need an explicit correspondence contract or separate treatment,
  not an assumption that literal sorting universally matches the intervention.
- Use fresh, matched initialization and compare a learner repeating one fixed
  matched order against a learner exposed to multiple matched orders. Both
  arms use the same intact/twin fact correspondence; only order diversity
  changes. The historical independently shuffled input policy may remain a
  separately labeled anchor, but is not this single-factor baseline. Equalize
  world/query exposure counts, repeated examples, optimizer updates, batch
  composition, and token/compute-budget accounting. Repeating each original
  example is the exposure-matched baseline; simply adding augmented examples
  and extra updates would confound serialization with training amount.
- Keep the reader mode fixed within each comparison. If both existing reader
  modes are included, treat them as separately matched strata with a frozen
  interpretation, not a post-hoc choice of the better checkpoint.
- Retain the original paired loss, **FP32 selected-choice training readout**,
  residual-norm cap **1.0**, parameterization, and optimizer policy in both
  cells. Native readout remains an evaluation/transport diagnostic here.
  Do not bundle native-loss training, pooling changes, a gate, a larger cap,
  or a new regularizer with the serialization intervention.
- Keep fact-equivalence consistency as a later candidate. If a consistency
  penalty is eventually tested, compare equivalent orders **within the same
  factual side**; never collapse intact and counterfactual targets. Its loss
  weight and gradient tradeoffs require a separate preregistered comparison.

Before execution, freeze train/development/confirmation worlds and permutation
families, exposure accounting, seeds, primary checkpoint, resource budget,
scoring, controls, and gates. The current two worlds and inspected orders are
exposed diagnostics. Reserve unseen orders **and** unseen worlds for distinct
generalization questions; holding out a shuffle is not holding out the world.

Measure both reciprocal directions, same-order donor contrasts, unaffected
preservation, within-side order effects, ties, full-vocabulary disturbance,
and zero/unrelated/random/schema controls. A larger average donor margin must
not hide a reversed reciprocal direction or a serialization-specific shortcut.
Recompute the head/cap reachability preflight before requiring perfect fit:
the existing 25/32 FP32 ceiling is specific to the old prefixes and cap, and
a new renderer can change the relevant base margins. Retain unreachable rows
as outcomes instead of dropping them from the denominator.

## Later units — keep optimization and capacity separate

Native-readout training is now implementable, but has not been run or shown
better. A later matched old-FP32-versus-native-loss experiment should hold
the now-frozen data/serialization policy constant and measure both finite
update effects and actual native output changes. Nonzero cast-surrogate
gradients alone do not show that updates survive BF16 rounding or improve
generation. Do not call connectivity proof quantization-aware training.

A readout-cap change comes later as another factor, with an independent
full-vocabulary disturbance budget and correctness safeguards. The old
unreachable examples justify measuring feasibility, not tuning the cap until
an exposed score improves. Neither capacity nor longer runs resolve order
confounding or answer-format failures by themselves.

## Preserve the judge-derived goals and the release boundary

The [three-judge synthesis](../v14/FT_BETA_JUDGE_SYNTHESIS.md) and
[keep/strengthen/add plan](../v14/FT_BETA_IMPROVEMENT_PLAN.md) still supply the
behavioral direction:

- **Keep** concise, calibrated, measurement-aware verification proposals as
  development sentinels, alongside base identity and exact no-op behavior.
- **Strengthen** grounded fact use, reciprocal-query discrimination, useful
  explanations, and adherence to explicit constraints. Preserve good behavior
  without freezing its known factual or causal-design omissions.
- **Add** reliable mechanical checks, verifiable evidence spans, content/schema
  controls, and independent human-readable paired regression records.

The one jointly preferred historical causal/sample211 answer is not a training
target or a representative quality result. Current relation-probe generation
does not show whether that preferred behavior was retained. Do not use selected
judge labels for preference learning or replace an invalid answer with a more
charitable reading of its first token.

Still pending are the complete **48 legacy case-regime memory-control bank**,
fresh non-change-selected quality tasks, blind human review, and the independent
equal-information correctness battery and statistical manifest. The requested
base floor remains zero allowed loss on each prespecified primary benchmark
and protected slice, with a separate paired, cluster-aware uncertainty contract
for generalization claims. Three judge settings and the present two-world assay
do not satisfy those gates.

No next experiment is executed by this document. Current status remains
`winner: none`, `semantic_promotion: false`, `non_regression: NOT_ESTABLISHED`,
and human evaluation `PENDING`. The next useful milestone is a qualified
output instrument and an interpretable serialization-learning comparison,
not an early FT-beta release claim.
