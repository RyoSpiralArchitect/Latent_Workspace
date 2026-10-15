# Fresh cue-confirmation verification receipts

Client date: 2026-10-10. GPU source:
`eabd3306d18e097ef69fbb398aa39750db1fd0ef`.

## Before model execution

The initial source `d5fc915` passed 49 new local and 49 remote CPU tests, but
its **real tokenizer-only preflight failed** before any model loading/scoring:

```text
ValueError: Question must end at an unambiguous text boundary
```

The no-cue native template puts `[/INST]` directly after the question mark.
The historical whitespace-only span binder rejected this. Inspection of the
pinned tokenizer showed `[/INST]` is ID 4, present in the added vocabulary and
declared `special=True`, but absent from `all_special_ids=[1,2,0]`.

The assay-local adapter in `scripts/v15_cue_span.py` checks the added token's
special declaration, literal token spelling, entire unmodified prefix IDs,
terminal offset, and complete disjoint question offsets. It inserts no space
and does not change the sealed historical binder, corpus, prompt, or gate.
The correction and nine adversarial boundary tests were committed before
model scoring, producing the GPU source above.

Final selected local regression suite: **625 passed in 40.75 seconds**;
Ruff clean. This includes 58 new tests and 567 existing selected regressions.

```sh
PYTHONPATH=src:scripts .venv/bin/pytest -q \
  tests/test_v15*.py tests/test_run_v15_elicitation.py \
  tests/test_verify_v15_elicitation.py tests/test_run_v15_completion_mass.py \
  tests/test_verify_v15_completion_mass.py tests/test_audit_v15_completion_portability.py \
  tests/test_verify_v15_readout_transport.py tests/test_render_v15_answer_bank.py \
  tests/test_precision_bridge.py tests/test_answer_bank_generation.py \
  tests/test_ft_beta_query_pool_runner.py tests/test_ft_beta_query_pool_eval.py \
  tests/test_verify_ft_beta_query_pool.py tests/test_v14_precision_bridge_eval.py \
  tests/test_run_v14_precision_bridge.py tests/test_run_v14_readout_precision.py
```

On the isolated Furnace worktree, with CUDA hidden, **58 passed in 13.64
seconds**. The pinned real tokenizer preflight then passed **512 prefixes /
2,048 one-token alias paths**, maximum prefix length **121 tokens**. Both
cue-present renderer parity and native no-cue terminal binding passed.

```sh
env CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  HF_HUB_OFFLINE=1 PYTHONPATH=src:scripts python3 -m pytest -q \
  tests/test_v15_cue_confirmation.py
env CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 python3 \
  scripts/run_v15_cue_confirmation.py --tokenizer-preflight
```

These CPU tests include synthetic bundles; they are not evidence of model
quality. No new-generation or learning qualification follows from preflight.

## Completed model execution

The final source ran once to completion after the successful tokenizer preflight
in the isolated Furnace checkout:

```text
/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-pre-v15-cue-20261010
```

The reserved raw directory was `runs/v15_cue_confirmation_20261010`. The run
completed all 512 prefixes, 2,048 alias continuations, and 512 generations in
502.29934676364064 seconds. `REPORT.json` records
`COMPLETED_CUE_CONFIRMATION`, with **primary_expression_gate: FAIL**.
There were zero optimizer updates and no workspace loaded. Source, tokenizer,
and base tensor identity checks passed before/after execution.

Exact forward-accounting receipts:

- ordinary/shared native initial logits: 512 checks;
- shared/historical native scoring: 2,560 checks, including 2,048 alias paths;
- shared/historical native generation: 23,047 checks.

The source-scoring distinction matters: the earlier `d5fc915` failure was a
tokenizer-only preflight, not a second scored model run. Its record is retained
above; no results were discarded to obtain the completed run.

## Portable verification on both hosts

The same frozen verifier passed against the preserved raw bundle on local
Mac Python 3.13.13 and Furnace CPU Python 3.14.4. The latter used
`runs/v15_cue_validation_20261010`, a separate verification bundle, without
modifying the original remote raw directory or rerunning the model.

```sh
PYTHONPATH=src:scripts .venv/bin/python scripts/verify_v15_cue_confirmation.py \
  --bundle provenance/pilots/v15_cue_confirmation_20261010
```

Both hosts returned `VERIFIED_RECEIPTS`, verified 66 source files, and retained
the scientific **FAIL**. The generated files were byte-identical across hosts:

| File | SHA-256 on both hosts |
|---|---|
| `VALIDATION.json` | `aeabf0a8b3ab6bb0badc694112545106b7cd3887e24e09c8640a311f230f2113` |
| `ARTIFACT_INDEX.json` | `fddf4c01085e2be6f6afa25e1397b5e223dfe2aab1beef5d7e5fcffa01cb186a` |

This is cross-host replay of saved scalar/accounting evidence, not independent
model execution or independent code review. Full logits, model state, and
tokenizer binding are not recomputed by the portable verifier.

The prospectively frozen new-run policy uses scalar relative tolerance 1e-12,
absolute tolerance 1e-15, and log-gap absolute tolerance 1e-12. IDs, text, hashes,
categorical predictions, counts, and the categorical-only summary remain exact.
No tolerance was widened after this run. The old completion bundle and its
exact Mac replay failure were not edited.

## Publication cross-check

A separate local calculation, without importing the assay's summary/parser,
reconstructed reachability from each rendered fact graph: all **64/64 labels
and one-/three-hop distances matched**. Whole-output case-folded yes/no plus
EOS parsing independently matched all **512/512** stored validity/correctness
rows. Direct summation of the saved native alias probabilities reproduced the
published choice/completion counts; paired generated-token comparison reproduced
the cue-removal corrections, regressions, and changed-sequence counts.

The answer bank is rendered from all 512 stored outputs, not a selected subset;
its text is checked against the frozen renderer. Verbatim output whitespace is
preserved. These checks support publication accounting, not a new semantic,
quality, non-regression, or training claim.
