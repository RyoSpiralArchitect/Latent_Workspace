# Native-memory 7B identity recovery 01 — exact update/restart gate passed

2026-10-20. **Engineering PASS, not a quality result.** The pinned original
Mistral-7B-Instruct-v0.3 completed two native full-parameter updates, saved
steps 1/2, and exactly repeated step 2 after restoring step 1 in a **fresh
process**. The dispatcher finished in **861.784 seconds** (14.36 minutes).
No retry, additional deletion, generation, judge or model download occurred.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
This short, four-input execution test establishes neither useful memory
learning nor original-base preservation, longer-sequence fit, a full training
population or release readiness.

## Provenance and the repaired gate

- Execution source: `03fdb960ef4a1e4c28112deaf03ecad41a440984`;
  [seal](furnace/SOURCE_SEAL.json) covers **690 source files**.
- [Recovery plan](../../../configs/v1_0/NATIVE_7B_CANARY_RECOVERY_01.json),
  canonical SHA-256
  `6f692b785185c60f294925a25fa22e3ee2774a86c85e0372240cc159a8657526`.
- Model revision: `c170c708c41dac9275d15a8fff4eca08d52bab71`;
  local cache only. Cut 4, BF16, eager attention, non-reentrant checkpointing,
  CPU FP32 Adafactor, learning rate `2e-7`, seed 47.
- [Prior failure](../native_7b_canary_20261020/README.md), including its source
  `59188535516eb32d57a42fb23fa4a7cc91585511`, old plan and raw receipts, is
  unchanged. The tokenizer prelaunch record is also unchanged.
- [Execution handoff](EXECUTION_HANDOFF.md),
  [terminal receipt](furnace/raw/FINISHED.json),
  [offline verification](OFFLINE_VERIFY.json).

The prior harness compared a tree-hash expected value against the legacy hash
function. Both schemes now have explicit names, expected values bound to the
historical V18 context, and actual measurements persisted **before** any
assertion. Both independent processes match both historical values:

| Named scheme | Expected and observed original-model digest |
| --- | --- |
| `legacy_state_v1_sha256` | `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312` |
| `state_tree_v1_sha256` | `9db998af86c8105f0a2d774c10f777e190f86e54473b6b756bb51b225064a189` |

See the literal [primary](furnace/raw/primary/ORIGINAL_IDENTITY.json) and
[replay](furnace/raw/replay/ORIGINAL_IDENTITY.json) measurements.
The plan repair changed only identity, recovery provenance, schema and
qualification additions. Native graph/owner/transport code, inputs, seed,
optimizer, numerical policy, resource limits and stop rules were not changed.
The persisted input file is byte-identical to the failed attempt's input file.

## Denominators and actual updates

| Item | Planned | Completed |
| --- | ---: | ---: |
| Local selected tests | 264 | 264 passed, no failures/errors/skips |
| Furnace CPU qualification | 244 | 244 passed, no failures/errors/skips |
| Furnace CUDA qualification | 244 | 244 passed, no failures/errors/skips |
| Unique native updates | 2 | 2 |
| Additional replay updates | 1 | 1 |
| Physical update executions | 3 | 3 |
| Backward row occurrences, including replay | 6 | 6 |
| Retained checkpoints | 2 | 2 |
| Replay weight files | 0 | 0 |

Fifteen new regressions supplement all prior selected cases. They reject
cross-scheme hashes, changed weights, missing/extra schemes and damaged
identity receipts; they also check exclusive writes and the unchanged recipe.
Local tests took **41.14 s**. CPU/CUDA qualification wrappers took
**50.986 s / 55.262 s** (literal pytest times 47.76 s / 51.78 s).
The qualification parent's CUDA peak was **64.16 MiB**, distinct from the 7B
measurements below. [Local XML](LOCAL_TESTS.xml),
[CPU terminal](furnace/qualification/cpu/FINISHED.json),
[CUDA terminal](furnace/qualification/cuda/FINISHED.json).

All **7,248,023,552 native parameter elements in 291 physical tensors** were
owned by the full-update optimizer. All 291 received finite gradients on each
backward row. CPU masters changed in 291/291 tensors at both unique updates;
native BF16 casts changed in 237/291 tensors. Full ownership does **not** mean
every BF16 value changes on every update.

| Unique step | Supervised window tokens | Changed CPU-master tensors | Changed native BF16 tensors | Changed native elements |
| --- | ---: | ---: | ---: | ---: |
| 1 | 9 | 291/291 | 237/291 | 124,461,834 |
| 2 | 21 | 291/291 | 237/291 | 150,103,783 |

These element counts are within-step changes, not disjoint totals. See
[step 1](furnace/raw/primary/step1.json) and
[step 2](furnace/raw/primary/step2.json). There are 30 unique supervised tokens,
51 processed token exposures including the repeated second window. Replaying
step 2 is not an independent third learned step or a new seed.

## Inputs and loss, not an answer-quality benchmark

The four authored synthetic rows are not benchmark/validation/judge-derived
gold. [Exact text, token IDs and labels](furnace/raw/primary/INPUTS.json) are
retained. Memory is written separately; query prompts are ignored by the loss,
and answer tokens plus EOS are teacher-forced. There is no free generation.

| Key | Memory tokens | Query plus answer tokens | Supervised tokens | Summed answer NLL |
| --- | ---: | ---: | ---: | ---: |
| `memory_a` | 11 | 18 | 6 | 13.065179824829102 |
| `direct_a` | 0 | 17 | 3 | 0.14059343934059143 |
| `memory_b` | 18 | 30 | 11 | 25.246957778930664 |
| `direct_b` | 0 | 20 | 10 | 32.70526123046875 |

Loss is summed per row and divided by its complete window's 9 or 21 tokens,
not averaged as equal-weight microbatch means. The two windows contain
different examples, so their losses are **not a before/after improvement
comparison**. The configured length limits are 128 memory / 128 query-plus-
answer / 32 supervised tokens; the actual maximum combined memory/query
length tested was only **48 tokens**. The configured limits are not measured
capacity claims.

## What exactly matched after restart

The [restore receipt](furnace/raw/replay/RESTORE.json) confirms exact step-1
native/master/optimizer/buffer/RNG/execution/history/cursor state restoration.
The entire [repeated step-2 record](furnace/raw/replay/step2.json) equals the
primary record: ordered row losses, accumulated-gradient hashes, transfer
receipts, update changes and all state fingerprints. Finally the checkpoint
payload state hash matches:

```text
288bb2d3b317f1222f9c3e4906ef11427854100c8c2379e13dc3fb090f2e13fe
```

See [replay](furnace/raw/replay/REPLAY.json) and the
[step-2 checkpoint receipt](furnace/raw/primary/CHECKPOINT_step2.json).
This is exact equality within the declared runtime/backend, not a tolerance
relaxation or a claim of cross-device/cross-library determinism.

## Measured resource envelope

RTX 5090, Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0, CUDA 13.2.
Two CPU threads; CPU oneDNN disabled. All limits were unchanged.

| Measurement | Primary | Fresh-process replay |
| --- | ---: | ---: |
| Role wall time | 524.793 s | 324.837 s |
| Peak CUDA allocation | 27.6903 GiB | 27.6903 GiB |
| Peak CUDA reservation | 28.2910 GiB | 28.2910 GiB |
| Peak host process RSS | 86.8090 GiB | 86.7618 GiB |
| Minimum sampled device free | 2.3281 GiB | 2.3281 GiB |
| Minimum sampled host available | 58.7706 GiB | 58.6890 GiB |

These are different measures, not interchangeable estimates of total memory.
The free-memory minima are **sampled guard points**, not continuous-monitor
minima. [Primary peak](furnace/raw/primary/PEAK.json),
[replay peak](furnace/raw/replay/PEAK.json), and each role's resource JSONL
retain the raw bytes and phases. The CUDA allocation cap remains 30.5 GiB.
The two-row CPU gradient accumulator plus staging peak was
28,992,094,208 bytes (27.0010 GiB); CPU masters and other copies are additional.
Wall times include whole-state hashing and snapshot checks, not just training.

The two checkpoint files total **58,008,756,440 bytes (54.0249 GiB)**:
29,004,378,188 bytes at step 1 and 29,004,378,252 bytes at step 2.
Both remain on Furnace; only their receipts are published in Git.
The [post-terminal read-only file check](CHECKPOINT_VERIFICATION.json)
rehashes both bodies and matches the primary receipts. Git metadata is not
a backup of the weight bytes. Replay wrote no additional checkpoint.
Final sampled free disk was **186.389 GiB**, above the unchanged 50-GiB floor.

## Verification and next gate

The copied execution bundle contains **43 files / 846,025 bytes**.
The offline verifier checks all 690 sealed source files, both qualifications,
named identities, nested manifests, fixed inputs, update denominators, exact
replay and unchanged claim ceilings. It returns
`OFFLINE_NATIVE_7B_CANARY_VERIFIED_NOT_QUALITY`; its `model_calls: 0` refers
to verification, not to the completed trial.
The publication audit also checked literal input/loss/update counts, checkpoint
receipt bindings and relative links. Scoped Ruff and `git diff --check` pass.
Execution source and historical evidence remain unchanged.

This closes the short native-memory 7B **execution and restart** gate.
Next, freeze a finite training/dev/held-out population, no-memory preservation
and irrelevant-memory examples, original-base references and prospective
quality/non-regression rules. Before using longer sequences or a larger window,
measure that declared shape separately. No full-FT pilot or quality evaluation
is launched here. See [the full-FT plan](../../../docs/v1_0/FULL_FT.md).
