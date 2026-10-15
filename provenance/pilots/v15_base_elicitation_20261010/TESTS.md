# Pre-V15 learning: elicitation verification receipts

Client date: 2026-10-10. Assay source:
`9983e42d082a9452feedc60bb0b72d0b810795b8`.
The protocol, corpus generator, renderer, runner and portable verifier were
committed before GPU scoring. No new training is part of this unit.

## Local tests

```sh
PYTHONPATH=src:scripts .venv/bin/pytest -q \
  tests/test_v15*.py tests/test_run_v15_elicitation.py \
  tests/test_verify_v15_elicitation.py tests/test_verify_v15_readout_transport.py \
  tests/test_render_v15_answer_bank.py tests/test_precision_bridge.py \
  tests/test_answer_bank_generation.py tests/test_ft_beta_query_pool_runner.py \
  tests/test_ft_beta_query_pool_eval.py tests/test_verify_ft_beta_query_pool.py \
  tests/test_v14_precision_bridge_eval.py tests/test_run_v14_precision_bridge.py \
  tests/test_run_v14_readout_precision.py
```

**456 passed in 10.30 seconds.** The 135 new tests cover input/corpus generation
(34), the runner (52), and summary/portable verification (49). The other 321
are existing selected native-readout, generation, and predecessor regressions.
The three new scripts and their tests also passed Ruff.

Tests cover frozen-plan mutations, complete row grids, historical replay,
same-content renderer binding, source/tokenizer identity, no-workspace native
readout, EOS and whole-answer parsing, paired uniforms, resource accounting,
label-specific and reciprocal-pair metrics, and exclusive artifact creation.
Test success is not real-model quality evidence.

## Furnace preflight

The isolated worktree was checked out at the above source commit. With CUDA
hidden, the same three new test files passed: **135 passed in 5.03 seconds**.
The pinned real tokenizer preflight then passed all **144 prefixes**, maximum
length **121 tokens**, without a model forward or any answer-based selection.

```sh
env CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  HF_HUB_OFFLINE=1 PYTHONPATH=src:scripts python3 -m pytest -q \
  tests/test_run_v15_elicitation.py tests/test_v15_elicitation_inputs.py \
  tests/test_verify_v15_elicitation.py
env CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 python3 \
  scripts/run_v15_elicitation.py --tokenizer-preflight
```

The tokenizer check verified anchored metadata files, active template identity,
raw/native template tokenization agreement, exact one-token suffixes, and
untruncated question-span bindings. Real-model run and outcome receipts are
separate from these tests.

## Completed run and portable audit

All 144 prefixes / 288 sequences completed on the first formal GPU run at the
frozen source. The 16 historical raw sequences replayed exactly. The model,
source, and anchored tokenizer files were unchanged. The run's expression gate
failed; mechanical success is not scientific qualification.

The portable verifier sealed the raw artifact index and recomputed
`VALIDATION.json` and the full `ANSWER_BANK.md`. An independent read-only audit
reproduced both files exactly, checked all 47 source hashes and all 7 tokenizer
metadata anchors, and inspected the 32 primary outputs. See `README.md` for the
outcome and resource measurements.
