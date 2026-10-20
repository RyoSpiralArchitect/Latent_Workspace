# Native full-update ownership

2026-10-20. Engineering contract for the post-beta native-memory graph.
This is not a new adapter, a preservation guarantee or a dispatchable 7B recipe.

## Ownership and arithmetic

[`NativeFullUpdateOwner`](../../src/latent_workspace/native_owner.py) owns one
`NativeMemoryCausalLM` and **all** its native physical parameters. Tied embedding
and head references are one parameter and one optimizer update. Distinct
Parameter objects sharing storage are rejected. Hosts must be FP32 or BF16 on
one CPU/CUDA device and must not have frozen parameters or pre-existing gradients.

The CPU gradient transport, complete-window primitive and checkpoint utilities
are verbatim promotions, pinned in [PROMOTIONS.json](../../configs/architecture/PROMOTIONS.json).
No living-engine import reaches the frozen historical package. The optimizer
retains the historical native-family FP32 CPU Adafactor recipe: absolute
learning rate, no relative step, no parameter scaling or warmup, no first
moment, `(1e-30, 1e-3)` epsilon, clip threshold 1 and decay rate -0.8. Clipping
uses one declared native-family norm limit. The new owner changes the parameter
partition and objective, not that arithmetic.

Before each window, declare **ordered unique row keys and positive supervised
token counts**. Each row's summed answer-token NLL is divided by the total
declared window token count before backward; this is not a mean of unequal
microbatch means. Every physical gradient must be present and finite. Ordered
native-dtype accumulation occurs on CPU; CUDA uses the existing pinned-copy
and synchronization path. No optimizer step occurs before the entire window
is complete. CPU FP32 masters are updated and cast/copied back to native
weights, with per-parameter master changes and native changed-element counts.
This makes a BF16 no-op visible without declaring every nonzero change useful.

## Checkpoints and failure semantics

Only clean completed-window boundaries are saved. The checkpoint binds source
commit, original-base content hash, frozen data hash, objective, cut/position/
cache contract, model configuration and module modes, checkpointing policy,
native schema/aliases, optimizer settings/state, ordered window history,
completed step/token counts, CPU masters, buffers and Python/NumPy/Torch RNG.
The initialized target must match the pinned original base. A saved snapshot
owns independent CPU tensors and metadata; it never aliases the live owner.
File creation is exclusive and returns file and structured-state hashes.

Restore validates content receipt, complete schema, provenance, execution,
parameter ownership, buffers, optimizer state and cursor/RNG before publishing
native casts or global RNG. A projected native-state hash avoids allocating
another full model merely to verify casts. Invalid-payload tests also recompute
the outer receipt to prove rejection is not just a checksum check.

The model and process RNG require exclusive ownership. A device/process failure
during publication is **not** an atomic transaction. Failed forward/backward/
update poisons the owner; recovery requires a fresh pinned model and a recorded
checkpoint. No in-place retry is performed. Out-of-band native updates,
mode/policy changes and altered recorded cursor/history/buffers are rejected.
This is not an adversarial sandbox against deliberate `.data` manipulation.

## Qualification boundary

The selected suite covers small initialized Mistral, OLMo2, GPT-2 and scratch
hosts, FP32/BF16, all-parameter reachability, tied weights, empty-memory parity,
padding, causal full-vocabulary labels, activation-checkpoint backward, exact
historical native-family updates, invalid restore, and fresh-process owner
replay. Graph-only ordinary CPU AdamW replay remains a separate test; even in
the CUDA suite not every graph test executes on CUDA. The owner/transport tests
select `LTWS_TEST_DEVICE`; fresh-process owner replay runs both dtypes on that
device with isolated imports. The 4-GiB CUDA cap is per process, including those
children, not a measured whole-machine memory bound.

Run [`qualify_native_owner.py`](../../scripts/qualify_native_owner.py) only on a
clean frozen source with a seal and fresh output directory. Its only exposed
commands are `prepare-seal` and `qualify`; no training role exists. Each device
must finish all 189 selected tests with no failures/errors/skips within 900
seconds. CPU precedes CUDA. Preserve any incomplete attempt; do not silently
rerun it. Fifteen additional local tests reject fabricated/altered evidence.
[`verify_native_owner_qualification.py`](../../scripts/verify_native_owner_qualification.py)
replays Git source completeness/hashes, device manifests, literal XML counts,
resource envelopes and claim ceilings offline, without model code.

The generic execution receipt's `native_weight_updates=0` and
`real_model_updates=0` refer to **pretrained-model/experiment updates**: the tiny
tests deliberately update randomly initialized parameters. A tiny engineering
PASS establishes no 7B capacity, semantic gain, original-base preservation or
release readiness. The old expression gate remains `FAIL`, winner `none`, and
non-regression `NOT_ESTABLISHED`.
