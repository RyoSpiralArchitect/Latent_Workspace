# V22 base comparison 01 — preparation

Status: inputs not yet sealed; no 7B scoring dispatched.
The [fixed design](../../../docs/v22/BASE_COMPARISON_01.md) and
[plan](../../../configs/v22/BASE_COMPARISON_01.json) specify two fresh-process
weight arms, 570 reused MMLU items, 96 held-out world inputs with two routes,
and 12 free prompts with two sampling seeds. No training or checkpoint saves.

Local development check: 17/17 new evaluation tests passed. The combined
138-test suite passed 136; both isolated owner-replay subprocess tests could
not import `typing_extensions` under local Python 3.13 `-I`. This is not a
passing qualification, and neither test is excluded. The planned independent
Furnace CPU/CUDA qualifications must each pass all 138 in the pinned runtime.
The Mac runtime (torch 2.11.0 / transformers 4.57.6) is not the execution runtime.
No dependencies were installed or changed. Ruff passed for all four new Python files.

Furnace managed-runtime doctor reported `ok: true`, no failure codes, pip
check and frozen-package identity passing. It emitted its existing
transformers/modelopt compatibility warning; no repair was attempted.
The first read-only doctor invocation had an incorrectly quoted command and
did not execute; the documented `spiral run -- spiral-local-llm doctor` succeeded.
The custom native-memory comparison uses the previously qualified PyTorch
runtime for graph/checkpoint compatibility, as described in the design.

Historical gate: **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
