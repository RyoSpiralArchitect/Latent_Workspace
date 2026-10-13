# Checkpoint v2: independent snapshots and non-mutating rejection

2026-10-14. Additive repair of the two [PR #12 review findings](ADAPTER_OWNER_REVIEW_20261014.md).
The 299-file execution source and both historical bundles remain unchanged.
Use `AdapterNativeLearnerV2` for new checkpoint work; v1 is retained for replay
and explicit negative controls, not offered as the repaired API.

## Ownership boundaries

`payload()` recursively detaches and **copies** every tensor to CPU and copies
all metadata containers. Retaining a payload across an update is supported;
editing it cannot edit the learner, optimizer, native buffers or caller metadata.
The format is `v15-adapter-native-resume-v2`; v1 checkpoints are not silently
relabelled or accepted. Update, graph-sharing, clipping and optimizer math are
inherited unchanged.

`restore()` has a preparation phase before any caller-owned parameter or global
RNG write. It checks receipt/provenance, native/bridge/buffer schemas, aliases,
original identity, proposed current-base hash, completed step, ordered optimizer
IDs, policies, coverage, moment shapes/dtypes/steps and RNG states. RNG validation
uses private Python, NumPy and Torch generators. Optimizer dictionaries and CPU
masters belong to the prospective new owner, not the input payload. Only after
all validation succeeds are target tensors and process RNG published.

Rejection preserves target values, object/storage identities, tensor version
counters, binding execution guards, the input payload and global RNG. Avoiding
copy-then-rollback matters: rollback can restore bytes while still advancing
version counters. Direct publication avoids `load_state_dict` callbacks.

This is **validation-failure atomicity under exclusive ownership**, not crash or
device-failure atomicity. Concurrent writers, malicious module overrides,
out-of-band `.data` mutation, process termination or a device failure during
the final copies are outside the contract. It is not a sandbox for untrusted
checkpoint objects. Deserialize the expected local artifact with weights-only
loading and verify its separately recorded content receipt.

## Resource accounting is separate

No second native GPU model is built. The proposed current-base hash streams one
CPU parameter cast at a time. A snapshot necessarily adds independent CPU state;
full restore also owns CPU masters and optimizer dictionaries. These host costs,
checkpoint write size and device transfer cost must be measured/admitted at 7B.
Tiny Torch peak allocation is not the host/process/device envelope.

## Qualification contract (execution recorded separately)

The [fixed plan](../../configs/v15/ADAPTER_OWNER_V2_QUALIFICATION_PLAN.json) runs
164 cases per runtime: the historical 71 unchanged plus 93 new cases. New cases
include eight unchanged two-window update cells, eight serialized next-update
replays, 65 malformed restores, snapshot independence, persistent/nonpersistent
buffers, step-zero state and two controls reproducing v1's reviewed defects.
The 60 general rejection cells cover full/frozen ownership; five additional
cells reject malformed base optimizer moments. Rejection cases also check
tensor versions and subsequent usability, not only an exception.

The synthetic windows have two pairs, **not** the real 16-pair world protocol.
CPU/CUDA results are separate per-runtime comparisons, not cross-device bit
equality. The frozen budget is 180 seconds and 6 GiB Torch allocation, with zero
7B updates, generated sequences, judge calls or weight deletions.

Real-Mistral admission and the [V16 handoff](ADAPTER_7B_MIGRATION_GATE.md) remain
separate. Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** remains.
