# Pinned-base elicitation before V15 learning

Date: 2026-10-10 (client date). Source: `9983e42d082a9452feedc60bb0b72d0b810795b8`.

**Execution completed; the prospectively frozen native-chat expression gate
FAILED. No method was selected and no new training was performed.**

## Question and fixed comparison

Does wrapping the same content in the pinned Mistral native chat template repair
the functional generation instrument? This is an original-base comparison, not a
workspace quality or non-regression test. Both methods receive identical user
content; native chat adds its pinned template and BOS, while raw preserves the
historical plain continuation. No demonstrations or prompt rewrites were added.

The panel has 4 exposed replay cases and 32 initially fresh confirmation cases
(8 reciprocal total-order families; 16 single-fact atomic and 16 three-hop
full-chain queries). All 640 historical exact world orders were excluded from
new family construction. Names and wording templates are reused, so this is not
an unseen-task benchmark. Two information conditions (query-only and inline),
two renderers, and two decoding regimes produce **144 prefixes / 288 generations**.
Sampling uses matched per-case, per-step uniforms; greedy uses no random draws.

The maximum is 64 new tokens with model EOS as the only early stop. Success
requires the whole stripped, casefolded answer to be `yes` or `no`, correct,
and EOS-terminated. Invalid answers and truncations remain in every denominator.
There is no first-word rescue, grammar, answer-dependent stop, or KV cache.

## Prospective primary result

The confirmation / inline / greedy cell was frozen as primary, with all 32
answers required to be valid and EOS-terminated, at least 12/16 correct in
each view, and at least 6/8 in each view-by-wording cell.

| Method | Valid whole answer + EOS / 32 | Strictly correct / 32 | Length-truncated / 32 |
|---|---:|---:|---:|
| Historical raw control | 0 | 0 | 32 |
| Native chat (prospective primary) | 24 | 16 | 0 |

| Native-chat primary view | Strictly correct | Correct yes | Correct no | Reciprocal pairs both correct |
|---|---:|---:|---:|---:|
| Atomic single fact | 9/16 | 8/8 | 1/8 | 1/8 |
| Full-chain three hop | 7/16 | 3/8 | 4/8 | 3/8 |

The native template improves termination on this panel but does **not** qualify
the instrument. Full-chain errors also include valid, single-word wrong answers;
this is not solely a formatting problem. Atomic/full-chain scores are respectively
5/8 and 3/8 for `outrank`, 4/8 and 4/8 for `ranked above`.

Across all 144 generations per renderer, raw has 17 EOS terminations, 11 valid
whole answers, 9 strict successes, and 127 truncations. Native chat has 136 EOS
terminations, 56 valid whole answers, 39 strict successes, and 8 truncations.
These totals mix query-only and inline, exposed and confirmation, greedy and
sampling; they are not a primary quality score. Query-only lacks the facts and
is not an equal-information performance control.

## Failure anatomy, not retrospective rescue

All seven invalid atomic primary outputs have a **wrong initial `yes`** on a
negative-target question, followed by an explanation, then EOS. Six contain
a later correct negation or explicit self-correction. They are not merely
correct answers rejected for verbosity. For example, case
`v15-confirmation-seed15001-family0004_atomic_d1` says:

> yes (This is incorrect because the question asks if Fenn is ranked above Eris, and the given fact states that Eris is ranked above Fenn, so the answer should be no.)

The seven initial lowercase-`yes` probabilities range from roughly 0.644 to
0.900. A capitalization alias cannot overturn their initial top-1 choice by
itself. Three full-chain cases start with capitalized `Yes`; those already count
as correct under the original casefolded whole-answer parser.

The lowercase initial-choice diagnostic is different from generation. For
inline atomic/full-chain it is 16/16 and 12/16 under raw, but 9/16 and 7/16
under native chat. Neither selected-choice scoring nor later self-correction repairs
the saved generated answer. Correct answer selection, complete answer production,
and stopping are distinct observables.

These results motivate one separately frozen, **post-result/exposed-panel**
diagnostic: score the same four symmetric answer aliases and their immediate
EOS completions on the exact same prefixes. It cannot change this FAIL or be
called new confirmation evidence. Its protocol is
[COMPLETION_MASS_PLAN](../../../docs/v15/COMPLETION_MASS_PLAN.md).

## Identity, mechanical checks, and resources

- Pinned `Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Base state SHA before/after:
  `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.
- 7 pinned tokenizer/model metadata anchors and the active chat template match;
  exact rendering/tokenization binding holds for all 144 prefixes.
- 144 initial ordinary/shared full-native logit comparisons match exactly.
  Initial plus generation shared/historical checks total 12,202.
- All 16 historical exposed/raw sequences replay exactly, including prompt IDs,
  generated IDs, full text, termination, and every token trace.
- No optimizer step, workspace checkpoint load, gain change, or source mutation.
- RTX 5090 elapsed **664.624 seconds**. Peak Torch allocation **14.1255 GiB**,
  reservation **14.2598 GiB**; sampled process peak **14.9219 GiB**; minimum sampled
  free device memory **16.4180 GiB**. The 18 GiB cap covers the Torch allocator,
  not all process/context allocations; device/process observations are sampled.

## Artifacts and reproducibility

[ANSWER_BANK.md](ANSWER_BANK.md) retains all 288 outputs, not selected examples.
[VALIDATION.json](VALIDATION.json) independently recomputes whole-answer scores,
label recalls, reciprocal pairs, paired information differences, and the frozen
gate. [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) seals the raw files.
[TESTS.md](TESTS.md) records local/remote tests and tokenizer preflight.

```sh
PYTHONPATH=src:scripts .venv/bin/python scripts/verify_v15_elicitation.py \
  --bundle provenance/pilots/v15_base_elicitation_20261010
```

Portable verification checks retained scalar/identity/resource receipts; it
does not reconstruct unretained full model logits. No LLM quality judge was
run. Semantic benefit, general quality improvement, and non-regression remain
**NOT ESTABLISHED**. V15 learning remains deferred.
