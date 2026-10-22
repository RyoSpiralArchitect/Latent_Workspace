# From readout diagnosis to workspace-dependent capability gains

## Separate the claims

1. **Ordinary FT gain:** original versus candidate on identical no-memory
   questions, including paired base-wrong repairs and base-correct losses.
2. **Useful workspace gain:** same information, question, answer budget and
   scoring rule supplied inline versus through workspace, in both model arms.
   Report `(candidate workspace - candidate inline) - (original workspace -
   original inline)` descriptively. This separates one generic FT interaction;
   it is not by itself a causal proof of latent reasoning or matched compute.
3. **Content dependence:** relevant, counterfactual, unrelated and absent
   memory. Appropriate answer changes and unaffected controls must coexist.
4. **Additional computation:** a future temporary working state S must beat
   matched depth/compute/capacity controls and its inference bypass. The current
   query-deferred prefix M is not automatically S, recurrence or persistent KV.

World banks are the controlled readout/availability instrument. They must not
become the sole definition of capability improvement. Keep the M/S/native
readout distinction from [workspace revival](../v23/WORKSPACE_REVIVAL.md).

## Broaden endpoints before selecting another checkpoint

Freeze a new group-level split before training/selection. Keep development,
selection and untouched confirmation separate, including all template families,
counterfactual variants, aliases and paraphrases of a source problem. Exposed
MMLU/MMLU-Pro questions, judged outputs and the V24 diagnostic references are
never training examples. No confirmation result is currently claimed.

| Domain | Primary externally checkable endpoint | Separate failure evidence |
| --- | --- | --- |
| Compositional reasoning and arithmetic | Exact result, units and independently checked derivation claims | Correct text/wrong label, invalid derivation, unanswered |
| Code and execution reasoning | Frozen sandboxed tests plus faithful explanation | Executable-but-wrong, misleading explanation, violated constraints |
| Instruction following and structured transformation | Exact constraints and preservation of source facts | Formatting-only gain, hallucinated detail, incomplete output |
| Writing and open-ended reasoning | Blinded qualified/human review, source-faithfulness and task completion | Length, truncation, order conflict, uncertainty |

Use short and multi-stage tasks with appropriate, fixed answer budgets. Do not
reward more words or shorter answers intrinsically. The no-memory base floor
is retained alongside *new ability gains*. A benchmark on empty memory alone
cannot demonstrate workspace use. A relevant-memory advantage over no-memory
alone may merely reflect access to information. Inline versus workspace changes
positions and arithmetic, so later compute/capacity controls remain necessary.

For all six model/route cells, bind exact tokens, tokenizer identity and the
route's oracle/scorer into `route_sha256`. The reducer checks matching hashes,
not their scientific validity. Wrong or unparsed answers are scored by the
frozen scorer, not conveniently marked invalid. Missing execution evidence
stays missing, with planned denominators and group counts visible. Source
groups, not paraphrases or tokens, are the replication unit. The reducer is
descriptive: no non-inferiority margin or statistical power is silently chosen.

## What the first diagnosis can decide

- If supplying correct content fixes label binding but unassisted answers
  remain wrong, prioritize useful intermediate computation/recruitment, not
  another loss that only rewards correct output formatting.
- If correct content is still misbound, test **B: content-to-answer binding**
  with train-only independently solved examples and randomized option maps,
  using the same native full-vocabulary CE. Correct visible explanations must
  remain aligned with their final answer; do not patch test labels afterward.
- If EOS becomes more probable at inappropriate early anchors, compare task
  mixtures and completion supervision. Do not simply suppress EOS, increase
  every token cap, or infer premature stopping from shorter outputs alone.
- Retain exact copying and no-memory preservation diagnostics. The old P-only
  comparison did not select a winner. Keep P fixed and explicit during a B-only
  contrast, then test interactions separately; do not jointly alter P, data
  scale, LR, precision, normalization and recurrence.

These are candidate decisions, not inferred outcomes. The tiny readout probe
can locate failure modes; it cannot choose a universal loss coefficient or
prove broad capability. Any new learner factor must be an engine option with
zero-effect parity and exact update/save/fresh-process restart, not a private
runner-side adapter or a Mistral-specific normalization workaround.

### Decision after the first 7B probe

The [completed probe](../../provenance/engineering/v24_readout_probe01_20261022/README.md)
now provides bounded evidence, without training a new fix:

- All three arms bind four of four exact supplied correct option contents;
  only two of four unassisted label anchors win. This argues against a universal
  absence of the label readout, not against every generated-history binding
  failure. Chemistry's assisted margins remain small. Exact option text is an
  unusually strong cue; do not treat it as independent reasoning.
- In four world groups, all eight reference directions remain content-sensitive
  in base and both FT arms. Three group means have lower content selectivity
  after FT. The largest intact-reference logprob improvement is format, mostly
  the period: about 79 nats over 10 format tokens versus 1.3 over 14 content
  tokens. The old scorer ignores a final period, so this decomposition does not
  explain the entire exactness gain or recode the old results.
- EOS is negligible at the initial reasoning anchor but often much more likely
  after a supplied complete answer. Global EOS suppression/length reward is
  not the next factor. Actual generated-history stopping remains unmeasured.

The next design priority is therefore **useful content/derivation recruitment
and answer use**, retaining the response-shaping gains as separate endpoints.
Do not simply add a second answer-format loss or increase P. Before a new full
update, freeze train-only solved tasks and an untouched group-held-out panel;
keep exact copy, content correctness, answer binding and completion as separate
measurements. None of the four exposed MMLU-Pro items or world references may
be used as training targets or future confirmation.

A concrete next factor can vary whether independently checked intermediate
results are available to the query-conditioned workspace, with identical
information inline as a control. First establish that the native M interface
uses those results; if testing newly computed S, add the model-independent
engine mechanism and bypass/matched-compute controls explicitly. Do not rename
extra supplied facts as new latent computation. Ordinary no-memory capability
and the model × route interaction are both required, not a world-bank-only win.

This is a development decision, **not a frozen training recipe**. Native
update/save/fresh-process replay and a new resource forecast precede dispatch.
P-on is not selected as the default; keep P a predeclared controlled factor.

## Storage gate before Full FT

Read-only Furnace inventory on 2026-10-22 found 56,976,289,792 bytes available
(approximately 53.06 GiB). The unchanged disk floor is 50 GiB. Readout adds no
weights; it can be admitted separately. Another checkpoint-writing run cannot
be admitted with this headroom.

Observed bodies and their subsequent disposition:

| Body | Bytes | Disposition |
| --- | ---: | --- |
| V23 `canary_step1.pt` | 29,004,386,444 | Retired after explicit approval; exact replay and full hash retained |
| V23 `off_step32.pt` | 29,004,418,636 | Keep: scientific comparison arm |
| V23 `on_step32.pt` | 29,004,428,108 | Keep: scientific comparison arm |
| V22 `training_step16.pt` | 29,004,396,428 | Retired after explicit approval; exact step32 continuation retained |
| V22 `training_step32.pt` | 29,004,418,636 | Keep: historical reference; equal size is not byte identity |

One conservative 28-GiB canary plus one 28-GiB final save and the 50-GiB floor
needs **106 GiB**, before optional new teacher/target bodies. A fresh two-arm
comparison with three retained saves needs **134 GiB**. Retiring only the V23
engineering canary would reach about 80.08 GiB, still insufficient for either.
The subsequent [two-file retirement](../../provenance/inventory/v24_intermediates_20261022/README.md)
reclaimed **54.0249 GiB** and left **105.7668 GiB** available, still **0.2332 GiB**
below that conservative concurrent-save forecast. This live snapshot supersedes
the earlier estimate; no floor is lowered and no further weight is deleted.

For the next protocol, consider an explicit **sequential retention lifecycle**:
save canary -> complete exact fresh-process replay -> publish its receipt and
retirement ledger -> retire that now-unused canary -> run/save the final model.
Only one new 28-GiB body then needs to coexist with the 50-GiB floor (**78 GiB**,
plus any other declared payloads), instead of treating a spent engineering
canary as a scientific final. This is a proposed separately tested lifecycle,
not a deletion already performed or permission for a runner to auto-delete.
Live shared-disk checks, original/previous scientific references and immutable
failure/replay receipts remain mandatory. A two-arm study needs its own peak
storage accounting; this one-body forecast cannot be reused for two finals.
