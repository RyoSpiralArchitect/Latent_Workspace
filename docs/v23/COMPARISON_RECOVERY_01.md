# V23 P-on whole-arm recovery 01

Ryō explicitly authorized a new P-on-only attempt after the operator CPU
qualification created a CUDA context and stopped the original P-on arm.
The first CUDA-initializing API remains **NOT_ISOLATED**. This is not a learner
quality failure and not permission to weaken the GPU exclusivity guard.

The original source `84073310cd7b2c56b5e3de046fb3bdc99e461bfb`, terminal
`INCOMPLETE_NO_RETRY`, all 79 partial P-on MMLU rows and completed base/off
stay unchanged. The new attempt regenerates all 570 MMLU scores, 192 world
teacher-forced rows, 192 world sequences and 24 free answers for P-on only.
The old 79 rows are excluded from the recovered panel, not spliced or replaced.
Original base/off and recovered P-on retain separate source seals and manifests.

The numerical evaluator and original input/seed/cap/model/strict owner restore
are called unchanged with the original plan. No training, saved weights,
deletions, new data, release, default promotion or hidden retries.

## Isolation gate

An additive qualification mixin sets `CUDA_VISIBLE_DEVICES` to the empty string
before importing torch and rejects late entry. Children inherit the mask.
A fresh isolated child must see zero CUDA devices, reject `torch.cuda.init`,
and remain uninitialized. The CPU suite then runs with that mask. Parent and
descendant PIDs are sampled against `nvidia-smi` every 0.5 seconds, including
before/after samples; any monitor error or own GPU client fails admission.
The parent must finish with zero visible devices and no initialized context.
This is device visibility with sampled observation, **not an OS sandbox**.

The external `qualification/CPU_ISOLATION.json` binds the CPU terminal hash
and PID. Passing test counts alone cannot admit a role: the audit must also
pass. Historical test receipts are never rewritten. CPU, CUDA and P-on run
in separate processes **sequentially**; CUDA admission and the real-model
exclusive-client checks remain unchanged. Both full selected tiny suites must
pass **244/244** with zero skips before the 7B evaluation. A fresh-process
regression covers the actual entry: the package initializer itself imports
torch, so the visibility guard lives in a standard-library-only script, before
any package import. This was caught in local development, before source freeze
or a new Furnace qualification/model call. The local 60-test boundary, judge
and MMLU-Pro regression selection passed; the two full Furnace suites are the
execution gate, not that local subset.

## Downstream

Judge and MMLU-Pro remain blocked until the new whole P-on arm is complete
and byte-verified. A new explicit combined-bank adapter must name both
provenances; it must not manufacture a successful original dispatcher.
The calibrated judge rubric, request construction, parser, model and settings
stay frozen. The existing MMLU-Pro selected IDs and tokenized inputs stay
frozen. Report base-wrong/FT-correct **and** the reverse transitions, all
missingness/caps/ties, and the limitation of a previously exposed diagnostic.
The old expression gate remains **FAIL**, winner **none**, non-regression
**NOT_ESTABLISHED**.
