# Native length resource recovery 01 — three backward rows passed

2026-10-21 JST. This is the separately authorized correction of
[probe 01](../native_resource_probe01_20261021/README.md), not a replacement
of that failed result. Source: `d6188f17d5130f39b7480de1637904307fa7a0dd`,
694 sealed files. The fix retains the genuine
`query_only_token_weighted_causal_nll` objective identifier and changes only
the resource-input identity. A regression exercises the real small-model owner.
The previous limits, model, arithmetic and no-update/no-save scope are unchanged.

## Observed result

- CPU **254/254 PASS**; CUDA **254/254 PASS**; no failures, errors or skips.
- Both historical identities of the pinned original Mistral match.
- **3/3 backward rows**, one accumulation window, **48 supervised tokens**.
  No optimizer step, checkpoint, learner generation, judge call or deletion.
- All 291 physical native parameter tensors / 7,248,023,552 elements are
  registered with the real CPU-master owner. Native and FP32 master state
  hashes are unchanged at the end; diagnostic gradients are discarded.
- Peak CUDA allocated: **27.696311 GiB**; reserved: **28.365234 GiB**.
  Peak process host RSS: **59.266785 GiB**. RSS is not whole-machine RAM use.
  Role elapsed time: **151.915 seconds**, including setup/identity work.

| Row | Memory tokens | Query tokens, including answer | Supervised tokens |
| --- | ---: | ---: | ---: |
| direct | 0 | 128 | 16 |
| memory | 64 | 128 | 16 |
| memory | 128 | 128 | 16 |

These are exact synthetic tensor lengths with repeated neutral text, not
semantic examples or a quality evaluation. The measured scope includes CPU
FP32 masters, BF16 gradient accumulation/staging, differentiable memory
encoding and native full-vocabulary readout. It does **not** measure an
optimizer step/save/restart at length 256, longer contexts, teacher prose
lengths, or a full training population. The older short two-update/fresh-process
replay pass remains separate evidence.

## Replay and provenance

[Offline replay](analysis/REPLAY.json) verifies committed source blobs, both
qualification XML/terminal counts, nested file manifests, named model
identities, all three tensor-length axes and the unchanged-state results.
The role terminal SHA-256 is
`77227c10f0554c2acbcd07a06cef377546b95794278f263817b517b762fe8a91`.

`furnace/raw/probe/INPUTS.json` and `CONTEXT.json` retain the generic canary
preparation context. They are **not** the three resource rows: the executed
rows are `RESOURCE_INPUTS.json`, whose canonical SHA-256 is
`74e8aee77911745d0683184419fd447ca0d03febdac49a69b4651438d73ac4fb`.
The sealed `resource_contract()` replaces the owner's input hash with this
value before accumulation. Raw receipts and logs are preserved literally.

```sh
python scripts/report_native_data_preparation.py resource \
  --input provenance/engineering/native_resource_probe_recovery01_20261021/furnace \
  --output provenance/engineering/native_resource_probe_recovery01_20261021/analysis \
  --verify
```

Historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
