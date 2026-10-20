# Native full-FT data preparation, first bounded stage

2026-10-21 (JST). Ryō authorized the proposed world-bank preparation and a
64-example teacher inspection, alongside remaining engineering checks.
This is **not** authorization to launch the full-FT population, paid judges,
delete weights, replace the beta, merge a PR, or publish a model.

The completed two-update/replay canary remains unchanged. A new additive
[resource probe](../../configs/v1_0/NATIVE_RESOURCE_PROBE_01.json) measures
three forward/backward lengths up to 128 memory + 128 query tokens, with the
native FP32 CPU masters and gradient-spill buffers present. It performs **zero**
optimizer steps and saves **zero** weights. It does not measure optimizer-step
peaks at those lengths or establish longer-context fit. Same pinned base,
arithmetic and allocation floors; exclusive paths, sealed source and no retry.
CPU work on dataset tooling can proceed alongside this GPU role. Teacher
inference waits for the role to exit; it must not contend for GPU or host RAM.

## Data roles

- Programmatically constructed worlds and independent semantic solvers supply
  canonical facts, answers and evidence. A world is written before its query.
- Relevant, absent, unrelated, locally edited and stale/current-state cases
  teach distinct memory-use boundaries. "No memory" does not always mean
  "unknown": ordinary instruction examples remain answerable without it.
- No-memory instruction seeds cover a small, explicitly limited preservation
  starter set. Neither seed count nor synthetic correctness proves retention
  of broad capabilities.
- A larger teacher sees canonical world facts inline and proposes natural
  language. Generated text is quarantined as a candidate; JSON/anchor/evidence
  checks are not a semantic-equivalence proof and do not auto-admit it to FT.
- Related worlds, twins and renderings share a split group. Held-out structure
  families and exposed historical evaluations are never teacher inputs.
- Source revisions, model/quantization hashes, prompts, requests, outputs,
  truncations, rejected cases and denominators are retained. No per-case retry
  or post-result prompt adjustment inside the 64-request inspection.

Full-FT mixture weights, update count, public benchmark selection and
non-regression bounds remain **UNSET**. No data from the old beta validation,
judge rankings or public evaluation test sets is imported as training gold.
Final selection uses development data; a final unseen evaluation stays sealed.
Token-denominator accounting uses the pinned **student** tokenizer, not the
teacher tokenizer or a row-count proxy.

## Teacher candidate

Official `Qwen/Qwen2.5-32B-Instruct-GGUF`, revision
`a15e3cc10f8bbb2c0af6f8f1f34a32e3b060c09d`, Q5_K_M, Apache-2.0.
The six split files total 23,262,157,568 bytes; verify each published SHA-256
before inference. No merge/copy of the split weight files is required.
`llama.cpp` source is pinned at
`1ba568c5ad5c6c718984bd2bf4e7c71485b706f9`. Installation is task-local;
there is no system package update or change to the existing FT environment.

References:
[model card](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF),
[llama.cpp build](https://github.com/ggml-org/llama.cpp/blob/1ba568c5ad5c6c718984bd2bf4e7c71485b706f9/docs/build.md).
Inference backend, request settings and resource bounds must be frozen before
the first request. A CPU-only speed result cannot be inferred from a GPU run.
