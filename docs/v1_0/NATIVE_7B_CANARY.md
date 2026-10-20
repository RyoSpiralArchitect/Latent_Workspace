# Native-memory 7B canary: engineering before the training population

2026-10-20. Prospective bounded engineering trial, **not yet launched**.
Ryō approved proceeding after the
[recorded V16 retirement](../../provenance/inventory/v16_scientific_retirement_20261020/README.md).
The [plan](../../configs/v1_0/NATIVE_7B_CANARY.json) and
[entry](../../scripts/run_native_7b_canary.py) freeze one cut-4 condition:
pinned original Mistral-7B-Instruct-v0.3, all native BF16 parameters trainable,
FP32 CPU Adafactor masters, eager attention and non-reentrant activation
checkpointing. The qualified graph and update arithmetic are not redesigned
for this trial. CPU oneDNN is explicitly off, as in the tiny qualification.

## Fixed scope

Four authored synthetic rows, not benchmark/validation/judge-derived gold.
Each of two ordered windows contains one separately written factual memory
with a teacher-forced answer and one no-memory answer. Every forward reencodes
memory from IDs using current weights. The native full-vocabulary NLL is divided
by the total supervised answer tokens in its complete window, including EOS;
unequal-length answers are not averaged as equal-weight microbatch means.

The pinned native user chat prefix receives separately encoded, space-prefixed
answer tokens plus EOS. Tokenization explicitly sets `return_dict=False` and
validates integer IDs; Transformers 5.15 defaults to a mapping. The
[first prelaunch](../../provenance/engineering/native_7b_canary_prelaunch01_20261020/README.md)
was superseded before CUDA/7B dispatch when this API mismatch was found.
Prompt labels are ignored. Memory has no special tokens
and never contains the question/answer. Persist exact text, IDs, labels and
counts before model loading; fail instead of truncating above 128 memory tokens,
128 query-plus-answer tokens or 32 supervised tokens. Microbatch size is one.
These short cases establish only their measured resource envelope.

Primary: two updates and checkpoints 1/2. Replay: a **fresh process**, fresh pinned
original host, load checkpoint 1 and repeat window 2. Planned denominator:
**2 unique updates + 1 replay update, 6 backward rows, 2 retained checkpoints**.
No replay weight file, free generation, paid judge, model download, deletion,
benchmark or release is part of this trial. No adapter/route weights are added.

## Gates and receipts

Run the existing 203 selected tiny checks plus 26 new harness checks (229 total) on both
CPU and CUDA from the same sealed source, with the existing 4-GiB per-process /
900-second qualification limits. Every case must pass without skips before
any 7B dispatch. The old qualified receipts remain historical, not replacements
for qualification of this new entry and activity-count receipt policy.

Real-model guards retain 31-GiB free-GPU admission, 30.5-GiB CUDA allocator cap,
0.75-GiB free-GPU floor, 100-GiB host admission, 24-GiB host available floor,
50-GiB remaining disk floor and 7,200 seconds **per role**. CPU threads: two.
Forecast two checkpoints within 64 GiB; require an additional 32 GiB available
above the host floor before an independent snapshot/load. Other GPU clients
stop this job, never theirs. Source/qualification errors, OOM, nonfinite or
missing gradients, invisible native updates, resource violations and replay
mismatches stop the attempt; retain evidence, do not retry or relax limits.

Record row losses, ordered accumulated-gradient hashes, native/master update
counts, native/optimizer/master/buffer/RNG fingerprints and checkpoint content
hashes. Restore must match step 1 exactly. Repeated window 2 must match all
algorithmic row/update/state records and its serialized state hash exactly,
within this same declared runtime/backend. Wall times/resource peaks are
observations, not equality endpoints. Measure CUDA allocated/reserved and host
RSS separately for primary and replay. Count physical updates including replay
separately from unique updates. Interrupted activity is unknown, not zero.

Success establishes real-7B execution and restart equivalence for this short
graph only. It establishes no faithful use of memory, useful learning, longer
sequence fit, base non-regression or linguistic quality. The historical
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
Only after this gate should the full-FT population, preservation mixture,
held-out examples and quality comparisons in [FULL_FT.md](FULL_FT.md) be frozen.
