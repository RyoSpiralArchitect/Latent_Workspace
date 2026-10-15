# Post-seal CPU test portability finding

This addendum preserves the sealed experiment, plans, tests and 62-file artifact
index at evidence commit `d260019def96cb40b7816176f3eed62b1aba7792` unchanged.
It does not rerun training, select a new result, or widen an experiment tolerance.

## Validation outcomes are separate

- Local selected suite: **75 passed** (Python 3.13.13 / Torch 2.11.0).
- Furnace selected suite: **74 passed, 1 failed** (Python 3.14.4 / Torch 2.13.0+cu132,
  CPU tests with `OMP_NUM_THREADS=2`). This is not a fully passing remote suite.
- Formal evidence verifier: **PASS** locally and on Furnace, including the latter's
  SHA-256 and size check of all four old and four new checkpoint bodies.
- Scientific result remains **winner: none**. Test portability does not change that result.

The failed test is
`tests/test_bridge_mechanistic.py::test_collapsed_memory_removes_query_dependence_and_centered_value_path`.
It requires exact zero after a **manual projected-V centering intervention** on a toy
FP32 fixture. A later assertion also requires exact zero within-slot RMS.
This is not a failure of the new centered reader's production-path unit test.

## Localizing the difference

An independent CPU diagnostic on the unchanged failing fixture found:

| Stage | Maximum absolute difference |
|---|---:|
| Identical source slots | 0 |
| Normalized-memory slots | 0 |
| FP32 projected V slots | 5.960464477539063e-8 |
| Centered FP32 V | 5.960464477539063e-8 |
| Centered existing V using FP64 reduction | 2.9802322387695312e-8 |
| V slots projected in FP64 from the same normalized inputs and weights | 0 |
| Final bounded centered residual | 9.776966791719133e-9 |

The V projection already introduces row-dependent floating-point differences despite
identical input rows; changing only the subsequent mean reduction to FP64 does not remove
them. Thus algebraic cancellation does not imply bitwise zero in this diagnostic path.
The slot RMS was 2.2480485029063857e-8 and 12 residual elements were nonzero.

The additive [diagnostic script](../../../scripts/diagnose_v14_mech_roundoff.py)
reports the actual fixture values and a dimension-derived FP32 dot-product error bound.
Its output is saved in `roundoff_furnace.json`; `VALIDATION.json` binds these post-seal
files separately from the unchanged original artifact index.

No failed assertion is marked xfail or skipped. No old test is rewritten to make this
run green. A future test-contract revision should distinguish mathematical zero from
operation-bounded floating-point zero, address both assertions, and retain this failure
receipt. Such a revision is still pending. The experiment's fixed `1e-5` reconstruction
and identity gates were not relaxed and passed as originally specified.
