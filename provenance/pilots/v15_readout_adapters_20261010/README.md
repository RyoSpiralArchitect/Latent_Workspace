# V15 readout adapters: differences survive, but the answer route still fails

Client date: 2026-10-10. **Read-only qualification, not a new trained candidate.**
Execution source: `a078c4d6ee0ff456ef075bf8c2979c639f1b8360`.

## Outcome and denominators

The [new model-independent core and explicit HF backend](../../../docs/v15/READOUT_ADAPTERS.md)
preserve the original model's complete forward, including native normalization
and post-head transformations. The retained Mistral comparison gives **192/192
bit-exact old/new full-logit outputs**, **192/192 historical native-choice
replays**, and **64/64 current-base written-zero identities**. Four final states
each contribute 16 queries × intact/twin/zero = 48 outputs. There are **64
intact/twin transport pairs**, including **16 affected pairs** (four per state).
These are repeated measurements on the same two exposed worlds, not 64 new
independent semantic examples or a fresh held-out benchmark.

The key localization is more precise than “BF16 erased the hidden difference”:

- All **16/16 affected pairs retain nonzero native hidden differences**. The
  FP64 diagnostic projection of those applied differences is also nonzero.
- All **64/64 pairs change some actual vocabulary logits**, but **0/16 affected
  pairs change either of the two no/yes logits**. Their gap is zero at the raw
  native head already, before any model-level postprocessing.
- The intended diagnostic direction aligns with the donor on only **2/4 per
  state**. Preserving more precision alone would not establish reciprocal
  content binding. In the full-updated state, one of those aligned directions
  reverses during hidden composition/casting, leaving **1/4** aligned there.
- All **64/64 paired greedy next-token decisions remain identical**. This is
  next-token inspection, **not** 64 newly generated sequences.

The following table is checked against the [offline summary](SUMMARY.json).
The first two direction columns are linear FP64 diagnostics of production
residuals, **not native logits or accuracy**. Changed vocabulary uses all 16
pairs per state; the direction columns use the four affected pairs only.

| Retained state | Intended donor-aligned | After hidden cast | Native donor-aligned | Changed vocabulary |
|---|---:|---:|---:|---:|
| reader/legacy step 8 | 2/4 | 2/4 | 0/4 | 16/16 |
| reader/query_modulated step 8 | 2/4 | 2/4 | 0/4 | 16/16 |
| full/frozen step 2 | 2/4 | 2/4 | 0/4 | 16/16 |
| full/full step 2 | 2/4 | 1/4 | 0/4 | 16/16 |

There is **one nonzero native no/yes gap change among all 64 pairs**, and it is
on an **unaffected** question: full/full, world 1, query 5, `-0.125`. The intended
linear change there is `-0.0010017703378625738`, and the after-input-cast linear
change is `-0.0007717762782704085`. Its greedy token still does not change.
This is a counterexample to both “nothing reaches logits” and “native visibility
implies useful factual selection.” It is not a newly discovered donor success.

## Exact illustrative transport rows

These scalars come from [the full-updated panel](raw/full_full.json), with gap
defined as `logit(yes) - logit(no)` and changes as twin minus intact. Donor sign
is applied only afterward; it is never an inference input.

| Coordinate | Donor sign | Intended linear change | After input cast, linear | Actual native head change | Changed vocabulary entries |
|---|---:|---:|---:|---:|---:|
| world 0, query 0 | -1 | -0.00003579399190128951 | 0.00009443046292290092 | 0.0 | 247 |
| world 1, query 0 | -1 | -0.001021967485162206 | -0.0010637626724019356 | 0.0 | 864 |

The first row loses its intended direction before the head; the second retains
that projected direction through the native hidden cast, but it is not visible
in the two answer logits. The latter discrepancy belongs to the **native head
arithmetic/output stage as a whole**; this assay does not identify the internal
accumulator precision of an individual GPU kernel. Mistral's model-level
postprocessing contributes zero gap residual here. None of these scalar probes
replaces the complete native head during training, evaluation or decoding.

## What is implemented and verified

The opt-in adapter protocol separates reader/query policy from model-owned
normalization, native head execution and published logits. The first HF backend
admits exact GPT-2, Mistral, OLMo2 and Gemma2 classes at Transformers 5.15.0.
It adds no parameters and preserves live gradients. Unsupported layouts,
concurrent/recursive adapter calls, replaced parameters, offload wrappers,
pre-existing head hooks and incomplete head geometry fail closed.

**63 local CPU tests** cover these four tiny randomly initialized architectures,
FP32/BF16, full and frozen gradients, written-zero identity, exception cleanup,
anchored query extension, ambient autocast, and checkpointed backward. A native
head-hook reference matches outputs and every parameter gradient. Mistral also
matches the old learner's answer/EOS objective and gradients exactly. Gemma2's
test uses a deliberately small softcap to expose the difference between raw
head and model-published logits. It is not evaluation of a trained Gemma model.
The relevant prelaunch selection passed **189 tests on Furnace**. Broader local
source regressions passed **402 tests**, before the added publication tests.
The final combined source/publication selection passed **414 tests**; Ruff and
offline source/artifact/literal-number checks also passed. These are local
verification receipts, not GitHub CI or merge status.

The sealed `V15NativeLearner` and its optimizer/resume format are **not** migrated
by this patch. This is a qualified readout component and differentiable CE path,
not a claim that the full 7B optimizer owner now supports arbitrary models.
KV carry, padding/batching, compiled/distributed execution and `generate()`
integration remain outside this backend's contract.

## Provenance and reproducibility

The [298-file source/input seal](SOURCE_SEAL.json) binds the new code and old
inputs. [Eight raw files](ARTIFACT_INDEX.json) retain all rows, paired stage
measurements, process/resource observations and terminal receipts. The fixed
[plan](../../../configs/v15/READOUT_ADAPTER_PLAN.json) was committed before
execution. Checkpoint file hashes and state hashes were checked before load;
native base and reader content hashes were checked before and after each state.
The full state was reconstructed from its saved FP32 masters, without an
optimizer. No checkpoint file was changed or deleted.

Execution took **168.43507570493966 seconds**, with **14.195143222808838 GiB**
peak Torch allocation and **14.388671875 GiB** peak reservation. It completed
without a retry. There were **zero optimizer steps, zero new learner sequences
and zero judge calls**. The previous generation bank and failure metrics are
unchanged; [the handoff](EXECUTION_HANDOFF.md) provides machine paths.

Offline reproduction and publication checks:

```sh
python scripts/summarize_v15_readout_adapters.py --bundle provenance/pilots/v15_readout_adapters_20261010
pytest -q tests/test_readout_adapters.py tests/test_readout_adapter_receipts.py
```

## What to carry into the next learner change

Keep the common-response route, query-independent writer, strict zero identity,
full native output contract and previous exact-resume state ownership. The
data now support separating **semantic selection** from **numerical transport**
in the experiment design, not declaring either solved.

1. First qualify adapter identity inside complete-window/checkpoint metadata
   with a matched one-update/resume migration, without changing the objective.
2. Test a separately budgeted common-response versus query/content-interaction
   path as one representation/update factor. The old donor loss already targets
   reciprocal interaction; duplicating it is not the proposed repair. Keep a
   matched parameter/resource control and the existing diagnostic controls.
3. Treat any output-precision change as a separate, named **model adapter**
   intervention. It requires a newly matched direct-base control; it must not be
   silently presented as native equivalence. The present 2/4 projected direction
   is a reason not to promote a higher cap or higher precision alone.
4. Independently own a pinned-original preservation reference. Exact zero against
   updated theta does not repair the previous original-base regressions.

These are proposals, not executed additional training. **Old FAIL, winner: none,
and non-regression NOT_ESTABLISHED remain unchanged.** The closed judge study
also remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`; this audit adds no judgments.
