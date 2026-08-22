# Model and backend decision

## Decision

Start with `mistralai/Mistral-7B-Instruct-v0.3` on PyTorch CUDA. Treat a 14B-class
model as a later replication, not as the first port and not as a pooled extension
of the 7B result.

The starting revision is frozen to
`c170c708c41dac9275d15a8fff4eca08d52bab71`. The prefetch receipt must prove that
the resolved snapshot equals this commit before any model load or training run.

## Why 7B first

1. It is a text-only causal language model close to the existing text harness.
   This limits simultaneous changes while moving from GPT-2 CPU/MPS to CUDA.
2. Full-parameter training is already a hard memory problem on the furnace's
   single 32,607 MiB RTX 5090. A 7B pilot is the smallest of the proposed models
   that tests the intended scaling regime.
3. The pilot can expose optimizer-state, activation, checkpoint, and resume costs
   before multiplying them across conditions and seeds.
4. Failure at 7B is actionable evidence for checkpointing or offload design;
   starting at 14B would conflate backend correctness with resource exhaustion.

The observed environment supports CUDA and BF16, but DeepSpeed is not installed.
No claim is made that native full-parameter AdamW fits. The measured native path
uses Adafactor, activation checkpointing, and short sequences.

## Measured 7B execution envelope

The current CPU-spill engine completed all four eight-step smoke conditions on
the single RTX 5090. Peak CUDA allocation ranged from 29.572 to 29.833 GiB.
Every condition verified a finite nonzero gradient and optimizer update attempt
for all 291 base tensors / 7,248,023,552 elements. Persisted BF16 change remained
a stricter, separate diagnostic: F0, B, and O3 changed 240 of 291 tensors, while
F1 changed 241.

For all four fixed-schedule seed-42 runs, step-four checkpoint/resume equivalence
is bitwise verified. Each comparison used an eight-step uninterrupted control
and a four-step post-checkpoint resumed branch. Base model, workspace, trainer
state, and stable metrics were exact under only the receipt-declared dynamic
field exclusions. This covers active workspace routes in F1 and O3, but not
signal preemption, schedule extension, multi-GPU execution, or another runtime.

Current-source F0 also has an exact native-versus-CPU-spill oracle across the
base model, workspace, trainer state, and stable metrics. The eight-step mean
throughput was 83.950 supervised tokens/s for native accumulation and 5.895 for
CPU spill, an observed 14.24x slowdown. This is one matched short pilot, not a
replicated performance benchmark. B native multi-microbatch equivalence remains
capacity-blocked: its matched gradient-accumulation-two route OOMed during the
first backward pass near the 32 GiB limit.

The active engine SHA-256 is
`755ddaee835cd6cf0d30269212226250a5aeed14e5457385ceca60db0f39aa3c`.
The earlier optimizer-state dtype failure and its correction remain useful
historical evidence, but they are not the active source identity. Current smoke
evidence is under
[`provenance/pilots/v10_cuda_smoke_current/`](../provenance/pilots/v10_cuda_smoke_current/).

All four formal base-model bundles have been explicitly pruned after compact
export. Compact hashes prove recorded identity and history but cannot reconstruct
trained weights. A separate bounded cleanup removed all 76 scoped experimental
trained shards; independent postflight found no trained safetensors outside the
protected pinned initial-model cache. No loadable trained base-model copy
remains in the scoped Furnace worktree.

## Why 14B comes later

A 14B-class run approximately doubles parameter-side storage before activations.
It should be scheduled only after the 7B pilot and three-seed cut provide measured
VRAM, host-RAM, I/O, and wall-time envelopes.

The phrase “14B instruct” is not a sufficiently frozen model identity. A
candidate may be multimodal or use a different model class; on text-only data,
an untouched vision tower cannot honestly be described as a whole-model full
update. Before a 14B replication, freeze:

- exact repository, immutable revision, license, and tokenizer;
- text-only versus multimodal architecture;
- the precise parameter scope meant by “full update”;
- optimizer/offload implementation and numerical backend;
- a matched comparison contract that separates model-size effects from model-
  family, tokenizer, context-window, and architecture changes.

A text-only intermediate such as the Mistral-Nemo 12B family may be cleaner than
a multimodal 14B model, but that is a later decision and is not preregistered here.
The 14B lane therefore remains deferred; no 14B model or revision has been
selected for the current matrix.

## CUDA versus Triton

Use PyTorch CUDA first. Allow its scaled-dot-product attention implementation and
`torch.compile` to use supported optimized kernels, recording the selected
backend. Do not write a custom Triton kernel until a profiler shows a material
bottleneck and a reference implementation supplies forward, backward, and resume
parity tests.

Maintain two declared lanes if throughput kernels are nondeterministic:

- **attribution lane:** deterministic operations and fail-closed reproducibility;
- **throughput lane:** faster CUDA kernels with backend and tolerance receipts.

Results from the two lanes must not be silently mixed.
