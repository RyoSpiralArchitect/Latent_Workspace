# V11 Gate-0 attempt 1 — blocked

## Question

Can the pinned Mistral-7B base, through the exact current grouped-world wrapper
and raw double-newline elicitation, support F1 inline discrimination before any
optimizer update?

## Frozen design

- Source commit: `8e73d9f8f6d906fce6d754ffcc259696817ab869`
- Eval bytes: 64 paired worlds, 1,024 balanced no/yes cases
- Conditions: exact `F0_query_only` and `F1_inline`
- Optimizer updates: zero
- Gate contract SHA-256:
  `985c9f4703220429626134240a7521b6947d80af0039949b945c4703d9a5627e`

## Result

Integrity checks passed. Direct-base and wrapper logits were bitwise exact over
536,870,912 F0 and 2,625,634,304 F1 compared elements; predictions were exact
and the targets were 512/512 balanced.

The capability signal was real but asymmetric:

- F0: 498/1,024 = 0.4863
- F1: 684/1,024 = 0.6680
- F1 minus F0: +0.1816
- F1 one-hop: 324/512 = 0.6328; 95% Wilson lower bound 0.5902
- F1 no recall: 218/512 = 0.4258
- F1 yes recall: 466/512 = 0.9102

Eight of nine checks passed. The preregistered minimum 0.55 recall for each
label failed on `no`, so the overall Gate-0 status is `blocked`.

## Failed hypothesis and interpretation

The raw elicitation is not simply at chance: overall and one-hop F1 both clear
chance, and F1 improves materially over F0. However, the stronger hypothesis
that it is already a symmetric two-label instrument failed. The base has a
large yes bias (760 yes predictions versus 264 no predictions), which would
make early constant-choice dynamics harder to interpret.

The threshold will not be relaxed after observation. V11 training remains
unlaunched. Elicitation candidates must be compared on a frozen subset of the
training corpus, after which a new prompt contract may be tested once on eval.

## Claim boundary

This attempt establishes wrapper parity and a non-chance inline signal for the
pinned raw prompt. It does not qualify the instrument, establish the cause of
V10 collapse, or test the V11 choice-normalized training objective.
