# V23 preservation comparison 01 — qualification and live handoff

**472/472 CPU and 472/472 CUDA tests pass**, zero failures/errors/skips.
The 89-row real-model teacher role is complete; canary/replay and the two
comparative FT arms are not completed at this publication snapshot.
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

## Original-host teacher result

At `2026-10-21T19:27:19.841440Z`, teacher completion was verified and the
positive-P canary had started (PID 3690246). The teacher completed 89 rows /
18,727 supervised positions in 57.795876 seconds, without a weight update.
All 89 same-weight eval/train log-probability rows are bitwise equal: maximum
absolute difference and per-row initial mean KL are zero. This is only an
initial-execution sentinel, not evidence of preservation after training.

The private target file is 2,454,592,344 bytes, of which 2,454,585,344 are
tensor payload. SHA256:
`70db3a724404406604c4da62adad8fdb1189f2f3b305f9b53d5d8340d8336eaa`.
Its body is intentionally **not published or locally reverified**. The source-
sealed teacher terminal and owner admission on Furnace bind/validate it; local
offline replay verifies every published teacher file against the terminal
manifest, the omitted-file receipt, source, denominators and sentinel outputs.
The complete public [teacher metadata](furnace/raw/teacher/) contain no source
token arrays. Teacher peak allocation 14,922,329,088 bytes also does not qualify
the subsequent 7B update/save/replay envelope.

Preserve **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
Source/owner engineering qualification is not evidence that P improves
retention, identity transport or free generation. All historical audit and
failed-trial records remain at their original sources.
