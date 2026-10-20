# Native-memory 7B canary — stopped at the original-model identity gate

2026-10-20. **INCOMPLETE_NO_RETRY.** Both tiny-device qualifications passed,
but the first real-model role stopped after loading the pinned original model,
before constructing the full-update owner or running a training forward.
The failure is an identity-hash scheme mismatch in the new harness, not an
observed OOM, failed update or replay divergence.

No automatic retry followed. The replay role was never dispatched. This record
does not establish the real-7B training resource envelope or restart equivalence.
The historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.

## Frozen scope and provenance

- Execution source: `59188535516eb32d57a42fb23fa4a7cc91585511`, 688 source files.
- [Plan](../../../configs/v1_0/NATIVE_7B_CANARY.json): canonical SHA-256
  `ecb1058c32a4647cf4486710e4eec0fb0670a59139e34be63a7f4c8a9f206a71`.
- Original model: `mistralai/Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`; local cache only, no download.
- Condition: cut 4, native BF16, eager attention, non-reentrant activation
  checkpointing, all 7,248,023,552 native parameters intended to be trainable,
  FP32 CPU Adafactor masters at learning rate `2e-7`, seed 47.
- [Source seal](furnace/SOURCE_SEAL.json),
  [dispatcher terminal](furnace/raw/FINISHED.json),
  [primary terminal](furnace/raw/primary/FINISHED.json),
  [literal log](furnace/raw/primary.log),
  [offline verification](OFFLINE_VERIFY.json),
  [execution handoff](EXECUTION_HANDOFF.md).

This is a new native-memory graph, not a continuation of an old V18 training
checkpoint. The [prelaunch-01 source](../native_7b_canary_prelaunch01_20261020/README.md)
and its CPU-only qualification remain unchanged. That earlier source was
superseded before CUDA/7B dispatch by an explicit tokenizer-return-type repair.
It is separate from the identity-gate failure reported here.

## Denominators and missingness

| Stage | Planned | Observed |
| --- | ---: | --- |
| Local selected tests | 249 | 249 passed, no failures/errors/skips |
| Furnace CPU qualification | 229 | 229 passed, no failures/errors/skips |
| Furnace CUDA qualification | 229 | 229 passed, no failures/errors/skips |
| Real-model roles | 2 | Primary attempted and failed; replay undispatched |
| Unique completed updates | 2 | 0 journaled |
| Completed replay updates | 1 | 0; replay undispatched |
| Backward row occurrences | 6 | 0 journaled |
| Retained checkpoints | 2 | 0; output directory independently observed empty |
| Real-model quality / generation / judge | Not selected | Not run |

The generic failed-role and dispatcher receipts deliberately retain
`native_weight_updates: null` rather than converting every interruption into a
zero. Here the traceback identifies a stronger, narrower fact: the exception
is in `prepare`, before `NativeFullUpdateOwner` construction or any call to
`update`. The source path and absence of update/checkpoint receipts support
**no training updates reached in this attempt**. The raw null is not rewritten.
The offline verifier's `model_calls: 0` describes the verifier, not the attempted
model load.

The [persisted inputs](furnace/raw/primary/INPUTS.json) contain four authored
synthetic examples, not benchmark, validation or judge-derived gold:

| Key | Memory tokens | Query plus answer tokens | Supervised answer tokens, including EOS |
| --- | ---: | ---: | ---: |
| `memory_a` | 11 | 18 | 6 |
| `direct_a` | 0 | 17 | 3 |
| `memory_b` | 18 | 30 | 11 |
| `direct_b` | 0 | 20 | 10 |

The complete windows would have denominators 9 and 21, or 30 supervised tokens
over the unique inputs and 51 token exposures including replay. Those are
**planned**, not processed training tokens. No examples were truncated.

## Why the identity check failed

The new plan's `legacy_state_sha256` contains:

```text
9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189
```

That is the historical **tree-hash** value, not the historical legacy hash.
The [V18 primary context](../../pilots/v18_native_pilot_20261015/furnace/raw/primary/CONTEXT.json)
records both, explicitly:

| Scheme | Historical value |
| --- | --- |
| `original_base_sha256`, produced by `tree_hash(base.state_dict())` | `9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189` |
| `original_legacy_identity_sha256`, checked by `prior.state_hash(base)` | `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312` |

The sealed canary calls `core.legacy.old.prior.state_hash(model)` and compares
it to the former value. The algorithms serialize the same model differently:
the legacy scheme walks state-dict insertion order and concatenates names,
dtype/shape strings and tensor bytes; the tree scheme sorts mapping keys and
includes container/scalar/tensor type encodings. Matching one digest against
the other is not a valid model-identity test.

The exact thrown error is:

```text
ValueError: Pinned original model differs
```

The actual computed hash was not persisted before the exception. Consequently,
this diagnosis establishes the **wrong expected-scheme binding** from source
and historical receipts; it does not independently prove the current cache's
contents match either correct historical digest. Do not relabel this as cache
corruption or assume that correcting the binding alone guarantees a pass.

The next proposed repair is to name both identity schemes explicitly, bind
their expected digests to the historical source-backed pair, record both
observed values before asserting equality, and add a regression that rejects
cross-scheme comparison. The frozen source and this failed plan stay unchanged;
any authorized new attempt needs a new source, fresh CPU/CUDA qualifications
and fresh output paths. No identity check, runtime cap or stop rule is waived.

## Resources and verification

Qualification wrapper times were **49.207 s CPU / 53.426 s CUDA**; literal
pytest times were **45.98 s / 49.97 s**. The CUDA qualification parent peak
was **67,276,800 bytes (64.16 MiB)**. This is a tiny-model measurement, not a
7B estimate; child processes were independently allocation-capped.
See [CPU](furnace/qualification/cpu/FINISHED.json),
[CUDA](furnace/qualification/cuda/FINISHED.json) and
[local XML](LOCAL_TESTS.xml).

The primary stopped after **22.614 s**; the dispatcher terminated after
**24.740 s**. Its recorded admission sample had **31.348 GiB free GPU**,
**118.832 GiB available RAM** and **241.481 GiB free disk**, with no competing
GPU process. The 30.5-GiB allocator cap, 24-GiB available-host floor, 50-GiB
remaining-disk floor, 7,200-second per-role deadline and 64-GiB checkpoint
forecast were unchanged. There is **no terminal 7B peak receipt**, so training
VRAM/RSS and checkpoint sizes are unknown, not zero.

At 10:12:30 UTC, a read-only [terminal observation](TERMINAL_OBSERVATION.json)
found no remaining recorded process, no compute client and an empty checkpoint
directory. No further weights were deleted.

The copied execution bundle contains **16 files / 537,506 bytes**. Offline
verification replays all 688 source hashes, both qualification manifests and
XML denominators, and the failed dispatcher manifest; it returns
`VERIFIED_INCOMPLETE_NO_RETRY`, not a 7B pass. The primary nested manifest is
also independently checked during publication. No historical receipt is
rewritten. Full FT, benchmark non-regression, generation quality and release
remain unestablished.

Post-terminal local validation repeated the same 249 selected tests:
**249 passed in 41.37 s**, no failures/errors/skips
([XML](PUBLICATION_TESTS.xml)). Scoped Ruff and `git diff --check` passed.
The offline publication audit validated relative links, literal token counts,
both historical identity values and the absence of execution-source or
historical receipt edits, without calling a model. The separate unit tests use
tiny scratch models; no additional pretrained-model load or GPU trial ran.
