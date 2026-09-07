# V14-T0 Mistral cache-trajectory canary — 2026-09-07

The frozen, one-run mechanical gate passed. A one-time signed random residual
pulse at Mistral decoder layer 16 was written into native BF16 K/V. With all
later tokens fixed, the first future position remained exact through layer 16
and changed at every layer from 17 through 31. This is the expected causal
shape for layer-16 history being read by attention and then entering the next
layer's new K/V.

The matched no-pulse cache replacement erased the future difference exactly at
all five horizons. An independent base replay was bit exact, and transplanting
the complete positive-pulse cache reproduced the positive branch's next logits
and K/V bit exactly. Stored pulse-position hashes remained unchanged while new
positions were appended.

This trajectory persisted but did not show random-direction amplification over
the five-token path: new-position K/V L2 declined from 12.18 to 5.50 for the
positive branch and from 17.06 to 6.08 for the negative branch after the pulse
position. Full-vocabulary logit displacement also generally declined. The
all-cache L2 increased because more changed positions were retained; that is
not a Jacobian-gain estimate.

The `no`/`yes` readout is deliberately nondirectional here. Candidate argmax
matched base in every cell and horizon, and semantic qualification is
`NOT_APPLICABLE_NON_SEMANTIC_SCREEN`. The result therefore validates the
mechanical history bridge, not semantic accumulation or free-chat behavior.

The full-sequence recompute route was not bit exact to incremental cache (max
absolute logit differences 0.09375–0.1484375). This is retained as a separate
cross-shape numerical diagnostic; every causal comparison used matched
incremental cache clones.

Evidence:

- `SUMMARY.json` is the compact interpretation with the claim ceiling.
- `MANIFEST.json` binds the copied artifacts and independent recomputation.
- `raw/report.json` is the complete Furnace receipt.
- `raw/trajectory.jsonl` contains all six frozen five-cell rows.
- `raw/recomputed_metrics.json` was regenerated locally from the raw rows and
  exactly matched the metrics embedded in the report.

Run `PYTHONPATH=src python3 provenance/pilots/v14_cache_trajectory_20260907/verify.py`
from the repository root to verify hashes, source/plan identity, metrics and
the curated layer/trajectory fields without rerunning Mistral.

No optimizer, training, held-out access, free generation, semantic direction,
download, weight write/delete, retry, or sweep occurred. The next semantic run
requires a separately qualified Mistral task interface and a frozen
checkpoint-derived direction with matched controls.
