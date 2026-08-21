# Latent Workspace FT — CUDA comparison harness

This repository is the clean staging surface for a CUDA-native, full-parameter
Latent Workspace comparison. It starts with a portable v10 engine, provenance,
data, and explicit decision boundaries.

## Status

- Canonical source is staged locally on branch
  `SpiralReality/cuda-full-update`. The GitHub remote and initial commit are
  pending the repository URL.
- The runtime contract is PyTorch CUDA, BF16, SDPA, gradient checkpointing,
  and full-parameter Adafactor. Custom Triton kernels remain deferred until a
  measured bottleneck and forward/backward parity test justify them.
- The starting model is `mistralai/Mistral-7B-Instruct-v0.3`, pinned to
  revision `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Furnace dependency, tokenizer, data, and immutable model-cache gates pass
  for the pinned receipts.
- The v1 pilot remains `invalid_final` and preserves the failed strict
  all-tensor persisted-delta hypothesis. The later v2 pilot verified dynamic
  optimization attempts, but predates the current engine and is retained as
  historical evidence rather than the active baseline.
- The fixed-engine `F0_query_only`, seed 42 pilot completed eight steps under
  engine SHA-256
  `3139c6edea71575310a2e6f245999e504318fedede202786fe2c949861ad2e1c`.
  Its run-verification receipt
  (`ba5d5a524565a9e59e6bfc207b861d786ea9e21514008318db63e1f6d8ed1191`)
  binds exact, duplicate-free optimizer membership and dynamic update evidence
  for all 291 base tensors.
- Exact persisted comparison again found a nonzero stored delta in 240 tensors.
  The other 51 BF16 Mistral RMSNorm scales had verified update attempts but zero
  net persisted BF16 delta. Peak CUDA allocation was 29.587 GiB and peak
  reservation was 30.182 GiB.
- The required held-out and amputation assays passed execution-integrity checks
  under receipt
  `410b295534e25f7d24faa1fd988cf86ef85bef06d2b77dff210572571ef2480a`.
  Both accuracies were 0.5 and the amputation delta was 0.0, so the scientific
  direction is neutral, not positive.
- Fixed-schedule checkpoint/resume equivalence passed. Across the equivalence
  harness, the uninterrupted control executed eight optimizer steps and the
  resumed branch executed four post-checkpoint steps (12 executed steps total).
  The resulting 291 tensors / 7,248,023,552 elements had zero bitwise
  differences, and workspace and trainer state were exact. The bound receipt is
  `5e5b4178005a89beacfb5742edd307e15401a49d1af33543da5f36374330a645`.
- The verified F0 final is now `verified_pruned`: a rehashed compact export was
  retained and 14,496,105,708 bytes of trained base-model bundle were removed
  from the baseline run's `final/base_model` under an explicit prune receipt.
  The compact hashes cannot reconstruct that deleted bundle. Exact loadable
  copies currently remain in the successful resume-equivalence pilot, but they
  are not declared or managed as a durable backup.
- The obsolete failed optimizer-dtype resume attempt was pruned under a separate
  bounded receipt: 16 safetensors totaling 57,984,323,680 bytes were deleted,
  while compact diagnostics, trainer/workspace states, and manifests were
  retained. This does not authorize automatic failed-run pruning.
- The remaining three smoke conditions are pending. n=3 and n=10 remain blocked
  behind smoke completion and profile-level retention gates.
- Legacy v9 remains frozen as a structurally valid `partial_nonfinal`
  snapshot: 28/190 training runs, no final validation, and no scientific final.
- Model weights, optimizer state, checkpoints, and run directories are excluded
  from Git. Durable artifacts must be stored separately and referenced by hashes.

## Claim boundaries

Verified engineering evidence:

- immutable Mistral-7B model and tokenizer identity;
- full-file functional-data integrity;
- CUDA/BF16 execution and eight-step F0 training feasibility;
- exact, duplicate-free optimizer membership for every base tensor;
- finite nonzero gradients and optimizer update attempts for every base tensor;
- a verified, assay-complete F0 run under the dynamic-coverage contract;
- exact persisted deltas in 240 tensors and evidence-backed zero net persisted
  deltas in the other 51 tensors;
- bitwise-exact fixed-schedule resume for all 291 base tensors and exact
  workspace, optimizer, scheduler, scaler, sampler, RNG, RunState, and stable
  metric state for this F0 seed on the recorded single-GPU runtime;
- a tested explicit compact-export and prune transition that remains
  distinguishable as `verified_pruned`.

Not yet verified:

- completion of the four-condition smoke profile, n=3, or n=10;
- signal-preemption, schedule-extension, multi-GPU, cross-runtime, or active
  stochastic-workspace resume equivalence (F0 bypasses the workspace route);
- training quality, causal memory, content-specific memory, generalization,
  model superiority, or comparability with GPT-2 v9.

The v1 artifacts cannot distinguish sub-quantization updates, later
cancellation, or missing dynamic processing. The fresh v2 run resolves that
evidence gap: every base tensor had a verified update attempt, while 51 still
had zero net BF16 persisted delta. This does not imply that every stored value
moved.

### Current pilot result

The first F0 run preserves a failed strict all-tensor persisted-delta
hypothesis. Its compact evidence and exact claim boundary are recorded in
[`provenance/pilots/F0_8step_all_tensor_gate_failed/RECEIPT.json`](provenance/pilots/F0_8step_all_tensor_gate_failed/RECEIPT.json).

The fresh v2 run verifies full-scope optimization attempts while retaining
that all-tensor persisted-delta result as an independent failed diagnostic.
Its compact evidence is recorded in
[`provenance/pilots/F0_8step_v2_verified/RECEIPT.json`](provenance/pilots/F0_8step_v2_verified/RECEIPT.json).

The current fixed-engine F0 adds assay, exact resume, compact-export, and prune
receipts. Its path-free publication record is
[`PUBLIC_EVIDENCE.json`](provenance/pilots/F0_fixed_engine_verified_pruned/PUBLIC_EVIDENCE.json),
SHA-256
`d787e5ac95fc355c1397d4bff2e6bcda95e41065b722ac2ac482447d35686fcb`.

One earlier resume attempt is retained as negative evidence. PyTorch's standard
optimizer reload cast saved FP32 Adafactor moments to the BF16 parameter dtype,
causing resumed weights and optimizer moments to diverge. The engine now
replaces loaded optimizer tensor state from the checkpoint with exact
dtype-preserving tensors after validating the name-bound optimizer mapping;
the fixed rerun is the bitwise PASS reported above.

The old failed resume attempt's bounded weight cleanup is recorded in
[`PRUNE_RECEIPT.json`](provenance/pruning/F0_resume_attempt2_failed_optimizer_dtype_weights/PRUNE_RECEIPT.json).
Its deleted shards are not guaranteed reconstructible, but the negative result,
root-cause evidence, trainer/workspace states, metrics, and manifests remain.

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
F0, but n=10 remains blocked until smoke and n=3 complete and a profile-level
retention schedule is frozen and capacity-checked. See
[`docs/ARTIFACT_RETENTION.md`](docs/ARTIFACT_RETENTION.md).

## Runtime choice

The first implementation should use PyTorch CUDA. PyTorch SDPA and
`torch.compile` may select optimized CUDA/Triton kernels internally. Hand-written
Triton kernels are deferred until profiling identifies a specific bottleneck and
a numerical-parity test exists.

## Repository layout

- `src/latent_workspace_ft_v10/` — portable engine and CUDA/Mistral split adapter.
- `tests/` — offline tiny-model equivalence and optimizer coverage tests.
- `configs/v10/` — pinned 19-condition contract and smoke/n3/n10 profiles.
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
