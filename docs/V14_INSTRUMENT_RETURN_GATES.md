# V14 bounded instrument detour and Mistral return

OLMo is an engineering portability control, not a replacement research programme.
The stopping rule is frozen before any model sees this calibration set.

| Stage | Required evidence | Next action |
| --- | --- | --- |
| Structural preflight | Parsed-text oracle; paired edit validity; family-atomic splits; exact reversal balance; source/data identity | Tokenize calibration only |
| OLMo mechanical instrument | Exact prefix tokenization; direct/bypass parity; zero-up no-op; opened sidecar effect; detached gradient ownership; passive norm observation; restoration | One fixed F0/F1 calibration screen |
| OLMo screen complete | All 480 answer cases, finite logits, matched route parity and unchanged source/model snapshot | Return to Mistral **regardless of task accuracy** |
| Mistral re-entry | Same frozen screen and mechanical checks on pinned original base | Record model-specific qualification or failure, then stop |
| Future scientific experiment | Separate admission of hard-task elicitation, deferred-route sufficiency, trained reader and appropriate intervention controls | Requires a new plan; not authorized by this receipt |

Mechanical, integrity, coverage or execution failures stop the run. They do not
prove a model incapable. Preserve partial evidence; no automatic retry, fallback,
prompt search or added OLMo condition. Repairs require a new source-bound plan.
No finite categorical tie is forced into an answer. Ties are UNKNOWN, while their
continuous zero margin remains observable. Finite coverage is not accuracy.

## Fixed scope

- Existing offline snapshots only: OLMo-2-0425-1B `a1847dff35000b4271fa70afc5db10fd29fedbdf`
  then Mistral-7B-Instruct-v0.3 `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- One process/model, one SDPA condition, BF16 base and newly constructed FP32
  workspace under CUDA BF16 autocast. TF32 disabled; no cross-backend identity claim.
- Workspace LayerNorm remains LayerNorm (epsilon 1e-5); no norm sweep. The
  sidecar-only instrument uses FP32 final-logit accumulation, not global FP32 math.
- 12 calibration families: 96 primary paired records / 384 cases, plus 24 easy
  records / 96 cases. All crossed views belong to their original family.
- 12 separate held-out families remain model-unscored. Structural audits may
  inspect them; no held-out score is produced and no trained-held-out claim exists.
- Primary raw-completion symmetric instruction, choices ` no` / ` yes`, no chat
  template or added BOS/EOS. This is deliberately a matched format, not a claim
  that raw completion optimally elicits either model.
- One paired record/batch, two sides and two queries; token caps 192/96/256
  (context/query/inline); right padding to multiple 8, no silent truncation.
- 2 CPU threads, at most 90% of the GPU allocator, one active model, no optimizer,
  no parameter updates/checkpoint writes/deletion/downloads. A temporary seeded
  adapter-up probe is restored; it is not a trained checkpoint.

## Calibration task gates (not the return rule)

Compute family-cluster bootstrap confidence intervals using 4096 samples and
seed 1404. Easy F1 accuracy must be at least .75, each-label recall at least .60;
primary hard F1 accuracy at least .60, each-label recall at least .55. Both need
the 95% family interval for accuracy strictly above .50, and the interval for
paired F1-minus-F0 accuracy strictly above zero. Missing/unknown outcomes do not
support a passing claim. These are small-screen engineering thresholds, not
generalization estimates or a powered confirmatory test.

F0-to-F1 is same-target context benefit. Context-original-to-twin within one
route is donor-directed change. Never label the former donor gain. Easy full
reversals are separate controls, not primary local-edit causal evidence.

## What Mistral return does not mean

Returning means applying the portable instrument to the pinned **original base**,
not resuming an old checkpoint or a long training matrix. Existing B/F1/O3 pure
native full-update equivalence remains deferred. Fresh sidecar wiring does not
prove memory necessity, deferred sufficiency, normalization-state semantic use,
or a bridge between R and D intermediate states. Inline base tokens contain the
world facts; a sidecar influence there is not evidence that memory was necessary.

Machine-readable source/data/model bounds live in
`configs/v14/INSTRUMENT_RETURN_PLAN.json`; run receipts bind its exact hash.
