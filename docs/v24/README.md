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

The next controlled factor is [R1 input-route learning](RECRUITMENT_FT_01.md):
same independently checked records, answers and training windows, supplied
inline versus through native M. New arithmetic/register/transform groups join
the unused V23 world expansion; preservation remains 80% of requested target
token exposure. The new bank/harness passed **60/60 CPU tests**; pinned offline
tokenization froze 538 rows / 21,112 targets across 32 windows per arm. The
[sealed FT qualification](../../provenance/engineering/v24_recruitment_ft01_20261023/README.md)
then passed **570/570 CPU and 570/570 CUDA tests**. The 7B canary completed one
update and saved, then stopped on an actual separate GPU client. Exact replay
and both scientific arms are unrun; no candidate result is claimed. Preserve
the failed trial and its checkpoint. The authorized
[same-source FT02 attempt](../../provenance/engineering/v24_recruitment_ft02_20261023/README.md)
then passed CPU 570/570 but stopped on one unlocalized external-audit ValueError;
CUDA and 7B remained unrun. An explicitly authorized
[FT03 audit-only recovery](../../provenance/engineering/v24_recruitment_ft03_20261023/EXECUTION_HANDOFF.md)
adds an independent observer process and 38 regressions without changing any
scientific conditions or safety floor. It must qualify all 608 tests per device.
FT03 then passed **608/608 on both devices and 137 clean observer samples**, but
[stopped after two recorded native updates](../../provenance/engineering/v24_recruitment_ft03_20261023/README.md):
the inherited in-memory payload check forecast another 32-GiB disk write despite
not writing a tensor file. Free space was 71.55 GiB, above the 50-GiB floor but
below the forecast gate. Save/restore replay and both scientific arms remain
unrun in FT03. Its negative terminal and newer canary remain protected.
The authorized [FT04 repair](../../provenance/engineering/v24_recruitment_ft04_20261023/EXECUTION_HANDOFF.md)
separates memory-only admission from real-file writes, retaining all safeguards.
It keeps 608 tests and adds 35; **643/643 passed on both CPU and CUDA**,
with 140 clean independent-observer samples. The
[7B checks passed](../../provenance/engineering/v24_recruitment_ft04_20261023/README.md):
both canary updates exactly reproduce FT03; fresh-process update-2 and full
payload replay are exact. This is engineering qualification, not scientific FT
or quality improvement. At checks completion, the scientific arms were unrun
pending storage.
Real saves retain the 32-GiB
reserve and paired-final admission is conservatively 110 GiB including the
50-GiB floor. The [FT01-only retirement](../../provenance/inventory/v24_ft01_superseded_20261023/README.md)
is complete (27.0124 GiB); replay stays explicitly NOT_RUN, not a training gate.

**New authorized transition, 2026-10-23 16:52 JST:** the
[FT03/FT04 canary-only retirement](../../provenance/inventory/v24_ft04_canaries_20261023/README.md)
reclaimed 54.0249 GiB after whole-body rehash and published ledger. Scientific
final weights and original Mistral remain protected; the FT03 failure is not
rewritten. Free disk reached 124.2520 GiB, and the unchanged training admission
passed. The same frozen FT04 source now runs inline then workspace, independently
initialized from base, 32 updates / 538 rows / 21,112 targets per arm. Follow
[the execution handoff](../../provenance/engineering/v24_recruitment_ft04_20261023/EXECUTION_HANDOFF.md).
Training is not yet complete; no improved capability or non-regression is claimed.

The [obsolete V15 engineering pair retirement](../../provenance/inventory/v24_v15_engineering_20261023/README.md)
then reclaimed **54.1187 GiB**, leaving about **119.98 GiB at that time**.
After shared storage fell again, the obsolete completed
[V18 engineering pair](../../provenance/inventory/v24_v18_engineering_20261023/README.md)
was separately journaled and retired, reclaiming **54.1718 GiB**. V22/V23 scientific
comparators remain. Next FT uses a separately verified spent-canary lifecycle,
not an implicit waiver of the 50-GiB free-space floor.
