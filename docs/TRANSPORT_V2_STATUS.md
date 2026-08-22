# CPU-accumulate transport v2 status

## Question

Can a 32 GiB RTX 5090 complete Mistral-7B full-parameter, gradient-accumulation-8
updates while moving accumulated gradients across CPU/GPU less often than the
old exact spill path, without changing the resulting state?

## Frozen implementation

`gradient_accumulation_offload=cpu_accumulate` retains the accumulated BF16
gradient on pinned CPU storage and performs cross-microbatch additions there in
parameter order. Each of eight current gradients moves D2H once and the final
accumulator moves H2D once. The old spill path required eight D2H and eight H2D
gradient-volume movements. The algorithmic movement count is therefore 9
instead of 16 per complete window, a 43.75% reduction.

The implementation trades this reduction for pinned host staging in addition
to the CPU accumulator. It is single-process CUDA only and rejects DDP,
non-CUDA execution, and schedule-extension resumes.

## Matched one-step result

All four conditions ran a full-parameter optimizer step with eight
microbatches. Every current-source candidate/reference oracle passed for all
291 base tensors and 7,248,023,552 elements, plus workspace state, trainer
state, scheduler, optimizer, RNG, sampler, and stable metrics under the
receipt's explicit exclusions.

| Condition | `cpu_accumulate` tok/s | old spill tok/s | Ratio | Peak CUDA GiB |
|---|---:|---:|---:|---:|
| F0 | 7.87745 | 5.67289 | 1.38861x | 29.57051 |
| B | 7.71049 | 5.43005 | 1.41997x | 29.83195 |
| F1 | 7.14073 | 5.20443 | 1.37205x | 29.62914 |
| O3 | 7.47349 | 5.31511 | 1.40608x | 29.83195 |

These are matched one-step observations, not long-run throughput guarantees.
F0 also passed a byte-exact comparison to an older GPU-resident reference, but
that cross-source run reached 58.17039 tok/s; CPU accumulation remains far from
native speed. Native multi-microbatch B/F1/O3 remains shelved because the
matched route OOMed.

## Failed activation-offload hypothesis

Broad `all_base` saved-activation offload did not create a useful path. F0 was
exact but slowed from 58.17039 to 52.04220 tok/s, and B still OOMed on its first
microbatch while requesting another 20 MiB with about 30.22 GiB allocated. The
negative evidence is retained under
[`negative_evidence/`](../provenance/pilots/transport_v2_cpu_accumulate/negative_evidence/).

## Behavioral pre-prune result

The first mandatory generation capture passed its artifact and B transport
sentinel gates. Its scientific-facing observation was negative: every trained
condition selected `no` on all 32 balanced task cases after one optimizer step.
Open-ended generation showed mixed local gains and regressions, with no
defensible winning branch.

See
[`BEHAVIOR_OBSERVATIONS.md`](../provenance/pilots/transport_v2_cpu_accumulate/BEHAVIOR_OBSERVATIONS.md)
and the reusable
[`GENERATION_BEHAVIOR_WORKFLOW.md`](GENERATION_BEHAVIOR_WORKFLOW.md).

## Claim boundary

Verified: bounded single-step transport execution, exact candidate/reference
state for the captured pairs, the measured throughput values, and the captured
behavior receipt.

Not verified: long-run stability or speed, pure-native B/F1/O3 equivalence,
multi-GPU execution, a 14B model, behavioral quality, causal or useful memory,
or a positive scientific result.
