# V23 preservation objective: from diagnostic targets to an owned update

**Status: additive metadata-binding implementation; objective/update integration
is proposed, not implemented or dispatched.** This work does not depend on a
favorable partial gradient result. The [existing audit](GRADIENT_AUDIT_01.md)
continues from its unchanged frozen source. Its coefficient, acceptance gate,
inputs and live process are untouched.

The next implementation must remain inside the model-independent engine and
the existing native owner, not create another version-specific learner or a
Mistral-only training wrapper. P (ordinary-host preservation) remains a
candidate factor, not a winner selected before the audit completes.

## What is implemented now

[`preservation_binding`](../../src/latent_workspace/preservation_binding.py)
binds the existing teacher-receipt **metadata format** to all of its ordered,
complete English training rows. It verifies a receipt digest pinned by the
caller, unique row keys, content hashes, empty memory, vocabulary extent, FP32
target metadata and temperature one. For every active label at position `j`,
it records the corresponding logit position `j - 1`. Prompt and continuation
tokens, masks, full query extent and source metadata cannot change unnoticed.
Neither row reordering nor cropped, padded or missing-target fallback is allowed.

Digest schemes are explicit: `expected_receipt_plan_sha256` is the canonical
JSON `execution.plan_hash` of the parsed receipt, **not its JSON file byte hash**.
The target body's byte SHA256 is a separate field. The frozen plan must also
identify the native-state hash scheme rather than mixing a state-tree digest
with the legacy model digest.

The binding is immutable and rechecks a row when used. Its detached manifest
contains fingerprints and positions, not the private input token arrays. The
vocabulary is taken from the pinned receipt, not hard-coded to Mistral. No
model or target tensor is instantiated by the binding functions.

This is deliberately **not target-body validation**: it does not read a
safetensors file, prove normalized probabilities, replay the teacher's source
seal, or certify that a descriptive `teacher_policy` string was executed.
The manifest explicitly says `NOT_PERFORMED_METADATA_ONLY` and
`owner_integration: NOT_IMPLEMENTED`. Actual training must additionally perform
the checks below. Synthetic metadata tests do not admit the real bank to FT.
See the [preparation receipt](../../provenance/engineering/v23_preservation_binding01_20261022/README.md).

## The current integration gap

| Surface | Current behavior | Next requirement |
| --- | --- | --- |
| [`native_owner._validate_contract`](../../src/latent_workspace/native_owner.py) | Only the literal `query_only_token_weighted_causal_nll` | A versioned, hashed objective descriptor; retain exact legacy handling |
| `NativeFullUpdateOwner.accumulate` | `loss_sum / whole_window_tokens`, one backward and spill per row | Owner-owned CE/KL composition with declared eligible positions and denominators |
| [`objective_audit.full_vocab_kl_sum`](../../src/latent_workspace/objective_audit.py) | Diagnostic FP32 full-vocabulary forward-KL primitive | Reuse the algebra with checked target identity and causal layout; do not mistake a primitive for a trained owner |
| `payload` / `restore` | Exact v1 source/data/objective/execution plus optimizer/RNG/history | Bind target identity, normalization, coefficients and both token cursors before publishing any restored state |
| [`GradientSpill`](../../src/latent_workspace/gradient_spill.py) | FP32 across-row **diagnostic** sum | Do not silently replace the owner's native-dtype window arithmetic |

V22 restoration under its original CE contract and a successful audit canary
do not qualify CE+KL updates or their restart.

## Proposed first objective, with coefficient still unselected

For a predeclared update window, let `N` be the count of all supervised query
targets and `Np` the count of eligible no-memory preservation targets. The
proposed P factor is:

```text
J = sum(CE over all window targets) / N
    + lambda * sum(KL(original_teacher || current_student)
                   over preservation targets) / Np
```

- Keep the existing CE term, native full vocabulary and shared W/Q parameters.
  No additional identity/copy/format weights, Q amplifier, LR change or new
  recurrence is bundled with the first P comparison.
- `lambda` is finite and nonnegative, frozen before a future trial. No value
  is selected here. The diagnostic panel's 532/932 denominators are not training
  window denominators, and norm ratios alone must not choose the coefficient.
- A positive-P window must declare `Np > 0`. A missing target or uncovered
  preservation row is an error, not permission to set KL to zero. World rows
  with absent memory are still world controls; empty memory alone does not
  make a row eligible for preservation targets.
- With P disabled, use the exact existing CE path: no extra teacher forward,
  target read, added zero-valued tensor, altered reduction order or RNG use.
  Numerical update parity is required, not only a nearly equal scalar loss.
- Compute one combined scalar and one backward per eligible row, then retain
  the existing ordered native-dtype spill, CPU FP32 masters and Adafactor.
  Computing two separate native backwards is not assumed bitwise equivalent.
- Record CE sum, KL sum, scaled contributions, `N`, `Np`, row order and eligible
  positions independently. KL does not count as another exposure to CE targets.
  Do not clamp a small numerical KL value or change its precision silently.

The first comparison should vary P only, with the same initialization, world
and preservation rows, realized token mix, step count and optimizer. Data
expansion, B (binding) and I (copy transport) remain separately matched factors.
This proposal is not evidence that P will satisfy the base floor.

## Target admission before a forward or a checkpoint restore

1. Obtain expected receipt, source, base, tokenizer/rendering and data identities
   from the new frozen plan, never from a target file's self-description alone.
   Replay the original source/result seals and verify the input body digest.
2. Verify the complete target-file digest and bytes, then exact tensor-key
   coverage and shape, contiguous causal ordering, detached FP32 finite values
   and full-vocabulary log normalization. No top-k or dtype-compressed substitute.
   The existing twelve-row, 932-position audit bank is not automatically the
   full training reference bank.
3. Bind every admitted row to the exact complete context. The owner must
   construct its batch from this checked row (or verify the actual batch
   tensors too); checking one metadata object while forwarding another is
   insufficient. Teacher-forced targets do not apply to changed free-generation
   prefixes, answer lengths or padding extents.
4. Freeze teacher evaluation and student training modes, native dtype, backend,
   tokenizer, masking and extent explicitly. Even unchanged weights do not
   prove identical logits across execution modes or layouts. A same-weight KL
   sentinel must characterize that difference before an update trial.
5. Revalidate file/row integrity at the declared lifecycle boundaries. A changed
   target body, index, schedule or normalization must fail before native/RNG
   publication during restore. Metadata binding alone cannot enforce this.

## State and initialization

Keep the v1 checkpoint reader and its literal CE contract intact. Extend the
same owner with an explicit new format/descriptor, rather than changing the
meaning of existing payloads. A new payload must bind the coefficient, both
normalizations, target-bank fingerprint, exact ordered row/target schedule,
CE and KL position cursors, execution policy, masters, moments and RNG.
Only complete clean-window boundaries are saveable, as today.

**Changing V22's objective is not exact resume.** Do not rewrite its
`run_contract`, optimizer or history to make it look like one. Starting both
P-off/P-on arms from the pinned original base is the simplest clean comparison.
If continuing from V22 is chosen instead, define a separate, explicit transition
receipt that binds the source checkpoint and whether masters/moments/counters
are retained or reset. Both arms must use the same transition. Its qualification
is additional to fresh-process resume *within* the new objective.

## Required gates, in order

1. **Metadata binding (this change).** Synthetic row/hash/causal-layout tests;
   the old owner must still reject an unsupported new objective.
2. **Owner integration, tiny CPU then CUDA.** P-off bitwise parity with old CE
   for FP32/BF16, all supported tiny hosts, tied parameters and recomputation.
   Positive-P arithmetic must match an independently composed reference update,
   with heterogeneous row lengths and masks. Coefficients used in tiny algebra
   fixtures are not selected 7B hyperparameters.
3. **Save and fresh-process replay.** Compare uninterrupted and saved/restored
   updates, native/FP32-master values, moments, RNG, losses and both token
   cursors. Wrong coefficient, teacher, row, causal shift, denominator, context,
   missing target and changed execution must fail before target/RNG mutation.
4. **New bounded 7B canary.** Qualify the chosen CE+KL graph, resource envelope,
   update/save/fresh-restart and target transport. The audit's 17.7802-GiB peak
   excludes training-owner costs and cannot serve as this admission estimate.
5. **Separately frozen full-FT comparison.** Choose the initialization,
   coefficient, data/budget and primary checkpoint rule only after the complete
   audit is replayed. Reserve untouched confirmation and base-retention tests;
   do not train on the exposed MMLU/old failure examples or tune a release floor.

Storage for full FP32 targets is `4 * vocabulary * eligible_target_positions`
bytes, plus headers. Stream only the current row to the device; avoid a second
resident teacher. Recompute resource/storage admission for the actual future
bank and checkpoint count. No additional weight retirement is needed or
performed by this preparation.

Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED**. Metadata checks,
local tests, gradient signs and later exact restart are different claims from
quality, preservation and a V23/1.0 release.
