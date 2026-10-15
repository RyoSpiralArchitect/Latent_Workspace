# V19: separate norm budgets for the common and workspace routes

2026-10-15. **ATTEMPT 01 STOPPED: `ordered_cap025` complete and
`NOT_ESTABLISHED` (0/256 flips); `final_cap025` stopped by the GPU contention
guard during its held-out evaluation; `ordered_cap100` and the replay not
run.** The workspace route now carries its full budget, but as a
memory-independent shift. See the
[results](../../provenance/pilots/v19_frozen_dual_budget_20261015/README.md).
**Closed by Ryō's decision** (no attempt 02); see the [closeout](CLOSEOUT.md)
and the [V20 scope](../v20/SCOPE.md). Frozen before launch as follows.
Ryō proposed V19 after the
[V18 frozen-backbone diagnostic](../../provenance/pilots/v18_frozen_diagnostic_20261015/README.md):
keep two norms, one for the ordinary (common) read route and one for the
workspace route, so the ordinary route can no longer eat the workspace read
path. The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is
unchanged.

## What changes, and what does not

The V18 reader gave its interaction route `0.25 × (1 − |common| / cap)` of a
shared soft budget. In the V18 diagnostic the common route reached about 0.998
of its 1.0 cap for every real memory by update 128, leaving the interaction
route about 0.0004; with random memory the interaction route did act (about
0.07). The memory-side LayerNorm has no learned parameters, so sharing it
couples nothing; the coupling is the norm budget.

The [V19 reader](../../src/latent_workspace_ft_v10/v19_dual_budget_reader.py)
keeps the common route exactly as before (its own soft cap, 1.0) and bounds the
workspace route by its **own** soft cap, `workspace_cap × raw / sqrt(workspace_cap² + |raw|²)`,
independent of the common output. The total residual stays below
`common_cap + workspace_cap`. Writer, centering, both queries, parameter layout
(20 writer / 6 common / 6 workspace tensors) and initialization order are V18's,
so V19 arms start from tensors identical to the V18 arms.

The [pipeline](../../src/latent_workspace_ft_v10/v19_dual_budget_pipeline.py),
[state guard](../../src/latent_workspace_ft_v10/v19_dual_budget_state.py),
[native owner](../../src/latent_workspace_ft_v10/v19_dual_budget_learner.py) and
[window owner](../../src/latent_workspace_ft_v10/v19_dual_budget_window_learner.py)
are additive V19 versions derived from the sealed V18 code; only the reader
binding, payload formats (`v19-dual-budget-*`) and policy names change. No V18
file is modified, so every V18 seal and runner stays valid on `main`.

[30 tiny tests](../../tests/test_v19_dual_budget.py) cover V18-identical
initialization, a workspace route that keeps its budget (and its gradient)
while the common route is saturated where V18's is exactly zero, exact zero
workspace output for zero output weights and for equal centered slots,
step-zero equality with the V18 pipeline in all three query modes, partition
ownership, and exact serialized next updates and independent window restores
for FP32/BF16, frozen/full and workspace caps 0.25/1.0.

## First V19 experiment: the same frozen diagnostic

[Plan](../../configs/v19/FROZEN_DIAGNOSTIC_PLAN.json),
[runner](../../scripts/run_v19_frozen_diagnostic.py),
[tests](../../tests/test_v19_frozen_diagnostic.py),
[offline verifier](../../scripts/verify_v19_frozen_diagnostic.py).
Everything except the reader repeats the V18 frozen diagnostic: pinned
Mistral-7B frozen, 256 training worlds, four seeded epochs = 512 complete
16-pair windows, V15.5 objective, bridge AdamW 1e-4, dev curve at
0/128/256/384/512 and the held-out 128-world final split at 0/512.

| Arm | Workspace query | Workspace cap |
| --- | --- | ---: |
| `ordered_cap025` | ordered operand difference | 0.25 |
| `final_cap025` | final state | 0.25 |
| `ordered_cap100` | ordered operand difference | 1.0 |

`ordered_cap025` is the pure decoupling test: the same maximum workspace
magnitude V18 allowed, no longer scaled by the common norm. The V18 arms are
the historical coupled-budget comparators and are not rerun.

Endpoints are V18's, unchanged and fixed at update 512 on the final split:
`CONTENT_REACHES_ANSWERS` needs the world-level sign test at p ≤ 0.001, at
least 26/256 donor-directed flips and at least 20 more flips than norm-matched
random memory; `DIRECTIONAL_ONLY` is the sign test alone; otherwise
`NOT_ESTABLISHED`. Two paired comparisons use the V18 rule (≥ 13 more flips and
exact one-sided McNemar p ≤ 0.01): **selection** (`ordered_cap025` vs
`final_cap025`) and **budget dose** (`ordered_cap100` vs `ordered_cap025`).
Zero-memory rows must equal the frozen direct base exactly. No dev selection,
early stopping or threshold change.

The tiny qualification runs both V19 test files (47 cases) on Furnace CPU and
CUDA; the ordered-cap-0.25 arm's step-256 checkpoint must replay window 257
exactly in a fresh interpreter. A dedicated V19 fresh-process owner
qualification is still required before any V19 full update.

## Path to the release goal

If memory content reaches answers here, the next steps are the dedicated V19
owner qualification, a frozen 7B full-update plan with held-out evaluation and
base preservation screens, and only then the conditional Hugging Face beta,
**mistral-7b-instruct-v0.3-LTWS β** ([checklist](../v18/HF_RELEASE.md)). If it
does not, the next bottleneck to test is native visibility (the injected
residual's content component staying below bf16 resolution).
