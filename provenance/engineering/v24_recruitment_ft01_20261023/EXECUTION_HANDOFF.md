# V24 R1 native route FT: execution handoff

2026-10-23. Branch `SpiralReality/v24-readout-improvement`, remote
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`. Local checkout:
`/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.

This is a new protocol following the completed readout diagnosis. The prepared
bank is fixed at `6f1869b47e2e592d9ffdb7fda21812d08a1baad9d9d7ec148067171e026cc854`.
Use [RECRUITMENT_FT_01.json](../../../configs/v24/RECRUITMENT_FT_01.json) and
[the design](../../../docs/v24/RECRUITMENT_FT_01.md); never change an executing
source seal, data body, target, threshold, coefficient or resource floor.

Furnace source directory: `worktrees/latent-v24-recruitment-ft01-20261023`.
Output: `latent-v24-recruitment-ft01-20261023`, both under
`/home/ryospiralarchitect/spiralreality/SpiralReality`.
The source commit must be read from its future `SOURCE_SEAL.json`; no launch or
qualification PASS is claimed by this pre-dispatch handoff.

1. [Checks launcher](../../../scripts/launch_v24_recruitment_checks.sh) runs the
   full 570-test selection on CPU, then CUDA (each 4-GiB/900-second tiny bound;
   CPU masked and externally audited), then two mixed-route 7B canary updates,
   one save, and an exact fresh-process replay of update 2. It cannot start FT.
2. After checks pass, publish a complete body hash/identity/receipt ledger for
   **this canary alone**, verify no open handles and exact replay, then retire
   its spent body under Ryō's current unused-artifact authorization. Preserve
   every receipt and original/scientific comparison checkpoint. The separate
   `CANARY_RETIREMENT.json` must match the runner's contract. No auto-delete.
3. Only then [training launcher](../../../scripts/launch_v24_recruitment_training.sh)
   starts inline and workspace in separate processes, 32 updates / 538 rows /
   21,112 targets each, from the same original model/seed. Save only the two
   finals; the canary is never inherited. Whole-pipeline terminal comes after
   both roles. Distinct updates: 2 engineering + 64 scientific; one additional
   replay update. Completion is engineering evidence, not a quality gate.

Storage admission is one 28-GiB body + 50-GiB floor for checks, then two 28-GiB
bodies + the same floor for training after retirement. GPU free/allocator/abort
thresholds are 31/30.5/0.75 GiB; host admission/abort 100/24 GiB; each real role
has a 14,400-second wall limit. Check current shared resources before dispatch.

No new generation, judge request, checkpoint selection, confirmation/OOD
model exposure, HF export, PR or recurring monitor is part of this runner.
On any stop, preserve missingness and terminal receipts; do not resume/retry
in place or silently swap numerical/data conditions. Old FAIL/winner:none/
non-regression NOT_ESTABLISHED remains. Keep private preservation token arrays
on Furnace; only non-private metadata/receipts and synthetic records are public.
