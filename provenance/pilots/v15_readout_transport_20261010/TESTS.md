# V15 verification receipt

Client date: 2026-10-10. Commands were executed, not merely proposed.

## Local regression tests

```sh
PYTHONPATH=src:scripts .venv/bin/pytest -q \
  tests/test_v15*.py tests/test_verify_v15_readout_transport.py \
  tests/test_render_v15_answer_bank.py \
  tests/test_precision_bridge.py tests/test_answer_bank_generation.py \
  tests/test_ft_beta_query_pool_runner.py tests/test_ft_beta_query_pool_eval.py \
  tests/test_verify_ft_beta_query_pool.py tests/test_v14_precision_bridge_eval.py \
  tests/test_run_v14_precision_bridge.py tests/test_run_v14_readout_precision.py
```

Result: **321 passed in 4.90 seconds**. This includes 162 V15 implementation
tests, 29 portable-verifier tests, 13 renderer tests, and 117 predecessor tests.
Ruff passed for the V15 modules, runner, summary, verifier, renderer and their tests.
These tests are not scientific quality or generalization evidence.

## Furnace source gate

In the isolated V15 worktree at commit `8e461f0`:

```sh
env CUDA_VISIBLE_DEVICES= PYTHONPATH=src:scripts python3 -m pytest -q \
  tests/test_v15_readout.py tests/test_v15_pipeline.py \
  tests/test_v15_generation.py tests/test_v15_transport_runner.py \
  tests/test_v15_assay_summary.py
```

Result: **162 passed in 26.59 seconds**, with GPU hidden from this test process.

## Real-model assay and portable verification

The pinned CUDA process completed all planned work in 125.72 seconds. Source,
model, checkpoint, and resource identities are in the seven indexed raw files.
No retry, tolerance relaxation, alternate decoding rule, or optimizer step was
used to turn a failed gate into a pass.

```sh
.venv/bin/python scripts/verify_v15_readout_transport.py \
  --bundle provenance/pilots/v15_readout_transport_20261010 \
  --write-index --output provenance/pilots/v15_readout_transport_20261010/SUMMARY.json
```

This exclusively created the index and derived summary after validation.
A separate `verify_bundle` call without index creation returned
`VERIFIED_RECEIPTS` and exactly matched the saved summary. Source checks include
the sealed predecessor bundle. See `VALIDATION.json` for file digests and scope.
Full logits, gradient tensors, checkpoint bodies, and tokenizer decoding are
not replayed by the portable verifier.

The answer-bank renderer's separate `--check` returned `MATCHED`, with all
64 answers in eight groups. It rechecks the indexed raw bundle and saved scalar
summary before comparing the entire Markdown rendering. No answer is shortened
or relabeled. Its unit tests also exercise output collisions and tampering.

An independent source/receipt review found no blocking inference bug. It
identified the original-order content/serialization confound, now explicitly
documented in the result README and derived summary without changing raw data.
