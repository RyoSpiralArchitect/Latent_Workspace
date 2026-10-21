# V23 next learner factors after separating W/Q/R

**Proposed engineering sequence, not a training dispatch.** Evidence is the
[completed frozen-V22 factorial](../../provenance/pilots/v23_state_factorial01_20261021/README.md).
No acceptance threshold or release gate changes. The objective is native full
FT that preserves ordinary ability and improves useful workspace computation,
not an optimized frozen-host hybrid or another task-specific output adapter.

## What the evidence rules out as a default

- Do not equate a small question-side gradient with the principal bottleneck.
  Q-only helps base R but has one nonempty and two absent-prefix losses with
  V22 R. Most improvement survives using the original Q with updated R.
- Do not call every improved next-token decision a reasoning gain. At fixed
  base W/Q, 87/108 R-induced repairs are period/EOS decisions. Preserve this
  useful alignment while measuring factual identity separately.
- Do not treat the late `ff`→`k` error as just weak question encoding. It
  appears only with jointly updated W/R, under either Q.
- Do not freeze only the head or only Q and declare retention solved. Both
  lower-only and upper-only changes retain the original two MMLU failures.
  All Q/R hybrids remain below the original count; compensation is not repair.
- W and Q are independent **state interventions**, not separate parameter
  groups. Freezing shared lower layers freezes both; detaching one branch
  does not stop shared weights changing through the other branch.

## Next finite implementation: a train-only gradient and objective audit

Use the existing English train-only world/preservation sources with a newly
frozen selection and no overlap with exposed diagnostic or confirmation groups.
Do not use the 16 observed groups, MMLU labels, copying patch masks or judged
test outputs as repair targets. Reusing a formerly OOD family for training
must be declared; it cannot remain an OOD confirmation family afterward.

Add an engine-owned diagnostic at the model-independent cut interface, not a
Mistral-only hook or a private version-specific learner. First tiny-qualify:

1. Separate loss contributions for oracle answer-identity tokens, later copy
   tokens and formatting/stopping tokens. Derive spans from the **training
   oracle and tokenization before scoring**, not a universal fixed index or
   observed mistakes. Preserve the original total-token denominator when
   decomposing CE; summing subgroup means changes the objective.
2. Measure each contribution's gradients at memory states, question-token
   states and continuation-token states, and their flow through the shared
   lower parameters versus upper reader. W/Q contributions must sum to the
   actual shared gradient; state interchangeability does not imply independent
   gradient ownership. Record norms, signs/cosines and native numeric visibility.
3. Compare them with a **no-memory original-host preservation objective** on
   the train-only instruction/prose/code bank. Stream gradient dot products
   per tensor instead of retaining several 7B gradient copies. Freeze teacher
   identity, arithmetic, prefixes and token budget before any teacher forward.
4. Require no-op objective parity, exact native update/save/fresh-restart, and
   hashes for the teacher targets/objective contract before a real-model trial.
   Any reference-target storage and resource costs need a new bounded canary.

The [first implementation and additive world preparation](PREPARATION_01.md)
now have [296/296 tiny tests on each device and replayed data](../../provenance/engineering/v23_preparation01_20261022/README.md).
The outer dispatcher had a retained receipt-contract error after the successful
data role; it was not rerun or relabeled. Live-state tracing, token contributions,
W/Q/R gradient attribution and full-vocabulary KL are tiny-qualified only.
The actual 7B gradient/conflict audit, reference-target generation and owner
integration have **not** run. A tensorwise reference avoids several full gradient
copies but is too replay-heavy to assume scalable; qualify a spill-based version.
The audit must determine whether the problem is missing/conflicting gradients,
margin, state compatibility or data distribution before choosing a loss weight.

The [scalable spill-based audit plan](GRADIENT_AUDIT_01.md) now implements
one backward per objective/row, with CPU FP32 diagnostic accumulation and
bounded tensorwise reductions. It keeps the prior 84-world/12-preservation
selection and separates a 7B path-sum resource canary from the panel-wide
conflict diagnosis. Implementation is not yet an executed 7B result; owner
objective integration and new-objective update/restart remain later gates.

The additive bank freezes 512 new groups / 4,096 raw rows, with 2,016 unique
train rows / 13,198 target tokens. The old two-hop family is explicitly promoted
using new groups; all old groups are excluded, and a new three-hop structure
is reserved as OOD. No model has evaluated the new confirmation/OOD groups.
The next 84-world + 12-preservation-row training panel is fixed at up to
105 memory / 128 query tokens. Its planned full-vocabulary base targets are
116.5 MiB, **NOT_RUN**. The larger OOD maximum of 163 memory tokens needs a
separate resource check. No mixture, optimizer or native training objective
changed merely because more candidate data is available.

## Independent learner factors, in order

**P — ordinary-host preservation.** Original-host full-vocabulary logit
anchoring on the train-only no-memory preservation bank, alongside ordinary
token CE. A frozen, chunked target bank avoids two live 7B models; its precision,
coverage and exact provenance are part of the objective. Do not truncate to
the gold token or turn a top-k approximation into an unqualified full-KL claim.
First compare P on/off with identical initialization, data and update/token
budgets. Native full FT remains the target; preservation is not a claim that
all host parameters should stop learning.

**B — question-conditioned recruitment.** Same memory/multiple questions and
same question/local counterfactual edits, with unaffected, absent and unrelated
controls. Audit the actual upper-reader binding path before making Q stronger.
Use train-only shared-prefix identities and compositional fact chains, with
fresh confirmation groups frozen before model selection. Compare normalized
answer correctness, identity-span decisions and punctuation/EOS separately.

**I — joint identity transport.** Late copying must remain reliable while W
and R co-adapt. Use varied train-only identifiers, near-neighbor symbols and
paired writer/reader state diagnostics. A reference-state penalty or another
copy objective is only a candidate after the gradient audit, not a consequence
automatically proven by the one exposed `ff` example. Do not silently train on
detached diagnostic banks or use the old model as a permanent writer shortcut.

Do not initially vary P/B/I, precision, data scale and LR together. Establish
the smallest useful factor, then a matched interaction comparison. Decide
primary checkpoint and untouched acceptance panel before seeing V23 results.
Generation review and reasoning/writing/code preservation follow their own
frozen matched-prompt/seed protocol; no new judge requests are implied here.

## Bring deliberation back without erasing the transport lesson

Keep three conceptual states distinct: query-independent stored memory **M**,
question-conditioned temporary working state **S**, and native readout. Future
latent steps should improve computation through S while leaving unrelated
facts in M usable. The current cut-4 composition demonstrates neither a new
recurrent S mechanism nor persistence across conversations.

After transport and preservation qualify, compare a native/shared computation
or boundary-feedback route at K steps against matched-compute/capacity controls
and an inference bypass. Respect the adapter's precise pre/post-normalization
boundary; feeding normalized final states back as arbitrary cut inputs is not
a validated recurrence. Keep zero-effect parity and model-independent host
bindings. Geometry/retention losses are health tools, not evidence of thought.

This revives v4's question—does work in the latent state help?—without importing
all its losses or promoting its old readout results. Availability, occupancy,
deliberation and consequence each keep their own endpoint. See
[WORKSPACE_REVIVAL.md](WORKSPACE_REVIVAL.md) and [the full roadmap](ROADMAP_TO_1_0.md).

Before another checkpoint-writing run, refresh storage admission. Ryō separately
authorized obsolete-weight cleanup on 2026-10-22: three completed engineering
canaries were [recorded and retired](../../provenance/inventory/v23_obsolete_canaries_20261022/README.md),
freeing 81.0373 GiB. The current V22 step16/32, original Mistral, previous
scientific weights and 6.30 GiB of diagnostic activation bodies remain. This
does not authorize deletion of every old experiment or any unrelated data.
