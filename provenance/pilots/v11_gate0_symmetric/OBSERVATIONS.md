# V11 symmetric Gate-0 — qualified

## Question

Does the train-selected symmetric instruction qualify on the untouched eval
corpus through the exact F0/F1 wrapper paths before any optimizer update?

## Frozen design

- Source commit: `f82b4120ec1e16d984cf538177b3ff07b9f7d6b6`
- Pinned model revision:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`
- Eval bytes: 64 paired worlds, 1,024 balanced no/yes cases
- Conditions: exact `F0_query_only` and `F1_inline`
- Optimizer updates: zero
- Gate contract SHA-256:
  `6052a7d5347d90fe836261361e89e29ad75dadf78ba169e56c0228d39fb2eebb`
- Receipt SHA-256:
  `0b852e53bd65b51499571ce5d9b5c05699c06d44fdf32fd686a2c8666406e7c7`

## Result

All nine preregistered checks passed, so the instrument status is
`qualified`.

- F0: 510/1,024 = 0.4980; choice loss 0.7196
- F1: 798/1,024 = 0.7793; choice loss 0.6750
- F1 95% Wilson lower bound: 0.7529
- F1 minus F0: +0.2812
- F1 one-hop: 349/512 = 0.6816; Wilson lower bound 0.6401
- F1 no recall: 346/512 = 0.6758
- F1 yes recall: 452/512 = 0.8828
- F1 predictions: 406 no and 618 yes

Direct-base and wrapper logits were bitwise exact over 1,879,048,192 F0 and
4,026,531,840 F1 compared elements; predictions were exact in both conditions.

## Interpretation

The first raw-prompt Gate-0 failure was an elicitation asymmetry, not absence
of inline task signal. A symmetric label definition selected only on the
training split preserved both classes and raised F1 while F0 remained at
chance. This qualifies the instrument and permits the frozen V11 F1
choice-normalized positive-control pilot to begin; it does not yet validate
the training objective or workspace mechanism.

## Provenance note

The immutable raw receipt accidentally retained the legacy wording in its
top-level `question` field. Its embedded frozen contract contains the correct
question and is authoritative. The runner was corrected for future receipts;
the completed receipt was not rewritten and eval was not rerun.

## Claim boundary

This result qualifies this pinned model, dataset, symmetric instruction,
choice scorer, and exact F0/F1 wrapper path at optimizer step zero. It does not
show that V11 training improves the model, that deferred workspace routing
works, or that the V10 failure mode has been repaired.
