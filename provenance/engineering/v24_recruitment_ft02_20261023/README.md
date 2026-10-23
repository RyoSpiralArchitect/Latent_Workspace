# V24 R1 FT02: CPU tests passed, external audit failed

2026-10-23. **Stopped before CUDA qualification and before any 7B dispatch.**
This fresh output used exactly FT01's execution source
`d43382833f6dc85787720bda80aec511c66f58be` and byte-identical source seal.
It is not a successful qualification, a replay, or a scientific FT result.

| Observation | Recorded result |
| --- | --- |
| CPU tests | 570/570 passed; zero failures/errors/skips, 72.176 s |
| CPU/GPU audit | `CPU_GPU_ISOLATION_FAILED` |
| Successful external samples | 134; all report no GPU clients, including own descendants |
| Failed external samples | One `ValueError`; command/stage/message were not recorded |
| CPU mask / child probe | Device count zero; CUDA initialization rejected; final not initialized |
| CUDA tests / canary / replay / scientific arms | All `NOT_RUN` |
| New 7B updates / checkpoint bodies / generations / judge calls | All zero |

The exception's cause is **UNKNOWN**. Healthy later PID queries and the 134
empty successful samples do not retrospectively validate the missing sample.
There is no evidence here that the masked CPU process actually used a GPU.
The audit exception correctly prevented later dispatch via the launcher's
`set -e`; no whole-run `FINISHED.json` was fabricated after the launcher exited.

The [seven original files](latent-v24-recruitment-ft02-20261023/) are preserved
without rewriting their source seal, terminal, log or XML bytes. The CPU terminal
SHA256 is `f7f8f15d0cdfd2cdd72532e1e017708f7ec8c5e9e28980022567315fcdab54e1`;
the failed audit SHA256 is
`ead025364dde04d9b5ea6b8c876b318523c1f1eaeefa37341a05998bae09a127`.
[Offline replay](OFFLINE_STOP_VERIFICATION.json) verifies all 831 source files,
the exact launcher, CPU manifest and XML counts, and the CPU-only artifact set.
Reproduce with `python3 -B scripts/verify_v24_ft02_stop.py`.

Ryō explicitly authorized a new-source, separate-attempt audit repair. The
[FT03 handoff](../v24_recruitment_ft03_20261023/EXECUTION_HANDOFF.md) separates the
observer into a stdlib-only process and retains bounded command/parse diagnostics.
This addresses an observer/test shared-state vulnerability; it does **not**
claim to have identified the historical exception. No failed sample is ignored,
retried or converted to an empty GPU list. Original FT01 and FT02 stay closed.

The old expression gate remains **FAIL**, winner **none**, and non-regression
**NOT_ESTABLISHED**. No quality, capability or release conclusion is available.
