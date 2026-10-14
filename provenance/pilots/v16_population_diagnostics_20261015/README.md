# V16 population diagnostics: launch evidence

2026-10-15. The [fixed evaluation contract](../../../docs/v16/POPULATION_DIAGNOSTICS.md)
is now dispatched on Furnace. The original-base arm starts first. This is a
launch record, not a completed comparison or a quality result.

Selected: pinned original base plus common/raw/slot-contrast step-2 checkpoints;
128 fresh world pairs / 1,024 queries (256 affected), and a fixed subject-balanced
MMLU test subset (570 questions, five-shot dev examples). One training seed only.
MMLU runs with **no workspace** and measures updated-base preservation, not
workspace-assisted knowledge or free generation.

The preceding [training pilot is complete](../v16_full_comparison_20261014/RESULTS.md).
This evaluation does not train, generate, call a judge, retry a failed cell,
modify old source seals, save checkpoints, or delete weights. Old
**FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## Qualification and source

| Check | Result | Evidence |
| --- | --- | --- |
| Local regression, including previous update/resume coverage | 308/308; zero failures, errors, skips | [XML](PRELAUNCH_TESTS.xml) |
| Source-isolated Furnace CPU tests | 22/22; pytest 1.98 s | [terminal receipt](qualification/cpu/FINISHED.json), [XML](qualification/cpu/TESTS.xml) |
| Source-isolated Furnace CUDA tests | 22/22; pytest 3.60 s | [terminal receipt](qualification/cuda/FINISHED.json), [XML](qualification/cuda/TESTS.xml) |
| MMLU tokenizer preflight, no model forward | 570/570 prefix-compatible single-token choices; maximum 3,295 tokens | [receipt](TOKENIZER_PREFLIGHT.json) |
| Ruff on new sources/tests | passed | frozen source checked before dispatch |

Frozen execution source `de0f14c7378abf7d92f582b6b22d31bdf688526b`:
[546-file source seal](SOURCE_SEAL.json). All preceding 535 source files remain
byte-identical. The 128 selected world pairs have zero order overlap with all
320 historical train/eval world pairs and with one another; no rejection was
needed. Entities/templates remain shared. MMLU comes from the pinned MIT source;
source parquet hashes, prompt bodies and selection indices are retained.

## Existing dispatch

[Outer launcher](LAUNCHED.json), [dispatcher STARTED](launch/STARTED.json), and
[original-arm dispatch](launch/DISPATCH_original.json) are immutable launch
receipts. Outer launcher PID 1776329; initial original worker PID 1776407.
Resolve current PIDs against their exact command lines. Do not start a second
copy or infer completion from a detached process.

The original model passed [exact replay of its old step-zero evaluation](launch/original/RESTORE.json).
Its [in-run token receipt](launch/original/TOKENS.json) matches the 570-question
preflight. The first ten native MMLU rows also passed the
[finite-score smoke](launch/original/MMLU_SMOKE.json): 3/10 correct, 0 ties in
this first subject's slice. This is not an accuracy acceptance gate or the
full-subset result; the remaining rows continue under the unchanged plan.

The [execution handoff](EXECUTION_HANDOFF.md) contains exact Furnace paths and
terminal verification commands. Source-isolated tiny passes and tokenizer
checks do not establish real-model completion or semantics. No recurring
monitor was created. Later results belong to the completed raw bundle, not this
launch snapshot.
