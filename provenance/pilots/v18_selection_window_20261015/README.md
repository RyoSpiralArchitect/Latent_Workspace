# V18 selection window owner — sealed Furnace CPU/CUDA qualification

2026-10-15. **PASS on Furnace CPU and CUDA, with offline source/receipt
verification.** Each device passed the frozen 102-case window-owner suite and
all ten producer/resumer restart pairs in separate interpreters. This
qualifies tiny engineering mechanics only: no 7B update, real reference
capture, preservation loss, generation, judge call or weight deletion occurred.
The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Source and dispatch

Execution commit `55a514afdf13457d38e03dba9a946d3037180268`, bound by the
[594-file seal](raw/SOURCE_SEAL.json) (SHA-256 `c1fbcdeb…09444cc`), written on
the clean Furnace checkout and byte-identical to an independent local seal.
[Execution handoff](EXECUTION_HANDOFF.md) records paths, the pre-dispatch
state and the local rehearsal. One detached
[dispatch script](raw/launch_window_qualification.sh) ran CPU, then CUDA after
CPU exited 0; its [log](raw/DISPATCH.log) shows one dispatch per device and no
retry. Every child passed the pre-import source guard with isolated Python and
a fresh bytecode prefix, and proved its imported project modules against the
seal, always including all six critical V18 sources (each tests child: 78
modules mapping to 77 sealed files).

| Runtime | Coordinator | Unit suite | JUnit time | Restart children | Peak CUDA allocated |
| --- | --- | --- | --- | --- | --- |
| Furnace CPU | PASS, 209.595 s | 102/102, 0 failures/errors/skips | 87.915 s | 20/20 PASS, 5.110–5.255 s | Not applicable |
| Furnace CUDA | PASS, 244.914 s | 102/102, 0 failures/errors/skips | 99.553 s | 20/20 PASS, 6.088–6.325 s | 67,695,616 bytes (64.56 MiB) |

Runtime on both: Python 3.12.14, PyTorch 2.13.0+cu132, Transformers 5.15.0,
NumPy 2.5.2, pytest 9.1.1, CUDA 13.2, two CPU threads, one interop thread,
TF32 off. CPU and CUDA ran serially, never concurrently. Tiny peaks are not a
7B forecast. Bundles: [CPU](raw/cpu/FINISHED.json), [CUDA](raw/cuda/FINISHED.json),
with literal [CPU](raw/cpu-coordinator.log) and [CUDA](raw/cuda-coordinator.log)
coordinator output.

## What passed

- All 102 [window-owner cases](../../../tests/test_v18_selection_window_learner.py)
  per device: three query modes, raw/centered factors, FP32/BF16, frozen/full,
  variable two-/three-pair windows, legacy final-route parity, malformed restore
  nonmutation, snapshot independence and partial-window rejection.
- Ten restart cases per device: eight ordered-query FP32/BF16 × frozen/full ×
  raw/centered cases plus BF16/full/centered final and symmetric controls. In
  each, a producer interpreter saved window 1 and computed window 2; a distinct
  resumer interpreter rebuilt the independent caller contracts, challenged the
  ambient RNG, loaded `weights_only=True` and reproduced the complete window-2
  receipt, owned optimizer/master/native/bridge fields and RNG continuation
  exactly. Saved bytes and payload were unchanged after the resume.
- The tiny `window1.pt` checkpoints (130,169–182,617 bytes) are retained in the
  bundles as evidence; they are not language-model weights.

The [offline verification](OFFLINE_VERIFY.json) rehashed all 594 sealed sources
and every artifact against both terminal manifests, then checked the exact
child population, 21 distinct process IDs per device, matching producer/resumer
receipts, checkpoint bindings and time/CUDA envelopes. It made no forward call
and did not replay tensor checkpoints. Comparisons are within each runtime;
CPU/CUDA bitwise equality is not claimed. These are 21 computation children per
device, not 21 independent scientific experiments.

## Local rehearsal (not evidence)

Before dispatch, the same commit ran once through the same sealed launcher in
a private Mac clone. It passed in 618.6 s and its local bundle passed the same
offline verifier. It exercised the runner end to end only; its bytes are not
retained or counted.

## Consequence

The selection/window owner, Furnace CPU/CUDA update and fresh-process resume
gates in the [roadmap](../../../docs/v18/FULL_UPDATE_ROADMAP.md) are complete for
tiny models. Real Mistral integration remains untested: operand binding from the
pinned tokenizer, the 7B ownership/layout checks, contextual backward with the
split query and resource envelope. The next stage is a separately frozen
native pilot. Its storage forecast permits one retained condition at a time.
