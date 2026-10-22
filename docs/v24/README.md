# V24: readout instruments and workspace capability improvement

Ryō's intended target is **improvement**, not "constancy" (the latter was a
typing error corrected on 2026-10-22). Preservation is a floor, not the primary
research claim. We want useful capabilities to improve *because of* workspace
computation, not merely shorter answers, better format or more supplied facts.

Base: merged PR #35, commit `bf68339c2fc942eb989f6bbd6e19dbe364e5059c`.
The [V23 synthesis](../v23/EVALUATION_SYNTHESIS.md) remains unchanged evidence.
Current ceiling: **old FAIL / winner:none / non_regression NOT_ESTABLISHED**.

## Engine additions, not a new learner objective

- [Native readout audit](../../src/latent_workspace/readout_audit.py): fixed,
  identical token continuations; full-vocabulary target/probe/EOS log probabilities,
  tie-aware ranks and margins; separate reference roles for content, copying,
  option binding, format and stop. It rejects changed histories, incomplete
  traces, and mismatched arithmetic/vocabulary in matched contrasts.
- The same module observes the existing full-vocabulary sampler through a
  forwarding view. Only one detached CPU vocabulary vector is pending at once.
  It neither resamples nor changes the model, head, optimizer, cache, stopping
  rule or generation source. Free histories may diverge and are **not** accepted
  as fixed-token causal evidence. Scores are before temperature/top-p.
- [Workspace improvement reducer](../../src/latent_workspace/workspace_improvement.py):
  original/candidate × no-memory/inline/workspace; explicit missing and invalid
  cells, repairs and losses, domain/condition strata and equal-group descriptive
  means. Generic FT gains are separated from the workspace-minus-inline
  interaction. This arithmetic does not itself validate an oracle, establish
  significance, or certify general intelligence.

All existing native graph/owner/sampler sources remain byte-identical. There is
no new loss, candidate-only head, trainable parameter, normalization-specific
hook, hidden-state recurrence or output rewriting. Historical input seals still
replay. Tiny-host parity is necessary, not a 7B or capability result.

## First bounded diagnostic

[Plan](../../configs/v24/READOUT_PROBE_01.json),
[runner](../../scripts/run_v24_readout_probe.py), and
[handoff](../../provenance/engineering/v24_readout_probe01_20261022/EXECUTION_HANDOFF.md).

Each of base / V23 P-off / V23 P-on has **44 cases, 197 forwards**; total
**132 case traces, 591 forwards**. All are teacher-forced, with zero new free
sequences, updates, checkpoint saves, judge calls or deletions.

- Four exposed MMLU-Pro failure IDs × five anchors: original direct score,
  reasoning-start EOS, answer-label prediction without a supplied result,
  answer-label prediction after the correct **option content is explicitly
  supplied**, and EOS after a complete correct reference. The oracle-assisted
  condition measures conditional binding, NOT independently solved reasoning
  or improved benchmark accuracy. Prompt changes between anchors remain a
  confound; only same-anchor model comparisons have identical token histories.
- Four exposed world groups × two reference answers × original/twin/empty
  memory. All three conditions for a reference use exactly the same question
  and target tokens. Oracle token roles use the existing lexical-prefix
  partition, with EOS split from punctuation. Compare both reference directions
  and preserve individual groups; do not count correlated tokens as independent
  solved problems. These remain availability/readout probes, not generality.

The old strict benchmark parser and gates are not relaxed. Tests cover portable
Mistral, OLMo2, GPT-2 and scratch hosts, FP32/BF16, sampler parity, identical
reference replay, future-token exclusion, empty/nonempty memory, missingness,
strict owner restore and CPU/GPU qualification isolation. The frozen remote
selection contains **350 tests on each device**, with a 4-GiB/900-second tiny
budget. Source/receipt status, not this planned denominator, establishes PASS.

The first local working selection passed 106 tests. The larger local selection
recorded **346 passed / 4 failed / 0 skipped** in
[LOCAL_350.xml](../../provenance/engineering/v24_readout_probe01_20261022/LOCAL_350.xml).
All four failures were fresh-process owner/preservation replay tests: the local
Python 3.13 isolated child could not import `typing_extensions`, before model
computation. No test was excluded or relabeled. The pinned Furnace CPU and CUDA
suites must each pass all 350; local Torch/Transformers versions are not silently
treated as Furnace qualification.

**Terminal update:** the pinned Furnace CPU and CUDA selections each passed
**350/350**, with CPU isolation PASS. Base/off/on each completed **44/44 cases
and 197/197 forwards**, and all **132 traces / 591 forwards** replay locally.
Read the [source-backed result](../../provenance/engineering/v24_readout_probe01_20261022/README.md):
assisted correct content yields four strict label wins per arm, while the
world references show a much larger format than content likelihood gain.
Content-sensitive memory use exists even in base; semantic selectivity did not
uniformly increase after FT. Immediate-EOS probabilities remain tiny. These
facts narrow the next question without proving a general readout fix.

The offline verifier and retirement helper passed **19/19** new local tests.
The earlier four local import failures remain unchanged; these new tests do
not replace or relabel the actual Furnace qualification.

## Next native Full FT

See [the capability and FT direction](FULL_FT_DIRECTION.md). Diagnosis chooses
the smallest next factor; the old P-on arm has not earned promotion. Fresh
train-only oracle/data contracts, update/save/restart parity, token budgets,
storage admission and an untouched capability panel precede a new FT run.
GPU use through Full FT was explicitly authorized in this turn. The diagnostic
launcher still cannot start FT automatically or bypass these gates.
