# PR #12 review: successful replay is narrower than safe checkpoint ownership

The [review of `6f1eb4c3ee`](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/12#pullrequestreview-5505524124)
completed at 2026-10-13 23:55 JST and raised two P2 findings. The subsequent
[tiny CUDA run](../../provenance/pilots/v15_adapter_owner_cuda_02_20261013/README.md)
passed all 71 unchanged cases. These facts are compatible: the cases verify
ordinary updates and **valid, immediately serialized** checkpoint replay, not
all snapshot or failed-restore behavior. Neither finding is closed by that run.

## 1. A returned payload is not yet an independent snapshot

[Finding](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/12#discussion_r4260240884).
`AdapterNativeLearner.payload` calls the sealed parent's `payload`, whose CPU
masters use `detach()` and whose `cpu_tree` does not clone already-CPU tensors.
The child adds some independently copied fields, but the inherited tensor tree
still aliases live state. Retaining it across another update can therefore
change its tensor values while its completed-step metadata stays old. Metadata
containers also need clear ownership. Cloning state on **restore input** does
not fix the **payload output** boundary.

Accepted by code inspection; no repair or new reproduction run is claimed here.
A follow-up should return an independent tensor/container snapshot, and verify
that later learner updates and caller mutation leave each other's state
unchanged. Cover full/frozen CPU, GPU staging, native buffers, master and
optimizer state, and metadata. Measure the extra snapshot memory cost before
a 7B save. Immediate synchronous `save` and its observed next-update equality
remain separate from a general snapshot API guarantee.

## 2. Rejected restore can already have changed the supplied model

[Finding](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/12#discussion_r4260240903).
The current `restore` copies bridge and native master values into the supplied
objects before all optimizer-policy and later validation has finished. The
existing malformed-policy test asserts rejection but does not assert unchanged
target state after rejection. Catching its `ValueError` can leave a caller with
partially restored parameters. A content hash identifies bytes; it does not
make a malformed or incompatible payload safe to apply.

Accepted by code inspection; no repair is claimed. A follow-up needs
validation before mutation or an explicit transaction that exposes new state
only after all checks pass. Include late failures in optimizer state/policy,
current-base identity, bridge schemas and RNG. Assert unchanged target values,
ownership and execution state, caller payload and global RNG after rejection,
not merely an exception. Avoid a hidden second full 7B allocation when designing
the transaction; its resource envelope is an independent gate.

## Disposition

Keep PR #12 **Draft**. Preserve the 299-file execution source and the original
CPU/CUDA failure records; any repair must have a new source identity and new
targeted evidence rather than retrospectively changing the successful run.
The state-owner implementation is opt-in and has not replaced the sealed 7B
runner. These are checkpoint API defects, not evidence that the measured
ordinary-update gradients or immediately saved next-update replay mismatched.

Do not generalize either the 71-case pass or the historical wording "fail
closed" into snapshot immutability or restore atomicity. Old **FAIL / winner:
none / non-regression NOT_ESTABLISHED** and all judge missingness remain.
