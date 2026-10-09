# V15 follow-up: qualify the instrument, then isolate serialization learning

Client date: 2026-10-10. **POST-RESULT DESIGN / PROPOSED / NOT EXECUTED**.
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
