# V23 recovered comparison — complete diagnostic, no release gate

P-on recovery 02 completed **570 MMLU scores, 192 world teacher-forced rows,
192 world sequences and 24 free answers**. Its native weights were unchanged
before/after inference. Both **248/248** CPU and CUDA qualifications and the
CPU isolation audit passed (107 samples, zero own GPU clients). The role took
578.595159 seconds and generated 5,990 tokens; no training, saved model weights,
deletions, retries, export or release occurred.

## Separate provenance, one paired diagnostic

The original dispatcher stays **INCOMPLETE_NO_RETRY**. Its completed base/off
come from `84073310cd7b2c56b5e3de046fb3bdc99e461bfb` (774 source files).
The whole new on arm comes from `af9cd1a727d98d942df1845c35a14628f8f7481b`
(792 files). All 774 original source files are unchanged in recovery. All
three input manifests are identical. Both source seals, full raw manifests,
matched journal IDs and qualification/audit receipts replay successfully.
The original 79 partial on scores are retained **outside** this analysis;
they are not spliced or overwritten. Its terminal sequence activity remains
historically null, not relabeled zero. Recovery 01's CPU collection error also
remains preserved separately.

The selected bank has **1,710 MMLU rows and 648 sequences** across three arms,
with 18,382 generated tokens. The 96 world rows represent 16 grouped worlds
and two routes, not 96 independent worlds. Free generation has 12 prompts ×
two seeds, not 24 independent prompts. These are previously exposed inputs,
not a new confirmation bank.

## Readout

| Endpoint | Base | P-off | P-on |
|---|---:|---:|---:|
| MMLU correct / 570 | 356 | 354 | 355 |
| MMLU tie-free correct / 570 | 351 | 349 | 349 |
| MMLU top-option ties / 570 | 15 | 18 | 15 |
| Latent world exact / 96 | 47 | 83 | 83 |
| Inline world exact / 96 | 75 | 87 | 86 |
| Free EOS / 24 | 14 | 15 | 14 |
| Free length cap / 24 | 10 | 9 | 10 |

All trained-arm world outputs end at EOS (192/192 per arm); base has 15/192
world length caps. Visible completion is not the same as correctness.

MMLU base→off: **0 gained, 2 lost**; base→on: **0 gained, 1 lost**.
On restores the two off regressions (`mmlu:all:test:9596`, `13900`) but loses
`mmlu:all:test:3119`, which base and off answered correctly. Thus off→on is
2 gained/1 lost, net +1; tie-free accuracy is unchanged. Neither trained arm
answers a base-wrong MMLU item correctly in this selected panel. This does
not establish impossibility on other items or under a different protocol.

World latent base→off and base→on are each 38 gained/2 lost; off/on have the
same per-item exactness outcomes, not only the same total. Inline on loses
one off-correct row. This panel cannot prove causal workspace use or general
non-regression. MMLU and free answers use the empty-memory/direct route.

Free answer text/token sequences differ on **24/24** base/off and base/on
pairs, and **23/24** off/on pairs. Different text is not a quality win.
The [complete literal answer bank](analysis/ANSWER_BANK.md) includes all 72
answers with seeds, stop reasons and token counts, including unchanged/capped
answers. The independent blind-judge readout remains separate from this
mechanical comparison; no preference is assigned here.

## Replay and next gates

- [Machine-readable full analysis and transition IDs](analysis/ANALYSIS.json)
- [Recovery dispatcher receipt](furnace/raw/FINISHED.json)
- [Original incomplete comparison](../v23_comparison01_20261022/README.md)
- [Execution handoff](EXECUTION_HANDOFF.md)
- [Explicit judge/MMLU-Pro follow-up](../../../docs/v23/RECOVERED_FOLLOWUP_01.md)

Run `python3 -B provenance/pilots/v23_comparison_recovery02_20261022/analyze.py verify`
to replay the combined source/manifest/ID/analysis/literal-bank checks.
`verify_qualification.py` additionally replays the XML counts and CPU audit.
`verify_decoding.py --tokenizer /path/to/pinned/tokenizer` checks every literal
sequence with the pinned local tokenizer, with zero model calls. All **648/648**
literal decodes passed; the [receipt](OFFLINE_DECODING.json) records all four
tokenizer-file hashes. The first local check had no cached tokenizer and made
no network/model call; the pinned tokenizer files were then copied from the
existing Furnace snapshot (no new model download). The old expression gate remains **FAIL**,
winner **none**, non-regression **NOT_ESTABLISHED**. The small aggregate MMLU
loss and strong world gains warrant further diagnosis, not a new winning arm.
