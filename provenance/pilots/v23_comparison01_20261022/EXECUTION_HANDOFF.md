# V23 base/off/on comparison 01 — execution handoff

## Frozen before launch

**NOT_DISPATCHED at creation.** Ryō requested reading the completed FT results
and proceeding with comparison. The [design](../../../docs/v23/COMPARISON_01.md)
and [plan](../../../configs/v23/COMPARISON_01.json) fix three fresh roles,
1,710 MMLU scores and 648 sequences in total. No learning, checkpoint save,
provider/judge request, weight deletion, PR/merge or release.

Local root: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/latent-memory-full-ft`.
Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Furnace source: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-comparison01-20261022`.
Furnace output: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-comparison01-20261022`.
Record the exact committed source, launch time/session and live receipt here
after dispatch, without changing the execution checkout.

Local development: 215 selected comparison tests passed with eight known
fresh-process environment cases deselected, plus seven offline publication
checks passed (222 total, eight deselected). This is not the Furnace gate.
The first local development pass had 16 fixture errors because the test
copied the updated graph instead of the pinned initial graph; the strict
owner correctly rejected it. Fixtures were corrected before freeze, with no
owner relaxation or real-model call. Ruff and terminal-artifact replay pass.
Furnace must run all **223/223** selected tests on CPU and CUDA, no skips,
before the base role starts.

Managed-runtime doctor passed without modifying the environment; its
ModelOpt/Transformers compatibility warning is retained as a warning, not
permission to upgrade. The qualified native PyTorch exception remains
necessary for this memory graph/owner state. Last pre-source disk observation
was 60.830 GiB, with a prior comparable worktree about 1.2 GiB; refresh the
50-GiB-floor admission after creating the isolated source.

Use only the once-launched pipeline. Check `raw/FINISHED.json` and per-role
terminal receipts, not process absence. If any gate fails, preserve missingness
and request a recovery decision; no automatic retry or source patch. Do not
resume the completed FT trial. Its sealed source is
`b46f04caefcfd596ccde3b0af8fd886d859f11b7` and all three saved weights remain.
No heartbeat monitor is requested or created.

After completion: verify both source seals, every published raw manifest,
unchanged native weight hashes, full per-arm denominators, seed/cap identity,
truncations and paired item transitions. Preserve old FAIL, no winner and
unestablished non-regression. Publish literal answer pairs without inferring
quality from different tokens. The new confirmation/OOD bank remains closed.
