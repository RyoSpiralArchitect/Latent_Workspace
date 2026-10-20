# Native latent-memory graph: local engineering qualification

2026-10-20. **Small-model CPU engineering checks only.** No 7B model was
loaded or trained, no CUDA calculation or provider call was made, and no
weight was deleted. The [full-FT plan](../../../docs/v1_0/FULL_FT.md) separates
these checks from the still-unimplemented production optimizer/restore owner
and the still-unlaunched 7B canary.

## Source and runtime

- Based on `d085344cd448ec9ee27daffa1c1c301b6f4c6bd2` (`origin/main`).
- New files: `src/latent_workspace/native_memory.py` and
  `tests/test_native_memory.py`, with public exports and documentation.
- Local worktree: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`;
  branch `SpiralReality/latent-memory-full-ft`.
- Python 3.13.13, PyTorch 2.13.0, Transformers 5.15.0, macOS 26.2 arm64.
- Tests use newly initialized tiny models, no downloaded model or dataset.
  Two CPU threads. Execution is local development qualification, **not** a
  source-sealed scientific run or CI verification.

The existing `.venv` in the semantic-chat checkout supplied the interpreter;
`PYTHONPATH=src` selected the **new worktree's** source. Commands below use
`python`/`ruff` as shorthand for those executables.

```sh
PYTHONPATH=src python -m pytest \
  tests/test_native_memory.py \
  tests/test_latent_workspace_stack.py \
  tests/test_latent_workspace_package.py \
  tests/test_latent_workspace_ladder.py \
  tests/test_latent_workspace_availability.py \
  tests/test_latent_workspace_execution.py \
  tests/test_architecture_rules.py \
  tests/test_v20_a5_stable_route.py \
  -q --junitxml=provenance/engineering/native_memory_full_ft_20261020/pytest.xml
ruff check src/latent_workspace tests/test_native_memory.py
git diff --check
```

## Coverage and result

**140 passed**, including **64 new graph tests**, with zero skips or expected
failures. Machine-readable test output: [pytest.xml](pytest.xml). Ruff and
`git diff --check` passed. This is the selected suite, not the entire repository
test suite.

- No-memory, zero-width memory and all-padding memory preserve the current
  host's no-cache logits, shifted loss and gradients **bitwise**, across tiny
  Mistral, OLMo2, GPT-2 and ScratchDecoder. Training-mode bypass also preserves
  dropout RNG consumption on the three HF families.
- The memory-bearing forward matches the beta's `CutPrefixRoute` host-only
  computation within the explicit tiny-model numeric comparisons. The full
  vocabulary is retained. Both independent encodings receive nonzero gradient;
  every native parameter has a finite gradient. A separate six-layer Mistral
  test exercises the beta's actual cut index, 4.
- Variable-length padding, a mixed empty-memory batch, query-only shifted
  labels, token-weighted loss and future-token causality are checked. Invalid
  masks, cut choices and labels fail closed. Rotary hosts' cut-0 forward is
  compared with inline tokens; no such equivalence is asserted for absolute
  position hosts.
- BF16 forward/backward is finite on all four tiny hosts. This is **CPU** BF16,
  not a CUDA qualification or a 7B precision result.
- On all three HF families, non-reentrant activation checkpointing in
  training mode produces bitwise-equal loss and gradients to the same
  uncheckpointed tiny graph, including the memory path.
- Two ordinary CPU AdamW updates run on each host. A separate fresh Python
  process restores the first state and repeats the second update in training
  mode, with model, optimizer, loss and RNG matching bitwise. This does **not**
  qualify FP32 CPU masters, gradient offload, atomic restore, complete-window
  ownership or large-checkpoint publication.
- Architecture guards verify the frozen historical package and the 303-file
  V15 legacy source seal remain untouched. Existing engine/promotion/package
  tests also pass. The published beta has not been rebuilt or changed.

## Development correction retained

The initial graph-only run had **44 passed / 3 failed**. All three failures
were the GPT-2 no-memory comparison: the test's native comparator omitted
`use_cache=False` and inherited GPT-2's cache-enabled default, while the graph
explicitly disables cache. The comparator now states the same no-cache policy.
The bitwise assertions were kept, not relaxed. The next graph run passed all
57 cases then present; the final suite adds BF16, cut-0 and cut-4 coverage and
training-mode fresh-process replay. These are development iterations, not
retries of a sealed study.

## Remaining gate

The next implementation is an engine-owned, generic native full-update owner
with the historical CPU-master arithmetic and restore safeguards promoted and
parity-qualified. The live Furnace check also found another GPU workload and
insufficient disk headroom under the old two-checkpoint-plus-floor policy;
see the [resource decision](../../../docs/v1_0/FULL_FT.md#resource-decision-measured-2026-10-20).
No unattended job or monitor was created.
