# V11 historical weight retirement, 2026-11-14

Scope: four single-link `base_model/model-*.safetensors` shards under the V11
`refinement16/O0_seed45_step16/final` run on Furnace. These are historical V11
weights, not the original pinned Mistral cache or V22–V24 final comparison
weights. The V11 config, index, run metadata and other state files remain.

Furnace parent:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-ft-v11-f1-o0-refinement/runs/v11/f1_o0_refinement/refinement16/O0_seed45_step16/final/base_model`

| File | Bytes | SHA-256 before deletion |
| --- | ---: | --- |
| `model-00001-of-00004.safetensors` | 3984728184 | `39e50bbc181bdaaf5410395a61e669ad0f4d22ff7592d51607b76e6cb403c1c2` |
| `model-00002-of-00004.safetensors` | 3967977000 | `30dbd9c4d5ea0c15cf6b07f58cb5b093c30675e8f8fb4422a4a802df10a9d8c3` |
| `model-00003-of-00004.safetensors` | 3926025456 | `93662226a4ab33368d0b6320874805dc9ec7ac989a32d6af73602bbeb3a46deb` |
| `model-00004-of-00004.safetensors` | 2617350280 | `f2570ca0ace9fb21eb2f11eb907dadfb9f5f88163da34b93a138775343954f61` |

Total logical bytes: 14,496,080,920. All four were regular, single-link files
at inventory time. Historical V11 receipt metadata was previously preserved
under `provenance/inventory/v12_weight_prune_20261014/` and
`provenance/inventory/v16_storage_inspection_20261014/`. This ledger records
identity, not a recoverable copy of the weight bodies. Re-running this exact
V11 checkpoint requires rebuilding the bodies from source/training inputs.

Status: **deleted** on Furnace after a second size, link-count, regular-file
and full SHA-256 check of all four targets. The first deletion command failed
at Python parsing before any file operation; its corrected invocation printed
`all four pre-delete checks passed` and `deleted four V11 historical shards`
and exited 0. No directory or other file was removed. Root-filesystem
available bytes rose from 18,211,024,896 immediately before the operation
to 32,707,133,440 afterward, a measured gain of **14,496,108,544 bytes**.
The historical shard bodies are no longer recoverable from this ledger.

The resulting 30.461 GiB free remains below the unchanged 50-GiB training
floor, even before reserving space for a new ~29-GB checkpoint. No 7B
training was admitted as a consequence of this retirement alone.
