# After FT04: recruit computation before answer readout

Status: **development design, not an implemented engine change or V25 run**.
Read the [completed crossed-route result](../../provenance/engineering/v24_recruitment_readout01_20261027/RESULTS_README.md)
and its [frozen protocol](RECRUITMENT_READOUT_01.md) first. The old expression
gate stays **FAIL**, `winner: none`, `non_regression: NOT_ESTABLISHED`.

## What changed, and what did not

The matched FT04 route arms reliably learned the response envelope: all four
FT/route cells terminate without a length cap, 34–36/36 parse, and all 12/12
absent/unrelated null cases answer correctly in each cell. Yet the 12 affected
target cases in **every** FT/route cell have the wrong answer. The inline arm
fails those cases even when training and inference both use inline facts, so
the failure is not uniquely attributable to the workspace transport. The
unaffected controls use simpler *different* tasks and cannot quantify the
same target computation with memory held fixed.

Answer-first training and reference targets provide the gold answer before
steps. Low step likelihood under that prefix may be answer-conditioned copying.
The steps-first reference reverses that assistance but still teacher-forces
gold steps, so its low later answer likelihood cannot demonstrate independent
computation. One loss scalar or one donor-prefix margin is not the missing
capability. The first milestone is a generated intermediate result that is
correct **before** the final answer, is actually used by readout, and survives
the unassisted generator without sacrificing base capabilities.

## Competing explanations to keep separate

1. **Target order / leakage.** Answer-first supervision may teach formatting
   and steps conditional on an already supplied result. Predict *earlier*
   step content without the gold answer, then test free generation. Do not call
   a steps-first answer token correct when gold steps are in its context.
2. **Insufficient computation curriculum.** The 21,112-target-token schedule
   contains only 2,023 world and 2,036 reasoning tokens. A 32-update run may
   learn short controls and null handling without robust multi-step operators.
   Compare group-held-out target correctness after changing only declared
   exposure, with preservation and old benchmark floors unchanged.
3. **Representation-to-readout failure.** Facts may be accessible in M while
   no query-conditioned result S is formed, or S may form but not affect
   answer logits/generation. Isolate retrieval, operation, result binding and
   final readout on identical inputs. A logit change alone is not correctness.
4. **Route mismatch.** The crossed routes differ in token positions and native
   arithmetic; matched information is not matched computation. A route effect
   requires a base/inline/workspace interaction *within* the same target family,
   with both a bypass and a compute-matched control before a causal claim.

These are hypotheses, not conclusions drawn from six source groups. Arithmetic,
register tracing and filtering all fail on affected targets, arguing against
fixing only one numerical operation.

## Bounded next experiment — freeze before model calls

First run an **offline-only reanalysis** of the existing literal outputs and
reference traces. The [result artifact](../../provenance/engineering/v24_recruitment_readout01_20261027/RESULTS.json)
already supports exact pair IDs, answer/step/format/EOS separation, donor
prefixes and all three checkpoint-by-route crosses. Preserve every invalid and
length-capped row. Report group-level counts and examples, not token-level
independent-sample significance. This publication is that first stage.

Next freeze a new, group-held-out diagnostic panel *before* using its outputs
to select an engine change. Each affected target needs an equally complex
same-operation control, a single-field twin with an independently executable
oracle, absent/unrelated M, no-memory ordinary tasks and copy sentinels. All
task families, templates, aliases and twin sides remain in one split. The six
already exposed V24 development groups are never relabelled confirmation.
Keep output budget, strict scorer, no grammar constraints and true free
generation fixed. Include both answer-first and steps-first references but
label gold-prefix assistance exactly.

For a learner contrast, change **one factor at a time**:

| Factor | Bounded candidate | Discriminating observation |
| --- | --- | --- |
| O: target order | Native answer-first baseline versus independently checked steps-before-answer supervision; matched source groups and token exposure | Correct *generated* steps and final answer improve without a gold prefix, not just reference NLL |
| S: internal result | Model-neutral, query-conditioned scratch workspace before answer readout; disabled path bit-exact to the prior engine | S bypass removes a target gain; an equal-compute inert S does not reproduce it |
| M route | Identical facts through inline or native M for each checkpoint | Improvement holds on both target twins and separates general FT from M-specific interaction |

Do not combine O and S in the first attribution run. Target-order O is a
control for leakage, **not** itself proof of latent S. A legitimate S cannot be
an oracle step, hidden label, extra supplied fact, post-hoc JSON rewrite or a
Mistral-only RMSNorm hook. It must be built from the query and supplied
information at inference; the final decoder must consume it. Any auxiliary
intermediate target belongs to the native engine's loss accounting with its
own denominator and no gold-answer information before the claimed step.

## Engineering and promotion gates

- Keep an engine option disabled by default. Verify exact original logits,
  gradients, optimizer update, checkpoint/save and fresh-process resume when
  disabled. For an enabled option, check nonzero question-side/reader gradients,
  parameter ownership, BF16 visibility and CPU/CUDA parity on tiny hosts
  before 7B. No Mistral-specific computation is embedded in the core.
- Freeze same initialization, train-only groups, target budget, update count,
  optimizer, precision, save policy and resource floors for paired 7B arms.
  Do not retry or silently replace a failed cell. Furnace availability and
  other workloads must be checked before any new remote execution.
- The quality gate requires affected target answers **and** independently
  checked intermediate computation on an untouched group panel, with
  counterfactual directionality and matched controls. Separately retain
  strict no-memory/base preservation on MMLU-Pro, code, instruction, prose and
  open generation. A broad answer or judge improvement cannot mask a
  base-correct loss or an affected target failure.
- Only after a new run passes its frozen evaluation may `winner` or
  `non_regression` change. No checkpoint retirement, public β promotion,
  judge call, threshold change or release follows from FT04 alone.

The registered Furnace endpoint timed out during the 2026-11-14 read-only
status check. No new GPU process was started; reachability is a logistics gate,
not a scientific result or proof that the host is powered off.
