# V18 selection native owner: local engineering checks

2026-10-15. The additive `SelectionNativeLearner` implements an explicit
split-query native state owner. It does not yet provide a selection-aware
complete-window envelope, source-isolated CUDA qualification or real 7B FT.
The [owner plan](../../../docs/v18/SELECTION_OWNER_PLAN.md) separates these gates.

The source and focused tests were frozen before the root combined check:

| File | SHA-256 |
| --- | --- |
| `src/latent_workspace_ft_v10/v18_selection_learner.py` | `f62bb0bf1b9a9764042d6d924e3f03624b635548f67e70faf7c9f2d75a1afb93` |
| `tests/test_v18_selection_learner.py` | `6a3746d4674c73633e21e712b9ca2cb809776fe6d865e73ab2696cc3600f3da9` |

The author's stable focused run passed 150/150 tests in 84.59 seconds with Ruff
passing. These are tiny local CPU tests, not 150 independent experiments. They
include FP32/BF16, frozen/full updates, three query modes and raw/centered reader
factors, exact same-process next-window replay, rejected malformed restores,
layout/storage ownership and preservation of historical V15/V2 arithmetic.
Production ownership is all 32 bridge tensors; this is distinct from the six
trainable tensors in the preceding diagnostic's historical toy policy.

The initial development run ended with 138 passes and one test-source inspection
assertion failure after source lines changed while that interpreter was alive.
It was replaced before freezing with a direct check that restoration delegates
to the unchanged V2 publication path. No numerical tolerance or guard was relaxed.

The separate strengthened fresh-process test passed **10/10 in 94.50 seconds**,
using 20 independent CPU interpreters. Its frozen source SHA-256 is
`20f418783835b88e4d975fa1f7daae7e3dd899e07068b356828b1309de165c03` for
`tests/test_v18_selection_fresh_process.py`. Eight cases cover ordered-query
FP32/BF16 × frozen/full × raw/centered; two cover BF16/full/centered final and
symmetric queries. This is not a full all-mode factorial matrix. Each producer
saves window 1 and computes window 2; a new interpreter rebuilds the independent
expected policy/contract, loads with `weights_only=True`, challenges the ambient
RNG, then reproduces window 2. All update receipts, per-field/full payload hashes,
owned state and Python/NumPy/Torch RNG continuation match exactly. Saved window-1
bytes and payload remain unchanged. Children pin dependency origins/versions,
use two threads, offline settings, and a 60-second timeout each.
The [metadata manifest](fresh_process/MANIFEST.json) binds all 30 case/process
JSON files, and the separate [offline consistency audit](FRESH_PROCESS_AUDIT.json)
rehashed them and matched all ten receipt pairs without any forwards. It does
not replay tensor checkpoints, which are not included. These ordinary local
unit tests are not a source-isolated Furnace launch: child receipts do not
embed the test-source hash or a pre-import source seal.

A preliminary system-interpreter attempt failed preparation-version admission
before any update or resumer. A subsequent qualified run passed 10/10 in 71.51 s;
the stronger dependency-identity version above passed again in 94.50 s. These
are iterations of the same ten tests, not twenty independent cases. No runtime
gate was relaxed. Final case and producer/resumer receipts are retained without
the temporary toy checkpoint bodies; hashes are not a checkpoint backup.

## Root combined regression

The frozen-source combined run passed **769/769 in 670.64 seconds**, with zero
failures, errors or skips. This includes the 150 native-owner cases above and
existing state/pipeline, V16/V2 owner, window, writer, numerical-diagnostic and
retirement tests. These are overlapping engineering checks, not additional
scientific samples. The ten fresh-process tests were run separately, not inside
this combined command. Ruff passes for the three new source/test files; all
three source hashes still match after completion.

[LOCAL_CHECKS.json](LOCAL_CHECKS.json) records the command and claims;
[LOCAL_TESTS.xml](LOCAL_TESTS.xml) retains all 769 case results. Its SHA-256 is
`105bf560835e8d78846015038064c6b4d9f574c70a0fae300cc15580cf4515b6`.
The XML suite duration is 670.633 s; pytest's displayed total is 670.64 s.

```sh
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python -m pytest -q \
  tests/test_v18_selection_learner.py \
  tests/test_v18_selection_state.py \
  tests/test_v18_selection_pipeline.py \
  tests/test_slot_contrast_learner.py \
  tests/test_adapter_native_learner_v2.py \
  tests/test_v18_window_learner.py \
  tests/test_v18_controlled_writer.py \
  tests/test_diagnose_v18_replay_flags.py \
  tests/test_retire_v16_engineering_checkpoints.py \
  --junitxml=provenance/pilots/v18_selection_owner_local_20261015/LOCAL_TESTS.xml
```

Next is a separately versioned selection-aware window owner, followed by its
source-isolated Furnace qualification and newly budgeted native admission. The
actual-writer study and historical permutation failures remain separate gates.
No CUDA qualification, 7B update, benchmark, generation, paid judge or
HF upload is claimed here. Old **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remains unchanged.
