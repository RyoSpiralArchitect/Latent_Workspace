# CUDA full-update smoke cut

Date: 2026-08-22

## Question

Can the v10 Latent Workspace harness run a Mistral-7B full-parameter update on
one 32 GiB CUDA GPU, preserve the result of native gradient accumulation, resume
bitwise exactly at an optimizer-step boundary, and retain enough compact
evidence to delete the large trained base-model bundles safely?

## Frozen design

- Model: `mistralai/Mistral-7B-Instruct-v0.3` at revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Engine SHA-256:
  `755ddaee835cd6cf0d30269212226250a5aeed14e5457385ceca60db0f39aa3c`.
- Runner SHA-256:
  `07fdd920f76463f5996a5568447b940d41b8bce4675dd83594d3f68e54ecd68d`.
- Source-tree SHA-256:
  `33851900abae227475a27ddafd409225f02a01354be6c13a1f6209ddf3f5e835`.
- Runtime: one RTX 5090 32 GiB, PyTorch CUDA, BF16, SDPA, gradient
  checkpointing, and full-parameter Adafactor.
- Accumulation: eight microbatches per optimizer step. The CPU-spill path stores
  pageable CPU gradients after each microbatch and restores/adds them on CUDA in
  native dtype and native addition order before the optimizer step.
- Cut: `F0_query_only`, `B_local_invariance`, `F1_inline_upper`, and
  `O3_slots4_k1_lw_cf`; seed 42; eight optimizer steps each.
- Comparison: exact tensor bytes, not a tolerance-based floating-point metric.

No hand-written Triton kernel was introduced. PyTorch's CUDA/SDPA stack remains
the optimization substrate until profiling identifies a narrower kernel-level
bottleneck with an explicit forward/backward parity oracle.

## Result

All four smoke runs reached `verified_completed`, passed their configured assay
integrity checks and exact step-4 resume checks, exported compact evidence, and
then transitioned to `verified_pruned`.

| Condition | Last-step supervised tok/s | Peak CUDA allocation | Persisted base tensors changed | Held-out query accuracy | Scientific direction |
| --- | ---: | ---: | ---: | ---: | --- |
| F0 query-only | 5.902 | 29.572 GiB | 240 / 291 | 0.5 | amputation neutral |
| B local-invariance | 5.682 | 29.833 GiB | 240 / 291 | 0.5 | amputation neutral |
| F1 inline-upper | 5.429 | 29.630 GiB | 241 / 291 | 0.5 | amputation neutral |
| O3 slots4 k1 local-workspace counterfactual | 5.588 | 29.833 GiB | 240 / 291 | 0.5 | amputation opposes load-bearing; necessity does not support its gate |

For every condition, optimizer membership and dynamic update-attempt coverage
were exact for all 291 base tensors / 7,248,023,552 base elements. Every run
recorded 64 CPU spills, eight restored accumulation windows, zero discarded
windows, and zero single-microbatch windows. The persisted-delta count is a
separate diagnostic: a tensor can have a verified optimizer update attempt yet
finish with zero net stored BF16 change.

Each step-4 resume comparison passed with zero changed base tensors and zero
changed base elements, exact workspace state, exact trainer state, and exact
stable metrics after only the receipt-declared runtime telemetry exclusions.
This covers the four recorded single-GPU, fixed-schedule runs; it does not cover
signal preemption, schedule extension, multi-GPU execution, or another runtime.

## Native-versus-spill comparison

The current-source F0 native and CPU-spill runs matched exactly:

- 291 base tensors / 7,248,023,552 elements, zero byte differences;
- 81 workspace tensors / 74,379,022 elements, exact;
- 810 trainer tensors / 2,966,771 elements, exact after excluding only the
  receipt-declared run identity and signature fields;
- exact stable metrics after excluding declared runtime telemetry; and
- identical validated engine source identity.

The last-step throughput was 88.003 supervised tokens/s for native accumulation
and 5.902 for CPU spill, so this conservative spill implementation was about
14.9 times slower in this one matched eight-step F0 measurement. That is a
recorded pilot measurement, not a general CUDA benchmark.

A second base-only oracle matched the current spill result to the retained d5
native result for all 291 base tensors. Because that comparison did not bind two
current-source run bundles, its source identity remains explicitly unverified.

B could not receive the same native cross-offload claim. A reduced
gradient-accumulation-one native run completed, but the CPU path correctly
refused to call it an offload comparison because no multi-microbatch spill
window ran. The matched gradient-accumulation-two native route then OOMed during
its first backward pass with about 30.40 GiB already allocated and only about
23 MiB free. The formal B spill run and its same-spill resume comparison are
verified; native B equivalence is not.

## Failed hypotheses and negative results

- CPU gradient spilling was not close to native throughput in the matched F0
  pilot; exactness was obtained at an approximately 14.9x last-step slowdown.
- The eight-step smoke cut did not produce positive functional evidence.
  Held-out query accuracy remained 0.5 in all four conditions.
- O3 did not pass its functional evidence ladder. Its necessity receipt records
  F1 through F5 as false, and the amputation direction opposes a load-bearing
  interpretation.
- A single 32 GiB GPU is not an honest target for a 14B BF16 full update under
  this implementation. BF16 parameters and gradients alone exceed the card
  before activations and optimizer state. A 14B cut needs a separately frozen
  distributed/offload design and its own equivalence evidence.

## Interpretation

The CUDA port and the conservative CPU-spill mechanism solve the immediate
engineering blocker: all four smoke conditions can execute full-scope Mistral-7B
updates on the Furnace GPU, survive a strict save/reload boundary, and leave a
replayable compact evidence trail after trained base weights are removed.

They do not yet supply evidence that the workspace route learned a useful,
content-specific causal memory. The O3 result is particularly useful negative
evidence: the carrier was present and the intervention machinery executed, but
the functional gates did not move off chance.

## Claim boundary

Integrity `PASS` means the exact recorded run, artifacts, optimizer coverage,
spill windows, assays, resume comparison, and retention transition satisfied
their contracts. It does not mean positive training quality, causal memory,
generalization, superiority over another model, consciousness, or AGI.

The pruned trained base-model shards are not reconstructible from the retained
hashes. The pinned initial Mistral snapshot is recoverable from its immutable
revision; a trained final is recoverable only if an external weight backup was
kept. No such backup is declared by these receipts.

## Provenance

- Compact per-condition evidence:
  [`provenance/pilots/v10_cuda_smoke_current/smoke/`](../provenance/pilots/v10_cuda_smoke_current/smoke/)
- F0 current-source and historical d5 oracle receipts:
  [`provenance/pilots/v10_cuda_smoke_current/oracles/`](../provenance/pilots/v10_cuda_smoke_current/oracles/)
- Four top-level resume receipts:
  [`provenance/pilots/v10_cuda_smoke_current/resume_equivalence/`](../provenance/pilots/v10_cuda_smoke_current/resume_equivalence/)
- B native-capacity negative evidence:
  [`provenance/pilots/v10_cuda_smoke_current/negative_evidence/`](../provenance/pilots/v10_cuda_smoke_current/negative_evidence/)

The four formal pruning transactions removed 57,984,422,832 logical bytes in
total while preserving receipt-bound compact exports. A separate cleanup
transaction removed 76 duplicate/oracle/resume shards across 19 bundles,
totaling 275,425,537,480 logical bytes. Its observed free-space increase matched
the 275,426,062,336 allocated bytes exactly, and independent postflight found
zero trained safetensors outside the protected pinned model cache. That cleanup
must not be conflated with the four formal-run transitions.

- Duplicate-weight cleanup receipt:
  [`provenance/pruning/current_cuda_oracle_and_resume_raw_weights/PRUNE_RECEIPT.json`](../provenance/pruning/current_cuda_oracle_and_resume_raw_weights/PRUNE_RECEIPT.json)

## Next handoff

The four smoke runs are complete, but the next profile remains deliberately
machine-blocked: its required smoke `QUALIFICATION.json` has not been issued.
The preregistered n=3 profile contains 57 runs at 512 optimizer steps each.
Before issuing that operator receipt or launching n=3, preserve the current code
and evidence commit on the user-provided GitHub remote, freeze the per-run
export/prune cadence, and explicitly accept the measured spill-throughput cost.
The repository currently has no remote, so no GitHub publication has occurred.
