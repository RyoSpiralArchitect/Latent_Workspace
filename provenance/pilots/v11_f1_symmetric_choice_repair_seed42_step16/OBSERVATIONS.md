# V11.0 F1 choice-objective pilot — scientifically blocked

## Question

Is replacing full-vocabulary answer-token cross-entropy with normalized
`no`/`yes` choice cross-entropy sufficient to preserve or improve the
qualified F1 inline decision boundary under the otherwise frozen full-update
schedule?

## Frozen design

- Launch source commit: `e823caf67a11e44ec246c267cc13234ce9d26a9e`
- Pinned model revision:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`
- Route: F1 inline positive control
- Objective: `choice_normalized`; full-vocabulary loss weight `0.0`
- Optimizer: Adafactor, base LR `2e-5`, full 7.34B-parameter update
- Transport: eight-microbatch `cpu_accumulate`
- Eval: complete 1,024-case corpus at steps 0, 4, 8, 12, and 16
- Receipt SHA-256:
  `f06f12560539fe9c51ddae2dbb28a19b6dddaba316a56258f52e6ef713d8a79b`

## Integrity result

Integrity is `PASS`. The run completed all 16 optimizer steps, the final bundle
is complete, every optimizer and base-update coverage check passed, all 16 CPU
accumulation windows were restored, 128 microbatches were spilled in order,
and no non-finite decision diagnostic was recorded. Peak live CPU accumulator
storage was 14,496,047,104 bytes.

The final weights and optimizer-bearing checkpoint remain on Furnace under
`runs/v11/F1_inline_symmetric_choice_repair_seed42_step16` (28 GiB total).
They have not been pruned.

## Scientific result

The scientific status is `BLOCKED`; all five frozen F1 gates failed.

| step | choice loss | full-vocab NLL | accuracy | no recall | yes recall | classes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.6750 | 0.8429 | 0.7793 | 0.6758 | 0.8828 | 2 |
| 4 | 2.3819 | 8.9884 | 0.5000 | 0.0000 | 1.0000 | 1 |
| 8 | 0.7015 | 14.8125 | 0.5000 | 0.0000 | 1.0000 | 1 |
| 12 | 0.6978 | 14.9688 | 0.5000 | 0.0000 | 1.0000 | 1 |
| 16 | 0.6934 | 14.9688 | 0.5000 | 0.0000 | 1.0000 | 1 |

The first training window looked locally favorable (choice loss 0.5036 and
accuracy 0.8047 on its 16 recorded cases). The second window jumped to choice
loss 14.8916 and constant `no`; subsequent train windows alternated choice
direction before every full eval settled on constant `yes`. Gradient norms
were already 502 and 1,352 in the first two steps and reached 5,024 at step 5,
with the frozen per-family clipping reducing them heavily.

## Failed hypothesis and interpretation

The objective-only repair hypothesis failed. The full-vocabulary diagnostic
still rose from 0.8429 to 14.9688 even though it carried zero loss weight, and
the constrained decision boundary collapsed immediately. This removes
full-vocabulary normalization as a sufficient explanation for V10.

Relative to the original V10 run, this qualified continuation also uses the
train-selected symmetric instruction, so it is not a strict one-factor causal
comparison against V10. The within-run conclusion is still direct: it began
from a qualified two-class boundary and the frozen full update destroyed that
boundary despite the choice-normalized objective.

The curve is consistent with an update-scale or optimizer-dynamics failure,
but this pilot does not identify Adafactor, the learning rate, BF16 parameter
updates, or clipping as the unique cause. Those factors were deliberately held
fixed and therefore remain confounded. The next useful cut is a pre-registered
one-step update-response surface on F1 before any active-workspace branch.

## Generation behavior before pruning

The deterministic behavior receipt passed its artifact and execution checks
(SHA-256
`e700959342c4c14f42b880b32d2a830b9e94c839a543101b89f9522e1c2c4d14`).
`PASS` here means the capture is complete, not that the trained behavior is
good.

On the same symmetric task prompt, the original model scored 0.875 on the
selected 32 inline cases and emitted both labels (18 yes, 14 no). The V11 final
scored 0.500 and emitted `yes` for all 32 cases.

The six chat-templated free-form prompts also separated sharply. The original
produced coherent English and Japanese responses across reasoning,
instruction-following, mechanism-boundary, and creative prompts. The trained
base trunk exhausted the 96-token cap on every prompt with repetitions
dominated by `#`, `no`, and `Question`; examples include 96 repeated `#`
tokens for the ranking prompt and repeated `no` for the Japanese prompt. All
six completion token sequences differed from the original.

This qualitative evidence agrees with the full-vocabulary NLL explosion: the
failure is not merely a tied or poorly calibrated `no`/`yes` scorer. The saved
base trunk's general generation behavior was materially damaged within 16
updates.

## Decision and claim boundary

O0 was not launched because F1 did not pass. The 57-run matrix and 14B scaling
remain blocked. This run proves an auditable negative result for one seed and
one frozen schedule; it does not show that choice-normalized training is
generally harmful or that a stabilized full update cannot work.
