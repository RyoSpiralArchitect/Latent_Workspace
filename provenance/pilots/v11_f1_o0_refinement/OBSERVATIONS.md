# V11 F1 versus O0 through refinement — redesign the active route

## Question

Does the active O0 four-slot deferred route become a competitive or
mechanistically distinct alternative to the robust `1e-7` F1 inline control,
first after four full-model updates and then after a fresh sixteen-update
refinement schedule?

## Frozen design

- Launch source commit:
  `142335154e43c156795e56116c7454fa9874852c`.
- Runtime source SHA-256:
  `2d45a3c45bdd0a56d33103e8acfa629b7256b2b38d6836f85c1aaa2f097343cf`.
- Contract SHA-256:
  `5491e6c46d7982b6f9cda80e831b921179573d03fd060800aa01005d38b8eec3`.
- Pinned model:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Both systems used full-model BF16 Adafactor updates, base LR `1e-7`,
  workspace LR `3e-4`, cosine scheduling, global gradient clipping at `1.0`,
  and eight-microbatch CPU accumulation.
- F1 used the inline raw-sequence route with injection scale `0`. O0 used the
  deferred four-slot route with injection scale `1` and gate bias `-1`.
  Counterfactual and stability loss weights were both zero.
- Stage 4 reused the already receipt-verified F1 seeds 43–45 and ran three new
  O0 cells. Refinement ran both systems fresh from the pinned initial model for
  sixteen steps at seeds 43–45. It was not a 4-to-16 resume or schedule
  extension.
- Complete 1,024-case eval ran at step 0 and every update in stage 4, then at
  steps 4, 8, 12, and 16 in refinement.
- Generation was captured before pruning for the original model and every
  checkpoint. O0 also received automatic final amputation and an explicit
  nine-mode F0–F5 necessity assay.
- O0 was competitive only if every seed passed the cell gates and every paired
  seed stayed within the frozen behavior, complete-eval accuracy, and recall
  margins.

This is a system-level contrast. Route topology, memory representation, and
activation of the injection path change together. The comparison does not
isolate one architectural factor.

## Integrity result

Integrity is `PASS` for stage 4 and refinement. The scientific result is
negative for O0 and the frozen V12 decision rule is `redesign_route`.

- Local validation before launch: 282 passed and 3 CUDA-only skipped. Furnace
  validation at the exact launch commit: 285 passed. Ruff and diff checks
  passed.
- All nine new runs completed with exact config, source, optimizer-coverage,
  full-base update, LR-chain, CPU-offload, metric-sequence, and final-bundle
  bindings.
- Every refinement cell exactly replayed the appropriate step-0 and first
  pre-update-forward prefix: F1 against the prior verified F1 cell, O0 against
  its new stage-4 cell.
- Every run restored all expected CPU accumulation windows and ended with no
  live host buffer or active spill window. No transport failure or non-finite
  skip explains the scientific result.
- Exact BF16 comparisons covered all 291 persisted base tensors. All nine
  checkpoints contained non-zero persisted base updates.
- Generation checkpoint bindings, workspace-state hashes, final amputation
  reports, and all three necessity checkpoint bindings passed.
- Eight canonical result artifacts copied from Furnace match their remote
  SHA-256 bytes. The 125 GB raw run root and all weights remain on Furnace and
  are not committed to Git.

The canonical receipts are
[`STAGE4_RECEIPT.json`](STAGE4_RECEIPT.json), SHA-256
`f1da7a7fec541cc6d4302573e70c8cca60f6c9128121e62b04efa45a401ea102`,
and [`REFINEMENT_RECEIPT.json`](REFINEMENT_RECEIPT.json), SHA-256
`2c7a08f00a0800e18c51e8b9e44be2c43c16ddef13e82d8d6a7a4d92a9467f55`.
The machine-selected handoff is
[`V12_DECISION.json`](V12_DECISION.json), SHA-256
`fd9a667b0312b3d296228f00ae5b8373fc89315313ca3e2c960fb2f7f82328e7`.

## Four-update contrast

O0 was already at chance before training: step-0 accuracy was `0.4980`, choice
loss `0.7196`, no recall `0.1250`, and yes recall `0.8711`. The verified F1
anchor at the same pinned model was accuracy `0.7793`, choice loss `0.6750`, no
recall `0.6758`, and yes recall `0.8828`. Thus the active O0 path introduced a
large initial competence gap before any optimizer update.

| O0 cell | choice loss | full NLL | accuracy | no recall | yes recall | behavior | exact changed fraction | eligible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| seed 43 | 1.6930 | 2.1316 | 0.5000 | 1.0000 | 0.0000 | 0.5000 | 1.0042% | no |
| seed 44 | 2.0702 | 2.5128 | 0.5000 | 1.0000 | 0.0000 | 0.5000 | 1.0005% | no |
| seed 45 | 2.3895 | 2.4858 | 0.5000 | 0.0000 | 1.0000 | 0.5000 | 1.0024% | no |

All three O0 cells collapsed to one predicted class. Automatic route
amputation reduced choice loss to `0.7114–0.7138` and full NLL to
`0.8087–0.8096`, showing that the active route was strongly harmful at step 4.
All three paired non-inferiority checks failed. Stage-4 status is therefore
`O0_4STEP_NOT_COMPETITIVE`.

## Fresh sixteen-update refinement

| cell | choice loss | full NLL | accuracy | no recall | yes recall | behavior | exact changed fraction | eligible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| F1 seed 43 | 0.5833 | 0.7606 | 0.7646 | 0.7715 | 0.7578 | 0.7500 | 1.1883% | yes |
| F1 seed 44 | 0.5831 | 0.7610 | 0.7715 | 0.7715 | 0.7715 | 0.7812 | 1.2147% | yes |
| F1 seed 45 | 0.5819 | 0.7591 | 0.7715 | 0.7715 | 0.7715 | 0.7812 | 1.2098% | yes |
| O0 seed 43 | 0.6938 | 2.2881 | 0.4971 | 0.9902 | 0.0039 | 0.4375 | 1.3505% | no |
| O0 seed 44 | 0.6925 | 0.9504 | 0.4932 | 0.7324 | 0.2539 | 0.5312 | 1.3645% | no |
| O0 seed 45 | 0.6935 | 10.4962 | 0.5000 | 0.0000 | 1.0000 | 0.5000 | 1.3392% | no |

F1 is robust in all three seeds. Its mean complete-eval accuracy is `0.7692`
with a worst-seed minimum recall of `0.7578`. O0 passes no seed; its mean
accuracy is `0.4967` and its mean minimum recall is `0.0859`.

The matched O0-minus-F1 accuracy deltas are `-0.2676`, `-0.2783`, and
`-0.2715`. Behavior deltas are `-0.3125`, `-0.2500`, and `-0.2812`. O0 changes
slightly more exact base elements than F1, so insufficient persisted updating
does not explain the gap.

The O0 LR horizon damped the early oscillation toward choice loss near
`ln(2)`, but it did not recover balanced decisions. Seed 45 is especially
diagnostic: choice loss looks superficially finite at `0.6935`, while the
zero-weight full-vocabulary diagnostic explodes to `10.4962`. Cutting the route
reduces full NLL to `0.8081`, a `9.6881` improvement. The diagnostic prevented
the near-chance choice loss from being misread as recovery.

At step 16, intact O0 choice loss is about `0.020` lower than the amputated
model in every seed, yet accuracy stays at chance. The active route therefore
learned a small calibration or shortcut effect, not the required semantic
decision boundary. Amputation cannot restore the F1 result because the base
trunk was jointly updated under the corrupt route throughout training.

## Generation behavior

The untouched original scored `0.875` on the balanced 32-case inline slice.
F1 refinement scored `0.7500`, `0.78125`, and `0.78125`; every F1 checkpoint
emitted both choices and passed the bounded repetition veto. This is robust
enough for the frozen gate, but it is not an improvement over the original or
over the prior four-step F1 behavior score of `0.84375`.

O0 refinement scored `0.4375`, `0.53125`, and `0.5000`. Seed 43 emitted 30
`no` and 2 `yes`; seed 44 emitted 23 `no` and 9 `yes`; seed 45 emitted 32
`yes`. This agrees with the complete-eval imbalance rather than exposing a
metric-only artifact.

Free-form completions from both routes remained fluent and avoided extreme
token repetition. Ranked-world and instruction-precision completions were
token-exact across all seven models. Other prompts showed bounded lexical
variation but retained the already known instruction and causal-overclaim
weaknesses. The failure is therefore task-route-specific under this suite, not
a broad autoregressive text-loop collapse. Behavior PASS remains a veto, not a
general quality claim.

The complete captures are
[`stage4/GENERATION_BEHAVIOR.json`](stage4/GENERATION_BEHAVIOR.json) and
[`refinement16/GENERATION_BEHAVIOR.json`](refinement16/GENERATION_BEHAVIOR.json).

## F0–F5 necessity

All three O0 necessity assays achieved full F0 intervention coverage. No seed
passed F1 deferred sufficiency, F3 counterfactual direction, F4 local causal
specificity, or F5 held-out generalization. F2 carrier insufficiency passed
only seed 44, where intact accuracy `0.5049` merely exceeded intervention
accuracies around `0.496–0.500`; F1 was still false. That isolated threshold
crossing is not replicated and is not upgraded into a carrier or content
claim.

| seed | F0 | F1 | F2 | F3 | F4 | F5 | primary gate |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 43 | pass | fail | fail | fail | fail | fail | fail |
| 44 | pass | fail | pass | fail | fail | fail | fail |
| 45 | pass | fail | fail | fail | fail | fail | fail |

The intervention machinery worked, but content-specific causal load-bearing
was not observed. This selects route redesign, not stabilization of an already
semantic route.

## Failed hypotheses and interpretation

1. **More refinement will let O0 catch F1.** Falsified under the frozen
   schedule. O0 remains at chance in all three seeds after sixteen updates.
2. **The prior failure was mainly CPU/GPU transport.** Not supported. Every
   offload receipt, prefix replay, and final bundle passed; F1 succeeds through
   the identical transport substrate.
3. **A non-zero carrier or semantic workspace signal is emerging.** Not
   supported. F1/F3/F4 fail in every seed; F2 appears only once at chance-level
   accuracy.
4. **Stable F1 loss reduction implies broad model improvement.** Not
   supported. F1 choice loss improves and remains robust, but complete-eval
   accuracy is flat to slightly lower than its step-0 anchor and generation
   task accuracy is below the untouched original.

The leading failure mode is present before training: injection scale `1` with
gate bias `-1` activates an uncalibrated deferred path and drops step-0
accuracy by about 28 points relative to F1. Joint training then exposes the
workspace family to a configured LR 3,000 times the base LR under one global
clip. Large early raw gradient norms and seed-dependent class flipping follow.
These facts motivate the next design, but this system-level experiment cannot
attribute causality to the gate, LR ratio, slot representation, or ownership
policy individually.

## V12 design derived from the contrast

The selected rule is `redesign_route`: redesign injection and workspace
training before scale-up. V12 should be cut into ordered falsifiable gates.

### V12.0 — exact no-op boundary

- Preserve the current F1 `1e-7` sixteen-step branch as the competence and
  transport control.
- Make the initialized deferred path functionally null. An active-path model
  must match the F1/base step-0 choice logits, complete eval, and generation
  behavior before it is allowed to train.
- A zero gate that also blocks workspace learning is insufficient by itself.
  Provide an explicit calibration phase or auxiliary target so workspace
  parameters can learn while the injected residual remains bounded.
- Fail closed if route-on versus route-off step-0 behavior exceeds the frozen
  non-inferiority margins. Do not spend a training matrix trying to repair an
  already destructive initialization.

### V12.1 — separate update ownership

- Freeze the base trunk first and train only the workspace path under a small,
  pre-registered LR response surface. Do not carry forward `3e-4` merely
  because it was used by the failed system.
- Split base and workspace clipping and record raw gradient, clipped gradient,
  optimizer-step, and persisted-delta norms by parameter family. The current
  global clip obscures which family owns the effective update.
- Ramp the injection or gate only after the workspace residual passes a bounded
  logit-delta and no-op-parity check. Require intact O0 to be non-inferior to
  its amputation, including both label recalls, before releasing the base.
- Release the base at the already qualified `1e-7` only in the final joint
  phase. This prevents early route noise from teaching the base a compensating
  shortcut.

### V12.2 — add semantic pressure as a separate factor

- The failed O0 system had zero counterfactual and stability loss weights. Add
  content-specific supervision only after V12.0 and V12.1 pass.
- Keep at least three branches: unchanged F1 control, identity-calibrated O0
  with task loss only, and the same calibrated O0 plus counterfactual/stability
  objectives. This separates route stabilization from semantic supervision.
- Preserve fixed-carrier, random-carrier, counterfactual-twin, and
  cross-world-shuffle controls. Promotion requires replicated F3 and F4, not a
  lone F2 threshold crossing.

### V12.3 — promotion order

1. One-seed no-update and one-update instrumentation.
2. Four-update seeds 43–45 only after exact no-op and ownership gates pass.
3. Fresh sixteen-update seeds 43–45 only after every four-update cell passes.
4. Capture original, F1, and every promoted O0 generation before pruning.
5. Run the full necessity ladder and choose the next branch from the same
   predeclared decision rules.

This design deliberately does not authorize a broad optimizer sweep, 14B
scale-up, or V12 training yet. The first implementation target is the V12.0
no-op boundary and ownership telemetry.

## Claim boundary

Supported: on the pinned Mistral-7B model, seeds 43–45, and this exact BF16
Adafactor/CPU-accumulation contract, F1 remains robust through sixteen fresh
updates while the active O0 system is non-competitive, behavior-vetoed, and
without replicated content-specific necessity.

Not supported: that deferred slots are intrinsically incapable, that one
specific O0 component caused the failure, that F1 broadly improves the model,
that all workspace LRs fail, or that these results transfer to 14B, another
optimizer, another dataset, or a pure-native backend.

## Next handoff

Implement only the V12.0 no-op-equivalence boundary and per-family ownership
telemetry first. Freeze its contract and pass the no-update gate before
launching another training branch. Keep the current 125 GB raw run root until
the V12.0 implementation no longer needs checkpoint-level inspection; its
location and hashes are recorded in `EVIDENCE_INDEX.json`.
