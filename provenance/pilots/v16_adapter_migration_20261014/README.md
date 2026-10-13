# Real-Mistral adapter migration: preparation

2026-10-14. **PREPARED_NOT_RUN** at this source commit. This bundle will retain
the terminal raw result separately; preparing a runner is not a 7B PASS.

[The frozen design](../../../docs/v16/ADAPTER_MIGRATION.md) compares the unchanged
old learner with the repaired v2 adapter, in frozen/full modes, two complete
windows each plus two adapter replays. Planned total: **8 unique + 2 replay
windows, 160 backward pairs**, zero generated sequences/judge calls/deletions.

[PRELAUNCH_TESTS.xml](PRELAUNCH_TESTS.xml) records **157/157 local CPU tests**:
28 migration/comparator/contract tests, 16 V16 reader-prototype tests,
12 deletion-helper safety tests, 93 checkpoint-v2 tests and eight v2 publication
tests. The migration-specific cases include four two-window FP32/BF16 ×
frozen/full comparisons and two BF16 complete-window serialized replays on a
tiny model. The other test families overlap previous evidence; they are not
157 independent scientific experiments. This ordinary local test run is not
the separately sealed CUDA/7B execution.

The V16 slot-contrast prototype is not used by this migration. All historical
sources and old FAIL / winner:none / non-regression NOT_ESTABLISHED remain.
