# Local preflight, before source freeze

- New state-factorial tests: **29/29 PASS** on macOS CPU.
- Selected complete suite: **214/216 PASS, 2 FAIL, 0 errors/skips**; retained
  in [LOCAL_TESTS.xml](LOCAL_TESTS.xml). Both failures are the existing
  `test_fresh_process_owner_replay` FP32/BF16 subprocesses: isolated local
  Python cannot import `typing_extensions` while importing PyTorch. No owner
  replay computation occurred in those two children. No test was omitted or
  dependency environment modified; this is not a complete local pass.
- Architecture invariants: **6/6 PASS**.
- Ruff on the new engine module, runner and tests: PASS after mechanical import
  sorting/formatting. Shell syntax: PASS. Source/document whitespace check:
  PASS; the raw XML retains two trailing-space traceback lines verbatim.

Formal dispatch requires all **216/216 on both CPU and CUDA** on the pinned
Furnace runtime, including those same fresh-process tests. The local limitation
does not relax that gate. All old source files and evidence bundles are intact.
