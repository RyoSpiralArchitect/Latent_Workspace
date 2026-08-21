# Legacy v9 partial handoff

This document pins the latest validated legacy snapshot used to define the CUDA
migration boundary. It does not import legacy model weights or claim that v9
completed.

## Receipt

- Legacy source identifier: `latent_workspace_ft_v9:gpt2_v9_n10`
- Validation receipt identifier: `evidence/cpu/LIVE_VALIDATION_RECEIPT.json`
- Receipt validation time: `2026-08-21T15:26:03.736346Z`
- Mode/publication: `partial` / `partial_nonfinal`
- Structurally valid partial snapshot: `passed=true`, `structural_errors=[]`
- Training: `28/190`
- Snapshot state counts: `training_completed=28`, `pending=161`, `running=1`
- Final validation: false
- Final claims allowed: false
- Global validation complete: false
- Contract assays complete: false
- Bitwise-attribution claims allowed: false

The receipt's `running=1` is snapshot metadata, not evidence of a live process at
the time this handoff is read. The legacy runner status must be checked separately.
The receipt reports necessity verification `0/160` as incomplete; this is missing
evidence, not a measured zero effect.

## Independently rehashed files

All hashes use SHA-256 and were recomputed from the legacy local files during this
handoff.

| Artifact | SHA-256 |
| --- | --- |
| `LIVE_VALIDATION_RECEIPT.json` | `7ecebe5d8c9ba36008a4321886c93c65ea49e7eb9129c996fb6e6c19406a09af` |
| `V9_SUMMARY.json` | `ff46f701339be7b907cdc1ebb741d1749c12e10ad9a5f0892fc293af327e3aad` |
| `V9_RUN_LEDGER.jsonl` | `bee2adb2a20bf8b7eaacb5869bbf37bb6985ba46f6d31a785c725e504b10e3a3` |
| `V9_RUNS.csv` | `749fa17bbe65407601d1ff505ad061fdf94f29d5bf2491f144f32a213dcc7706` |
| `MATRIX.json` | `02a77f5cf4c35a50610fc549899c4b44d124ee39f2bb4106f3499a72dea3f942` |
| full CPU `CONTRACT.json` | `ca5a19fa9062adace087d037d069698b8d430d9ecc145b5d585ebe59908607c0` |
| `run_v9_matrix.py` | `5b2962688bbbd72892192a61dd072bc354d1991ee8be4deb725c55ca30f50308` |
| `latent_workspace_ft_v9_mps.py` | `61e2996b599ddbac7f722cb64581945e69d92931d8f3525217962ce631e8b43d` |
| `summarize_validate_v9.py` | `d3724af0a1a6cf78271e4ef21b78216da9747d38db778473be06da2755132099` |
| `functional_train.jsonl` | `c7b012933a7a986e5cea80edf2ab87c45319a982bd500716206e71ee231ff855` |
| `functional_eval.jsonl` | `c50949f8e2618ef9b6159c5650a70a231008243433729d41f79b9482e977a156` |

The stale runner `PROGRESS.json` also records source hash
`8a7aade36630990414b0509a4ea2f80adc6506f162a9ad7e92bd9c0a95ca4d17`.
The v10 vendoring step independently rehashed the same source bytes; see
`src/latent_workspace_ft_v10/source_manifest.json`.

## Migration boundary

The CUDA/Mistral experiment is a new experimental generation. It starts with the
same byte-identical functional datasets but changes the base model, tokenizer,
backend, scale, and likely optimizer/offload path. Its results must not be pooled
with legacy GPT-2 results or described as completing the v9 matrix.

The first CUDA contract should carry forward the condition semantics and controls,
then establish new backend attribution, optimizer coverage, resume equivalence,
and held-out assay receipts before interpreting effects.
