# V20 A5 — attempt 01 (stopped at the CUDA qualification)

2026-10-18. **STOPPED BEFORE ANY ROLE; `INCOMPLETE_NO_RETRY`.** Nothing about the
outcome was observed: no role was dispatched, no route was trained and the
final split was not read.

- **Run identity:**
  - source `5199f990cb83c61a7b1e3a1c3f6c928c93c06cbf`;
  - [seal](SOURCE_SEAL.json) `481d9a6b…`, 662 files, byte-identical locally;
  - plan `b8357d51…`.
- **Dispatch:** once at 2026-10-17T17:46:46Z, through
  [the launch script](launch_v20_a5_stable_route.sh)
  ([timeline](LAUNCH_TIMELINE.log)).
- **CPU qualification:** passed at 17:46:56Z, 59/59.
- **CUDA qualification:** all 59 tests passed, but it ended
  `INCOMPLETE_NO_RETRY` at 17:47:05Z with `Tiny CUDA envelope`
  ([receipt](qualification/cuda/FINISHED.json)).
  - The skeleton requires a positive peak CUDA allocation.
  - A5 has no extraction, and its roles run on CPU only, so none of its tests
    touches CUDA. The peak was 0.
- **Records:** every file of the task root except the transfer bundle. The
  task root, `tmp/latent-v20-a5-stable-route-20261018`, stays as it is.

**Fix before attempt 02** (no change to the design or the endpoint):
- **Engine:** the execution skeleton lets a plan name
  `qualification_devices: ["cpu"]` for a run whose roles never use a GPU
  (`execution.qualification_devices`, with its own test). The default still
  requires both CPU and CUDA.
- **A5:** the plan names CPU alone, and the launch script runs only the CPU
  qualification.
- **Attempt 02:** a new seal of the same design with only this change and the
  qualification count, in a new task root.
