# V23 preservation comparison 01 — qualification and live handoff

**472/472 CPU and 472/472 CUDA tests pass**, zero failures/errors/skips.
The new real-model pipeline has started its teacher role; canary/replay and
the two comparative FT arms are not completed at this publication snapshot.
This is not a training-completion or quality report.

Frozen execution source: `b46f04caefcfd596ccde3b0af8fd886d859f11b7`;
769 sealed source files. The [plan](../../../configs/v23/PRESERVATION_FT_01.json)
and [design](../../../docs/v23/PRESERVATION_FT_01.md) fix original-base
initialization, seed 47, unchanged V22 rows/optimizer and 32 updates per arm.
Only preservation KL differs: off=0, on=1. The native owner retains exact
legacy CE handling and adds a separate positive-P v2 checkpoint contract.

| Qualification | Cases | Failures/errors/skips | Seconds | Peak CUDA allocated |
| --- | ---: | --- | ---: | ---: |
| CPU | 472 | 0 / 0 / 0 | 63.414626 | not applicable |
| CUDA | 472 | 0 / 0 / 0 | 73.010434 | 139,254,272 bytes (0.12969 GiB) |

Tests cover four tiny host families, FP32/BF16, tied parameters, recomputation,
independent CE/KL composition, disabled-path parity, actual context/target
validation, corruption before restore publication and fresh-process restart.
The tiny peak is **not a 7B memory estimate**. All eight tests deselected in
the documented local development run execute in each complete Furnace suite.

The raw qualification bundles and source seal are in [furnace/](furnace/).
Offline replay verifies XML denominators, manifests, original Git source bytes,
source/plan identity and resource limits. Reproduce without models or network:

```bash
python3 -B provenance/engineering/v23_preservation_ft01_20261022/verify_qualification.py \
  --root provenance/engineering/v23_preservation_ft01_20261022/furnace --repo .
```

Live observed at `2026-10-21T19:26:15.927189Z`: dispatcher PID 3689226,
teacher PID 3689304. These identifiers are observations, not evergreen liveness
claims. The [handoff](EXECUTION_HANDOFF.md) identifies the exact source/output
and the single no-retry pipeline. The 7B teacher bank is a new 89-row / 18,727-
position train-only reference, not the earlier 12-row diagnostic bank.
After its gate, positive-P two-update/save/fresh-replay must pass before off/on
32-update training. Native Mistral and V22 scientific weights remain untouched.
No further weight deletion, provider/judge calls, new generated sequences,
PR/merge or Hub publication is performed by this pipeline.

Preserve **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
Source/owner engineering qualification is not evidence that P improves
retention, identity transport or free generation. All historical audit and
failed-trial records remain at their original sources.
