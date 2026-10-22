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

## Storage gate before Full FT

Read-only Furnace inventory on 2026-10-22 found 56,976,289,792 bytes available
(approximately 53.06 GiB). The unchanged disk floor is 50 GiB. Readout adds no
weights; it can be admitted separately. Another checkpoint-writing run cannot
be admitted with this headroom.

Current exact observed bodies:

| Body | Bytes | Disposition |
| --- | ---: | --- |
| V23 `canary_step1.pt` | 29,004,386,444 | Engineering replay candidate for a future explicitly approved retirement |
| V23 `off_step32.pt` | 29,004,418,636 | Keep: scientific comparison arm |
| V23 `on_step32.pt` | 29,004,428,108 | Keep: scientific comparison arm |
| V22 `training_step16.pt` | 29,004,396,428 | Keep: earlier checkpoint; no new deletion authorization |
| V22 `training_step32.pt` | 29,004,418,636 | Keep: historical reference; equal size is not byte identity |

One conservative 28-GiB canary plus one 28-GiB final save and the 50-GiB floor
needs **106 GiB**, before optional new teacher/target bodies. A fresh two-arm
comparison with three retained saves needs **134 GiB**. Retiring only the V23
engineering canary would reach about 80.08 GiB, still insufficient for either.
An alternate volume or an explicit further retention decision is necessary;
no floor is lowered and no old/scientific weight is deleted by this plan.
