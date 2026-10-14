# V18 window/reference qualification — original attempt

2026-10-15. **TERMINAL FAILED**, not a completed engineering qualification.
Both suites passed their tests, but post-test import-source verification failed.
The receipts are retained without rewriting their status.

Execution source: `8d719ef22506ddc4bf174b799135e0bee0f03b4f`,
[557-file source seal](SOURCE_SEAL.json).

| Runtime | Tests passed / planned | Failures / errors / skips | Test time | Total time | Terminal |
| --- | --- | --- | --- | --- | --- |
| Furnace CPU | 310/310 | 0 / 0 / 0 | 81.548 s | 83.843319 s | FAILED |
| Furnace CUDA | 310/310 | 0 / 0 / 0 | 110.322 s | 112.846303 s | FAILED |

Sources: CPU [JUnit](cpu/TESTS.xml), [terminal receipt](cpu/FINISHED.json);
CUDA [JUnit](cuda/TESTS.xml), [terminal receipt](cuda/FINISHED.json).
Each suite includes 85 bank, 59 objective and 166 learner tests. Test completion
is distinct from a valid source/import/terminal qualification. CUDA peak
allocation is **UNKNOWN**: the guard failed before that field was recorded.
The configured ceiling was 4 GiB; this is not a measured peak.

## Failure and preservation

The runner used `getattr(module, '__file__')` on all loaded modules, including
PyTorch's virtual `torch.ops` namespace. Its class-level `_ops.py` attribute
was resolved relative to the checkout and mistaken for a real local file.
Both terminal tracebacks record the same `FileNotFoundError`. No learner test
failed, but the import closure is incomplete and must not be relabelled PASS.

[Failure replay](FAILURE_REPLAY.json) verifies the two manifests, exact JUnit
populations and all 557 source hashes against the original Git commit. A
post-run pre-import check also confirmed the unchanged clean remote checkout;
that check does not retroactively complete the missing imported-module proof.
The separate [114 local runner/verifier tests](LOCAL_RECEIPT_TESTS.xml) passed
before launch, but did not contain this virtual-module regression case.

Both original processes terminated with exit 1; no original trial is resumed.
Ryō explicitly authorized a separately recorded CPU/CUDA recovery after fixing
the guard, with the same 310 selected tests, 4-GiB limit and 900-second deadline.
The fix must distinguish direct real-module metadata from third-party virtual
namespaces without admitting missing/shadowed project source.

No 7B update, real reference capture, new learner generation, judge call, weight
deletion or HF upload occurred. **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remains unchanged.
