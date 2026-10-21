# V23 gradient audit 01 — execution record

Protocol: [GRADIENT_AUDIT_01.md](../../../docs/v23/GRADIENT_AUDIT_01.md).
This is a new no-update run, not a retry/relabeling of preparation 01.

Pre-freeze local checks: [338 cases](LOCAL_TESTS.xml), **336 PASS / 2 FAIL**.
Both failures are the existing fresh-process owner replay tests: the Mac's
isolated Python cannot import `typing_extensions`. No test was excluded and
no global environment was changed. Separate new transport tests pass 28/28;
actual runner/causal target-layout tests pass 6/6. Furnace must pass all 338
CPU and CUDA cases before admitting any model role.

Managed-runtime doctor passed (`ok:true`, no failure codes); the existing
modelopt/transformers compatibility warning was retained, not repaired.
The gradient/cut/owner diagnostic uses the pinned native PyTorch runtime,
not the serving runtime. No API calls or external teacher are planned.

**Execution results not yet recorded.** All later status, failed/absent roles,
resource peaks and exact denominators belong here after terminal verification.
The unchanged ceiling is FAIL / winner:none / non_regression NOT_ESTABLISHED.
