# V11.0 F1 update-response surface — four-update baseline promoted

## Question

Can the qualified symmetric F1 positive control survive a real full-parameter
update when only the base learning rate is varied, and can a surviving point
remain inside frozen metric and generation-behavior gates for four optimizer
steps?

## Frozen design

- Launch source commit:
  `dc1324a74367596afa2f7408ba0e9c85d8eb17ca`
- Finalizer commit:
  `0fb77586cb178930521a9639fcc7637918c585c2`
- Runtime source SHA-256:
  `2d45a3c45bdd0a56d33103e8acfa629b7256b2b38d6836f85c1aaa2f097343cf`
- Contract SHA-256:
  `4dcc8119572e9b0cfd21698a0dd8f0b911a45d0af1573314e49d49ede39bcb1c`
- Pinned model revision:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`
- Route and objective: symmetric F1 inline, `choice_normalized`, zero
  full-vocabulary loss weight.
- Held fixed: BF16 stored parameters, Adafactor, clipping, weight decay, seed
  42, the same first eight-record CPU accumulation window, and the complete
  1,024-case eval corpus.
- Single varied factor: base learning rate. The five one-update values were
  executed once in the frozen descending order `2e-5`, `6.324555e-6`, `2e-6`,
  `6.324555e-7`, and `2e-7`.
- The no-update control was the already qualified symmetric Gate-0 receipt.
- Only an eligible one-update point could authorize its pre-frozen four-update
  config. No threshold was changed after observing a result.

The canonical one-update receipt is
[`UPDATE_RESPONSE_RECEIPT.json`](UPDATE_RESPONSE_RECEIPT.json), SHA-256
`360b9ba8c31bdf35a7732d57ce94d5ee646227412a2fbc027c27c6acab60d67d`.
The four-update receipt is
[`STEP4_PROMOTION_RECEIPT.json`](STEP4_PROMOTION_RECEIPT.json), SHA-256
`8d56f695fe67d0598693629c7849081b978cb693a7eecbddb30772e2a5c19124`.

## Integrity result

Integrity is `PASS` for all five one-update runs and the selected four-update
run.

- Every run used the same runtime source digest and exactly replayed the
  qualified step-0 metrics.
- All five one-update runs had exactly the same first pre-update forward
  metrics. The four-update run replayed both that window and the selected
  point's step-1 eval exactly.
- Optimizer and all-base update coverage passed. The offload records show one
  restored accumulation window with eight ordered spills per surface point and
  four restored windows with 32 spills for the promoted run.
- The recorded `applied_lr_base` sequence is continuous with the scheduler;
  the legacy `lr_base` field is explicitly the post-scheduler value.
- Exact CPU tensor comparison covered all 291 persisted tensors and
  7,248,023,552 base-model elements.
- The four top-level remote receipts and captures were copied byte-for-byte.
  Before compacting the Git evidence set, all 54 fetched run artifacts matched
  the SHA-256 values embedded in the two canonical receipts. Repeated full
  coverage arrays and duplicate final configs from the five surface points
  were then omitted from Git; their hashes remain in the receipt and their
  bytes remain with the retained Furnace runs. Full coverage arrays are kept
  locally for the promoted step-4 run as the representative artifact.
- Local validation at the final source state: 263 passed, 3 CUDA-only skipped;
  Furnace validation: 266 passed. `ruff check .` and `git diff --check` passed
  locally.

The six final weight bundles remain on Furnace. No weight was pruned.

## One-update response surface

The no-update F1 anchor was choice loss 0.6750, full-vocabulary NLL 0.8429,
accuracy 0.7793, no recall 0.6758, and yes recall 0.8828.

| base LR | exact changed elements | changed fraction | choice loss | full NLL | accuracy | no recall | yes recall | 32-case behavior | eligible |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 2e-5 | 5,303,400,812 | 73.1703% | 14.9023 | 15.0437 | 0.5000 | 1.0000 | 0.0000 | 0.5000, all `no` | no |
| 6.324555e-6 | 2,934,410,491 | 40.4857% | 9.7336 | 10.4543 | 0.5000 | 1.0000 | 0.0000 | 0.5000, all `no` | no |
| 2e-6 | 1,093,993,746 | 15.0937% | 6.0555 | 6.4875 | 0.5000 | 1.0000 | 0.0000 | 0.5000, all `no` | no |
| 6.324555e-7 | 362,634,064 | 5.0032% | 1.4275 | 1.6259 | 0.5215 | 0.9883 | 0.0547 | 0.5312, 31 `no` | no |
| 2e-7 | 121,583,181 | 1.6775% | 0.6159 | 0.7895 | 0.7744 | 0.7578 | 0.7910 | 0.8438, both labels | yes |

Only `2e-7` passed every frozen metric and behavior gate. Its persisted change
was not a no-op: 237 of 291 tensors and 121,583,181 exact BF16 elements
changed. It therefore selected and authorized only the matching four-update
continuation.

The failure transition is sharp within the sampled grid. `6.324555e-7` still
emitted both labels, but it was almost constant `no`; every larger learning
rate became exactly constant `no` on the complete eval. The loss explosion and
changed-element fraction both fall monotonically as learning rate decreases.

## Four-update result

The frozen step-4 receipt status is `PROMOTED`; this means the F1 branch is a
usable V11 baseline under this bounded contract.

| step | choice loss | full-vocab NLL | accuracy | no recall | yes recall | classes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.6750 | 0.8429 | 0.7793 | 0.6758 | 0.8828 | 2 |
| 1 | 0.6159 | 0.7895 | 0.7744 | 0.7578 | 0.7910 | 2 |
| 2 | 0.5829 | 0.7609 | 0.7627 | 0.7773 | 0.7480 | 2 |
| 3 | 0.5720 | 0.7507 | 0.7656 | 0.7793 | 0.7520 | 2 |
| 4 | 0.5705 | 0.7486 | 0.7627 | 0.7773 | 0.7480 | 2 |

Choice loss was monotonically non-increasing across the recorded curve. At
step 4, all six pre-registered gates passed: accuracy at least 0.7, two
predicted classes, both recalls at least 0.6, choice loss below step 0,
full-vocabulary NLL at most 1.5, and behavior-veto PASS. The final model differs
from the pinned base in 140,449,235 elements, or 1.9378%, across 237 tensors.

## Generation behavior before pruning

The deterministic one-update and four-update captures are
[`GENERATION_BEHAVIOR_STEP1.json`](GENERATION_BEHAVIOR_STEP1.json) and
[`GENERATION_BEHAVIOR_STEP4.json`](GENERATION_BEHAVIOR_STEP4.json). Their
SHA-256 values are respectively
`6ef1ec936915bbf364232c687b6ca90f2f0199fcc33a18e1a8b3233956f523c6`
and
`e9827320d3ab8b304cdccbb4db35d8c19b4f7199feba1c7e8a4e676dca318482`.
`PASS` means capture integrity, not general model quality.

On the balanced 32-case inline slice, the untouched original scored 0.875
with 14 `no` and 18 `yes` predictions. The selected one-update wrapper scored
0.84375 with 17 `no` and 15 `yes`. The four-update wrapper scored exactly the
behavior threshold, 0.75, with 20 `no` and 12 `yes`. This is a warning against
reading the improving full-corpus loss as uniform behavior improvement.

The free-form surface gives a mixed, mostly conservative picture.

- Ranked-world explanation and instruction-precision completions are token-ID
  exact across original, step 1, and step 4. The first still ignores the
  requested short-sentence constraint and hits the 96-token cap; the second
  gives the same three concise numbered items in all three models.
- All three counterfactual answers confuse the unchanged relations to Oren;
  their token sequences differ, but none is a correctness improvement.
- All three mechanism-boundary answers overclaim. The four-update text still
  suggests independence or insignificant impact from a single negative
  intervention, which the prompt does not license.
- All three Japanese answers hit the token cap. The step-4 decode ends in
  replacement characters at that boundary, so the snapshot records the defect
  but cannot distinguish stable corruption from a cap-ending byte fragment.
- The creative completions remain coherent and become shorter after training,
  but none follows the requested four-line form. There is no broad qualitative
  winner.

The four high-LR one-update branches do **not** show the extreme free-form token
loops seen in the old 16-step failure. Their behavior vetoes fail because the
task answer collapses, while the bounded free-form repetition diagnostics stay
inside threshold. The one-step decision boundary is therefore the earlier and
more sensitive failure indicator here.

## Failed hypotheses and interpretation

The useful negative result is narrower than “full update fails.” Full update
does not inevitably collapse this F1 branch: `2e-7` survives and improves both
recorded losses for four steps. Conversely, merely reducing `2e-5` by about
32x to `6.324555e-7` is still insufficient.

Within this frozen setup, update scale is strongly implicated: learning rate,
the exact BF16 changed-element fraction, loss explosion, and label collapse
move together across all five points. The experiment does not identify
Adafactor, BF16 quantization, clipping, or their interaction as the unique
cause because those factors were held fixed. It also does not locate a precise
stability threshold between the two lowest sampled values.

The four-update promotion is deliberately qualified. The bounded generation
task declines from 0.84375 at step 1 to the exact 0.75 veto boundary at step 4,
and only one seed was run. This is a viable control branch, not evidence that
longer training or an active workspace will win.

## Decision and claim boundary

`2e-7` becomes the candidate V11.0 F1 full-update baseline. No O0 branch,
16-step continuation, multi-seed matrix, optimizer comparison, or 14B scaling
was authorized or launched by this contract. The retained weights allow those
choices to be made without losing this evidence.

Supported claim: for the pinned Mistral-7B model, symmetric F1 route, seed 42,
choice-normalized objective, Adafactor/BF16 implementation, and exact four-step
schedule, the `2e-7` branch passed all frozen metric and behavior gates.

Not supported: active-workspace superiority, B/F1/O3 pure-native equivalence,
multi-seed robustness, sixteen-step stability, 14B transfer, or general
capability improvement.

## Next handoff

Before making this the long-run reference, pre-register a small seed-robustness
check around the surviving low-LR basin. The natural next contract is a matched
four-step comparison at `1e-7` and `2e-7` over multiple seeds with the same
full-corpus and behavior gates. Only after a seed-stable baseline exists should
an active-workspace/O0 branch be compared against it under identical transport
and update exposure.
