# V22 full-FT 01: long updates pass; replay stops on reserved CUDA memory

2026-10-21. **Terminal `INCOMPLETE_NO_RETRY`; V22 training was not dispatched.**
This is a retained engineering failure, not a failed quality benchmark and not
completed full training. Neither the old expression gate nor the numerical or
resource limits were relaxed.

Execution source: `3c6da4218526cbaaf4690efe6910a2dc493d004b`,
[`SOURCE_SEAL.json`](furnace/SOURCE_SEAL.json), **717 source files**.
[Frozen plan](../../../docs/v22/FULL_FT_01.md),
[data preparation](../../data/v22_english_mixture01_20261021/README.md), and
[terminal dispatch receipt](furnace/raw/FINISHED.json).
The dispatcher exited after 698.657 seconds; no later role or automatic retry
was launched. Both `DISPATCH_train_a.json` and `DISPATCH_train_b.json` are absent.

## Established and unestablished gates

| Gate | Planned | Observed |
| --- | ---: | --- |
| Furnace CPU qualification | 290 tests | 290 passed, zero failures/errors/skips |
| Furnace CUDA qualification | 290 tests | 290 passed, zero failures/errors/skips |
| Long mixed canary updates | 2 | 2 completed |
| Canary backward rows | 9 occurrences | 9 completed |
| Canary checkpoint | step 1 | saved and independently rehashed |
| Fresh-process restore of step 1 | exact | exact full state/RNG fingerprint match |
| Replay backward rows | 5 | first row completed; later four not reached |
| Replay step-2 update/payload equality | exact | **NOT_ESTABLISHED**, resource stop before update |
| Training updates | 32 | **UNDISPATCHED** |
| Training rows / supervised tokens | 723 / 20,860 | **UNDISPATCHED** |
| Training checkpoints / development forwards | 2 / 80 | **UNDISPATCHED** |

The generic failed replay/dispatch receipts retain
`native_weight_updates: null`, not a fabricated zero. There are two confirmed
canary update receipts. Source/trace inspection shows the replay stopped after
its first backward row and before its `owner.step()` call; restoration itself
is not an extra learned update. The planned 35 physical executions / 737
backward occurrences must not be reported as completed.

CPU/CUDA qualification wrappers took **50.912 / 53.542 seconds**; literal
pytest times were 47.77 / 50.02 seconds. The CUDA qualification parent peak was
132.803 MiB, distinct from the real-model peaks below. The prior local Mac
isolated-child dependency failures remain in the data validation record and
were not excluded from the 290-case Furnace gate.

## Long actual updates and checkpoint

Both named original-weight hashes matched in both real-model processes.
All 7,248,023,552 native parameter elements / 291 physical tensors remained
optimizer-owned. The canary used complete 1,024-token instruction and 993-token
code examples, world memory through 78 tokens, and no-memory/irrelevance
controls. It did not test every possible 128-memory/1,024-query combination.

| Canary step | Window targets | CPU-master tensors changed | Native BF16 tensors changed | Native elements changed |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1,128 | 291/291 | 237/291 | 123,643,325 |
| 2 | 1,128 | 291/291 | 238/291 | 161,078,127 |

Element changes are within-step counts, not disjoint totals. These are
engineering updates on a separate condition, never inherited by training.
The canary completed in **522.885 seconds** with peak CUDA allocated/reserved
**27.751 / 29.324 GiB** and peak host RSS **86.821 GiB**.
See [step 1](furnace/raw/canary/step1.json),
[step 2](furnace/raw/canary/step2.json), and
[canary terminal](furnace/raw/canary/FINISHED.json).

The sole retained checkpoint has **29,004,378,380 bytes (27.0124 GiB)**:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft01-20261021/checkpoints/canary_step1.pt`.
Its SHA-256 is
`278466e8a5c2b763f4ebae94ae05577e7d8ffae459bf81692c21615078bb2aaf`.
The post-terminal `sha256sum` matched the original
[save receipt](furnace/raw/canary/CHECKPOINT_canary_step1.pt.json).
The body stays on Furnace; Git metadata cannot reconstruct it if later deleted.

## Failure localization

[RESTORE.json](furnace/raw/replay/RESTORE.json) records a successful exact
step-1 restore. The first repeated code row (982 supervised tokens) then has
**exactly equal receipt values** to its original canary execution:
loss sum `252.60910034179688`, scaled loss `0.22394423186779022`, and accumulated
gradient SHA-256
`29175c6d9a69b8cde2e758ee0c094bd498e657b7ebe5dc55c0e720b8eb0f7f78`.
Compare [original row](furnace/raw/canary/step2_row0.json) with
[replayed row](furnace/raw/replay/step2_row0.json). This is one-row equivalence,
not completion of the five-row update or its final optimizer state.

Immediately afterward the resource guard aborted at
`step2:row0:spilled`:

| Measurement at the failed sampled boundary | Value |
| --- | ---: |
| Device free memory | **440 MiB** |
| Unchanged minimum free requirement | **768 MiB** |
| Torch allocated memory | 13.563 GiB |
| Torch reserved memory | 30.219 GiB |
| Reserved minus allocated | **16.656 GiB** |
| Peak allocated / reserved so far | 27.750 / 30.219 GiB |
| Competing GPU clients | 0; only the run's own child |

[Resource samples](furnace/raw/replay/RESOURCES.jsonl) and
[failure traceback](furnace/raw/replay/FINISHED.json) distinguish this from
an observed CUDA allocation exception, identity mismatch, NaN loss or failed
restoration. The replay's maximum live allocation was essentially the canary's,
but its allocator reservation was larger. Unused reservation is evidence for
a cache-lifetime/allocator-layout issue; the exact allocator mechanism and a
successful remedy remain **UNVERIFIED**. Not all unused reservation is assumed
immediately reclaimable.

The current harness has no explicit unused-cache release at completed CPU
spill or restore boundaries. The proposed next change is a measured,
synchronized release there, with tests proving no live tensor/parameter,
gradient, optimizer, RNG, ordering or arithmetic change. Keep the same 30.5-GiB
allocator cap and 768-MiB free floor, and require a new source/separate trial.
No `empty_cache` remedy was silently applied to this run.

## Verification, storage and recovery decision

The copied terminal bundle has **42 files / 842,396 bytes**. Offline verification
checked the 717-file committed source, both qualification manifests/XML,
the frozen data index/schedule, completed canary updates, terminal manifests
and unchanged claim ceilings. It returns `OFFLINE_V22_PARTIAL_OR_FAILED`.
The verifier makes zero model calls; that is not a statement that this trial
made zero forwards. Eleven additional local publication/checkpoint-helper checks
passed; these are not extra Furnace qualification cases.

After termination the worker had exited, no GPU compute process remained,
and the execution worktree was clean. Available disk was **127,762,071,552
bytes (about 119 GiB)**. A new three-save trial plus the 50-GiB floor requires
134 GiB, so a full identical repeat would not currently pass storage admission.
Ryō has been asked separately to authorize (1) the cache-boundary correction,
tests and a fresh trial, and (2) retirement of **only this failed trial's
canary step-1 body**, after a new replay passes and after a hash/ledger record,
to make room for the training saves. Neither action has happened in this record.
Original Mistral, all other checkpoints and both parent banks remain untouched.

This run leaves **FAIL / winner:none / non_regression NOT_ESTABLISHED** unchanged.
No V22 learner generation, teacher generation, paid judge, benchmark result,
weight deletion, beta replacement, PR merge or HF publication occurred.
See [the terminal handoff](EXECUTION_HANDOFF.md) before any continuation.
