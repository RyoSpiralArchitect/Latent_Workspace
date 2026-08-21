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

A native full-parameter Adafactor F0 pilot completed eight steps on the single
RTX 5090, peaking at 29.587 GiB allocated and 30.182 GiB reserved. This proves
only that this short-sequence, eight-step F0 configuration executes and saves
on the observed furnace environment.

It does not prove that the 512-step F0 or workspace conditions remain stable,
or that AdamW or a 14B-class model fits. The fixed-engine eight-step F0 verified
a finite nonzero gradient and optimizer update attempt for all 291 base
tensors. The independent strict claim that every tensor retains an exact
persisted BF16 delta remains false: 51 RMSNorm scales had a verified update
attempt but zero net stored delta.

For this fixed-schedule F0 seed, step-four checkpoint/resume equivalence is now
bitwise verified. The uninterrupted control ran eight optimizer steps and the
resumed branch ran four post-checkpoint steps, for 12 executed optimizer steps
across the comparison. All 291 tensors / 7,248,023,552 elements had zero
differences, and workspace and trainer state were exact. The bound resume
receipt SHA-256 is
`5e5b4178005a89beacfb5742edd307e15401a49d1af33543da5f36374330a645`.

The first strict resume attempt exposed a backend-specific correctness issue:
PyTorch's standard optimizer reload cast saved FP32 Adafactor moment tensors to
the BF16 parameter dtype. The current engine validates the name-bound optimizer
mapping and restores checkpoint tensor state with its original dtype and exact
value. That fix, under engine SHA-256
`3139c6edea71575310a2e6f245999e504318fedede202786fe2c949861ad2e1c`,
is what the bitwise rerun verifies. It does not establish signal-preemption,
schedule-extension, multi-GPU, cross-runtime, or active stochastic-workspace
resume equivalence.

The path-free fixed-engine evidence is
[`PUBLIC_EVIDENCE.json`](../provenance/pilots/F0_fixed_engine_verified_pruned/PUBLIC_EVIDENCE.json),
SHA-256
`d787e5ac95fc355c1397d4bff2e6bcda95e41065b722ac2ac482447d35686fcb`.
The baseline run's final base-model bundle has been pruned and cannot be
reconstructed from compact hashes. Bitwise-identical loadable copies currently
remain in the successful resume-equivalence pilot, but they are not a declared
durable backup. The obsolete failed attempt's 16 weight shards were separately
pruned under a bounded receipt while its diagnostic states and manifests were
retained; this does not establish an automatic failed-run retention policy.

## Why 14B comes later

A 14B-class run approximately doubles parameter-side storage before activations.
It should be scheduled only after the 7B pilot and three-seed cut provide measured
VRAM, host-RAM, I/O, and wall-time envelopes.

The phrase “14B instruct” is also not a sufficiently frozen model identity. Some
current Mistral 14B offerings include a vision tower and a different model class.
On text-only data, an untouched vision tower cannot honestly be described as a
whole-model full update. Before a 14B replication, freeze:

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
