# Fixed answer-plus-EOS mass: a pre-learning diagnostic

Date: 2026-10-10 (client date). Frozen scoring source:
`012c5172788b333fdc14ca81fbcbe53c10c2e96c`.

**All 144 prefixes and 576 forced alias continuations completed. No training,
new generation, workspace loading, prompt change, or gain change occurred.**
This is a post-result diagnostic on an already-exposed panel, not a new
confirmation benchmark. The preceding 288 generated answers and their
**FAIL** expression gate remain unchanged.

## What was measured

For each exact predecessor prefix, score four frozen one-token aliases:
` no`, ` No`, ` yes`, ` Yes`. Preserve the entire original prefix, deduplicate
token-identical paths within each answer class, and reject cross-class token
collisions. All four bindings were distinct here. For each alias, score its
initial full-vocabulary probability and the conditional probability of the
pinned EOS token immediately after that alias, with full-prefix recomputation.

For class `c`, the two measurements are:

```text
start_mass(c)    = sum P(alias | prefix)
complete_mass(c) = sum P(alias | prefix) * P(EOS | prefix, alias)
```

Sums include every fixed unique alias of that class, not its best alias. Native
logits are normalized with FP64 log-softmax at temperature 1. Gold labels are
used only for accounting, never as forward inputs or candidate selectors.
We retain absolute class masses and the sum of both classes, not just a
renormalized probability conditional on this small candidate set.

This is a finite four-string path set. It is not the exhaustive probability of
every whitespace/capitalization/tokenization accepted by the old parser. It is
also not a new decoder: forced-path ranking does not rewrite generated text.

## Results on the original 32-case family panel

All cases in this table were exposed before this diagnostic. Each row contains
16 questions, eight with each label. Counts are diagnostic class-rank correctness,
not whole-generation success. The last column is the mean **unnormalized** mass
of all four immediate-EOS paths, including wrong-label paths.

| Renderer | Information | View | Original lowercase choice | Alias start mass | Alias + EOS mass | Mean covered completion mass |
|---|---|---|---:|---:|---:|---:|
| Native chat | Inline | Atomic | 9/16 | 9/16 | 14/16 | 0.573305 |
| Native chat | Inline | Full chain | 7/16 | 7/16 | 8/16 | 0.829503 |
| Raw | Inline | Atomic | 16/16 | 16/16 | 16/16 | 0.208056 |
| Raw | Inline | Full chain | 12/16 | 12/16 | 13/16 | 0.153420 |
| Native chat | Query only | Atomic | 8/16 | 8/16 | 9/16 | 0.004941 |
| Native chat | Query only | Full chain | 9/16 | 9/16 | 8/16 | 0.020001 |
| Raw | Query only | Atomic | 6/16 | 8/16 | 7/16 | 0.160773 |
| Raw | Query only | Full chain | 8/16 | 8/16 | 8/16 | 0.157145 |

For native-chat inline atomic questions, five wrong initial classifications
become correct under completion-path ranking; none move the other way. Negative
label recall changes from 1/8 to 6/8, while positive recall remains 8/8.
Reciprocal pairs with both answers correctly ranked change from 1/8 to 6/8.
Adding capitalization alone changes none of these predictions. For the inline
full-chain cell, completion ranking only changes 7/16 to 8/16; reciprocal
both-correct remains 3/8. Answer completion does not solve the reasoning errors.

Across **all 144** prompt conditions (including historical replay and missing-fact
controls), lowercase / alias-start / completion counts are 83 / 85 / 92.
Completion versus alias-start has **17 corrections and 10 regressions**, not a
uniform improvement. Those heterogeneous totals are not a quality benchmark.
Query-only has no authoritative facts; its tiny chat completion mass also
illustrates why a conditional class probability alone can be misleading.

## The seven wrong initial atomic answers

These are exactly the seven negative-target native-chat inline atomic cases
that generated wrong `yes` plus explanation in the preceding greedy assay.
Case IDs have prefix `v15-confirmation-seed15001-`. Both probability columns
below include lowercase **and** capitalized aliases followed immediately by EOS.
All initial alias-start class predictions were `yes`.

| Case suffix | P(no/No then EOS) | P(yes/Yes then EOS) | Completion class |
|---|---:|---:|---|
| family0000_atomic_d1 | 0.050487 | 0.008997 | no |
| family0001_atomic_d1 | 0.034858 | 0.044902 | yes |
| family0002_atomic_d1 | 0.138667 | 0.008095 | no |
| family0004_atomic_d1 | 0.057479 | 0.003899 | no |
| family0005_atomic_d1 | 0.304400 | 0.100509 | no |
| family0006_atomic_d1 | 0.072278 | 0.036075 | no |
| family0007_atomic_d1 | 0.062509 | 0.081306 | yes |

For `family0004_atomic_d1`, lowercase `yes` initially has probability 0.896581
versus 0.057316 for `no`. But EOS after forced `yes` has probability 0.003806,
versus 0.997918 after forced `no`. This accounts for the reversal in the finite
complete-path ranking without changing any weights. It does not establish that
the model reliably knows the answer, or that its later explanation is a causal
representation of correct reasoning. Two of the seven still rank `yes` higher.

The relevant boundary is therefore **local answer-token preference versus a
completed-answer path**, not just uppercase aliases or inadequate token budget.
The raw condition is a complementary warning: good candidate ranking can coexist
with low completion mass and failed free generation.

## Verification and the exact-replay portability limitation

The unmodified frozen verifier passed on the execution host (Python 3.14.4,
Linux x86_64, glibc 2.43). [VALIDATION.json](VALIDATION.json) is that host's
receipt. All 56 source hashes, 144 original lowercase scores/probabilities,
720 shared/historical native readout comparisons, base before/after hashes,
and tokenizer identity receipts pass. Raw files are sealed by
[ARTIFACT_INDEX.json](ARTIFACT_INDEX.json).

The same exact-summary check **fails on the local Mac**: four derived floating
probabilities differ by one FP64 ULP each (maximum absolute difference
1.1102230246251565e-16). Class log-masses, predictions, ties, counts, transitions,
and aggregate cells match exactly. The observed difference is consistent with
host math/runtime variation; its precise library cause has not been isolated.
We did not change the frozen source, widen a tolerance, replace the report's
summary, or relabel the local failure as a pass.
[PORTABILITY.json](PORTABILITY.json) records the exact local mismatch separately.
The added audit utility is diagnostic only, not a replacement verifier.

To run the frozen verifier on its pinned runtime:

```sh
PYTHONPATH=src:scripts python3 scripts/verify_v15_completion_mass.py \
  --bundle provenance/pilots/v15_completion_mass_20261010
```

Portable scalar receipts are not an independent model-logit rerun. The original
local elicitation verifier still passes; this limitation concerns the new
completion summary's bitwise cross-host reconstruction.

## Resource and scope receipts

Elapsed **45.367 seconds**; 144 initial prefixes plus 576 forced alias forwards.
Peak Torch allocated/reserved: **14.1255 / 14.2598 GiB**; sampled process peak:
**14.9219 GiB**; minimum sampled device-free: **16.4180 GiB**. The unchanged 18 GiB
cap applies to Torch, not the entire process. These are sampled device/process
observations. At completion Furnace was idle again (10 MiB, 0%, no compute
processes); no other job was interrupted. [TESTS.md](TESTS.md) records test scope.

Base SHA before/after:
`54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.
No optimizer, workspace checkpoint, deletion, or paid judge was involved.
Semantic benefit, non-regression, instrument qualification, and FT-beta release
remain **NOT ESTABLISHED**. New V15 learning is still deferred.

See the [288-answer bank](../v15_base_elicitation_20261010/ANSWER_BANK.md),
[preceding failed gate](../v15_base_elicitation_20261010/README.md), and
[updated next-step priorities](../../../docs/v15/NEXT_STEPS.md).
