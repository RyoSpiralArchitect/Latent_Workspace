# V23 recovered MMLU-Pro 01 — allocator-reservation safety stop

This separately launched attempt used source
`cda0a8ae8c3648c41fae2be45b3208c9a5f1a9b6` (799 sealed files).
CPU and CUDA qualification each passed **301/301**, with zero skips/errors/
failures. The CPU isolation audit passed. Dispatch started only after both.

Base completed **280/280 direct scores**, with **92 correct**, then stopped
before generation step 107 of its **first** reasoning item. Its reasoning
journal has **zero complete rows**; partial generated tokens were not journaled.
The terminal sequence-activity count stays **null**, not zero. P-off and P-on
were never dispatched: **280/840 direct scores** and **0/84 complete reasoning
sequences** are retained. No paired base-vs-FT conclusion can be computed.

The original 0.75-GiB free-GPU floor stopped the run. The final snapshot has
570,425,344 free bytes, 14,529,603,584 live allocated bytes and 32,403,095,552
reserved bytes; peak live allocation was 15,601,157,632 bytes. Only this
evaluation's PID was a GPU client. This is allocator-reservation growth during
variable-length full-prefix generation, not another CPU-isolation collision.
No OOM exception occurred. The post-inference native-identity check was not
reached; do not call this a complete read-only arm verification.

All raw journals, resource logs, qualification receipts and the source seal
are retained exactly. `verify_terminal.py` replays manifests, historical source,
XML counts, target/score decisions and the resource stop. No resumed/retried
cell or completed result is fabricated. The separately authorized
[attempt 02](../../../docs/v23/RECOVERED_MMLU_PRO_02.md) leaves these files intact.
The complete P-on comparison and its independent answer-bank judge are not
invalidated by this later benchmark failure.

Old expression gate **FAIL**, winner **none**, non-regression
**NOT_ESTABLISHED**. No training, saved weights, deletions or release.
