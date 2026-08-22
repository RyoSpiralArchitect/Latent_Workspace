# V11 train-only elicitation calibration

The prompt comparison used only functional-train records 0–63 (1,024 balanced
world-side/query cases per condition). Candidate order, gates, and selection
rule were frozen at source commit `425cf12cafb573c6372eb939558d0bce410df53b`.

Only `symmetric_instruction` qualified:

- F1 inline: 767/1,024 = 0.7490
- F1 one-hop: 343/512 = 0.6699; Wilson lower bound 0.6281
- no recall: 308/512 = 0.6016
- yes recall: 459/512 = 0.8965
- F1 minus F0: +0.2451

The legacy prompt failed one-hop and label-recall gates. Adding only an
explicit `Answer no or yes:` cue improved overall accuracy but still missed no
recall. Combining the symmetric instruction with that explicit cue collapsed
to constant `yes`. This negative interaction is retained rather than averaged
away.

The selected instruction defines both labels symmetrically, remains in the
query branch shared by F0 and deferred O0, and does not modify dataset bytes.
Selection on train does not qualify eval. A new config and Gate-0 contract must
be frozen before the single eval rerun.
