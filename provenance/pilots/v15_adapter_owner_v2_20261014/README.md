# Adapter checkpoint v2: two review defects repaired and requalified

2026-10-14. **TINY_CHECKPOINT_V2_REPAIR_PASS_NOT_7B_QUALIFICATION**.
Execution source: `8359635cc443271407763601fc3c619cc79777f4`, with a
[306-file source seal](SOURCE_SEAL.json). See the [mechanism contract](../../../docs/v15/ADAPTER_CHECKPOINT_V2.md).
The original 299 execution files and the old CPU/CUDA failure and recovery
bundles remain byte-for-byte unchanged. Their review-open summaries remain
historical, not retrospectively relabelled as repaired runs.

| Runtime | Passed / planned | v2 matched updates | v2 next-update replay | Non-mutating rejection cases | Elapsed |
|---|---:|---:|---:|---:|---:|
| Local CPU | 164 / 164 | 8 / 8 | 8 / 8 | 65 / 65 | 30.90 s |
| Furnace CUDA | 164 / 164 | 8 / 8 | 8 / 8 | 65 / 65 | 43.99 s |

No failures, errors or skips. Each runtime runs the unchanged historical 71
cases plus 93 v2 cases. The old conditions in the historical suite are not
additional independent v2 conditions. Raw [CPU](raw/cpu/FINISHED.json) and
[CUDA](raw/cuda/FINISHED.json) receipts retain runtime, imported project sources,
pre-import guard, source hashes, raw JUnit hashes and complete denominators.
Both launches use isolated Python and fresh bytecode caches in separate clean
execution checkouts. No package installation or shared-environment change was
needed; CUDA used the previously verified dedicated Python environment.

## What is now observed

- Retained payloads remain unchanged across further updates and caller metadata
  edits; payload edits cannot change live tensors, optimizer state or metadata.
- Both full and frozen owners reject incompatible provenance, schemas, aliases,
  completed steps, current-base hashes, optimizer policies/moments and RNG before
  target/global RNG writes. Tests check values, object/storage identities,
  tensor versions and binding guards; the target remains usable after rejection.
- Eight full/frozen × FP32/BF16 × checkpointing conditions match unchanged
  two-window update math and valid serialized next-update replay.
- Two negative controls per runtime reproduce the historical v1 defects:
  a retained payload changes after an update; a late optimizer-policy rejection
  changes the supplied target. These are expected controls, not failed v2 tests.

The 65 rejection cases are 60 general full/frozen cases and five additional
malformed base-optimizer cases. Snapshot/buffer tests also cover persistent
and nonpersistent native buffers, nested metadata and nonleaf metadata tensors.
The GPU path stages an independent CPU snapshot, not an alias to CPU masters.

CUDA peak **Torch allocated** memory was 67,697,664 bytes (64.56 MiB), below the
frozen 6-GiB cap. This is not total process/device or host memory and not a 7B
forecast. CPU used Python 3.13.13 / Torch 2.13.0; CUDA used Python 3.12.14 /
Torch 2.13.0+cu132 (CUDA 13.2); both used Transformers 5.15.0 / pytest 9.1.1.
These are within-runtime equivalence results, not CPU/CUDA numerical identity.

An additional selected local regression run passed **609/609** cases, with
[JUnit output](REGRESSIONS.xml). It overlaps the qualification suite and is not
609 extra independent mechanism observations. The source-sealed CPU/CUDA runs,
not this ordinary local regression invocation, establish isolated execution.

## Replay and claim boundary

Run `scripts/verify_v15_adapter_owner_v2.py verify` for offline replay of the
[summary](SUMMARY.json), [artifact index](ARTIFACT_INDEX.json), exact test
coordinates, both source seals and original failure/recovery evidence.
This performs no model computation or API call. The publication verifier and
its mutation tests are post-execution tools, not additions to the execution seal.

V2 repairs **validation-failure** atomicity under exclusive ownership. It does
not promise recovery from process/device failure during final publication or
concurrent mutation. It does not silently accept the defective v1 format.

Real 16-pair-window Mistral migration remains unqualified and storage-gated.
The new snapshot's host-memory cost must also be admitted at 7B. No real-model
updates, new sequences, judges, weight deletions or merge occurred. Old
**FAIL / winner:none / non-regression NOT_ESTABLISHED** remains unchanged.
