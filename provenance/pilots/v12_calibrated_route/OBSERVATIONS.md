# V12.0-V12.3 calibrated inline sidecar - stable but redundant

## Question

Can a pinned Mistral-7B inline baseline be preserved exactly while a new
workspace sidecar is calibrated, updated without touching the base, and then
compared under matched task-only and semantic objectives after controlled base
release? If both branches remain stable, does the semantic sidecar become
content-specific and causally load-bearing?

## Frozen design

- Launch source commit:
  `fbcd9178934cbc02758fa3695c94798317a796a4`
- Finalizer commit:
  `57cefff535f2fc1e7f2dc670255aab29ea84c477`
- Runtime source SHA-256:
  `aee2a1fe3b95c6c0ff21d89870c0d3bb959da28fc544aaa9aced7ccc0abae133`
- Contract SHA-256:
  `3dd0fe81f5519c9721430c8ae259f3739b6b69e99cb6dda0cc4fca79d7536a60`
- Pinned model:
  `mistralai/Mistral-7B-Instruct-v0.3@c170c708c41dac9275d15a8fff4eca08d52bab71`
- Original runtime snapshot inventory SHA-256:
  `853b0c6a6f67661ff08bdc43f9dafd136ec1362645aa2828fb1f2299bc23957c`
  over 11 files and 14,498,796,037 logical bytes.
- Route: `inline_sidecar` at boundary layer 16, four slots, zero-initialized
  logit residual, initial sigmoid gate about 0.119, BF16 base parameters, and
  detached context/query features for the semantic auxiliary path.
- Task objective: choice-normalized loss. Semantic cells add counterfactual
  weight 1.0 and stability weight 0.25; task cells set both to zero.
- Workspace LR surface: `1e-5`, `3e-5`, and `1e-4`. Base LR after release:
  `1e-7`.
- Seeds: 43, 44, and 45. Evaluation uses the complete 1,024-case functional
  corpus. Generation behavior uses the frozen six-prompt suite and balanced
  32-case task-native slice.
- V12.0 requires exact no-op equivalence. V12.1 selects one workspace LR after
  one frozen-base update. V12.2 runs both branches for four frozen-base
  updates. V12.3 runs both branches for 16 updates: four frozen-base updates,
  followed by 12 matched full-base updates.
- The final decision rule was frozen before execution. `stable_redundant_sidecar`
  means the semantic branch is robust but content-specific necessity does not
  replicate. It is not a winning-branch label.

## Integrity result

Integrity is `PASS` for the final V12 receipt.

- V12.0 compared 4,026,531,840 full-logit elements. Routed and amputated full
  logits, choice logits, predictions, metrics, and their hashes were bitwise
  exact; every recorded delta was zero.
- In V12.1 and V12.2, base sentinels stayed exact, base optimizer state stayed
  absent, and the workspace optimizer acquired state and changed the
  zero-initialized output sentinel.
- Every V12.3 cell records exactly four frozen ownership rows followed by 12
  released rows. Frozen rows have no base update and no base optimizer state;
  released rows have nonzero base updates. All ownership checks passed.
- Exact CPU comparison covered all 291 persisted base tensors and
  7,248,023,552 elements for every final checkpoint.
- Generation behavior was captured before any weight pruning. All six F0-F5
  necessity receipts were bound to the final checkpoints and runtime source.
- The 16 compact files in this directory were copied from Furnace byte for
  byte; every local SHA-256 matched its remote source.
- Local validation at the final implementation state: 293 passed and 3
  CUDA-only skipped. Furnace validation: 296 passed.
- During the 16-step matrix, the CUDA allocator repeatedly failed optional
  20 MiB expandable-segment mappings with only about 9-18 MiB free. The runs
  completed using already reserved memory, but this is negative performance
  evidence: the 7B configuration had effectively no VRAM headroom.

Two no-op attempts failed before any scientific optimizer step. The first
found that the ordinary Hugging Face cache held only tokenizer/config files;
the second exposed a scalar byte-view bug in exact tensor comparison. Their
receipts are retained here. The successful run used a V12-local pinned cache
whose inventory matches the previously verified original snapshot. A later
generation-capture preflight also stopped before output because `HF_HOME`
would have appended `/hub` to that cache root; retrying with the exact
`HF_HUB_CACHE` root passed.

The complete V12 run root remains on Furnace. It occupied 207 GiB at capture,
with 850 GiB free on the filesystem. No weights were pruned because storage
was not under pressure and there is not yet a V12-scoped fail-closed pruner.

## V12.0 no-op gate

The no-op gate is qualified. The pinned inline baseline was preserved exactly:

| metric | value |
| --- | ---: |
| functional query accuracy | 0.779296875 |
| choice loss | 0.6750163380 |
| full-vocabulary NLL | 0.84291458 |
| label-0 recall | 0.67578125 |
| label-1 recall | 0.8828125 |

This establishes initialization equivalence only. It does not show that the
sidecar can become useful after an update.

## V12.1 one-update calibration

All three workspace learning rates passed update ownership, but none changed
the full-corpus functional outputs after one update. The base remained exact,
while the workspace output sentinel changed at the expected order of scale.
Because all scientific tie-break inputs were equal, the predeclared smallest-LR
tie-break selected `1e-5`.

This was a valid deterministic selection, not evidence that `1e-5` had the
best learning response. The one-update assay could see parameter motion but
could not see output-level sidecar motion.

## V12.2 four-update branch gate

Task-only and semantic branches both passed the frozen four-update stability
gate for all three seeds. All six runs retained the baseline full-corpus
accuracy, scored 0.8125 on the bounded 32-case task slice, and kept the base
exact. Their intact and amputated task metrics were identical. All six task
logit tensors and all six free-form completion sets were mutually exact.

Both branches were therefore formally promoted to V12.3, but this promotion
meant only stable execution under the frozen gate. In hindsight it was an
early warning that the gate admitted a safe but functionally invisible route.

## V12.3 matched refinement

After base release, task-only and semantic cells were exact matches within
each seed at the persisted base, full-corpus metrics, bounded task logits, and
free-form generation levels.

| seed | branch pair choice loss | query accuracy | amputated accuracy | full NLL | exact changed base elements | changed fraction | 32-case accuracy |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 43 | 0.6253778 | 0.7763672 | 0.7763672 | 0.7983804 | 64,858,283 | 0.89484% | 0.84375 |
| 44 | 0.6255677 | 0.7773438 | 0.7773438 | 0.7987556 | 65,810,018 | 0.90797% | 0.84375 |
| 45 | 0.6245428 | 0.7773438 | 0.7773438 | 0.7972898 | 64,816,130 | 0.89426% | 0.84375 |

The base update is real: choice loss fell from 0.6750 to about 0.625, and about
0.9% of persisted BF16 base elements changed. Accuracy stayed near, but
slightly below, the 0.7793 baseline. This is not a broad quality win.

On the six free-form prompts, ranked-world explanation and instruction
precision remained token-exact with the original. The other four prompts
changed after base training. For every prompt, however, task-only and semantic
checkpoints with the same seed were token-exact. Their 32-case choice-logit
hashes were also exact within seed. Thus the observed generation change is
attributable to the matched base trajectory, not to a semantic-sidecar win.

The sidecar parameters were not identical across objectives. Necessity
telemetry records small objective-dependent changes in the internal residual
norm. Those changes remained below the functional observation floor: intact,
hard bypass, zero memory, fixed/random carrier, token shuffle,
counterfactual-twin, and cross-world shuffle all produced exactly unchanged
choice loss, accuracy, world accuracy, and choice margin.

## Necessity result

All six checkpoints pass F0 engineering coverage and fail F1-F5.

| seed | intact query accuracy | all-query world accuracy | affected donor accuracy | unaffected stability | held-out accuracy | passed levels |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 43 | 0.7802734 | 0.09375 | 0.3515625 | 0.8242188 | 0.7617188 | F0 only |
| 44 | 0.7773438 | 0.09375 | 0.3515625 | 0.8203125 | 0.7578125 | F0 only |
| 45 | 0.7773438 | 0.09375 | 0.3554688 | 0.8216146 | 0.7597656 | F0 only |

Task and semantic branches share these outcomes within each seed. The frozen
thresholds were 0.75 for all-query world sufficiency and affected donor
direction, 0.9 for unaffected stability, and 0.8 for held-out accuracy.
`semantic_content_specific_seed_count` is therefore zero.

## Failed hypotheses and interpretation

Three hypotheses failed in a useful way.

1. A real workspace update selected by the one-step calibration would become
   output-visible after four or 16 updates. It did not.
2. Adding counterfactual and stability objectives would separate semantic from
   task-only behavior once the base was released. It did not; matched pairs
   remained exact at every externally observed output surface.
3. A stable four-update branch would be a useful candidate for semantic
   refinement. Stability was real, but it measured absence of harm while the
   sidecar remained redundant.

The narrow supported interpretation is that V12 successfully repaired
initialization and update ownership, and that the matched base schedule learns
without collapse. The sidecar receives updates and carries nonzero internal
signals, but under this BF16 readout, gain, gate, and LR combination it does
not acquire content-specific causal load-bearing.

This does not show that sidecars in general cannot work. It localizes the next
problem to route observability and causal readout before scale or longer runs.

## Decision and claim boundary

The frozen rule selects `stable_redundant_sidecar`. Integrity is `PASS`, while
the scientific result is negative. Neither branch is a winning workspace
branch. No 14B scale-up, broader sweep, or V13 training is authorized by the
receipt.

Supported claims are limited to the pinned Mistral-7B model, exact datasets,
V12 route, optimizer semantics, three seeds, and 16-step schedule. The result
does not establish broad capability gains, intrinsic workspace necessity,
transfer to 14B, or a general global workspace.

## V13 design handoff

V13 should be a route-visibility assay, not a longer continuation of V12.

1. Keep the base frozen and preserve the V12.0 bitwise no-op gate.
2. Instrument the residual immediately before and after BF16 casting, including
   the residual-to-ULP ratio at the two choice logits. This distinguishes
   learned content from a readout quantization floor.
3. Calibrate only the sidecar output gain, gate, accumulation dtype, and
   workspace LR until a predeclared nonzero intact-versus-hard-bypass choice
   logit effect appears on held-out cases without collapsing either label.
4. Require content-sensitive separation from fixed/random carrier and require
   counterfactual-twin direction before releasing the base. A mere nonzero
   carrier or internal residual norm is insufficient.
5. Only after that frozen-base causal gate passes in at least two seeds should
   a matched task-only/semantic base-release comparison or a 14B design be
   authorized.

The machine-readable handoff remains `DESIGN_ONLY`; these are proposed V13
contract requirements, not executed results.
