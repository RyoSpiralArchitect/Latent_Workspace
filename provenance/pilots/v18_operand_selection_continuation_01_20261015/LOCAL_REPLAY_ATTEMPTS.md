# Local cross-runtime replay attempts

2026-10-15 JST. Both controlled studies returned `COMPLETED`. The supplementary
auditor was frozen at `d2752de88b1f908ed5ee52496196853fe9d5cbca` before fitting.
Its first offline replay attempts ran in the Mac checkout, not in the Furnace
execution runtime. Both rejected at the frozen raw-metric exact-equality check:

```text
CPU: ValueError: Raw metric replay mismatch: 17/centered_final/dev/torch.float32
CUDA: ValueError: Raw metric replay mismatch: 17/centered_ordered/dev/torch.float32
```

The supplemental source, import, population and control checks completed before
that rejection. No successful audit receipt was written. This is a verifier
failure, not a new fitting attempt or permission to relax metric comparisons.
The original results and both frozen verifier sources remain unchanged.

Next diagnostic action: replay the exact saved artifacts with the same frozen
auditor in an isolated Furnace checkout and the original execution interpreter.
This performs no model forward or optimizer update. Cross-runtime floating-point
reductions are a hypothesis until the differing keys and same-runtime replay
have been checked.
