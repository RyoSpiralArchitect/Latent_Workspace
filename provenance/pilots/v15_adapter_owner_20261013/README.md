# Adapter-owned updates: graph-sharing parity, CPU qualified / CUDA pending

Client date: 2026-10-13. Execution source:
`64171c8e63642024070236ee0f7df22ecd966331`.
This additive successor to [PR #11](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/11)
does not modify the historical 7B learner, source seals or observations.

## Result and denominators

| Execution | Planned test cases | Observed | Update / resume conditions | Disposition |
|---|---:|---|---|---|
| Local isolated CPU | 71 | 71 passed, 0 failed/error/skipped | 8/8 matched; 8/8 exact next-update replay | Tiny engineering qualification only |
| Furnace isolated CUDA, first attempt | 71 | 0 collected/executed | 0/8 observed; 0/8 observed | Environment failure before model/GPU dispatch |

These are the same fixed synthetic cases on the planned two devices, **not 142
independent semantic examples**. Only CPU completed. Its eight ownership cells
are full/frozen × FP32/BF16 × gradient checkpointing off/on. Each compares two
ordered **two-pair synthetic windows** (one affected, one unaffected); the resume
test saves window 1 and reproduces window 2. They are not the real 16-pair
complete-world training window. The readout-only part exercises tiny random
GPT-2, Mistral, OLMo2 and Gemma2; **end-to-end context/owner qualification is
Mistral only**. CPU and CUDA values are not compared across hosts.

The [fixed plan](../../../configs/v15/ADAPTER_OWNER_QUALIFICATION_PLAN.json),
[source seal](SOURCE_SEAL.json), [attempt inventory](RUNS.json),
[raw CPU results](raw/cpu/FINISHED.json), [raw CUDA failure](raw/cuda/FINISHED.json)
and [derived summary](SUMMARY.json) retain the distinction. CPU wall time was
**11.824668665998615 seconds** (pytest: 8.856 seconds). Runtime was Python
3.13.13, Torch 2.13.0, Transformers 5.15.0 and pytest 9.1.1, macOS/arm64.
No CUDA peak was measured because the CUDA suite did not start.

## A useful negative control: equal loss is not equal training

The deliberate independent-forward control recomputes each factual side's
question graph. On one tiny affected pair, its scalar loss is exact but:

| CPU dtype / scope | Different base gradient tensors | Different bridge gradients | Largest absolute element difference |
|---|---:|---:|---:|
| FP32 / full | 20/21 | 0/26 | 5.029141902923584e-08 |
| BF16 / full | 20/21 | 0/26 | 0.00146484375 |
| FP32 / frozen | not trainable | 0/26 | 0 |
| BF16 / frozen | not trainable | 0/26 | 0 |

All per-tensor differences are retained in the `negative_control` properties of
[TESTS.xml](raw/cpu/TESTS.xml), not filtered to only the most interesting value.
The maxima above both occur at the token embedding. These are **negative-control
gradient differences**, not the new adapter's errors and not 7B measurements.

The old objective reuses one live normalized question graph across branches;
native-dtype gradients combine before that shared backbone backward. Separate
forwards change the placement of addition and rounding. The new adapter makes
this sharing and construction order explicit while retaining the real native
outer forward/head/postprocessing. The positive tests compare every eligible
gradient, then native weights, bridge, FP32 masters and optimizer state across
two updates. Checkpoint replay also compares owned buffers, metadata and RNG.
No tolerance was widened to make the result pass.

## What the implementation changes

- `HFTrainingReadoutAdapter`: one exclusive paired-objective graph scope, live
  prepared prefixes, exact native-boundary checks, no cross-window cache, and
  cleanup/rejection for unsupported mutations or hooks.
- `adapted_pair_objective`: the historical six terms/reductions and fixed
  two-world/eight-query supervision, with no new loss or precision policy.
- `AdapterNativeLearner`: explicit backend binding plus unchanged historical
  complete-window accumulation and CPU-master update methods. No architecture
  switch or normalization/head formula is added to the neutral owner.
- `v15-adapter-native-resume-v1`: binds runtime, arithmetic, adapter/context,
  graph policy, buffer/parameter ownership, optimizer policy, original-base
  identity, run contract and RNG. Importing state must not alias the caller's
  checkpoint payload. Original identity is **not** a preservation loss.

See the [implementation contract](../../../docs/v15/ADAPTER_STATE_OWNER.md).
Repeated native forwards make this a conservative parity reference, not a speed
optimization or a demonstrated 7B memory envelope. Old entry points remain
unchanged; nothing here silently redirects the historical runner.

## CUDA launch failure is retained, not retried

The pre-import source guard passed on Furnace: isolated Python, fresh bytecode
cache, all-untracked checks, and 299 matching source files. `/usr/bin/python3 -I`
then raised exactly `ModuleNotFoundError: No module named 'pytest'`. Its normal
non-isolated environment had found those packages in the user's site directory,
which isolation intentionally excludes. The terminal receipt contains no test
or model execution and must not be represented as a GPU parity failure or pass.

A separate existing virtual environment was subsequently checked with `-I`
and can import Torch 2.13.0+cu132, Transformers 5.15.0 and pytest 9.1.1. That was
an **import-only check, not the CUDA qualification**; no environment or other
workload was modified. Any new attempt needs a separately recorded decision and
output directory. The original failure and raw bytes remain immutable.

The pre-import check follows the [actual PR #11 review](../../../docs/v15/READOUT_REVIEW_20261013.md).
It does not cryptographically attest the Python/package runtime or defend
against a malicious concurrent filesystem owner; those remain trusted inputs.
The successful CPU receipt also records and validates the actual imported
project source paths, avoiding accidental redirection through an editable install.

## Boundaries and next step

There were **zero real-model updates, new learner sequences, judge/API calls or
weight deletions**. Tiny optimizer steps inside the tests are real engineering
operations and are not counted as zero optimizer activity. Old **FAIL / winner:
none / non-regression NOT_ESTABLISHED** and judge missingness remain unchanged.
There is no semantic improvement, FT-beta release or general model-independence
claim. Separate-model readout coverage is not universal training support.

The [next 7B migration gate](../../../docs/v15/ADAPTER_7B_MIGRATION_GATE.md)
requires CUDA qualification, a separately frozen complete-window comparison and
resource admission. Furnace reported about 44 GB disk free; the historical
contract requires a 50-GiB floor **after forecast writes**, and two additional
full checkpoints need roughly 54 GiB. An idle GPU is not sufficient admission.
Existing weights are left untouched. Semantic interaction, numerical transport
and immutable-original preservation remain later **separate factors**.

The [publication validation record](VALIDATION.md) records **507 selected CPU
regressions passed**, Ruff, old-bundle replays and source checks. This regression
set overlaps the 71-case sealed CPU qualification; the counts are not additive
independent observations. Four pytest warnings concern `record_property` under
the regression run's xunit2 output; the source-bound qualification uses xunit1.

Offline replay (no Torch or model invocation):

```sh
.venv/bin/python scripts/verify_v15_adapter_owner.py verify
```

The helper and its publication tests are post-result analysis code, not part of
the 299-file execution source seal. [Terminal handoff](EXECUTION_HANDOFF.md)
records exact locations and the deliberately unmet next gate.
