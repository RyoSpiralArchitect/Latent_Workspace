# V23 toward 1.0 — use the existing memory better, protect the host

**Proposal grounded in V22 diagnostics, not a training/release dispatch.**
Evidence: [original comparison](../../provenance/pilots/v22_base_comparison01_20261021/README.md),
[weight/readout diagnosis](../../provenance/pilots/v22_weight_diagnostics01_20261021/README.md),
[memory causality](../../provenance/pilots/v22_memory_causality01_20261021/README.md).
Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED** until a separately
frozen acceptance protocol is actually passed. Do not rename the existing beta
or increment a release merely because this investigation completed.

## What to preserve

- Differentiable, adapter-free native-memory graph; native full-vocabulary
  generation; explicit empty-memory bypass; exact complete-owner restart.
- Content-sensitive counterfactual answering: V22 correctly changes from the
  original to donor answer in 12/16 exposed groups, including 7/10 groups with
  matched memory length. Unrelated-memory abstention is 16/16 in this panel.
- English-only, group-disjoint data admission and actual token-weighted
  instruction/prose/code/world mixture. Test/benchmark examples never become
  repair labels or checkpoint-selection targets.
- Transparent negatives and completion semantics. Exact symbol copying,
  correct reasoning, faithful instructions and concise formatting are separate
  outcomes; length caps cannot be relabeled as successful complete answers.

## What the new evidence changes

The writer/reader cells are 36, 39, 70 and 69 correct out of 80: most gain
travels with the reader, and the base-written memory is already usable by V22.
Yet the reader intervention also changes the query encoder, so it does not
locate the gain solely in layers above the cut. Writer adaptation has both
benefits and a specific harmful interaction: base-written memory restores
`Nymszrcrff.` where V22-written memory produces `Nymszrcrk.` with the same
V22 reader. Do not choose a hybrid based on this one exposed repair.

The remaining unaffected-query failures follow a competing object's changed
location. This points toward **question-to-fact binding and exact identity
transport**, rather than simply needing more nonzero memory or a larger writer.
Base already shows directional logit movement in all 32 twin directions, so
directional movement alone is not the milestone. The target is using that
information reliably in the actual answer without damaging the ordinary host.

## Next finite diagnosis, before another full-FT recipe

1. Separate **memory writer, query encoder, upper reader/head** at matched,
   identical-token decision prefixes through the existing model-independent
   host/cut interface. Use cross-state controls and exact self-cell replay.
   Start with frozen weights and a finite factorial, not multiple learner
   modifications at once. Carry affected, unaffected, absent and unrelated
   controls; retain both identity decisions and later exact-copy positions.
2. For the copy regression, patch bounded state regions/directions only after
   freezing the panel and masks. Distinguish useful memory content from writer
   perturbations that disturb an otherwise working native reader. A mask derived
   from test outcomes is diagnostic, never a training target or release score.
3. Expand to **fresh group-disjoint** multi-query worlds and natural fact-order
   paraphrases/distractors, with oracle preservation checked before scoring.
   Reversing contextualized states was an off-manifold stress test, not this
   natural invariance test. Hold out confirmation groups before choosing factors.

The host shares lower-layer parameters between memory and query encoding.
“Freeze only the writer” is not a simple parameter toggle: freezing the bottom
layers also freezes the query encoder; detaching the memory branch does not
stop those shared parameters changing via query gradients. State-patch results
must not silently become an allegedly independent writer parameter group.

## Candidate learner factors — independent, matched comparisons

**A. Query-conditioned answer identity.** Use train-only oracle pairs with the
same memory/different question and same question/counterfactual memory. Measure
the first differing answer-identity span and correct abstention through native
logits. Before adding another contrastive term, inspect gradient delivery and
conflicts at the implicated query/reader states. Keep ordinary token CE and
copy fidelity visible; do not convert generation into a two-candidate head.

**B. Ordinary-host preservation.** The earlier MMLU head factorial places the
two losses mainly in changed head inputs; freezing or increasing precision of
the head alone is insufficient. Evaluate original-host logit anchoring on the
existing **train-only** preservation bank as its own factor. Freeze teacher
identity, exact target distribution, token budget and storage/transport policy.
Do not train on MMLU answers or the exposed diagnostic mistakes. Report losses
and repairs, not only aggregate accuracy, at matched update/token budgets.

**C. Numerical/shape consistency.** Future-content and masked-future controls
are exact at 2,492 positions; cropping changes native argmax at 12 base and two
V22 positions. Assess decision margins using inference-realistic prefixes.
Any proposed static padding/bucketing policy must be fixed independently of
the unknown target answer/length and shared deliberately between train/eval.
Qualify it as a new condition; never rescore old generations to obtain a pass.
Norm precision remains a separate factor, not bundled with reader loss/LR.

For each selected learner change, require tiny CPU/CUDA tests, resource bounds,
exact full-update/save/fresh-restart verification and a frozen trial. Do not
increase epochs, teacher data, LR and multiple losses together. Preserve the
shared native parameter ownership and model-independent adapter boundary API.

## What a future 1.0 acceptance protocol still needs

- A fixed primary checkpoint rule and untouched confirmation data, with
  statistical/non-inferiority criteria decided **before** observing V23 results.
  “Few losses” or equality after a new tie-break is not the requested base floor.
- Ordinary-host public benchmark coverage independent of the exposed 570 MMLU
  questions, plus instruction, prose and code preservation. Keep per-task
  paired loss/repair counts and uncertainty, not a single pooled score.
- Content necessity/direction, unaffected-query stability, unsupported-answer
  abstention, exact copying and new compositional families. Same-length and
  natural-order controls must survive outside this 16-group panel.
- Complete paired generation on fixed prompts/seeds for reasoning, writing,
  code and multi-turn memory use. Evaluate reasoning consistency separately
  from a final correct token. Keep caps, contradictions and all selected pairs.
  Human/blind-judge review needs its own frozen rubric, order controls,
  calibration/repeatability and complete denominators; no judge calls here.
- Reproducible packaging, licenses/provenance, inference/restart checks and a
  model card with the actual qualified scope. Tiny portability tests on four
  architectures do not establish full-FT quality on other hosts. A Mistral-7B
  1.0 must not be advertised as a general architecture-independent quality win.

No new training, judge, generation extension, checkpoint deletion, PR/merge,
beta replacement or Hub upload is executed by this roadmap.
