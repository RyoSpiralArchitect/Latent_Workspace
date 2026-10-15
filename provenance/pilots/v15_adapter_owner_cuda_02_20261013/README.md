# Authorized CUDA recovery: tiny update/replay parity passes; review remains open

Execution source: `64171c8e63642024070236ee0f7df22ecd966331`, **unchanged 299-file
source seal and unchanged 71-case test selection**. The fixed execution sequence
began before midnight JST; this CUDA test suite started at **2026-10-14 00:02:06
JST** (its raw timestamp is 2026-10-13 15:02:06 UTC). The directory keeps the
original sequence's date identifier.

## Result

| Attempt | Planned cases | Completed tests | Matched update cells | Valid serialized next-update replay cells |
|---|---:|---|---:|---:|
| Original CPU | 71 | 71 passed | 8/8 | 8/8 |
| Original CUDA environment failure | 71 | 0 collected/executed | 0 observed | 0 observed |
| Authorized CUDA attempt 02 | 71 | **71 passed**, 0 failed/error/skipped | **8/8** | **8/8** |

The [original bundle](../v15_adapter_owner_20261013/README.md) is retained
byte-for-byte, including its initial CUDA failure, then-current README and
derived summary. [ORIGINAL_BUNDLE_INDEX.json](ORIGINAL_BUNDLE_INDEX.json) binds
all 13 original files. This new result supersedes only the current CUDA test
status, not the historical receipts or the model-quality gates.

CUDA wall time was **16.021751103922725 s** (pytest: **13.482 s**). Peak Torch
allocation was **67,697,664 bytes / 64.5615234375 MiB**, below the fixed 6-GiB
allocation ceiling. This is not whole-process/device memory and says nothing
about the new adapter's 7B memory envelope. No competing GPU client was admitted;
the post-run GPU client query was empty.

The eight cells are full/frozen × FP32/BF16 × gradient checkpointing off/on.
Each uses two ordered **two-pair synthetic windows**, with the next window
replayed from immediately serialized window-1 state. They are not real 16-pair
world windows. Readout-only tests include tiny random Mistral/GPT-2/OLMo2/Gemma2;
**Mistral is the only end-to-end context/owner binding tested**. Native weights,
bridge, FP32 masters and optimizer state are compared to the legacy route;
valid resume also compares the saved ownership/metadata/buffers and RNG.

CPU and CUDA each passed the same 71 cases under their own runtime; this is
**not cross-device bitwise equality, 142 independent semantic observations,
universal architecture support, or safe checkpoint behavior for every API use**.

## Same negative control on CUDA

Independent forwards still reproduce scalar loss but change full-update base
gradients on one tiny affected pair. Full per-tensor values are retained in
[TESTS.xml](cuda_attempt02/TESTS.xml).

| CUDA dtype / scope | Different base gradient tensors | Different bridge gradients | Largest absolute element difference |
|---|---:|---:|---:|
| FP32 / full | 20/21 | 0/26 | 2.2351741790771484e-08 |
| BF16 / full | 20/21 | 0/26 | 0.0008544921875 |
| FP32 / frozen | not trainable | 0/26 | 0 |
| BF16 / frozen | not trainable | 0/26 | 0 |

The preregistered CUDA assertion required nonempty base differences for full
updates and no bridge differences; **20 was observed, not imposed after the
run**. CPU had its own fixed count check and different magnitudes. The positive
adapter/update comparisons remained exact. This supports carrying graph-sharing
policy into the arithmetic contract, not a semantic improvement claim.

## Environment repair, explicitly recorded

[The direct human authorization and execution decision](EXECUTION_DECISION.json)
allowed one separate tiny CUDA attempt and dependency preparation. A dedicated
empty Python 3.12 environment was created, but offline installation could not
resolve Torch from the package cache. **No package was installed or changed.**
Rather than modify an unrelated working environment or change versions, the
already verified existing virtual environment was used unchanged from our
isolated checkout. It runs Python **3.12.14**, Torch **2.13.0+cu132**, CUDA **13.2**,
Transformers **5.15.0** and pytest **9.1.1**. The original failed interpreter was
system Python 3.14; runtime identity is therefore different and explicit.

The pre-import guard passed with isolated Python, fresh bytecode cache,
all-untracked checks and 299 matching source hashes. Actual imported project
paths are retained in [FINISHED.json](cuda_attempt02/FINISHED.json). The
interpreter/packages remain separately trusted runtime inputs, not
cryptographically attested by that project-source guard. The existing virtual
environment and all other workloads were left unchanged. There was no automatic
third test attempt or background monitor.

## Review findings are not closed by a passing suite

[The completed PR #12 review](../../../docs/v15/ADAPTER_OWNER_REVIEW_20261014.md)
identified two P2 issues **before this dispatch**: a returned payload can still
alias live CPU state, and a late restore rejection can leave caller-supplied
targets partially mutated. Both are accepted by code inspection and remain
unfixed. The unchanged tests establish ordinary updates and valid serialized
replay; they do not assert retained-payload immutability or rejection atomicity.

PR #12 therefore remains **Draft**. Fixes need a new source identity, targeted
failure-path tests and renewed relevant qualification. The old 299 execution
files and all old result bundles are unchanged; no legacy source was patched to
make this run pass. Rejection by exception alone is not a general fail-closed
guarantee. No new reproducer run or repair is claimed in this publication.

## Verification and next gate

[SUMMARY.json](SUMMARY.json) is derived from raw receipts, not manually scored.
The new offline verifier checks both source seals, all raw hashes, exact test
coordinates/counts, negative-control coverage, imported project paths and scope.
Its nine new tamper/coverage tests plus the original nine offline receipt tests
pass (**18/18**, no model computation). Ruff passes for both new files. The
prior 507-regression pass remains historical evidence for the unchanged source;
it was not rerun or relabeled as CUDA evidence.

```sh
.venv/bin/python scripts/verify_v15_adapter_cuda_recovery.py verify
.venv/bin/python scripts/verify_v15_adapter_owner.py verify
```

The new helper/tests are post-result offline publication code, not part of the
execution seal. [Terminal handoff](EXECUTION_HANDOFF.md) has the exact command
and locations. The [next real-model gate](../../../docs/v15/ADAPTER_7B_MIGRATION_GATE.md)
still requires checkpoint API repairs, a separately frozen 7B comparison and
resource/storage admission. About 44 GB free disk remains below the historical
50-GiB floor even before new full checkpoint writes; no storage threshold is
relaxed and no existing weight is deleted.

**Zero real-model updates, new learner sequences, judge calls or weight
deletions.** Tiny optimizer updates inside the tests did occur. Old **FAIL /
winner:none / non-regression NOT_ESTABLISHED**, all negative results and all
closed judge missingness remain unchanged.
