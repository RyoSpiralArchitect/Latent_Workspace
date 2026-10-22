# V23 local terminal-publication checks

This folder records **local, offline** publication regression tests on 2026-10-22.
It is not a new Furnace trial, model run, benchmark generation or judge request.
[LOCAL_TESTS.xml](LOCAL_TESTS.xml): **128 tests, zero failures/errors/skips**.
See [LOCAL_VALIDATION.md](../../../docs/v23/LOCAL_VALIDATION.md) for the exact
test selection, environment limitation, artifact replay and earlier local-only
collection-name collision. All new helpers use additive paths; sealed execution
sources and original failed trials remain unchanged.

The [MMLU-Pro analysis](../v23_recovered_mmlu_pro02_20261022/analysis/MANIFEST.json)
and [judge analysis](../v23_recovered_behavior_judge01_20261022/analysis/MANIFEST.json)
bind their generated publication files independently of the compute/run seals.
The [review guide](../../../docs/v23/FULL_FT_REVIEW_GUIDE.md) distinguishes
historical GPU qualification, current local checks and still-unestablished
scientific/release claims. No model-weight body is added by this publication.
