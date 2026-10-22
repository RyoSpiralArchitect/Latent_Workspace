# V24 readout probe 01 — execution handoff

Execution source: `bb1ecc8b3b3b98f9b63a67da1dbdd76033c76c79` (814 sealed
source paths). Launched once on 2026-10-22 at 04:26:14 UTC in tmux
`ltws-v24-readout-probe01-20261022`; initial pane PID 3964874.

At the 04:35 UTC read-only check, CPU **350/350** and CUDA **350/350** passed
(zero failures/errors/skips), CPU isolation passed, and base/P-off each had
their complete **44-case / 197-forward** terminal receipt. P-on and the overall
dispatch receipt were still pending. This snapshot is not overall completion.

Local repo: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/v24-readout-improvement`.
Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Furnace isolated source (detached at the execution commit):
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-readout-probe01-20261022`.
Exclusive output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-readout-probe01-20261022`.

Ryō authorized GPU use through Full FT, after the merged V23 readout, on
2026-10-22. The immediate [sealed plan](../../../configs/v24/READOUT_PROBE_01.json)
is diagnosis only: CPU -> CUDA -> base -> P-off -> P-on, each a separate
process; 350 tiny tests/device, 44 cases/197 forwards/model. No retry/resume,
new free generation, update, save, judge, deletion, release or automatic FT.

Old sources, input bundles and all earlier terminal records remain unchanged.
Native owner checkpoints are fully validated/restored with their original
contracts, then explicitly transitioned to inference. New code only observes
native readout. The pending score buffer is CPU-only; no new KV cache, logits
processor, learned head or trainable parameter exists.

On any failure preserve the exact run, publish missingness and request the next
recovery decision. Process absence alone is not completion. No heartbeat is
created. Local/pinned-runtime test success and scientific quality are separate.
Full FT additionally needs a frozen factor/data protocol and storage admission;
the current 53.06-GiB free space cannot hold another canary/final plus the
50-GiB floor. No deletion is authorized by this diagnostic.

Local prerequisite record: 346/350 tests passed; four isolated-child imports
failed with `ModuleNotFoundError: typing_extensions`. The raw XML is retained
as [LOCAL_350.xml](LOCAL_350.xml). This is not a sealed Furnace failure and does
not waive any of its 350 tests. An earlier 106-test working selection passed.

Ryō subsequently authorized retirement of no-longer-needed intermediate weights.
That is a separate inventoried operation, not permission for this launcher to
delete anything. Exact eligible targets and receipts must be checked first;
scientific final comparison arms remain protected.

The separate [intermediate retirement ledger](../../inventory/v24_intermediates_20261022/README.md)
selects only V23 canary step1 and V22 training step16. Its first inventory
stopped before deletion on a `fuser --` syntax error; the original attempt
remains intact. The corrected, separately named inventory passed complete
body hashes and replay/continuation checks. Publish its ledger before removal;
do not modify the running source worktree or its source seal.
