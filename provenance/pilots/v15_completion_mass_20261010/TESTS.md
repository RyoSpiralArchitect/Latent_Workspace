# Completion-path diagnostic verification receipts

Frozen run source: `012c5172788b333fdc14ca81fbcbe53c10c2e96c`.

## Before GPU execution

Selected local regression suite: **543 passed in 21.36 seconds**; Ruff clean.
This includes 87 new completion tests (12 runner, 42 pure accounting, 33 portable
verifier), plus the previous 456 tests. No model weights or CUDA are needed for
these tests; synthetic bundles are not real-model evidence.

```sh
PYTHONPATH=src:scripts .venv/bin/pytest -q \
  tests/test_v15*.py tests/test_run_v15_elicitation.py \
  tests/test_verify_v15_elicitation.py tests/test_run_v15_completion_mass.py \
  tests/test_verify_v15_completion_mass.py tests/test_verify_v15_readout_transport.py \
  tests/test_render_v15_answer_bank.py tests/test_precision_bridge.py \
  tests/test_answer_bank_generation.py tests/test_ft_beta_query_pool_runner.py \
  tests/test_ft_beta_query_pool_eval.py tests/test_verify_ft_beta_query_pool.py \
  tests/test_v14_precision_bridge_eval.py tests/test_run_v14_precision_bridge.py \
  tests/test_run_v14_readout_precision.py
```

Furnace, with CUDA hidden: **87 passed in 8.66 seconds**. The real tokenizer-only
preflight bound every one of the 144 frozen prefixes and 576 one-token alias
paths, with no model forward or answer-dependent selection.

```sh
env CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  HF_HUB_OFFLINE=1 PYTHONPATH=src:scripts python3 -m pytest -q \
  tests/test_run_v15_completion_mass.py tests/test_v15_completion_mass.py \
  tests/test_verify_v15_completion_mass.py
env CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 python3 \
  scripts/run_v15_completion_mass.py --tokenizer-preflight
```

## Formal execution and verification

The formal GPU scorer completed on its first run in the isolated Furnace
worktree at the frozen source. It used `nice -n 10`, two CPU threads, offline
model loading, the original pinned model, and the unchanged resource contract.
144 exact initial-choice/probability replays and 720 native parity checks passed.

The original verifier initially failed on the Mac with `Completion summary
mismatch`: four one-ULP differences in derived floating probabilities. No plan,
raw receipt, frozen source or tolerance was changed. The same unmodified verifier
then passed on the execution host (CPU only); its sealed index and validation
were copied back byte-for-byte. This is **same-runtime verification**, not a
cross-host exact replay pass. The separate portability audit preserves that
limitation and does not grant an acceptance result.

The additive portability audit has **24 passing CPU tests** and Ruff is clean.
Its saved diagnostic records 7,083 scalar pairs: 7,079 exact, four float-only
one-ULP differences; all 3,855 non-float scalars and every structure/type match.
An independent 80-digit Decimal recomputation confirmed all 144 start/completion
class predictions and checked the 576 recorded path identities and scalar
probabilities, without independently retokenizing them or changing raw receipts.

Final selected local regression rerun, adding
`tests/test_audit_v15_completion_portability.py` to the above command:
**567 passed in 22.77 seconds**. The prior elicitation validation, new raw-file
index, and saved portability audit all reproduce exactly on the Mac; the new
completion strict-verifier failure remains separately recorded as described
above. No CI pass or merge is claimed by these local/remote execution receipts.
