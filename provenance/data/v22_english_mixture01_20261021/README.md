# V22 English-only projection and frozen training schedule

Built and fully regenerated offline on Furnace, 2026-10-21, from source
`ed0d8d8dbd3248f221eccdb5ce387c18a71c101e`. Both commands exited zero.
No model forward, weight update, teacher call or original-bank mutation was
part of this data build. The first builder used explicit source-file hashes;
the forthcoming GPU run additionally requires a complete committed-source seal.

Parents: [world bank](../native_world_bank01_20261021/README.md) and
[preservation bank](../native_preservation_bank01_20261021/README.md).
Their historical plans, data, manifests and results remain unchanged.
Ryō explicitly requested Japanese exclusion and progression to V22 training.

## Population and exclusions

| Role, English only | Train rows | Train target tokens | Dev rows | Dev target tokens |
| --- | ---: | ---: | ---: | ---: |
| Executable-oracle worlds, deduplicated | 4,608 | 29,948 | 576 | 3,715 |
| General instructions | 512 | 134,979 | 64 | 18,995 |
| Human prose | 1,084 | 137,356 | 100 | 12,647 |
| Code answers | 125 | 46,278 | 15 | 5,898 |
| Total | 6,329 | 348,561 | 755 | 41,255 |

Preservation alone is **1,721 train / 179 dev**, **318,613 / 37,540** targets.
The projection removes 33 Japanese train and five Japanese dev rows without
rewriting or changing their parent dispositions. Exact world controls remove
1,536 train / 192 dev duplicate occurrences, retaining their alias IDs. Original
768 test and 512 OOD world rows are excluded from this projection entirely.
Teacher candidates and the small instruction-seed bank are not admitted.
All preservation rows have empty memory. Labels and target counts use the
pinned Mistral tokenizer, with full assistant completion/EOS for instructions
and code; prose has its original causal span, no artificial EOS.

Group overlap and duplicate projected sequences are zero. This inherits the
parent source/group and exact/50-word exclusion checks, not a semantic or
all-benchmark contamination proof. All declared language metadata is English;
this is not a newly run language-classification audit of each sentence.

## Fixed exposure, not a quality result

[SCHEDULE.json](furnace/SCHEDULE.json) freezes every row key before training:

| Role | Training row occurrences | Target tokens | Actual token share |
| --- | ---: | ---: | ---: |
| World | 636 | 4,097 | 19.640% |
| General instruction | 37 | 8,415 | 40.340% |
| Prose | 41 | 5,207 | 24.962% |
| Code | 9 | 3,141 | 15.058% |
| Total | 723 unique | 20,860 | 100% |

32 windows have at least 512 supervised tokens, with complete final rows
allowed to overshoot. The maximum realized window is 41 rows / 1,003 targets
(these maxima occur in different windows). Token shares are not per-window
objective coefficients; the [summary](furnace/SUMMARY.json) also reports their
mean per-window shares. No new loss weighting or short-answer row averaging
is introduced. Selection is a deterministic token-exposure fair queue with
hash-ordered rows. The source-byte-pinned data recipe fixes development role
order as well as seed and quotas.

The separate canary has two windows, 4 + 5 rows, with full 1,024-token
instruction and 993-token code examples, and maximum memory length 78.
It uses training candidates only and is never inherited as the initial
training checkpoint. A fixed **40-row / 4,694-target** development panel has
one example per six world families × four modes, plus eight instructions,
four prose spans and four code answers. It is an NLL diagnostic panel, not an
unseen final benchmark and not a source for threshold or checkpoint selection.

## Reproduction and storage

Data recipe: [DATA_01.json](../../../configs/v22/DATA_01.json).
Manifest SHA-256:
`fe463daf2a349df824eacb9f33d345b5c235edf74f2aee6dc7252f238dadf71c`.
The [manifest](furnace/MANIFEST.json) binds every payload and builder source.
The text-free [index](furnace/index.json.gz) preserves IDs, parent-row hashes,
split/role metadata, lengths and denominators for independent recounting.

Raw token arrays stay only on Furnace at:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-data01-20261021/bank/rows.json.gz`.
Their SHA-256 is
`9d521ccc2ac9dffa1e4423c65d0bfcb020020ef0d2d08c7f5f884214c2e8d2c1`.
The builder uses `build` for exclusive output and `verify` for full offline
regeneration, never overwrites old output, and never downloads a model.

This is a user-authorized private research selection. Upstream rights claims,
including jurisdiction-specific PG claims, are retained, not independently
certified; redistribution review is still pending. Nine code training rows
cannot establish code-capability retention. Broad non-regression, answer
quality and deployment readiness are **NOT_ESTABLISHED**. See the
[bounded V22 execution contract](../../../docs/v22/FULL_FT_01.md).
