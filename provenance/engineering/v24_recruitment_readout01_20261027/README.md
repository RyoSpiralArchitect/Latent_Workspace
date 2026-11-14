# V24 FT04 post-training readout 01 — execution record

**Later terminal result:** the run completed all six cells. See the separate
[source-backed result](RESULTS_README.md) and literal [analysis](RESULTS.json).
The preparation and dated launch snapshots below are preserved as historical
records, not the current execution status.

New bounded evaluation of existing weights, authorized by Ryō's continuation
after post-relocation recovery and cache cleanup. No training, new checkpoint,
judge, weight deletion, upload or GitHub push belongs to this run.

See the [frozen protocol](../../../docs/v24/RECRUITMENT_READOUT_01.md) and
[plan](../../../configs/v24/RECRUITMENT_READOUT_01.json). Planned scope is six
checkpoint/runtime-route cells, six previously unexposed development source
groups, 432 fixed traces / 6,960 fixed forwards and 216 free generations capped
at 128 tokens each. Confirmation groups remain unexposed. Old FAIL /
winner:none / non_regression NOT_ESTABLISHED remain unchanged.

## Local implementation checks

- New instrument and runner/reducer tests: **62/62 passed** on Mac CPU.
- Full selected set: **437 passed, 4 failed, 0 skipped of 441**;
  [original JUnit](local/TESTS_CPU.xml). All four failures are existing
  fresh-process replay tests (native owner and preservation owner, FP32/BF16).
  The isolated Mac Python cannot import `typing_extensions` while loading
  PyTorch; no test assertion reached a numerical mismatch. This is **not** a
  full local PASS and these tests were **not** removed from qualification.
- The Mac uses Python 3.13 / torch 2.11 / transformers 4.57.6, not the pinned
  Furnace runtime. Furnace must pass all 441 tests separately on CPU and CUDA,
  with the independent CPU observer, before any real-model call.
- Ruff and shell syntax passed. No historical learner, sampler, data generator,
  numerical precision or old run source was edited.
- Initial tokenizer-only preparation failed before input creation because the
  Mac tokenizer needed the original `tokenizer.model` as well. Copying that
  exact pinned dictionary resolved local preparation without configuration
  edits; `INPUT_REPLAY.json` is still required from the pinned runtime.

## Execution contract

New source checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-readout01-20261027`.

New output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-readout01-20261027`.

Expected original training source remains
`4b69c6b0d604f4947b7075e40430b9b8f113f4ad`. The two final bodies are rehashed
against the copied original save receipts during restoration. Both stay on
Furnace. No off-host tensor backup is claimed.

The new source commit and live state are recorded in `EXECUTION_HANDOFF.md`
after source freeze. Never rerun the launcher, resume a cell, overwrite a
terminal, or change a protocol in place. A failed or missing terminal requires
a separate recovery decision. Use only closed metadata for final replay.

This document records preparation, **not a completed evaluation result**.

## Qualified and started — 2026-10-27 09:25 JST

Pinned-runtime input replay matched exactly. Furnace CPU and CUDA each passed
**441/441 tests, zero skips**, and the independent CPU isolation audit passed.
The complete source/qualification replay is in
[QUALIFICATION_REPLAY.json](QUALIFICATION_REPLAY.json). The guarded real-model
dispatcher then started base; 4/72 free generations and 10 fixed reference
traces were journaled at the last observation. Neither the base nor dispatcher
terminal was present yet. The two FT-model roles are still pending.

[Execution handoff](EXECUTION_HANDOFF.md) records the immutable source, exact
paths, process identities, observation time and no-retry recovery instructions.
No quality comparison is reported before complete terminal replay.
