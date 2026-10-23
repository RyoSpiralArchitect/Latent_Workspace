# Latent Workspace

Research repository for building a continuous intermediate **latent workspace**
in decoder LLMs.
This repository follows the long arc named in the project description: from
full fine-tuning, through host portability, toward from-scratch latent workspace
models. The current public Mistral-7B-Instruct-v0.3 LTWS β is a measured
frozen-host artifact on that path, not the architectural endpoint.

The repository is the source record for that path: designs, sealed runs,
offline replay records, negative results, failed results, package checks and
scope limits are kept together. Runs are frozen before launch, execute from a
sealed commit on a remote CUDA node ("Furnace"), are replayed offline, and keep
every negative or failed result. The historical claim ceiling remains explicit:
**FAIL / winner:none / non_regression NOT_ESTABLISHED** where not superseded by
dated evidence.

## Reading this repository

**2026-10-23 next FT preparation:** the [matched native input-route bank](provenance/engineering/v24_recruitment_preparation01_20261023/README.md)
is frozen after 60/60 isolated Furnace CPU tests: **32 updates / 538 rows /
21,112 targets per arm**, with identical information/targets supplied inline
versus through workspace. Arithmetic/register/transform tasks broaden the
unused world expansion; preservation stays a floor. [Scope and controls](docs/v24/RECRUITMENT_FT_01.md)
and [execution handoff](provenance/engineering/v24_recruitment_ft01_20261023/EXECUTION_HANDOFF.md)
separate preparation, real-model restart and training. [CPU and CUDA each passed
570/570 tests](provenance/engineering/v24_recruitment_ft01_20261023/README.md),
but the 7B canary stopped after **one of two updates and its first save** when
another GPU client appeared. Replay and both scientific arms remain unrun;
the failed trial and its checkpoint are preserved. No new candidate result
yet. A separately recorded
[V15 engineering-pair retirement](provenance/inventory/v24_v15_engineering_20261023/README.md)
reclaimed 54.12 GiB; original and V18/V22/V23 comparison weights remain.

**V24 readout complete:** [portable diagnosis and workspace capability improvement](docs/v24/README.md),
with [all 132 traces / 591 forwards replayed](provenance/engineering/v24_readout_probe01_20261022/README.md)
after 350/350 CPU and CUDA tests. Four assisted-content probes bind the correct
option in all three arms; on four world groups, reference-format likelihood
gain dominates content gain. This is exposed conditional evidence, not a new
benchmark or a universal bottleneck diagnosis. No new scientific FT arm has run.
New engine-owned observational instruments separate fixed-token content/copying,
option binding and EOS; original/candidate × no-memory/inline/workspace contrasts
keep missingness and group-level denominators. This bounded 7B diagnostic
is not new FT or evidence of general intelligence. Preservation remains a floor;
useful workspace-dependent improvement is the target. See the
[execution handoff](provenance/engineering/v24_readout_probe01_20261022/EXECUTION_HANDOFF.md)
for live receipt status and the separate Full-FT/storage gates.
Two superseded engineering/intermediate checkpoints were
[recorded before deletion and retired](provenance/inventory/v24_intermediates_20261022/README.md),
freeing 54.02 GiB; scientific final comparison weights remain intact.
The subsequent [paired-route FT qualification](provenance/engineering/v24_recruitment_ft01_20261023/README.md)
passed 570 CPU/CUDA tests but stopped after one canary update on another GPU
client. [FT02](provenance/engineering/v24_recruitment_ft02_20261023/README.md)
stopped earlier on an external-audit error despite 570 passing CPU tests.
[FT03](provenance/engineering/v24_recruitment_ft03_20261023/EXECUTION_HANDOFF.md)
is the authorized audit-only, separate-source recovery with 608 tests per device;
no scientific arm or quality success is claimed. Historical failures remain.

**2026-10-22 readout complete:** [integrated V23 evaluation](docs/v23/EVALUATION_SYNTHESIS.md)
and [full-FT PR review map](docs/v23/FULL_FT_REVIEW_GUIDE.md).
MMLU-Pro direct base/off/on is **92/101/100 of 280**; strict parsed reasoning
is **11/9/8 of 28**. These use different prompts and a nested small panel, not
a causal readout comparison. The 174-request blind judge returned **170 valid
and four invalid** judgments, with **13/72 main-pair order conflicts** and
**4/12 repeat disagreements**. It favors some FT writing/constraint behavior
but does not establish a winning arm or general non-regression. All outputs,
negative results, exclusions and source seals are retained; no release gate changes.

Latest V23 step: [matched P-off/P-on native full FT is complete and replayed](provenance/engineering/v23_preservation_ft01_20261022/TERMINAL.md):
32 updates / 723 rows / 20,860 targets per arm, after 472/472 CPU and CUDA
tests and exact real-model v2 restart. On the same exposed 40-row dev panel,
base/off/on NLL is 1.267038 / 1.058723 / 1.069616. Both improve this loss;
KL-on gives slightly less CE gain, with retention **not yet established**.
Off exactly reproduces V22's final state fingerprint and dev results.
The [complete recovered benchmark/generation diagnostic](provenance/pilots/v23_comparison_recovery02_20261022/README.md)
now combines original base/off with whole recovered P-on under separate source
seals. MMLU base/off/on is **356/354/355 out of 570** (tie-free **351/349/349**);
latent-world exactness is **47/83/83 out of 96**, inline **75/87/86**. No trained
arm gains a base-wrong MMLU item on this selected panel. This is not a general
retention pass or proof of causal workspace use. The [literal answer bank](provenance/pilots/v23_comparison_recovery02_20261022/analysis/ANSWER_BANK.md)
contains all 72 free answers, including capped/unchanged ones; all 648 world/free
literal sequences replay. P-on passed both 248-test suites and CPU isolation.

The [original incomplete comparison](provenance/pilots/v23_comparison01_20261022/README.md)
and [failed collection recovery](provenance/pilots/v23_comparison_recovery01_20261022/README.md)
remain unchanged. Their partial rows are never spliced into the completed bank.
The [explicit follow-up](docs/v23/RECOVERED_FOLLOWUP_01.md) retains the
[32/32 passed Mistral calibration](provenance/pilots/v23_behavior_judge01_20261022/README.md)
for the [now-completed 174-request study](provenance/pilots/v23_recovered_behavior_judge01_20261022/README.md).
Its validity, order/repeat sensitivity and bounded preference view are reported
separately; text differences alone do not establish quality. The
[first recovered MMLU-Pro attempt](provenance/pilots/v23_recovered_mmlu_pro01_20261022/README.md)
passed 301/301 CPU and CUDA plus isolation, but stopped on inactive CUDA
reservation growth after base's 280 direct scores (92 correct), before any
complete reasoning row. Off/on were undispatched. A separately authorized
[cache-only repair](docs/v23/RECOVERED_MMLU_PRO_02.md) preserves all inputs,
decoding conditions and resource floors. Its [new attempt is complete](provenance/pilots/v23_recovered_mmlu_pro02_20261022/README.md):
840 scores / 84 reasoning sequences, all replayed locally after historical
315/315 CPU and CUDA gates. No stopped run was resumed or partial arm spliced.
See the [design](docs/v23/PRESERVATION_FT_01.md) and
[execution handoff](provenance/engineering/v23_preservation_ft01_20261022/EXECUTION_HANDOFF.md).

The README is an entrypoint, not the claim authority.

For the public β package scope, read
[docs/v20/BETA_PACKAGE.md](docs/v20/BETA_PACKAGE.md).
For the architecture and portability target, read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
For run evidence, read the linked provenance records.
For historical status, keep the dated claim ceilings attached to each run.

## Toward native full fine-tuning (2026-10-20)

The [post-beta full-FT plan](docs/v1_0/FULL_FT.md) starts from the native
latent-memory path, with both writer and reader differentiable and the entire
native vocabulary head trained. Its first implementation is
[`NativeMemoryCausalLM`](src/latent_workspace/native_memory.py), separate from
the beta's frozen two-candidate adapter. Small-model graph qualification is
not a 7B training result. The engine-owned CPU-master optimizer/checkpoint
owner now passes [203/203 selected tests on both CPU and CUDA](provenance/engineering/native_owner_qualification_attempt03_20261020/README.md),
including exact fresh-process replay. Two earlier CPU backend failures remain
recorded; the qualified condition explicitly disables CPU oneDNN and retains
BF16. After separate approval, the [six closed V16 checkpoints were recorded
and retired](provenance/inventory/v16_scientific_retirement_20261020/README.md),
recovering 162.46 GiB; 243.61 GiB was available afterward. V18 and the original
Mistral remain. Git preserves evidence, not recoverable weight bytes.
The [new bounded 7B canary](provenance/engineering/native_7b_canary_20261020/README.md)
passed 229/229 tiny checks on each device, then stopped at original-model
identity before any training update: the new harness compared a historical
tree-hash digest with the legacy hash function. The failed source and raw
receipts are retained, replay was not dispatched, and no automatic retry
followed.
The separately authorized [identity recovery](docs/v1_0/NATIVE_7B_RECOVERY_01.md)
then passed 244/244 CPU and CUDA checks and
[completed two real-7B native updates, two saves and exact fresh-process
step-2 replay](provenance/engineering/native_7b_identity_recovery01_20261020/README.md),
with both original-model hashes matched and the recipe/limits unchanged.
Peak CUDA allocation was 27.690 GiB and peak host RSS 86.809 GiB. This is a
four-input engineering gate, not a quality gain: a finite full-FT recipe,
longer-sequence resource qualification and original-base non-regression
evaluation remain unmet.

### Data and longer-backward preparation (2026-10-21)

The separately authorized
[resource recovery](provenance/engineering/native_resource_probe_recovery01_20261021/README.md)
passes 254/254 CPU and CUDA checks and all three no-update backward rows up
to 128 memory + 128 query tokens. Peak CUDA allocation/reservation is
27.696/28.365 GiB; both native and CPU master weights remain unchanged.
This does not extend the short optimizer-step/restart proof to those lengths.

The [deterministic world bank](provenance/data/native_world_bank01_20261021/README.md)
now contains 1,024 grouped worlds / 8,192 rows plus 128 small instruction seeds,
with executable answer checks and disjoint groups; 2,048 control duplicates
are explicitly counted. A [local 32B teacher inspection](provenance/data/native_teacher_inspection01_20261021/README.md)
completed 64/64 fixed requests. All pass structural checks, but 48/48 world
questions drop the memory-use policy and 9/24 twin pairs change question text.
The additive composer therefore retains canonical memory/query and takes
teacher answer prose only; all 64 derivatives remain quarantined, not approved
for training. The [full preparation notes](docs/v1_0/DATA_PREPARATION.md) keep
source seals, original failures, raw outputs and exact token denominators.
In that original bank, ordinary instructions are only 4.05% of canonical
training-candidate answer tokens under row-uniform sampling.
The additive [preservation candidate bank](provenance/data/native_preservation_bank01_20261021/README.md)
now provides 1,754 train / 184 development candidates, with 324,616 / 39,761
supervised Mistral tokens, using existing human prose and a pinned 41.6 MB
OpenAssistant acquisition. QSpace's CodeXGLUE validation is exclusion-only.
Offline full regeneration passes; 635 rows exceed the tested 128-query-token
backward axis. These are not training approvals or a retention result:
rights/admission review, mixed-recipe resource qualification, full-FT mixture
and unseen non-regression gates remain before training.

### V22 English-only native pilot (2026-10-21)

Ryō authorized an additive English-only projection, mixed update/save/replay
qualification, and then native full-parameter training. The
[frozen V22 plan](docs/v22/FULL_FT_01.md) specifies 32 updates / 723 unique rows /
20,860 supervised tokens, with token-balanced world/instruction/prose/code
exposure. The [data projection](provenance/data/v22_english_mixture01_20261021/README.md)
fully regenerates offline and leaves both original banks unchanged.
Long 1,024-token mixed canary/replay and complete CPU/CUDA qualification gate
the training roles; training starts from the original, not canary weights,
and resumes in a fresh process at step 16 if its prerequisite gates pass.
The [first execution](provenance/pilots/v22_full_ft01_20261021/README.md) now passes
290/290 checks on each device and two real-7B long updates plus checkpoint
save/restore. Replay's first row has exact loss/gradient equality, but its
post-spill free GPU memory falls to 440 MiB (768-MiB minimum) while 16.656 GiB
remains reserved but unallocated. The run stops without retry; **full V22
training remained undispatched in that trial**. The separate
[cache-boundary recovery](provenance/pilots/v22_full_ft_recovery01_20261021/README.md)
now passes 318/318 CPU and CUDA checks, both real-7B updates and complete exact
fresh-process replay. One explicitly approved old canary body was retired after
the successful gate and published ledger. The recovery then **completed all
32 native full-parameter training updates / 723 rows / 20,860 supervised
tokens**, including exact step-16 state restoration in a fresh process.
On the same fixed 40-row development panel, all 40 teacher-forced NLLs fell;
the token-weighted mean changed from **1.267038 to 1.058723 (−16.4411%)**.
All seven panel means fell, including the small instruction/prose/code panels.
This is the original versus updated model under the same native-memory graph,
not a public benchmark or a free-generation comparison. Three checkpoint
bodies and both source seals were verified; the old failed trial is unchanged.
**FAIL / winner:none / non_regression NOT_ESTABLISHED** stays in force.
Unseen non-regression, causal memory-use and paired generation evaluations
remain separate next gates; no beta replacement or release is implied.

### V22 versus original base: first comparison (2026-10-21)

The [fixed-checkpoint comparison](provenance/pilots/v22_base_comparison01_20261021/README.md)
completed both arms, 1,140 MMLU scoring rows and 432 generated sequences.
The reused 570-question MMLU panel changes **356→354 correct (−0.351 pp)**;
both argmax regressions become BF16 B/D ties. Strict-tie scoring also loses
two net answers. This is not established non-regression.

On grouped held-out worlds, latent-route exact generation changes
**32→64/72 test** and **15→19/24 OOD**. The test latent-versus-inline gap
shrinks from 25 answers to one; the OOD gap remains three. Four of the
12 affected test repairs are formatting-only; remaining abstention and
exact-symbol-copy errors are retained. These are 16 twin groups, not
independent evidence from hundreds of tasks.

All [24 fixed-prompt/seed free-generation pairs](provenance/pilots/v22_base_comparison01_20261021/ANSWER_BANK.md)
are published unblinded. Every pair differs, but reasoning inconsistencies
and 10 base / 9 V22 length-capped free replies prevent a blanket quality claim.
Offline input/decoding replay and both 138-test qualification invocations pass.
No additional training, weight deletion, paid judge or release occurred;
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.

### V22 weight and readout diagnosis (2026-10-21)

The [additive read-only diagnosis](provenance/pilots/v22_weight_diagnostics01_20261021/README.md)
passes 158/158 selected checks on CPU and CUDA, then reproduces all 1,140
MMLU scores, 384 world conditions and 2,814 recorded next-token choices with
zero trajectory disagreement. No new continuation or training was performed.
Both original MMLU losses remain wrong with an FP32 head; matched head swapping
changes no predictions on the 570-question panel, while changed hidden states
change 11. Of the 13 remaining latent world failures, 12 first diverge within
two tokens; their decisive token accounts for 94.8–99.6% of target-sequence NLL.
FP32 head projection repairs none of those first forks.

The 291-tensor census finds changed values in 98.42% of FP32 master elements
but 11.15% of native BF16 elements; 52 native normalization tensors are unchanged.
Full-teacher versus prefix-only arithmetic also changes gold-argmax correctness
at two shared-prefix positions per arm; its numerical-versus-layout cause is
not established. The [next proposal](docs/v22/POST_DIAGNOSTIC_NEXT_STEPS.md)
therefore qualifies that instrument before separate reader-decision, body
preservation and normalization-visibility experiments. Historical scores and
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remain unchanged.

### V22 memory-content causality and the V23 direction (2026-10-21)

The [completed causal assay](provenance/pilots/v22_memory_causality01_20261021/README.md)
passes all 187 selected CPU/CUDA checks, 2,492 fixed-prefix controls and 928
bounded intervention/replay generations. Equal-extent changed/masked future
tokens leave every observed vocabulary logit identical; cropping explains the
remaining extent-sensitive discrepancy without evidence of answer-content leakage.

For 20 reciprocal directions in 10 equal-length memory-twin groups, V22's
donor margin increases in 20/20 and it correctly switches original→donor in
14/20 (base 4/20). The writer×reader comparison on 80 nonempty rows is
**36/80 base/base, 39/80 V22-writer/base-reader, 70/80 base-writer/V22-reader,
69/80 V22/V22**. Most gain travels with the reader side (which includes query
encoding). Base-written memory also repairs the `Nymszrcrff.`→`Nymszrcrk.`
copy regression at the otherwise unchanged V22 reader. Unaffected-query
misbinding remains in two OOD groups. No hybrid is promoted from this panel.

The [V23-to-1.0 proposal](docs/v23/ROADMAP_TO_1_0.md) prioritizes query/fact
binding, exact identity transport and ordinary-host preservation as separate
factors. This is exposed-panel mechanism evidence, not a release pass: native
MMLU remains 356→354/570 and free-generation quality remains unjudged.
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.

### V23 preparation: question encoding versus the upper reader (2026-10-21)

The [completed frozen-V22 state factorial](provenance/pilots/v23_state_factorial01_20261021/README.md)
separates memory writer W, query/continuation encoder Q and upper reader/head R.
It passes 216/216 selected tests on each of CPU/CUDA, 2,386 full-logit self-parity
checks and 1,193 repeated endpoints, with **7,008 unique diagnostic cells** and
zero training or new generations. All 96 exposed worlds and 570 reused MMLU
questions remain diagnostics, not fresh release confirmation.

With base W/Q, changing only R improves gold-prefix next-token agreement from
442 to 550/559, but 87/108 repaired positions are period/EOS decisions: useful
output alignment, not an equivalent reasoning gain. Updated Q helps base R but
adds one nonempty and two absent-prefix errors with V22 R. The late `ff`→`k`
copy error requires jointly updated W/R under either Q, isolating a different
compatibility failure. Original MMLU losses survive both lower-only and upper-
only hybrids; the four Q/R counts are 356, 354, 355 and 354/570.

[Next learner factors](docs/v23/NEXT_FACTORS.md) therefore start with train-only
gradient/conflict analysis, ordinary-host protection and joint identity
transport—not simply stronger question-side loss. The
[workspace revival](docs/v23/WORKSPACE_REVIVAL.md) restores availability,
occupancy, deliberation and consequence as distinct goals. No hybrid is
promoted, no V23 weights are trained, and the old FAIL/non-regression ceiling
is unchanged. Full row-level examples are in the
[fixed-prefix panel](provenance/pilots/v23_state_factorial01_20261021/FACTORIAL_PANEL.md).

### V23 oracle expansion and objective instruments (2026-10-22)

The [additive preparation](provenance/engineering/v23_preparation01_20261022/README.md)
adds **512 groups / 4,096 raw world rows**, disjoint from all prior groups and
identifiers. After duplicate controls, the new train pool has 2,016 rows /
13,198 supervised tokens. Fresh naming/binding controls and a reserved 3-hop
structure accompany the explicit promotion of the former 2-hop OOD family.
No new confirmation/OOD model scores or training updates were produced.

Tiny CPU/CUDA suites each pass **296/296**, including no-op trace parity,
oracle-defined identity/copy/format contributions, shared W/Q/R gradient
attribution and full-vocabulary preservation-KL primitives. The outer dispatcher
failed on a missing completion-status key **after** the data role passed.
The failed receipt is retained; offline replay verifies the child results,
and the subsequent configuration/validation fix has three local regressions.
No role was rerun. This is not an all-green 7B run or a new trained learner.

Preparation froze the next train-only inputs at 84 world + 12 preservation rows;
base-target generation was **NOT_RUN in that stage**. See the
[updated next factors](docs/v23/NEXT_FACTORS.md). All historical quality/release
ceilings remain unchanged; no weights were deleted during preparation.

### V23 scalable 7B gradient audit — complete (2026-10-22)

The [new spill-based audit](provenance/engineering/v23_gradient_audit01_20261022/README.md)
passes **338/338 CPU and CUDA tests**, then the real-7B engineering canaries at
both original base and frozen V22: **291/291 parameter-path sums per model**
within the predeclared BF16 numeric bound. Trace/no-trace and detached-reader
forward replay are bitwise exact. Base peak CUDA allocation is 17.780 GiB;
this is a short diagnostic, not an optimizer-training memory estimate.
All 12 base teacher distributions / 932 supervised positions are prepared
with full-vocabulary FP32 log probabilities (116.5 MiB of tensor payload).
V22's strict step32 restore passes before its canary.

The fixed **84-world / 14-group + 12-preservation** panel is now
[complete and replayed](provenance/engineering/v23_gradient_audit01_20261022/TERMINAL.md).
Both native hashes remain unchanged. Identity contributes 99.018% of remaining
world CE, while the median per-row question/memory state RMS ratio is 1.235.
Total world and preservation-KL gradients have a small negative cosine
(-0.020744); this is not an optimizer or quality result. The next factor is a
matched preservation on/off comparison, not automatic Q amplification.
No optimizer update, new generation, held-out test, judge or release occurred
in the audit. Its [interim snapshot](provenance/engineering/v23_gradient_audit01_20261022/interim_furnace/INTERIM_MANIFEST.json)
is preserved. See the [handoff](provenance/engineering/v23_gradient_audit01_20261022/EXECUTION_HANDOFF.md).

In parallel, [offline preservation-target binding](provenance/engineering/v23_preservation_binding01_20261022/README.md)
now connects pinned target metadata to exact complete rows and causal logit
positions. It does not consume target bodies or change the existing owner.
The [next objective-owner contract](docs/v23/OBJECTIVE_OWNER_CONTRACT.md)
separates P-off arithmetic parity, CE/KL normalization and new-objective
save/restart from a V22 checkpoint transition. Coefficients and a training
recipe remain unselected pending the complete audit; no extra GPU run starts.

Separately, [three obsolete engineering canaries](provenance/inventory/v23_obsolete_canaries_20261022/README.md)
were recorded and retired, freeing **81.0373 GiB**. Original Mistral, V22
step16/step32, previous scientific branches, activation banks and datasets stay.
Git retains metadata and hashes, not recoverable copies of the deleted weights.

## Current public artifact: LTWS β (2026-10-18)
 
**[mistral-7b-instruct-v0.3-LTWS β](https://huggingface.co/RyoSpiralArchitect/mistral-7b-instruct-v0.3-LTWS-beta)**
is on Hugging Face as a research preview, under Apache-2.0.

LTWS β packages one narrow A-line slice of the project on a frozen
Mistral-7B-Instruct-v0.3 host. Facts are written as latent memory through the
host's lower layers and read by a small route for yes/no questions. The adapter
is the current release form for a checked experiment; it does not replace the
full fine-tuning, other-host, or from-scratch targets.

Read it as:

a checked package of the current frozen-host experiment;
an artifact for inspecting latent-memory readout behavior;
a stepping stone toward full fine-tuning, host portability and from-scratch
workspace training.

Do not read it as:

a general QA model;
a text-generation route;
a general reasoning improvement;
a broad non-regression guarantee outside the checked settings;
the final architecture.

Evidence currently exposed by the package:

**Frozen host:** LTWS β adds routes to Mistral-7B-Instruct-v0.3 and changes no
upstream weights.
**Latent memory path:** facts are run alone through the host's first four
layers; their states can be cached and read with a question later.
**Standard benchmark checks:** with LTWS off / no relevant memory, checked
logits match the upstream host in the recorded package tests.
**BoolQ diagnostic:** frozen Mistral reads a real passage held as latent
memory almost as well as from its prompt (0.831 against 0.850), while the β
route itself is not claimed as a natural-QA route.
**Scope limit:** the sealed β claim is narrow: synthetic ranking worlds,
yes/no questions and a fixed English format.

Details, checks and records are in
[docs/v20/BETA_PACKAGE.md](docs/v20/BETA_PACKAGE.md); the benchmarks are in
[provenance/beta/ltws_beta_benchmarks_20261018](provenance/beta/ltws_beta_benchmarks_20261018/README.md).

 ## Status (2026-10-16)

This section is retained as historical status at that date. It predates the
public LTWS β package above; dated release-goal lines below should be read in
that historical context.

## Architecture

[ARCHITECTURE.md](docs/ARCHITECTURE.md) maps every module onto one stack (host
binding, workspace algorithms, routes, composition, ownership, instruments)
toward portability to other models and to training from scratch.
[`latent_workspace`](src/latent_workspace/) is the engine: it owns its code and
never imports the frozen historical package. Historical algorithms enter it only
by promotion, a verbatim copy pinned by a
[parity test](tests/test_latent_workspace_stack.py); so far the cut protocol
(Mistral, OLMo2, GPT-2, and a small from-scratch decoder), the native readout,
v4.1/v5 lattices, `LatentWorkspaceLoss`, v4's logit adapter and the exact
statistics, with three routes (logit, answer-position, cut).
[Rule tests](tests/test_architecture_rules.py) keep generality from growing
outside the engine.

## Version map

| Version | Focus | Start here |
| --- | --- | --- |
| V20 | A2: the flip through v4's logit route, on the `latent_workspace` engine (next) | [docs/v20](docs/v20/README.md) |
| V19.5 | The square of Deliberation, Occupancy, Availability and Consequence; the architecture and `latent_workspace` engine; D1 (Deliberation pilot) and A1 (Availability ladder). Files keep their `v20` names. | [scope](docs/v20/SCOPE.md) |
| V19 | Separate norm budgets for the common and workspace routes: dual-budget reader and owners, frozen diagnostic attempt 01 | [design](docs/v19/DUAL_BUDGET.md) |
| V18 | Complete windows and reference ownership, operand selection, selection owners, first 7B pilot, frozen-backbone diagnostic | [roadmap](docs/v18/FULL_UPDATE_ROADMAP.md) |
| V17 | — | There is no V17. The maintainer skipped the number by mistake; the gap means nothing. |
| V16 | Separate slot-contrast route, 7B adapter migration, bounded three-arm full comparison, population diagnostics | [plan](docs/v16/PLAN.md) |
| V15 / V15.5 | Native readout contracts, full-native backward, full-update learner, readout adapters, adapter state owner | [plan](docs/v15/PLAN.md) |
| V14 | Portable operators, instrument gates, boundary and precision assays, precision bridge, answer bank and judging | [portable boundaries](docs/V14_PORTABLE_BOUNDARIES.md) |
| V13 | Normalization-state design and visibility diagnostics | [design](docs/V13_NORMALIZATION_STATE_DESIGN.md) |
| V9–V12 | Query-deferred harness, transport v2, V11 objective and LR studies, V12 calibrated route | [runtime status](#historical-runtime-status-not-v13v14-qualification) |

V13–V18 were developed as stacked branches and merged into `main` on
2026-10-15 (PRs #14, #12, #13, #15, #16 and #17). Three V11/V12-era
fixes that `main` had received are kept in history but not in the merged
sources, because V14–V18 seals pin those files byte for byte; see PR #14.
V19, its stopped diagnostic, closeout and the first scope note followed in
PR #18. V19.5 followed in PRs #19–#22: the square (#19), the D1 Deliberation
pilot (#20), the architecture with the `latent_workspace` engine (#21) and the
A1 Availability ladder (#22). V20's A2 groundwork and power checks followed in
PR #23, and the A2 depth ladder in PR #24.

## V19: separate norm budgets for the common and workspace routes

The [dual-budget reader](src/latent_workspace_ft_v10/v19_dual_budget_reader.py)
bounds the workspace route by its own soft cap instead of the share the common
route leaves over; writer, queries, parameter layout and initialization are
V18's, and the pipeline, state guard and owners are additive V19 copies
([design](docs/v19/DUAL_BUDGET.md), 30 owner tests). The
[frozen diagnostic, attempt 01](provenance/pilots/v19_frozen_dual_budget_20261015/README.md)
repeated the V18 design with three arms. `ordered_cap025` completed: the
workspace route sits at its 0.25 cap for intact, twin, reversed and unrelated
memory alike, the intact-versus-twin answer-gap change is about 0.003 in FP64
and undirected, and 0/256 held-out answers flip. `final_cap025` stopped during
its held-out evaluation when another project's process appeared on the GPU;
`ordered_cap100` and the replay never ran. Offline verification of the stopped
attempt passed locally and on Furnace, and exposed a stale V18 checkpoint-format
check in the sealed V19 verifier, now fixed with
[regression tests](tests/test_v19_frozen_verifier.py). A fresh-process
[owner qualification](scripts/qualify_v19_dual_budget.py) is implemented and
rehearsed locally, not yet run on Furnace. V19 is closed by Ryō's decision; the
[closeout](docs/v19/CLOSEOUT.md) records what it settled, what V20 inherits and
the questions it leaves.

## V18: complete windows, operand selection, owners and the first 7B runs

The prospective [V18 preparation](docs/v18/PREPARATION.md) integrates the V16
diagnostics with original-base preservation and a generalized complete-window
reduction contract. Its additive [window/reference state layer](docs/v18/WINDOW_REFERENCE.md)
now [passes 310/310 tiny tests on CPU and CUDA](provenance/pilots/v18_window_reference_recovery_01_20261015/README.md),
including source/receipt replay; the original guard failure is retained. This
foundation alone implies no 7B training, preservation loss or selection mechanism.

The subsequent [additive operand-selection prototype](docs/v18/OPERAND_SELECTION.md)
now separates common and interaction queries. Its
[authorized continuation](provenance/pilots/v18_operand_selection_continuation_01_20261015/README.md)
completes **200/200 CPU and CUDA engineering tests**, then **12/12 controlled
reader-only fits per runtime**, with exact same-runtime offline replay.
Ordered selection passes every seed's toy learnability gate (held-out strict
**1,150/1,152, 1,152/1,152, 1,152/1,152**), but **not** the +5 pp advantage gate.
All three final-state comparisons retain their failed permutation-tolerance
checks; only 9/12 control bundles pass per runtime. The
[original CUDA admission failure](provenance/pilots/v18_operand_selection_20261015/README.md)
is unchanged. The [next boundary is the actual writer](docs/v18/ACTUAL_WRITER_TRANSITION.md),
not a 7B launch, owner admission, semantic winner or non-regression claim.

The [saved-state numerical diagnosis](provenance/pilots/v18_selection_permutation_20261015/README.md)
now completes 12/12 states on CPU and CUDA. Repeats and instrumentation parity
are exact, but **0/24 historical logit arrays reproduce bit-for-bit**, despite
zero historical/new answer changes in 13,824 state-query observations per
runtime. Centered-memory rounding is localized in the new execution, not yet
established as the historical cause. All cells retain
`BLOCKED_CONTROL_REPRODUCTION_MISMATCH`. The separate
[flag intervention](provenance/pilots/v18_replay_flags_20261015/README.md) now
explains that observed discrepancy: retaining historical flags reproduces all 24
historical arrays and full controls; freezing all parameters reproduces all 24
prior diagnostic outputs. Both policies remain eval/no-grad. The historical
six permutation failures remain unchanged. The actual-writer helper has 42
tests and the [selection state guard](docs/v18/SELECTION_STATE_GUARD.md) has 76;
neither is a fitted writer or a full update/resume owner. That diagnostic's
combined selected suite passes 533 local CPU tests.

The separate additive
[selection native owner](provenance/pilots/v18_selection_owner_local_20261015/README.md)
now passes 150 tiny local mechanics tests and ten CPU process-restart cases,
with exact next-update state and RNG agreement. Its
[window envelope](provenance/pilots/v18_selection_window_20261015/README.md)
then passed sealed Furnace CPU and CUDA qualification: 102 tests and ten
independent-process restart pairs per device, verified offline.

The first real
[7B native pilot](provenance/pilots/v18_native_pilot_20261015/README.md) then
matched the V16 receipt bit for bit, completed two centered-ordered full-parameter
windows and replayed exactly in a fresh process; intact/twin memory still changed
no native answer gap. A [frozen-backbone diagnostic](provenance/pilots/v18_frozen_diagnostic_20261015/README.md)
then trained only the workspace for 512 windows: 0/256 held-out donor flips in
both query arms, with the common route saturating the shared residual budget.
None of this repairs the historical permutation failures or establishes
semantic improvement.

The [full-update roadmap](docs/v18/FULL_UPDATE_ROADMAP.md)
orders state ownership, native capacity, FT, benchmark and conditional release.
The [behavior protocol](docs/v18/BEHAVIOR_EVALUATION.md) separates original base,
updated backbone and workspace effects; a blank
[Claude manual review sheet](docs/v18/CLAUDE_REVIEW_SHEET.md) supports a later
blinded transfer without a Claude API key. No new answer bank or judgments exist.
The conditional [Hugging Face beta release checklist](docs/v18/HF_RELEASE.md)
targets **mistral-7b-instruct-v0.3-LTWS β**, pending agreed acceptance,
V18 evidence, licensing and fresh-load export parity. Nothing was uploaded.

The separately authorized [V16 engineering-weight retirement](provenance/inventory/v16_engineering_retirement_20261015/README.md)
has now removed four completed update/resume-test checkpoints, **54.213 GiB**,
after publishing their hashes and 40 evidence bindings. All six active V16
comparison saves remain (latest/previous per condition), as do the original
model/cache and V18 diagnostic states. Terminal free space is **156.235 GiB**;
the [one-arm forecast](docs/v18/SELECTION_OWNER_PLAN.md) is distinct from the
unmet 242-GiB three-arm envelope. Git records do not reconstruct deleted weights.

## V16: separate slot-contrast route, migration, comparison and population diagnostics

The [V16 plan and prototype](docs/v16/PLAN.md) separates the existing common
reader from an additional slot-contrast route, with an identically initialized,
parameter-matched uncentered control. The new route is exactly zero for identical
valid slots; its separate norm budget does not rescale the common output.
[16 local CPU mechanism tests](provenance/pilots/v16_slot_contrast_prototype_20261014/README.md)
pass, including tiny Mistral FP32/BF16 zero identity and live backward. This is
not factual binding, V16 FT, CUDA qualification or original-base preservation.
The new reader is deliberately not admitted by the old checkpoint owner.

The v2 checkpoint fixes below are complete at tiny CPU/CUDA scale. After the
[read-only storage inventory](provenance/inventory/v16_storage_inspection_20261014/README.md),
Ryō authorized [all V12 experiment weights to be removed](provenance/inventory/v12_weight_prune_20261014/README.md):
90 files / 206.805 GiB, with hashes and 315 metadata copies retained. Available
space after cleanup was 249.571 GiB; V14/V15 and model caches were not changed.
The [real-7B migration](provenance/pilots/v16_adapter_migration_20261014/README.md)
now passes exact frozen updates and serialized replay: **80/160 planned pairs**.
Full was never dispatched: the warmed process fell below the unchanged 31-GiB
start floor. Original status is **INCOMPLETE_NO_RETRY**, not OOM or a numerical
mismatch. The authorized [full-only continuation](provenance/pilots/v16_adapter_full_continuation_01_20261014/README.md)
passed admission and completed legacy full updates, then stopped **before any
adapter update**: production preparation registers an HF input-gradient hook
twice, leaving one unowned. A CPU construction-only diagnosis reproduced the
gap missed by direct-HF tiny tests. At that point: **112/160 pairs**, full
comparison and replay incomplete. Both historical failures remain sealed.

The separately authorized [owned-preparation repair](provenance/pilots/v16_adapter_full_recovery_02_20261014/README.md)
now passes 295/295 local regression tests, 22/22 source-isolated CUDA cases,
and **7B full exact updates plus serialized replay**. Only the missing adapter
48 pairs ran; neither frozen nor completed legacy work was repeated. Combined:
**160/160 pairs, 8/8 unique windows, 2/2 replays** across three source-provenanced
processes. The strict hook guard and all math/resource thresholds remain intact.
The repair took 19 min 24.57 s, with 27.751 GiB peak allocated CUDA memory.
Preparation is now an explicitly owned, idempotent adapter setup boundary.
The new [V16 reader-state owner](docs/v16/SLOT_STATE_OWNER.md) now completes that
next engineering gate: [145/145 source-isolated cases on each of CPU and CUDA](provenance/pilots/v16_slot_state_owner_20261014/README.md),
including 16/16 serialized replay cells and eight independent update references
per runtime. Writer/common/interaction partitions and same-shaped candidate/control
policies are explicitly owned in a new format; v15/v2 still rejects the prototype.
Local regression is 440/440, with another 14/14 offline-verifier cases. CUDA tests
took 247.295 seconds with 64.465 MiB peak allocation, a **tiny-model** observation.
At that qualification, the next step was freezing the three-arm Mistral pilot
and its new resource forecast; no new 7B FT had run. Old **FAIL / winner:none /
non-regression NOT_ESTABLISHED** stays.

For that prospective three-arm run, the subsequent
[explicitly authorized V14 cleanup](provenance/inventory/v14_weight_prune_20261014/README.md)
recorded all 44 weight hashes and 502 literal metadata files in Git **before**
removing 82.838 GiB of V14 payloads. Terminal available space is **270.661 GiB**,
above the 242-GiB conservative output-plus-floor screen by 28.661 GiB.
V15/V16 checkpoints and the original model/cache were not deletion targets;
98 protected weight stats and all 502 source metadata hashes are unchanged.
Hashes are not weight backups. This clears the storage screen only, not the
new-reader GPU/host admission or semantic/non-regression gates. No V16 7B FT,
new generation or judge request ran during cleanup.

The [bounded V16 full-update comparison](docs/v16/FULL_COMPARISON.md) has
[completed and replayed offline](provenance/pilots/v16_full_comparison_20261014/RESULTS.md):
6/6 unique update windows, 3/3 exact next-update replays, 144/144 backward pairs.
Final intact/twin correctness is common 10/16 and 8/16, raw control 8/16 and
8/16, slot contrast 9/16 and 8/16. All three retain 0/4 native affected-margin
changes and 0/4 donor-directed flips. These are two training-exposed worlds,
not a held-out gain or base-floor pass. Slot-query gradients are live but the
interaction output is small. **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remains unchanged.

The [population diagnostic](docs/v16/POPULATION_DIAGNOSTICS.md) has now
[completed with offline replay](provenance/pilots/v16_population_diagnostics_20261015/RESULTS.md):
all four arms × 128 fresh worlds / 1,024 queries and MMLU 570 questions.
Ordinary MMLU is original/common/raw/slot **356/356/355/354**, strict
**355/352/352/348**. Slot retains **0/256 donor flips**; centered variation
exists and the cap is not exhausted, but selection is near uniform and intended
FP64 direction is mixed (127 positive / 129 negative). It adds no training,
generation, judge call or weight deletion. One training seed remains one;
**FAIL / winner:none / non_regression NOT_ESTABLISHED** stays.

The [2026-10-13 readout PR review](docs/v15/READOUT_REVIEW_20261013.md) adds a
pre-import source guard for future runs and qualifies the historical
untracked-file cleanliness claim. Old audit sources and receipts are unchanged.

## V15 adapter-owned updates: graph sharing and exact resume

The [new opt-in state owner](docs/v15/ADAPTER_STATE_OWNER.md) carries the native
adapter boundary through complete-window updates and checkpoint/RNG resume.
An independent-forward control exposed **equal scalar loss but different
gradients in 20/21 tiny base tensors**: paired graph sharing is part of the
arithmetic contract, not merely a forward implementation detail.

The [source-bound CPU qualification](provenance/pilots/v15_adapter_owner_20261013/README.md)
and [authorized CUDA recovery](provenance/pilots/v15_adapter_owner_cuda_02_20261013/README.md)
each pass **71/71 tiny tests**, including **8/8 matched-update conditions and
8/8 valid serialized next-update replay conditions**. The original CUDA import
failure is retained unchanged. CUDA took **16.02 seconds**, with **64.56 MiB**
peak Torch allocation; this does not establish a 7B memory envelope or
cross-device equality. The [PR #12 review](docs/v15/ADAPTER_OWNER_REVIEW_20261014.md)
identified two checkpoint API issues: payload snapshot aliasing and mutation
on failed restore. The additive [v2 repair](docs/v15/ADAPTER_CHECKPOINT_V2.md)
now passes [164/164 cases on both CPU and CUDA](provenance/pilots/v15_adapter_owner_v2_20261014/README.md),
including 65 non-mutating rejection cases, eight matched-update cells, eight
serialized replay cells, and two controls reproducing v1's defects per runtime.
609 selected local regression cases also pass. **PR #12 stays Draft pending
follow-up review; old receipts and the known-defective v1 API remain historical.**
That checkpoint-repair qualification ran no 7B update or new generation. The sealed
historical runner is unchanged. The
[next real-model gate](docs/v15/ADAPTER_7B_MIGRATION_GATE.md) requires separate
complete-window and capacity admission after the v2 repair; old **FAIL / winner:
none / non-regression NOT_ESTABLISHED** remain unchanged.

## V15 readout adapters: native equivalence, separate semantic and transport failures

The [opt-in model-independent readout core](docs/v15/READOUT_ADAPTERS.md) now
delegates normalization, head execution and post-head transformations to an
explicit native-model adapter. Tiny GPT-2/Mistral/OLMo2/Gemma2 tests cover
FP32/BF16 outputs and live gradients; this is not universal model qualification.
The sealed optimizer/resume runner remains unchanged.

A [read-only retained-Mistral audit](provenance/pilots/v15_readout_adapters_20261010/README.md)
reproduces **192/192 old/new full-logit outputs** and **64/64 written-zero
identities**. All **16/16 affected pairs retain native hidden differences**,
yet their two answer logits remain identical at the native head. All **64/64
pairs change other vocabulary logits**, without changing the greedy next token.
The intended projected donor direction is only **2/4 per state**; one direction
reverses during hidden casting in the full-updated state. One native answer-gap
change occurs on an **unaffected** pair. Neither more visible logits nor higher
precision alone establishes content binding.

No new training, learner sequences or judges ran. The next factors separate
semantic selection, explicitly controlled adapter precision and immutable
original-base preservation. **Old FAIL / winner: none remain unchanged.**

## V15 native learner: full updates and exact resume; content binding still open

The [new end-to-end state owner](docs/v15/NATIVE_LEARNER.md) now connects live
question/context features, writer/reader, native readout, complete-window CPU
accumulation, all-base FP32-master updates, and optimizer/RNG checkpoint resume.
The [completed pinned-Mistral pilot](provenance/pilots/v15_native_learner_20261010/README.md)
retains **1,152 evaluation rows and 160 greedy sequences**. Both the frozen and
full arms reproduce the next update exactly after checkpoint reload; all 291
physical base tensors change in their FP32 masters, including all 65 RMSNorm
tensors. Native BF16 changes are counted separately. Full-process peak Torch
allocation is **27.751 GiB**, with **2.203 GiB** minimum sampled device free.

This is engineering qualification, not a semantic win. Fresh legacy/modulated
reader training remains **16/32 correct and 0/4 donor flips**. The full arm reaches
**18/32**, but with **3 repairs and 1 new error** relative to original base;
its updated base without workspace is **15/32**. All four final comparisons
still have **0/4 donor flips, 0/4 strict workspace generation and identical
intact/twin tokens on 4/4 queries**. Current-base zero identity does not establish
original-base preservation. [Literal outputs](provenance/pilots/v15_native_learner_20261010/GENERATION_BANK.md),
eight retained-checkpoint receipts and exact replay evidence are published.

V15 now denotes the full native learner; the prior frozen-native milestone is
conceptually V14.5 without changing historical paths. [Next design factors](docs/v15/NEXT_STEPS.md)
separate common response from useful question/content interaction and make
pinned-original reference ownership explicit. No redundant donor loss, automatic
longer run or winning model is inferred. Old **FAIL / winner: none / non-regression
unestablished** and closed judge missingness remain. The sections below retain
the preceding results and their then-current proposals.

## V15 reader factor audit: localize binding failure before more learning

The [new no-update factor audit](provenance/pilots/v15_reader_factors_20261010/README.md)
separates common, question, memory and question × memory corrections in 64
four-corner blocks. The retained output projection puts **87.966884%** of its
squared-Frobenius energy into one singular direction. The modulated reader's
mean-slot/actual interaction-norm ratio is **99.839031%**: large interaction
magnitude does not establish differentiated fact selection (mean slots still
contain world information). At both affected reciprocal pairs, donor-directed
interaction remains much smaller than memory bias; cap anisotropy adds another
local constraint but cannot alone explain the failure.

All 64 actual-memory native vectors match previous results: **16/32 correct and
0/4 donor flips per reader**. No weights changed; no autograd, training,
generation or judge calls ran. 232 local/Furnace prelaunch tests and 14 offline
post-result tests passed. The existing loss already targets reciprocal donor
direction; simply adding a similarly named loss would duplicate supervision.
Next, test whether fresh matched short reader training grows useful interaction
under unchanged losses/cap/native scoring before full updates. Removing common
directions or raising the cap is not an established repair. Old **FAIL / winner:
none / non-regression unestablished** and closed judge missingness remain.

## V15 reader refinement: question sensitivity improved; semantic result unchanged

The [new opt-in reader](docs/v15/READER_MODULATION.md) adds one parameter-free,
bounded question/value modulation before the existing output projection. In a
[completed no-update 7B comparison](provenance/pilots/v15_reader_modulation_20261010/README.md),
retained-state reader-input gradient norms increased **324.40×**, and intact
reciprocal-question correction distances increased **418.13×**, including
direction changes after norm matching. Cap, parameters and checkpoint bytes
were held fixed; old source and zero-memory identity remain intact.

This is not a semantic win: all 32/32 retained-state native truth-bearing score
vectors still match the legacy reader, accuracy remains **16/32**, and correct
donor flips remain **0/4**. Common-slot and unrelated controls also exhibit
question dependence. All 512 evaluation rows and 320 reader-gradient leaves
are retained from two already-exposed worlds, not fresh held-out evidence.
199 selected tests passed locally and on Furnace; all weights stayed unchanged.
The next priority is a matched fresh, short reader-learning comparison before
full-backbone optimizer work. No training, generation or judge call was added;
old **FAIL / winner: none / non-regression unestablished** remain unchanged.

## V14.5 to full-update V15: real 7B backward qualified, no optimizer update

The separate [live-native contracts](docs/v15/FULL_UPDATE_BACKWARD.md) preserve
the old frozen path and recompute current-backbone features. The
[completed no-step probe](provenance/pilots/v15_full_update_backward_20261010/README.md)
ran two diagnostic states × three exposed pairs: all 291 base tensors received
finite nonzero gradients, and the retained bridge carried gradients through
both memory and reader inputs. Each state's 317 restored gradient tensors
matched a same-order CPU reference exactly. Native/zero and historical choice
controls remained exact; all weights were unchanged.

The six backward passes took 106.13 seconds with 28.22 GiB peak Torch allocation;
sampled free device memory reached 1.21 GiB, so optimizer headroom is not yet
qualified. There were no optimizer steps, new generations or judge calls.
The earlier proposed complete-window/one-update/resume audit is now deferred
behind the reader-learning comparison above. Useful content learning and
original-base preservation
remain unestablished; old **FAIL** and **winner: none** are unchanged. The native
frozen-base milestone is conceptually V14.5; historical `v15_5` paths are retained.

## V15.5 learner restart: native path exercised, no winning arm

Diagnostic judge collection is closed at its valid observed coverage. The
[new learner plan](docs/v15_5/NATIVE_ANSWER_LEARNER.md) resumes the FT line with
two matched eight-update workspace-only arms: native full-vocabulary answer CE,
and the same CE plus correct-answer-conditioned EOS. The
[completed CUDA pilot](provenance/pilots/v15_5_native_answer_20261010/README.md)
retains **576 evaluation rows and 80 greedy sequences**. Native logits changed;
answer-only training changed text for 2/4 exposed queries, but intact/twin tokens
remained identical for 4/4 in both arms. Choice accuracy stayed 8/16 per factual
condition, affected donor changes stayed zero, and workspace generation remained
0/4 strict-correct with 4/4 length stops per arm/checkpoint. EOS CE fell only in
the EOS-trained arm, without improved observed termination. **No winner.**

The run took 70.01 seconds with a 14.13 GiB Torch allocation peak on Furnace.
232 selected tests passed locally and on the execution host; offline receipts
replay. [All outputs](provenance/pilots/v15_5_native_answer_20261010/GENERATION_BANK.md)
and per-condition checkpoints are retained. No additional judge call or weight
deletion occurred. No judge text became a training target. The prior expression
FAIL and independent base-floor requirements remain unchanged; this is neither
full-backbone training nor a qualified FT-beta candidate. The
[next proposal](docs/v15/NEXT_STEPS.md) prioritizes content-selective learning
and per-loss gradient diagnostics over automatically extending this pilot.

## V15.5 diagnostic evaluation: continuation closed as partial

The [authorized 320-call continuation](provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010/README.md)
ended on 2026-10-10 at 08:00 JST with **155 valid diagnoses, four new ambiguous
timeouts and 161 never-dispatched requests**. Combined with the immutable
[original partial run](provenance/pilots/v15_5_diagnostic_judge_20261010/README.md),
main coverage is **343/512**; study plus fixed repeats has 374 valid, one invalid,
eight unknown and 161 undispatched coordinates. No call was retried. The
heartbeat is paused at Ryō's request; further recovery needs a new decision.

The [frozen unary-judge protocol](docs/v15_5/DIAGNOSTIC_JUDGE_PROTOCOL.md) reuses
512 existing pinned-base outputs on 16 correlated world clusters, not new
learner generations. [Calibration](provenance/pilots/v15_5_diagnostic_judge_20261010/CALIBRATION_REVIEW.md)
admitted Mistral (16/16 expected matches, 8/8 equal repeat signatures) and blocked
OpenAI (15/16 matches, 6/8 equal against a 7/8 requirement); all 544 OpenAI study
calls remain undispatched. The Mistral fixed-repeat panel remains 25 equal,
six differing and one invalid pair out of 32. There is no two-judge consensus.

Renderer stratification matters: among **87 diagnosed native-chat inline
outputs**, 29 strict failures comprise 13 internal contradictions, 13 wrong
commitments, two format-only candidates and one grounding case. All 82 diagnosed
inline length failures belong to raw rendering; two native length stops in the
full bank have no diagnosis. A stopping-only explanation is insufficient for
the observed native failures. Missingness is not assumed random.

The [combined literal panel](provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010/analysis/DIAGNOSTIC_PANEL.md)
and [bounded next-step proposal](docs/v15/NEXT_STEPS.md) preserve the old **FAIL**,
strict scores, unknowns and all source records. No learner was trained in that
diagnostic collection; no
quality, non-regression, semantic-mechanism or winner claim is established.

## Earlier V15 no-training engineering checkpoints

The fresh [cue-by-envelope confirmation](provenance/pilots/v15_cue_confirmation_20261010/README.md)
completed **512 generations** on 16 new world families. Removing `Answer:`
did not repair the interface: native-chat inline strict correctness was
**44/64 with the cue versus 40/64 without it**, including 0/16 correct atomic
negative answers in the no-cue primary. All four generation gates failed.
With the cue retained, atomic candidate ranking was **21/32 at the first token
versus 30/32 for answer-plus-EOS paths**; this is a completed-path diagnostic,
not successful natural generation or a selected method. All outputs and the
failed gate are retained; the new verifier passes on both Mac and Furnace CPU
with identical receipts. **No new V15 learning was started in that assay.**

The preceding [pinned-base elicitation assay](provenance/pilots/v15_base_elicitation_20261010/README.md)
retains **288 complete generated outputs**: native chat improves termination,
but its frozen expression gate still fails (16/32 strictly correct in the
primary inline/greedy family panel). A separate, already-exposed-panel
[answer-plus-EOS diagnostic](provenance/pilots/v15_completion_mass_20261010/README.md)
finds native-chat atomic candidate ranking changes from 9/16 at the first token
to 14/16 for complete answer paths; full-chain changes 7/16 to 8/16. This is not repaired
generation or a qualified method. The latter's frozen verifier passes on the
execution runtime; local Mac exact summary replay retains four one-ULP scalar
mismatches. **New V15 learning was deferred at that checkpoint.**

The [V15 readout/serialization/generation assay](provenance/pilots/v15_readout_transport_20261010/README.md)
completed on 2026-10-10 with retained weights and no optimizer updates. Loss
diagnostics, evaluation and generation now share a tested native full-vocabulary
readout. All 384 crossover rows and 64 short generations are retained, including
the negative result: every generation violates the strict one-word contract,
even inline base. Historical intact/twin differences also confound content with
fact order; aligned-order controls weaken those effects.
See [the full answer bank](provenance/pilots/v15_readout_transport_20261010/ANSWER_BANK.md)
and [next isolated experiments](docs/v15/NEXT_STEPS.md).
This is not new trained-model quality or correctness-floor qualification.

## Historical V14 and V13 foundations

V14 begins with a **portable-operator foundation**, not a new training result.
Model boundary binding, functional workspace operators, normalization choices,
final-logit arithmetic, and bounded named-norm observation now have separate
contracts. The default path preserves the sealed V13 algorithm; changing a
workspace norm is a new algorithm condition, not an equivalent optimization.
Start with [`docs/V14_PORTABLE_BOUNDARIES.md`](docs/V14_PORTABLE_BOUNDARIES.md)
and the fixed offline [OLMo2 portability plan](configs/v14/PORTABILITY_RUN_PLAN.json).
The selected cached OLMo-2 1B is a structural control, not an Instruct capability
comparison or evidence that the proposed read/transition bridge works.
The [two real-model CUDA canaries are complete](provenance/pilots/v14_portability_20260904/OBSERVATIONS.md):
within both BF16/SDPA and BF16/eager, three split boundaries preserve logits and
the middle boundary preserves all 179 parameter gradients with numerical
difference zero. Short native/split generations also match. This does not claim
SDPA/eager equality: their native CE values differ. The default-CPU DNNL backward
failures and the separately passing MKLDNN-disabled test run are both retained.

V13 now has a **completed bounded S0/S1 diagnostic pilot**, not a training run.
The broader design distinguishes workspace state that is readable now from state
that affects later recurrent transitions, with normalization explicit. Start with
[`docs/V13_S0_S1_PILOT.md`](docs/V13_S0_S1_PILOT.md). The original design remains
historical and non-executable:
[`docs/V13_NORMALIZATION_STATE_DESIGN.md`](docs/V13_NORMALIZATION_STATE_DESIGN.md)
and [`configs/v13/DESIGN_CONTRACT.json`](configs/v13/DESIGN_CONTRACT.json).
The separate pilot plan permits only synthetic falsification checks and retained
V12 numerical visibility measurements. No V13 training configuration is enabled.
V14's proposed bridge between the two state views remains a
hypothesis, not a demonstrated mechanism.

The current V14 Furnace line has now completed the bounded return sequence:
the atomic Mistral renderer/instrument and native checkpoint-direction gates
passed, while the full seven-fact task and five-cell semantic-accumulation claim
did not qualify. Matched eight-update task and semantic layer-16 cells were then
trained and evaluated; both failed grouped F1–F5, so no cell was selected. The
[post-comparison free-form diagnostic](provenance/pilots/v14_boundary_chat_20260907/README.md)
retains all 192 base/task/semantic continuations. It found zero intact-to-twin
first-answer changes, but a descriptive late semantic continuation trace. Since
that trace occurred under full-prefix recomputation with no K/V cache, it is a
control against treating delayed text divergence alone as cache accumulation.

The [first observations](provenance/pilots/v13_s0_s1_20260904/OBSERVATIONS.md)
localize a BF16 final-addition visibility loss at two retained checkpoints; they
do not establish semantic causal success. [Weight retention](docs/WEIGHT_RETENTION.md)
is latest two checkpoints **per condition**, not two version generations.
The scoped retention audit found no eligible older steps; no weights were deleted.

The completed parent is the bounded
[V12 calibrated-route study](provenance/pilots/v12_calibrated_route/OBSERVATIONS.md),
which demonstrated initialization/update ownership but no winning workspace
branch. The V13 design records interpretation corrections without modifying
historical evidence. The import package remains `latent_workspace_ft_v10` for
checkpoint/tooling compatibility.

This repository is the clean staging surface for a CUDA-native, full-parameter
Latent Workspace comparison. It starts with a portable v10 engine, provenance,
data, and explicit decision boundaries.

## Historical runtime status (not V13/V14 qualification)

- Canonical source is the
  [`RyoSpiralArchitect/Latent_Workspace`](https://github.com/RyoSpiralArchitect/Latent_Workspace)
  repository. The current V14 continuation is isolated on
  `SpiralReality/v14-semantic-chat`; its portability ancestor was based on the
  sealed V13 observation/retention commit `ed5ce398`.
  The historical observations below
  describe their named V10/V11 runs, not the current V13 implementation status.
- The runtime contract is PyTorch CUDA, BF16, SDPA, gradient checkpointing,
  and full-parameter Adafactor. Custom Triton kernels remain deferred until a
  measured bottleneck and forward/backward parity test justify them.
- The starting model is `mistralai/Mistral-7B-Instruct-v0.3`, pinned to
  revision `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Furnace dependency, tokenizer, full-data, and immutable model-cache gates
  passed for the pinned V10 receipts. V11 source and Gate-0 execution receive
  new hashes and receipts; V10 source receipts must not be reused as V11 proof.
- The four-condition seed-42 smoke cut is complete. `F0_query_only`,
  `B_local_invariance`, `F1_inline_upper`, and `O3_slots4_k1_lw_cf` each ran
  eight optimizer steps, passed run and assay integrity verification, passed an
  exact step-4 resume comparison, and transitioned to `verified_pruned`.
- Every formal run covered all 291 base tensors / 7,248,023,552 elements and
  recorded 64 CPU gradient spills, eight restored windows, zero discarded
  windows, and zero single-microbatch windows. Peak CUDA allocation ranged from
  29.572 to 29.833 GiB.
- Current-source F0 spill-versus-native comparison is byte exact for the base
  model, workspace, trainer state, and stable metrics under the receipt's
  explicit exclusions. The matched last-step throughput was 5.902 versus
  88.003 supervised tokens/s, an observed 14.9x spill slowdown for this pilot.
- The transport-v2 `cpu_accumulate` path keeps cross-microbatch BF16 additions
  on pinned CPU storage and reduces logical gradient-volume movement from 16 to
  9 per eight-microbatch window. Current-source one-step full-state oracles pass
  for F0/B/F1/O3, with observed old-spill speedups from 1.372x to 1.420x.
- A pre-prune behavior workflow now captures the pinned original model, every
  trained base trunk, complete functional-workspace task traces, exact transport
  sentinels, and a human observation note. Its first run passed integrity but
  found constant-`no` task behavior in all four one-step trained conditions.
- After that observation was durably recorded, a GitHub-published exact intent gated the
  first transport-pilot cleanup. It removed 80 checkpoint/final shards totaling
  289,921,618,400 logical bytes and retained the distinct
  `transport_pilot_weights_pruned` state; the weights are not recoverable from
  hashes or decoded generations.
- Native B multi-microbatch equivalence is not verified. The matched native
  gradient-accumulation-two route OOMed on its first backward pass; the reduced
  one-microbatch pair was correctly rejected because it never exercised a spill
  window.
- Assay integrity passed, but all four held-out query accuracies were 0.5. O3's
  amputation direction opposes load-bearing and its necessity gate is false.
  This cut is an engineering success and a negative/inconclusive scientific
  result.
- The four formal pruning transactions retained rehashed compact evidence and
  removed 57,984,422,832 logical bytes of trained base-model bundles. Hashes and
  compact metadata cannot reconstruct the deleted trained weights.
- A separate intent-bound cleanup then removed 76 duplicate/oracle/resume shards
  across 19 bundles: 275,425,537,480 logical bytes. Independent postflight found
  zero trained safetensors outside the protected pinned model cache. No loadable
  trained base-model copy remains; the hashes are evidence, not backups.
- n=3 and n=10 have not run. The n=3 profile contains 57 runs at 512 optimizer
  steps each and is machine-blocked by the intentionally absent smoke
  `QUALIFICATION.json`. Issue that operator receipt only after GitHub publication,
  a frozen per-run retention cadence, and explicit acceptance of the measured
  spill-throughput cost.
- Legacy v9 remains frozen as a structurally valid `partial_nonfinal`
  snapshot: 28/190 training runs, no final validation, and no scientific final.
- Model weights, optimizer state, checkpoints, and run directories are excluded
  from Git. Durable artifacts must be stored separately and referenced by hashes.

## Claim boundaries

Verified engineering evidence:

- immutable Mistral-7B model and tokenizer identity;
- full-file functional-data integrity;
- CUDA/BF16 execution for all four smoke conditions on the recorded 32 GiB GPU;
- exact, duplicate-free optimizer membership plus finite nonzero-gradient and
  optimizer-step attempts for every base tensor in every formal run;
- skip-free CPU-spill accumulation with 64 spills and eight restored windows per
  run;
- current-source F0 spill-versus-native byte equivalence for base, workspace,
  trainer, and stable metrics under explicit exclusions;
- current-source F0/B/F1/O3 `cpu_accumulate` versus old-spill full-state
  equivalence at gradient accumulation 8;
- deterministic pre-prune free-form and task-native behavior capture, including
  exact B/B-reference completion tokens and task choice logits;
- behavior-gated, intent-published removal of the exact 80 transport-v2 shard
  bodies while preserving the pinned model cache and non-weight evidence;
- bitwise-exact fixed-schedule resume for all four conditions, including active
  workspace routes; and
- assay-complete, compact-exported, explicitly pruned formal runs that remain
  distinguishable as `verified_pruned`.

Not yet verified:

- native multi-microbatch equivalence for B, F1, or O3;
- long-run `cpu_accumulate` throughput, stability, or behavioral outcome;
- n=3, n=10, a 14B full update, signal preemption, schedule extension,
  multi-GPU execution, or cross-runtime reproduction;
- training quality, causal memory, content-specific memory, generalization,
  model superiority, or comparability with GPT-2 v9.

The original CUDA smoke result remains in
[`docs/CUDA_SMOKE_STATUS.md`](docs/CUDA_SMOKE_STATUS.md). The current transport
result and failed activation-offload hypothesis are in
[`docs/TRANSPORT_V2_STATUS.md`](docs/TRANSPORT_V2_STATUS.md), and the mandatory
pre-prune behavior procedure is in
[`docs/GENERATION_BEHAVIOR_WORKFLOW.md`](docs/GENERATION_BEHAVIOR_WORKFLOW.md).
Historical F0 pilots remain preserved separately and must not be substituted
for the current engine or current-source oracle.

## Staged comparison plan

### 1. Pilot

Run one condition and one seed for the minimum useful number of steps. The pilot
must pass all of these gates before any matrix expansion:

- frozen model repository and revision, tokenizer hash, data hashes, config hash;
- CUDA/BF16 preflight and an explicit attention-backend receipt;
- finite loss/gradients, nonzero parameter deltas, and full optimizer coverage;
- checkpoint/resume equivalence at the declared tolerance;
- held-out evaluation and null-control execution, even when they are inconclusive;
- disk, RAM, VRAM, runtime, and failure receipts.

### 2. Three-seed cut

After the pilot passes, run the same preregistered contrast groups at `n=3`. Keep
the query-only/local-invariance controls and the functional-workspace conditions
separate. Use the same seeds across matched conditions. Do not select conditions
from favorable pilot outcomes without recording that selection rule.

### 3. Ten-seed cut

Expand to `n=10` only if the `n=3` gate is complete and the resource estimate is
acceptable. Aggregate a condition only after every contracted seed is valid.
Run the post-training necessity, replacement, amputation, and held-out assays
before allowing final claims.

The measured final base-model bundle selected by the retention policy is
14,496,105,708 bytes per run. Keeping one such bundle per run would require
approximately:

- smoke, 4 runs: 57.984 GB / 54.002 GiB;
- n=3, 57 runs: 826.278 GB / 769.531 GiB;
- n=10, 190 runs: 2.754 TB / 2.505 TiB.

These are strict lower bounds: optimizer state, workspace state, checkpoints,
logs, archived failures, and assay artifacts are excluded. The observed
furnace snapshot had approximately 1.4 TB free, so naive n=10 retention cannot
fit. The per-run compact-export and opt-in pruning path has now been tested on
all four smoke conditions, but n=10 remains blocked until n=3 completes and a
profile-level retention schedule is frozen and capacity-checked. See
[`docs/ARTIFACT_RETENTION.md`](docs/ARTIFACT_RETENTION.md).

## Runtime choice

The current implementation uses PyTorch CUDA and SDPA. Framework internals may
select optimized CUDA/Triton kernels; there is no hand-written Triton code in
this harness. A custom kernel remains deferred until profiling identifies a
specific bottleneck and a numerical-parity test exists.

## Repository layout

- `src/latent_workspace_ft_v10/` — engine, model bindings, workspace writers and
  readers, learners and state owners (the package keeps its V10 name).
- `tests/` — offline tiny-model tests, including the suites that sealed
  qualifications run on Furnace CPU and CUDA.
- `configs/v10/` … `configs/v18/` — frozen per-version contracts and run plans
  (`configs/v13/` is a non-executable design).
- `scripts/` — data preparation, sealed runners behind the pre-import
  `run_source_sealed.py` launcher, and offline verifiers.
- `data/` — byte-identical v9 inputs, Mistral-safe v10 functional train/eval
  data, and manifests.
- `docs/` — per-version plans and decisions (`docs/v14/` … `docs/v18/`, with
  earlier notes at the top level).
- `provenance/` — environment receipts, sealed run bundles under
  `provenance/pilots/`, inventories and weight-retention ledgers.

The observed furnace environment is recorded in
[`provenance/FURNACE_DEPENDENCY_RECEIPT.json`](provenance/FURNACE_DEPENDENCY_RECEIPT.json).
The observed tokenizer result is recorded in
[`provenance/MISTRAL_TOKENIZER_GATE.json`](provenance/MISTRAL_TOKENIZER_GATE.json).
The offline full-data audit on furnace is recorded in
[`provenance/FURNACE_DATA_DOCTOR_RECEIPT.json`](provenance/FURNACE_DATA_DOCTOR_RECEIPT.json).
The legacy boundary is recorded in
[`provenance/V9_PARTIAL_HANDOFF.md`](provenance/V9_PARTIAL_HANDOFF.md).

## License

Copyright (C) 2026 Ryo Higa / RyoSpiralArchitect

This repository is free software: you can redistribute it and/or modify it
under the terms of the GNU Affero General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your option)
any later version (`AGPL-3.0-or-later`). It is distributed in the hope that it
will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See [LICENSE](LICENSE) for
the full text.

Exceptions, under their own licenses:

- **The LTWS β release:** everything under [`release/ltws_beta/`](release/ltws_beta/),
  and the β package built from it, is licensed under Apache-2.0 by the copyright
  holder. That covers its route weights and its copy of `src/latent_workspace`.
- **The MMLU subset:** MIT, with its notice in
  [`configs/v16/population_20261015/MMLU_NOTICE.md`](configs/v16/population_20261015/MMLU_NOTICE.md).
- **Mistral-7B-Instruct-v0.3:** Apache-2.0 by Mistral AI. This applies to copies
  of its chat template kept in provenance records. The model's weights are not in
  this repository.
