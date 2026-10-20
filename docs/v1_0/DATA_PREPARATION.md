# Native full-FT data preparation, first bounded stage

2026-10-21 (JST). Ryō authorized the proposed world-bank preparation and a
64-example teacher inspection, alongside remaining engineering checks.
This is **not** authorization to launch the full-FT population, paid judges,
delete weights, replace the beta, merge a PR, or publish a model.

The completed two-update/replay canary remains unchanged. An additive
[resource probe](../../configs/v1_0/NATIVE_RESOURCE_PROBE_01.json) measures
three forward/backward lengths up to 128 memory + 128 query tokens, with the
native FP32 CPU masters and gradient-spill buffers present. It performs **zero**
optimizer steps and saves **zero** weights. It does not measure optimizer-step
peaks at those lengths or establish longer-context fit. Same pinned base,
arithmetic and allocation floors; exclusive paths, sealed source and no retry.
CPU work on dataset tooling can proceed alongside this GPU role. Teacher
inference waits for the role to exit; it must not contend for GPU or host RAM.

The [first resource attempt](../../provenance/engineering/native_resource_probe01_20261021/README.md)
stopped before backward because the diagnostic substituted its purpose label
for the loss identifier. After separate approval, the
[recovery](../../provenance/engineering/native_resource_probe_recovery01_20261021/README.md)
passed 254/254 checks on each device and all three backward rows, with both
native and master weights unchanged. Peak CUDA allocated/reserved was
27.696/28.365 GiB; peak host RSS was 59.267 GiB. This is still not a longer
optimizer-step or quality result.

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
An initial `llama.cpp` source build at
`1ba568c5ad5c6c718984bd2bf4e7c71485b706f9` passed CPU compilation, but its CUDA
13.1 build failed at compiler identification: OS `rsqrt`/`rsqrtf` exception
specifications conflict with the toolkit headers. No generation was dispatched.
The failed build directory is preserved; system headers and FT dependencies
were not changed. Before any request, the teacher runtime was selected as the
official **b11756 CUDA 12.8** binary, source
`d80619397c2ba5cf1366c29f7d43699ca3a159b9`. Both archive hashes and extracted
runtime files are checked. This is a task-local install, not a system update.
The CPU-only build is retained but is not the selected inference condition.

The [teacher plan](../../configs/v1_0/TEACHER_INSPECTION_01.json) fixes 48
world examples (four twin pairs per family) and 16 instruction examples (two
per starter family), maximum 256 generated tokens each, temperature 0.2,
per-request seeds, one server slot and no retries. Inputs are entirely training
split material. All outputs remain candidates, including structurally valid
ones. A separate source-sealed run freezes every exact request before dispatch.

References:
[model card](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF),
[llama.cpp build](https://github.com/ggml-org/llama.cpp/blob/1ba568c5ad5c6c718984bd2bf4e7c71485b706f9/docs/build.md).
Inference backend, request settings and resource bounds must be frozen before
the first request. A CPU-only speed result cannot be inferred from a GPU run.

## Completed stage and remaining decisions

The [world-bank result](../../provenance/data/native_world_bank01_20261021/README.md)
contains 8,192 world rows from 1,024 groups plus 128 instruction seeds. Full
regeneration passes. The 2,048 paired control duplicates are retained for
audit, not treated as independent evidence. All canonical rows fit within
the tested token axes, but this does not prove update/restart fit.

The [teacher inspection](../../provenance/data/native_teacher_inspection01_20261021/README.md)
completed 64/64 requests without retries, truncation or transport errors.
All were structurally valid; semantic/training approvals remain zero.
Post-hoc inspection found omitted memory policy in all 48 world questions and
different question text in 9/24 twin pairs. A separately recorded compiler
now uses immutable canonical memory/query plus teacher answer prose, producing
64 quarantined derivatives without any new generation or raw-output edit.
All 64 literal outputs are available in the linked human review panel.

Before full FT, freeze these decisions rather than treating preparation as a
quality gate:

1. **Sampling by role and supervised tokens.** Do not silently double-count
   paired duplicate controls. Ordinary instructions currently supply only
   1,523/37,615 canonical candidate tokens (4.05%) under row-uniform sampling.
   World/ordinary/absent/unrelated mixture and a finite update budget are UNSET.
2. **Preservation targets distinct from teacher style.** Broaden instruction
   coverage and establish original-Mistral rehearsal/anchors on independent
   training material. A 32B teacher is a source of proposed useful behavior,
   not proof of original-base non-regression. No new base generations or
   preservation loss are implemented in this preparation stage.
3. **Unseen evaluation and matched controls.** Freeze public benchmark versions,
   token/correctness denominators, tolerances, same-seed generation prompts
   and original/updated direct/latent/inline comparisons before FT. Use
   development data for choices, not the final held-out set.
4. **Length-specific update/save/restart.** The long backward result and short
   exact replay are separate. A selected full-FT recipe must have a justified
   resource/storage forecast and its own bounded dispatch authorization.

No full FT, paid judge, additional learner generation, weight deletion, PR
merge, beta replacement or Hub upload followed from this stage.

## Additive preservation candidates (2026-10-21)

Ryō subsequently authorized reusing existing Aether prose, inspecting
Q_Space_Manifold code assets, and a small HF acquisition where needed.
The [preservation bank](../../provenance/data/native_preservation_bank01_20261021/README.md)
is now prepared: 1,754 train candidates / 324,616 supervised student tokens,
and 184 development candidates / 39,761 tokens. These are separate from the
original world bank and its 4.05% instruction-token observation.

The bank keeps three **no-memory** roles: plain-text causal-LM prose,
assistant-masked general instructions, and assistant-masked code answers.
Existing Aether human prose supplies 1,184 short spans; pinned OpenAssistant
train material supplies 754 complete first-turn pairs. Synthetic Aether prose
and user-owned writing are excluded from this first bank. CodeXGLUE validation
from QSpace and official OASST validation are exclusion-only, never training
inputs. Their use for exclusion does not make them pristine final tests.

The HF download was bounded to four files / 41,617,955 bytes. Source hashes,
group splits, masks, exclusions, unfilled quotas and token counts are frozen in
the plan/report. CPU full regeneration passed; no new model call or training
occurred. This establishes a reproducible candidate substrate, not retention:

- 635 rows exceed the tested 128-query-token backward axis; maximum length is
  1,024. A mixed update/save/restart recipe has not been qualified.
- There are only 33 Japanese train instructions and no Japanese code pairs.
  Code correctness and broader capability coverage remain untested.
- PG rights claims are jurisdiction-specific; review and training admission
  remain pending. Raw text/token arrays are kept on Furnace, not published.
- Actual role weights, original-base anchors/controls, benchmark versions and
  non-regression tolerances remain UNSET. No preservation loss is yet wired
  into the full-FT trainer by this preparation-only change.
