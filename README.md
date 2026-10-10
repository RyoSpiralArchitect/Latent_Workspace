# Latent Workspace FT — CUDA comparison harness

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

- `src/latent_workspace_ft_v10/` — portable engine and CUDA/Mistral split adapter.
- `tests/` — offline tiny-model equivalence and optimizer coverage tests.
- `configs/v10/` — pinned 19-condition contract and smoke/n3/n10 profiles.
- `configs/v13/` — non-executable normalization-state design; unresolved run gates remain explicit.
- `scripts/` — deterministic data remapping, contract preparation, and runners.
- `data/` — byte-identical v9 inputs, Mistral-safe v10 inputs, and manifests.
- `docs/` — model and backend decisions.
- `provenance/` — immutable environment and legacy handoff receipts.

The observed furnace environment is recorded in
[`provenance/FURNACE_DEPENDENCY_RECEIPT.json`](provenance/FURNACE_DEPENDENCY_RECEIPT.json).
The observed tokenizer result is recorded in
[`provenance/MISTRAL_TOKENIZER_GATE.json`](provenance/MISTRAL_TOKENIZER_GATE.json).
The offline full-data audit on furnace is recorded in
[`provenance/FURNACE_DATA_DOCTOR_RECEIPT.json`](provenance/FURNACE_DATA_DOCTOR_RECEIPT.json).
The legacy boundary is recorded in
[`provenance/V9_PARTIAL_HANDOFF.md`](provenance/V9_PARTIAL_HANDOFF.md).
