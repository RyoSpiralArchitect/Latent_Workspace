# Publication validation, not a model-quality result

2026-10-13, local publication checkout. 507 selected tests passed in 11.96 s.
Four pytest warnings concern negative-control `record_property` under xunit2;
no tests failed, errored or skipped. The sealed 71-case qualification uses
xunit1 and retains those properties. The full regression XML is
[REGRESSION_TESTS.xml](validation/REGRESSION_TESTS.xml).

The selected command was:

```sh
.venv/bin/python -m pytest -q --tb=short \
  --junitxml=/tmp/latent-readout-review.4kbF9M/validation/REGRESSION_TESTS.xml \
  tests/test_training_readout.py tests/test_adapter_native_learner.py \
  tests/test_source_sealed_launcher.py tests/test_readout_adapters.py \
  tests/test_readout_adapter_receipts.py tests/test_v15_native_learner.py \
  tests/test_v15_native_runner.py tests/test_v15_reader_factors.py \
  tests/test_v15_reader_modulation.py tests/test_v15_full_update.py \
  tests/test_v15_readout.py tests/test_v15_pipeline.py tests/test_v15_5_learner.py \
  tests/test_precision_bridge.py tests/test_reader_query.py \
  tests/test_v15_5_native_answer_runner.py tests/test_v14_model_binding.py \
  provenance/pilots/v15_reader_factors_20261010/test_receipts.py \
  provenance/pilots/v15_native_learner_20261010/test_publication.py \
  tests/test_adapter_owner_receipts.py
```

Ruff passed for the four new implementation modules, qualification and offline
verification scripts, and their three new test modules. `git diff --check`
passed. The 299 execution-source hashes are replayed without rewriting the
seal. This publication helper and its nine tests were added after execution;
they are not described as pre-run qualification.

The following pre-existing offline validations also passed in this publication
checkout, without loading models or making judge calls:

| Offline verifier | Preserved result |
|---|---|
| `summarize_v15_readout_adapters.py` | 192/192 native outputs, 64 pairs, 16 affected; semantic gate unchanged |
| `verify_v15_native_learner.py` | Both phases' engineering receipts; 576 evaluation rows and 80 sequences each |
| `v15_native_learner_20261010/check_publication.py` | 8 selected claims, 3 literal excerpts, 243 links and 8 retained-checkpoint receipts |
| `verify_v15_cue_confirmation.py` | Original expression FAIL and complete stored parity accounting |
| `verify_v15_5_native_answer.py` | 576 rows, 80 sequences; expression FAIL and non-regression NOT_ESTABLISHED |
| `summarize_v15_reader_factors.py` | 303 source files and 8 raw files; bounded scalar receipt replay |
| `continue_v15_5_diagnostic_judge.py verify-analysis` | INCOMPLETE_OR_CALIBRATION_BLOCKED; original 1,042 files unchanged |

The last replay retains 374 valid study-plus-repeat Mistral outcomes, one
invalid, eight unknown and 161 undispatched coordinates. OpenAI remains
calibration-blocked; this work does not request any recovery. The historical
literal outputs, missingness, source seals, model weights and gate definitions
are not modified.

These are stored-evidence and implementation checks. They do not independently
recompute old 7B forwards or judge outputs, qualify CUDA, establish useful
content learning, or show a base correctness floor.
