# Transport v2 generation behavior: first pre-prune record

## Question

Before deleting the one-step transport-pilot weights, what qualitative behavior
is visible relative to the pinned original Mistral model, and does the new
`cpu_accumulate` transport remain behaviorally exact to its old-spill B
reference?

## Frozen design

- Original: `mistralai/Mistral-7B-Instruct-v0.3` at
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Trained bundles: seed 42, one full-parameter optimizer step, gradient
  accumulation 8, conditions F0, B, F1, and O3.
- Free-form surface: six fixed prompts, chat template, greedy decoding,
  `max_new_tokens=96`, seed `20260822`. Trained rows use the saved base trunk.
- Task surface: functional eval worlds 0 and 1, all eight queries on both sides,
  one-token choices `no` and `yes`. This gives 32 cases with 16 examples of each
  expected choice, 8 affected and 24 unaffected cases, and 16 heldout and 16
  non-heldout cases.
- Complete trained wrappers use their saved route: F0 query-only, B deferred,
  F1 inline, and O3 deferred with an active injection scale.
- B candidate versus B old-spill reference is an exact behavioral sentinel.

The canonical receipt is
[`GENERATION_BEHAVIOR_V1.json`](GENERATION_BEHAVIOR_V1.json), SHA-256
`f84815721d5b9eb32c96400df8e942f2e029081112a79aa3841f2966e96c3b7a`.

## Integrity result

`PASS`.

- B and B-reference completion token IDs match for all six free-form prompts.
- Their complete task choice-logit tensors and selected predictions also match
  exactly.
- A second capture after repairing the task selection reproduced every
  free-form token sequence and every complete trained task-logit tensor from
  the first capture.
- F0, B, and B-reference are exact on all six free-form completions and on all
  32 task choice-logit rows. O3 shares their ranked-world and counterfactual
  completions but differs on the other four prompts. F1 forms its own completion
  group on all six prompts.

This is a positive transport-integrity result. It is not a positive model
behavior result.

## Task-native result

| Model surface | Correct | Behavior |
|---|---:|---|
| Original, query only | 16/32 | 0.500; no usable context dependence |
| Original, inline context | 26/32 | 0.8125; predictions change with world text |
| F0 complete wrapper | 16/32 | predicts `no` on all 32 cases |
| B complete wrapper | 16/32 | predicts `no` on all 32 cases |
| F1 complete wrapper | 16/32 | predicts `no` on all 32 cases |
| O3 complete wrapper | 16/32 | predicts `no` on all 32 cases |
| B old-spill reference | 16/32 | exact match to B |

The mean `yes - no` logit gap is `-5.3984` for F0/B/B-reference,
`-1.2773` for F1, and `-5.6250` for O3. Every trained row remains negative,
so the nominal 0.5 accuracy is only the balanced-class constant-`no` baseline.
The bounded sample therefore shows no task-native answer differentiation after
one optimizer step. O3's active workspace route does not rescue the selected
behavior.

The original inline score is only an anchor. It does not make the original
model architecture-equivalent to a functional-workspace wrapper.

## Free-form observations

### Ranked world explanation

The original gives the correct `yes` and a long transitive explanation but hits
the token cap. F0/B/O3 give a short, correct but redundant `yes, yes` response.
F1 gives `no` and an invalid explanation. Concision improved in three branches,
while F1 regressed on correctness.

### Counterfactual update

No branch gives a reliable answer. The actual adjacent Mira/Niko swap changes
their mutual ordering while preserving both relations to Oren. The original and
F0/B/O3 instead describe Mira/Oren or Niko/Oren changes and contain internal
contradictions. F1 becomes notation-heavy and is truncated. There is no
qualitative improvement to claim.

### Instruction precision

All branches produce three numbered points with short clauses. The original is
the cleanest direct response; F0/B add an unnecessary preamble, F1 adds blank
spacing, and O3 remains compact. This small prompt does not expose a large
capability difference.

### Mechanism boundary

Every branch overclaims. The prompt permits only the bounded conclusion that
the tested intervention did not change the tested answer. The models instead
infer that the hidden signal was not directly influenced, was caused by other
factors, or was independent. None cleanly preserves the requested causal claim
boundary.

### Japanese synthesis

F0/B/O3 more directly mention recording implementation validation separately
from statistical support, but their wording leans on `証明` and all hit the
96-token cap. The original and F1 fall back to generic experiment-note lists and
also truncate. The sample suggests a shift in framing, not a verified quality
gain.

### Creative four-line scene

Only F1 obeys the four-line form and avoids the banned words. The original,
F0/B, and O3 produce a single paragraph or line. This is a localized
instruction-following improvement for F1 despite its regressions on the
reasoning prompts.

## Failed capture design preserved

The first task selection used queries `[0, 2, 4, 6]`. That created 14 expected
`yes` rows and only 2 expected `no` rows, making the trained constant-`no`
behavior appear as 0.125 accuracy. The result was rejected as a comparison
design, not interpreted as a model result.

The rejected receipt is retained at
[`negative_evidence/GENERATION_BEHAVIOR_V1_UNBALANCED_SELECTION.json`](negative_evidence/GENERATION_BEHAVIOR_V1_UNBALANCED_SELECTION.json),
SHA-256
`a97dd7b4c0256e9e8e8f1e1556d27e85738650b12bd99da989909442e817dc3b`.
Its exact free-form outputs and complete trained task logits match the canonical
rerun; only the reporting selection was repaired.

## Interpretation

The workflow succeeded as an engineering and retention mechanism: it caught a
biased qualitative slice, preserved that failure, forced a balanced rerun, and
added exact behavior-level evidence to the existing tensor/state parity.

The first scientific-facing observation is negative. After one optimizer step,
the trained task surfaces collapse to a constant choice on this bounded sample,
and the open-ended prompts show a mixture of concision, instruction-following
changes, factual mistakes, truncation, and causal overclaiming. There is no
single favorable ranking across F0, B, F1, and O3.

## Claim boundary

- This is a deterministic six-prompt and 32-case snapshot, not a statistical
  benchmark, blinded human study, safety evaluation, or broad quality result.
- The models ran for one optimizer step; the observations do not predict a
  long-run outcome.
- Free-form rows exercise trained base trunks only. Task rows separately
  exercise complete wrappers with constrained one-token answers.
- Several outputs stop at the 96-token cap, so incompleteness must not be read as
  a stable stylistic property.
- Exact B/B-reference behavior is bounded to the captured artifacts, inputs,
  software, and RTX 5090 run. It does not establish all-input or cross-runtime
  behavioral equivalence.
- No result here supports causal memory, useful latent transport, model
  superiority, or selection of a winning scientific branch.

## Provenance

- Engine SHA-256:
  `967f49b9d54b23a4c2382608e318b1e63974aef3ea1bf9c4c4f20c22ef4df494`
- Capture script SHA-256:
  `1fcedebd2856fe236a6232de428571e41dc84e8cb3f28d92c7fd0b592fe11661`
- Prompt suite SHA-256:
  `f3710a323b876fd42da19b2c4a97e6fd303b67c0db338da53c57209177979373`
- Functional eval SHA-256:
  `fcd7bdd3966cbcd0fd02315ee76c813aaf51b82f913abdd074f1585d5958386e`
- Original local runtime snapshot inventory SHA-256:
  `853b0c6a6f67661ff08bdc43f9dafd136ec1362645aa2828fb1f2299bc23957c`

The receipt additionally binds each final manifest, experiment config,
workspace state, and every saved base-model file.

## Next handoff

Make this capture plus human observation note mandatory for future retained
checkpoints before pruning. For a longer run, freeze the prompt suite before
training, keep the balanced task contract, add selected intermediate
checkpoints only if storage permits, and treat constant-choice behavior as a
blocking diagnostic rather than allowing aggregate accuracy to conceal it.
