# V23 gradient audit 01 — execution record

**Terminal update:** the [complete result](TERMINAL.md) now replays on Furnace
and locally. Both roles passed; all components are complete and native weights
are unchanged. The interim account below is retained as dated history, not the
current completion state. No optimizer update or quality gate was performed.

Protocol: [GRADIENT_AUDIT_01.md](../../../docs/v23/GRADIENT_AUDIT_01.md).
This is a new no-update run, not a retry/relabeling of preparation 01.

Pre-freeze local checks: [338 cases](LOCAL_TESTS.xml), **336 PASS / 2 FAIL**.
Both failures are the existing fresh-process owner replay tests: the Mac's
isolated Python cannot import `typing_extensions`. No test was excluded and
no global environment was changed. Separate new transport tests pass 28/28;
actual runner/causal target-layout tests pass 6/6. Furnace must pass all 338
CPU and CUDA cases before admitting any model role.

Managed-runtime doctor passed (`ok:true`, no failure codes); the existing
modelopt/transformers compatibility warning was retained, not repaired.
The gradient/cut/owner diagnostic uses the pinned native PyTorch runtime,
not the serving runtime. No API calls or external teacher are planned.

## Interim result: engineering gates pass; panel still running

Snapshot: **2026-10-22 01:21:52 JST** (2026-10-21 16:21:52 UTC).
Execution source `66467502064b08b1ea8e246edc6696bd9d35a60e`, 761 sealed files.
The [interim manifest](interim_furnace/INTERIM_MANIFEST.json) covers 27 public
files / 1,224,369 bytes (excluding the manifest itself). It is **not** a
terminal receipt: the V22 row logs and parent/V22 FINISHED are not published
as if complete. [Offline verification](publish_interim.py) rechecks all source
bytes against Git, child receipt manifests, canary bounds and target provenance.

| Completed gate | Result |
| --- | --- |
| Furnace CPU suite | 338/338, no errors/failures/skips; wrapper 45.943 s |
| Furnace CUDA suite | 338/338, no errors/failures/skips; wrapper 52.376 s |
| Base 7B W/Q/R canary | 291/291 parameter tensors within frozen bound |
| Frozen V22 7B W/Q/R canary | 291/291 parameter tensors within frozen bound |
| Trace/no-trace and detached R forward | Bitwise exact at both canaries |
| Base teacher target bank | 12/12 rows, 932/932 supervised positions |
| V22 strict owner restore | Exact step32 state before audit-policy transition |
| Whole 84-world/12-preservation conflict panel | **RUNNING, NOT COMPLETE** |
| V23 training or new-objective save/restart | **NOT_RUN** |

Both canaries use the same preselected maximum-memory train row:
`wb02-20261022-inventory-train-0007/s0/unaffected`, 105 memory / 46 query
tokens. Base also runs the independent 128-query-token preservation sentinel.
W and Q each reach the same 37 lower tensors; R reaches 254 others in this
Mistral canary. This is not separate W/Q parameter ownership. Independently
rounded path sums use the predeclared 1e-4 + 3%-of-full-max bound; their maximum
fractions of that bound are 0.1280 (base) and 0.1056 (V22). Do not call these
bitwise-equal gradients or a successful optimizer update.

The base arm finishes in 168.752 s. Peak GPU allocation is **17.7802 GiB**;
one full FP32 CPU gradient sum is **27.0010 GiB**, with two temporarily live
for the path-sum canary. This is not a matched training-speed/memory benchmark.
Base native hash remains
`9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189`.
V22's final post-panel unchanged-weight hash is **pending**, not inferred
from its successful restore or canary.

The full-vocabulary teacher tensor payload is **122,159,104 bytes (116.5 MiB)**;
the safetensors file is 122,160,008 bytes, SHA256
`80a3ab7d013c179eef8e6df5d1e0887be63cfca60abe14b95f31d30e90617655`.
This single private target body is omitted from publication. Source-owned
preservation input token arrays also remain on Furnace, never copied into Git.

The panel keeps 84 unique world rows in **14 group-level units**, not 84
independent worlds: 28 affected, 28 unaffected, 14 absent, 14 unrelated.
532 world targets split into identity 256 / copy 100 / format 176 / mixed 0.
There are 70 nonempty-memory state audits and 14 exact native bypass controls.
Preservation has 12 complete training rows / 932 targets, four rows each of
instruction, prose and code. This small short-context panel is not a retention
benchmark. Parameter conflicts are not yet interpreted; no P/B/I winner,
coefficient or quality improvement is selected from completed engineering gates.

The finite job continues with a four-hour-per-role ceiling and stops on its
first failure, without retry. No recurring monitor was created. Use the
[handoff](EXECUTION_HANDOFF.md) to inspect the existing process. After terminal
completion, publish into a separate `furnace` directory; retain this interim
snapshot unchanged. `verify.py` handles terminal replay; `analyze.py` produces
descriptive reductions only when the complete terminal audit passes.

Separate [completed retirement](../../inventory/v23_obsolete_canaries_20261022/README.md)
removed three obsolete engineering checkpoints / **81.0373 GiB**. Original
Mistral, V22 step16/32, all scientific branch weights, activations and data remain.
No new weight deletion occurs inside the audit. Deleted bodies are not backed
up by Git; hashes/receipts cannot reconstruct them.

The unchanged ceiling is **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
