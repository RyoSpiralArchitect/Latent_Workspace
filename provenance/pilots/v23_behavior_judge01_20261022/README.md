# V23 blind behavior judge 01

## Calibration complete; study blocked by incomplete P-on generation

New-rubric calibration **PASS: 32/32 valid, 32/32 expected preferences**.
All 16 normalized AB/BA comparisons agree, as do all 16 same-order repeat
comparisons. Eight analyst fixtures are not independent human gold. This is
judge admission evidence, **not** a learner-quality result or release gate.

Provider/model: Mistral `mistral-large-4`, requested and returned ID confirmed.
The service's underlying weight revision is unknown; it is the same provider
family as the evaluated Mistral host, not a cross-family consensus. OpenAI's
historical calibration failure is untouched. No other provider is called.

Calibration source: `62834104f4e3ced2bc61375b66561045c675e101`, recorded in
`calibration/SEAL.json` and verified against the committed source bytes.
Started `2026-10-21T23:00:23.562960+00:00`, finished
`2026-10-21T23:06:46.268070+00:00`; 32 single attempts, no invalidities,
timeouts, retries, missing calls or substitutions. Reported token usage:
15,408 prompt + 30,670 completion = **46,078** total. Actual invoice cost is
unknown. Raw responses, reservations, validation, bodies, model metadata and
terminal file manifest are retained under `calibration/`.

The [frozen protocol](../../../docs/v23/ADDITIONAL_EVALUATION_01.md) allows
174 subsequent study requests only after the original base/off/on generation
bank completes and verifies. All 72 free answers are required, not merely
changed answers. The original comparison run is never modified/restarted.

Offline replay (no key or model call):

```sh
python3 -B scripts/v23_behavior_judge.py verify \
  --output provenance/pilots/v23_behavior_judge01_20261022/calibration
```

The replay verifies request bodies, source hashes, response manifests, strict
envelopes and exact quote substrings. Quote validation proves textual presence,
not correctness of an interpretation. `BLIND_PACKET.json` is the manual review
transfer; operator mappings/expectations are separate and must not be supplied
to a blind reviewer. Old **FAIL / winner:none / non_regression NOT_ESTABLISHED**
is unchanged. Study status is **NOT_DISPATCHED: 0/174**. The concurrent
[comparison's operator isolation failure](../v23_comparison01_20261022/README.md)
left P-on incomplete. We do not replace the required 72-answer bank with only
the available 48 answers, change selection, or rerun calibration until a pass.
No provider failure or calibration failure caused this block.
