# V15 full native backward: live 7B routes and CPU restoration verified, no update

2026-10-10 · **COMPLETED_FULL_BACKWARD_NO_STEP**.

The separate live-backbone path completed **all six planned backward pairs**
(two diagnostic states × three exposed pairs). Every pair had finite, nonzero
gradients in **all 291 physical base parameter tensors**, including embeddings,
all decoder layers, RMSNorm parameters and the full language-model head.
The retained step-8 bridge also carried nonzero gradients through its context
input and question-reader input. This establishes a bounded differentiable
execution path, **not useful content learning or a full-update training result**.

Both CPU accumulation windows restored **317/317 gradient tensors exactly**
against a separately maintained same-order CPU reference. Base and bridge
weights remained hash-identical. No optimizer was constructed; update count,
new generations, judge calls and weight deletions are all **zero**.

## Identity, scope and denominators

The prospective [protocol](../../../docs/v15/FULL_UPDATE_BACKWARD.md) and
[plan](../../../configs/v15/FULL_UPDATE_BACKWARD_PLAN.json) were committed locally
before execution at `8d723ac17dd009760b3066477539f80b6f82cac9`. The
[source seal](SOURCE_SEAL.json) binds **276 source/data files**, copied to a
separate Furnace checkout without a GitHub push. The old frozen classes and
historical bundles were not modified.

The prior native-only stage is conceptually **V14.5**. Historical `v15_5` names
remain immutable identifiers. This V15 unit adds live contracts and backward
qualification; it does not claim that the project never ran full updates before.

- Base: original Mistral-7B-Instruct-v0.3, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`, BF16, all parameters eligible.
- Base tensor hash before and after:
  `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.
- Bridge: unchanged FP32 4,200,192-element / 26-tensor architecture, final reader,
  boundary-16 context writer, cap 1.0. Two separately loaded states: exact fresh
  seed-47 initialization and the retained answer-only step-8 checkpoint from
  the [native pilot](../v15_5_native_answer_20261010/README.md).
- Three distinct exposed input pairs, all from world 0: queries 0 and 1 are
  reciprocal affected questions; query 2 is unaffected. Six side targets per
  state comprise four `yes` and two `no`. **This partial window is not balanced
  training, not six independent tasks, and not the complete 16-pair objective.**
- The unchanged answer/EOS, affected, unaffected, unrelated and residual
  denominators remain **32/4/12/16/48**. EOS coefficient is zero, but the two
  answer-conditioned completion paths per pair are still evaluated.
- Native chat/Answer cue and serialization match the historical pilot.
  Non-reentrant activation checkpointing and the existing CPU accumulation
  implementation are used. No hidden feature cache, KV carry or early step.

[STARTED](raw/STARTED.json) records runtime and settings; [REPORT](raw/REPORT.json)
records terminal success and unchanged identity. All **21 raw files** are listed
in [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json); the offline
[SUMMARY](SUMMARY.json) retains the six pairs, not just aggregates.

## What reached backward

The following counts hold separately within each diagnostic state.

| Measurement | Initial seed 47 | Retained answer step 8 |
|---|---:|---:|
| Completed paired backward passes | 3/3 | 3/3 |
| Base tensors with present, finite, nonzero gradient, each pair | 291/291 | 291/291 |
| Bridge tensors with present gradient, each pair | 26/26 | 26/26 |
| Bridge tensors with nonzero gradient, each pair | 1/26 | 26/26 |
| Context-to-writer observations with nonzero gradient | 0/9 | 9/9 |
| Query-to-reader observations with nonzero gradient | 0/15 | 9/15 |
| Normalized query/completion observations with nonzero gradient | 3/9 | 3/9 |
| Restored gradient tensors equal CPU reference | 317/317 | 317/317 |

At initialization the bridge's zero output projection blocks upstream workspace
gradients as expected; only that projection receives a nonzero bridge gradient.
The direct backbone-to-answer path still reaches every base tensor. Do not
mistake broad base gradient coverage for successful memory learning.

In the retained state, context-to-writer nonzero gradient norms range from
**1.319782e-7 to 4.409437e-4**. Query-to-reader nonzero norms are only
**4.383368e-12 to 9.940400e-9**, while the original normalized query's total gradient
norms range **0.004734164–0.013099664**. These are gradients at different graph
locations, not an optimizer-step decomposition or a measured causal ratio.
They reinforce weak reader-question coupling as an open hypothesis; they do
not demonstrate that unfreezing repairs it.

The six zero query-to-reader observations in the retained state correspond to
the two zero-weight EOS completion paths per pair. Those forwards remain in the
graph; their lack of nonzero gradient is not hidden missingness. Likewise, only
the original query feature receives a nonzero gradient among each pair's three
query/completion feature observations. All declared hooks fired once.

The same-order CPU reference compares **7,252,223,744 gradient elements** per
state, including the base and bridge. It is not an independent GPU-add oracle,
not an optimizer-state comparison and not proof of long-run numerical parity.

## Native and historical controls

Each state checked three prefixes against ordinary current-base full logits:
shared zero-delta and written-slot-zero both matched exactly. Across two states,
that is **six prefix checks with two zero-path comparisons each**. All **12**
intact/twin native two-choice vectors also matched the corresponding previous
pilot records exactly. No score or parser was adjusted.

The [initial](raw/initial_seed47_PARITY.json) and
[retained](raw/retained_answer_step8_PARITY.json) parity files are saved before
backward; each pair has a forward-only receipt followed by a completed backward
receipt. The [initial window](raw/initial_seed47.json) and
[retained window](raw/retained_answer_step8.json) retain restoration hashes and
all accumulated gradient norms.

Written-zero parity here is with the unchanged original base. The tiny tests
also distinguish **current updated theta** from **original theta**: after a
synthetic parameter mutation, zero still matches the current ordinary model but
not its old output. Future full FT needs a separate original-base correctness
floor; this engineering identity cannot replace it.

## Resource observations

Both states together completed in **106.127638 seconds** on Furnace RTX 5090,
Python 3.14.4, Torch 2.13.0+cu132, Transformers 5.15.0 and CUDA 13.2.

| Counter | Observation |
|---|---:|
| Peak Torch allocated | 28.223701 GiB |
| Peak Torch reserved | 29.345703 GiB |
| Sampled own-process GPU memory peak | 30.070312 GiB |
| Minimum sampled device-free memory | 1.210938 GiB |
| CPU accumulator + staging peak, each state | 27.032286 GiB |
| Additional independent CPU gradient-reference tensor volume | 13.516143 GiB |
| Minimum sampled available host RAM | 73.342434 GiB |

There are **23 GPU and 23 host phase samples**, not continuous monitoring.
Allocator, process and device counters have different scopes. In particular,
the 28.22-GiB allocated peak must not be translated into four GiB of usable
optimizer headroom: the sampled free minimum was only 1.21 GiB. Temporary
Adafactor buffers, checkpoint saving, a 16-pair window and training throughput
were **not tested**. No fit or speed guarantee for an optimizer step follows.

Each three-pair CPU window retained an accumulator and staging buffer, then
released both after restore. The extra unpinned reference was diagnostic
overhead, not a required production training allocation. No backward tensor or
backbone checkpoint was saved. Postflight found no GPU compute process and
approximately 117.42 GiB free disk; no other job was stopped or weights pruned.

## Validation and next boundary

- [Local prelaunch](PRELAUNCH_VALIDATION.json): 118 native/full-path tests plus
  four selected engine/checkpointing tests passed; local Ruff passed.
- [Remote prelaunch](REMOTE_PRELAUNCH_VALIDATION.json): the identical 118 + 4
  tests passed on the exact execution source. Remote Ruff was not run.
- Eight additional local offline corruption/replay tests passed. Source hashes,
  model identity, gradient/route/CPU-reference denominators and raw-file hashes
  replay. This is **not independent model/gradient recomputation**.
- The old native pilot, original/continuation judge and cue-bundle receipts
  remain separate; their failed gates and missingness are not promoted by this
  backward result. See [terminal handoff](EXECUTION_HANDOFF.md).

The next proposed unit is a separately bounded **complete-window + one-update
and save/reload audit**, then a short matched frozen/full comparison. Match
bridge optimizer, initialization, objective and budget; retain EOS and reader
changes as separate factors. Actual BF16 parameter changes and optimizer peak
memory must be observed, not inferred from the present nonzero gradients.
No real-model optimizer step was started in this unit.

Current scientific status remains **old expression gate FAIL**, `winner: none`,
`non_regression: NOT_ESTABLISHED`. No fresh generated behavior or base-floor
result exists. The judge heartbeat remains paused. Source/results are local
branch commits only; no GitHub push, PR, merge or CI result is claimed.

Safe offline replay, from the repository root:

```sh
.venv/bin/python provenance/pilots/v15_full_update_backward_20261010/inspect_results.py
.venv/bin/python -m pytest -q provenance/pilots/v15_full_update_backward_20261010/test_inspect_results.py
```

Do not rerun the completed real-model probe or pass `--write` over existing
derived artifacts.
