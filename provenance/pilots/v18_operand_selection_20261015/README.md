# V18 operand selection — CPU qualified, CUDA admission blocked

2026-10-15. **INCOMPLETE; no controlled fitting study dispatched.**

The [new prototype and study protocol](../../../docs/v18/OPERAND_SELECTION.md)
separate the common final-state query from an inference-text-bound interaction
query. Exact operand bindings, CPU-FP32 pooling and model-neutral native head
ownership are implemented without modifying old source/checkpoint formats.

## Source and engineering result

Frozen source: `dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`,
[572 sealed files](SOURCE_SEAL.json). Execution used the new isolated Furnace
checkout and fresh processes specified in [the handoff](EXECUTION_HANDOFF.md).

| Runtime | Selected tests | Outcome | Elapsed | Peak CUDA allocation |
| --- | ---: | --- | ---: | --- |
| CPU | 200/200 | PASS, zero failures/errors/skips | 5.571444 s total; 3.23 s tests | Not applicable |
| CUDA | 0/200 dispatched | FAILED before any test/model dispatch: another GPU client | 2.005117 s | UNKNOWN; not measured |

The CPU population is exactly 87 operand-binding + 85 split-reader + 28 native
pipeline cases. Same-query outputs and gradients match the V16 reader; tiny
Mistral/GPT-2/OLMo2/Gemma2 layouts cover FP32/BF16 native head ownership. These
are tiny engineering observations, not all-model or semantic qualification.
Local checks additionally passed 567 selected regression tests and 78
guard/assay/replay unit tests, plus Ruff. Assay unit tests include only one-step
fixtures and a separately constructed capacity witness, not the planned fits.

The CUDA admission check reported exactly:

> ValueError: Other GPU workload; no test/model dispatched

A subsequent read-only observation found another `python3` GPU client, PID
1813656, using 6,960 MiB. This is the follow-up snapshot, not a measurement of
this trial's memory requirement. The other workload was not changed or stopped.
GPU idle had been observed during preparation, but it changed before admission.
Neither the empty-device rule nor resource limits were relaxed after the failure.

## What did not run

The plan requires both engineering runtimes to pass before fitting. Therefore
**0/12 CPU and 0/12 CUDA fitting cells** ran; each runtime's planned population
is four factors × three seeds, with 256 updates per cell. No toy score, donor
flip count or selection winner is available. Planned data are 1,152 train,
288 dev and 1,152 held-out rows per fit; those are not completed observations.
The planned held-out pairs have 384 affected, 768 unaffected and 576 reciprocal
pairs, not independent repeated samples. No trained state or answer bank was
created by this attempt.

No 7B updates, real writer fit, preservation loss, free generation, paid judge,
weight deletion, model download, HF upload, PR or merge occurred.

## Evidence and replay ceiling

Literal [CPU](cpu/FINISHED.json) and [CUDA](cuda/FINISHED.json) terminal receipts
are retained. The source commit/current-byte verification and complete CPU
receipt replay pass. The failed CUDA receipt's original source, start-file size
and hash were checked; it has no test report. The full two-runtime verifier
correctly rejects this bundle, rather than turning the CPU result into an
overall pass. [Offline audit](OFFLINE_AUDIT.json) records that distinction.
The preceding 557-file V18 foundation and 546-file V16 population source maps
remain byte-identical; historical evidence is unchanged.

Before a future fitting run, supplement the frozen raw-metric replay with a
strict terminal audit of control scalars, imported-source/pre-import identity,
offline flags and exact realized-population schemas/finiteness. The current
raw-metric replay does not by itself certify all those properties; no toy result
has been accepted under it. Do not rewrite this execution source to fix or retry
the failed attempt.

Next decision: after GPU availability is restored, authorize a separately
identified CUDA-only qualification attempt with unchanged tests/math/limits;
retain this failed admission. Actual-writer and full-update owner admission
remain later gates. No background monitor or automatic retry is active.

**Old FAIL / winner:none / non_regression NOT_ESTABLISHED remains unchanged.**
