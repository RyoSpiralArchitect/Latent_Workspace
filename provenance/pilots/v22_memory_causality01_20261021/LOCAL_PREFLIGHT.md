# Local development preflight (not Furnace qualification)

The 29 new causal-probe tests passed on macOS CPU in 5.77 s. The broader
selected invocation completed **185 passed / 2 failed / 187 total** in 28.65 s.
Both failures were existing `test_fresh_process_owner_replay` cases (float32
and bfloat16): the isolated `-I` Python process could not import
`typing_extensions` while importing torch, before model computation.

Interpreter: `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`;
torch 2.11.0, transformers 4.57.6. The error is retained, not called a pass.
No package, test exclusion or fallback was applied. The planned Furnace run
must independently pass **all 187 cases** on CPU and CUDA in its pinned
Python 3.12.14 / torch 2.13.0+cu132 / transformers 5.15.0 runtime.

Command (from the exact full-FT worktree):

```sh
PYTHONPATH=src LTWS_CPU_SDPA_BACKEND=math LTWS_CPU_MKLDNN_ENABLED=0 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  tests/test_native_memory.py tests/test_native_owner.py \
  tests/test_native_evaluation.py tests/test_native_diagnostics.py \
  tests/test_native_causality.py
```

Ruff passed on the three new Python files. The formal no-retry trial has not
started at this preflight point. This local failure is not a trial restart.
