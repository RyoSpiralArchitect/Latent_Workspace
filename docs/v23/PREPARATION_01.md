# V23 preparation 01: expanded worlds and a native objective instrument

2026-10-22 (JST). Ryō asked to proceed from the W/Q/R diagnosis while modestly
expanding the world bank. This finite stage prepares data and qualifies a
diagnostic instrument. It does **not** dispatch a 7B model, teacher, optimizer,
judge, generation, deletion, recurrent workspace or release.

## Additive data, not a rewritten evaluation

[WORLD_BANK_02.json](../../configs/v23/WORLD_BANK_02.json) adds **512 groups /
4,096 raw rows**. Each group retains two counterfactual worlds, affected and
unaffected queries sharing each memory, and absent/unrelated controls. Identical
paired controls are aliases, not independent observations: 3,072 unique rows.
All 1,024 prior groups and their exact identifiers/texts are exclusion-only.
The previous bank and exposed diagnostic mistakes are never repair targets.

| Split | Groups | Raw rows | Unique rows | Model evaluation in this stage |
| --- | ---: | ---: | ---: | --- |
| Train | 336 | 2,688 | 2,016 | None |
| Development | 56 | 448 | 336 | None |
| New in-distribution confirmation | 56 | 448 | 336 | None |
| New 3-hop structure OOD | 64 | 512 | 384 | None |

Half the groups use independent nonce identifiers; half share an eight-letter
prefix and differ at the last letter. Two irrelevant facts and a frozen fact
order are shared between twins. Both naming conditions occur in each split.
Oracle solving, group completeness, exact regeneration and cross-bank/split
collisions are checked. The expansion adds 50% to the old raw world count, but
does not change the training schedule or ordinary/world token mixture.

The **linked_location family is deliberately promoted** from old structure
OOD to training using fresh groups; its old groups remain excluded. It may no
longer be advertised as an unseen structure after such training. The new
whole-family holdout is two ownership edges followed by location (3 hops).
New confirmation inputs are structurally inspected/tokenized, not evaluated
by a model. This is a reserved bank, not yet a full 1.0 acceptance protocol.

## Instrument before intervention

`NativeMemoryCausalLM` has an optional live cut trace. It adds no parameters,
detach, cached states, loss or retained parameter gradients. Default computation,
native CE, dropout RNG order, empty-memory bypass and owner contract remain
unchanged. Empty-memory tracing returns no cut trace, not a silent split-native
substitute. Tests compare trace on/off logits, losses, gradients and RNG.

The engine's `objective_audit` partitions each oracle target **before scoring**:

- Identity: the shortest lexical token prefix distinguishing its value from
  other symbols in the visible oracle world/query. Numeric/abstention values
  and prefix-ambiguous cases use the whole lexical value. This is a local token
  discriminator, not a proof of semantic reasoning.
- Copy: later lexical tokens after that prefix, when present.
- Format: leading whitespace-only tokens, suffix punctuation and EOS.
- Mixed: tokens crossing the lexical-value/punctuation boundary. Do not force
  these into a semantic or formatting bin.

Each component uses the **same full row/window token denominator**. The total
uses the original CE reduction; component sums may have rounding residuals.
State gradients separate memory, question and fixed continuation, including
norms, signs, component cosines and additive residuals. Native update visibility
is explicitly not measured without an optimizer update.

A tiny reference independently replays the upper reader with detached cut
states to measure **W + Q + direct R** against the full parameter gradient.
Tied/shared parameters can participate in all paths. Another reference streams
CE/anchor gradient dot products tensor by tensor. These avoid retaining several
whole-model gradient copies, but repeatedly traverse the graph per parameter:
**they are not a resource-qualified or efficient 7B implementation**. A scalable
spill-based implementation and fresh resource canary precede a real-model audit.

The full-vocabulary forward-KL primitive accepts only normalized, detached FP32
targets aligned to the complete vocabulary. It rejects truncated/top-k, live,
BF16-compressed and nonfinite targets. It is not yet wired into the owner; no
new training objective or checkpoint format is admitted by this change.

## Frozen next audit inputs, not generated teacher targets

[PREPARATION_01.json](../../configs/v23/PREPARATION_01.json) selects one complete
training group per family/naming condition: **14 groups / 84 unique world
rows**. It also chooses **12** existing English training preservation rows,
four each of instruction/prose/code, hash-ranked among complete rows no longer
than 128 tokens. This small short-context panel is not a retention benchmark.
No held-out labels, teacher prose, Japanese or public benchmark answers enter it.

The future reference condition is the pinned original Mistral v0.3, native
BF16/eager logits, FP32 log-softmax, temperature 1, all 32,768 vocabulary entries
at every supervised causal position of the unchanged complete no-memory row.
Teacher targets are **NOT_RUN**. Exact input/selection hashes and the projected
target storage size are recorded before any future teacher forward.

## Qualification and boundaries

The sealed plan runs 296 selected tests on CPU and CUDA independently, at most
4 GiB CUDA allocation and 900 seconds each. Existing full-update/save/fresh-
process replay tests are included, not skipped. Tiny BF16 path sums have explicit
reference tolerances (3% relative + 1e-4 absolute); this is not a changed scientific
acceptance gate. Trace/no-trace computation itself must remain bitwise identical.
The data role uses only the offline pinned tokenizer, has a 900-second limit
and a 50 GiB disk floor, and reports length violations without truncation.

Furnace skill preflight found an idle GPU and approximately 67 GiB disk free.
Managed-runtime doctor passed with its existing modelopt compatibility warning;
no packages were changed. Native PyTorch is required for the tiny differentiable
graph/owner tests, which a serving runtime does not expose. All execution uses
a new source-pinned worktree. No old run directory or checkpoint is modified.

Local development caught and fixed an abstention classifier bug: Python
`islower()` also accepts spaces, accidentally making `Not specified` a nonce.
An explicit `N[a-z]+` rule and regression retain the whole abstention span.
An initial collection command also named a nonexistent test file and ran zero
tests; it was corrected to `test_architecture_rules.py`. The local wider suite
was 193/195: two isolated fresh-process tests cannot import `typing_extensions`
on this Mac. This environment limitation is retained, not a pass or exclusion;
both tests remain mandatory in the sealed Furnace suites.

The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. A real
gradient-conflict diagnosis, P on/off update comparison, exact new-objective
save/restart, unseen base floor and useful extra latent computation remain open.
