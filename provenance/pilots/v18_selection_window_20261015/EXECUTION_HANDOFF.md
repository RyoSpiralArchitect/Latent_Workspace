# V18 selection window: sealed Furnace CPU/CUDA qualification

2026-10-15 JST. Ryō approved finishing the window owner and the CUDA
update/restart checks, then proceeding to full FT. This handoff covers only the
frozen [window qualification](../../../docs/v18/SELECTION_WINDOW_QUALIFICATION.md);
it is not a 7B run and changes no historical arithmetic, seal or threshold.

Execution source: `55a514afdf13457d38e03dba9a946d3037180268`, pushed before any
remote computation. The previous session transferred it as `source.bundle`
(84,695 bytes) and created the clean detached Furnace checkout
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v18-selection-window-20261015`.
It stopped at a usage limit before writing a seal or dispatching anything. At
this continuation's preflight the output parent held only that bundle: no
STARTED/FINISHED receipt, no live process and no GPU compute client. Nothing
ambiguous is being resumed.

Output parent:
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v18-selection-window-20261015`.
Qualified interpreter (Python 3.12.14 / PyTorch 2.13.0+cu132):
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
`prepare-seal` on the Furnace checkout wrote `SOURCE_SEAL.json` in the output
parent: 594 files, SHA-256
`c1fbcdebd6322c108ac5eacbcdac9d494e3fa37a2d8e24cbcbc02f96e09444cc`. An
independently prepared local seal of the same commit is byte-identical.
The transfer bundle's SHA-256 is
`02a8f8b2e754b1d9618c42c0eb040dcb86479519fb0dd6e6020d3f8095bf635e`.

Dispatch is one detached run of `launch_window_qualification.sh` in the output
parent (SHA-256 `d9dc2ef7de2d98b1422db5803f32e4fa58ca865d2e68dc1fd60ce8d26fb9ef66`),
all through `run_source_sealed.py`: CPU coordinator to `cpu/`, then, only if CPU
exits 0, CUDA coordinator to `cuda/`. The script refuses to dispatch over an
existing device output and appends to `DISPATCH.log`. Limits are the frozen
plan's: 900 s per device, a 600-s tests child, 60-s restart children, two
threads and a 4-GiB CUDA cap. Existing STARTED/FINISHED receipts control what
happens next; a failed, quiet or interrupted device is recorded, not relaunched.

## Local rehearsal before dispatch

To exercise the runner end to end before spending the one Furnace attempt, the
same commit was cloned into a private scratch directory on the Mac and run
through the same sealed launcher on CPU (Python 3.13.13, PyTorch 2.13.0).
This is a development rehearsal, not qualification evidence, and its bytes are
not retained as a result bundle.

The rehearsal coordinator reported `TINY_SELECTION_WINDOW_AND_PROCESS_RESTART_PASS_NOT_7B`
in 618.6 s: 102/102 tests in 281.0 s, then all ten producer/resumer pairs
(12.6–17.7 s per child). The offline verifier then returned
`OFFLINE_SOURCE_AND_RECEIPT_PASS` for that local bundle: 21 independent child
processes, zero forwards, no tensor replay. The Furnace dispatch began only
after the first BF16 producer/resumer pair had passed; the rest of the
rehearsal finished while Furnace CPU was running and did not gate it.

## Dispatch record

`2026-10-14T20:57:35Z` (UTC): one detached dispatch. Preflight immediately
before it: no GPU compute client, 10 MiB of 32,607 MiB GPU memory used,
119 GiB host memory available, and no existing `cpu/`, `cuda/` or
`DISPATCH.log`. The launching SSH call stayed attached to its backgrounded
subshell and was not used to send any further command to the job.

## Terminal handoff — do not relaunch

CPU exited 0 at `21:01:05Z` and CUDA exited 0 at `21:05:10Z`; both coordinators
report `TINY_SELECTION_WINDOW_AND_PROCESS_RESTART_PASS_NOT_7B`. The literal
bundles, seal, dispatch script and logs are copied under `raw/`, and both pass
the offline verifier. No process from this dispatch remains. See the
[results](README.md). The Furnace output parent and checkout are left in place.
