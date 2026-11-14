# Furnace capacity candidates — read-only inventory, 2026-11-14

No file was removed, moved, rehashed for retirement, or declared disposable.
The live status showed an idle RTX 5090 and no compute process, but the single
root filesystem had **21,263,790,080 free bytes (19.803 GiB)** at the final
sample. This fails the established 50-GiB disk floor by approximately
30.197 GiB; a new ~29-GB final body would need additional headroom beyond
that. `du` is apparent directory usage, **not guaranteed reclaimable bytes**:
hardlinks, shared caches and live dependencies matter.

| Exact Furnace path / group | Observed apparent size | Classification before any retirement |
| --- | ---: | --- |
| `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a2-depth-ladder-20261016` | ~5.6 GiB | Historical V20 feature-extraction data; two large `FEATURES_*.safetensors` have link count 1. Release checks still reference this raw folder. Archive/rehash and reproduce its verifier before considering deletion. |
| `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a4-gated-route-20261017` | ~1.8 GiB | One unique large mismatch feature body; check its historical role and receipts before retirement. |
| `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v20-a5-dev-20261018` | ~4.2 GiB | One unique large feature body; verify whether any later beta assay still requires it. |
| `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-ft-v11-f1-o0-refinement/runs/v11` | ~17 GiB | Historical V11 final includes four unique safetensors shards totaling about 13.5 GiB. A comparison/ledger audit is required; do not retire merely because it is older. |
| `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-ft-cuda/runs/v10` | ~35 GiB | Mixed historical runs, resume checks, source snapshots and a Mistral model cache. The three ~13.5-GiB cache shards sampled have **link count 4 and the same inode** as the protected global Hugging Face cache; removing this worktree's names alone would not reclaim those shard blocks. Audit unique bytes and replay dependencies before any selection. |

The first three V20 directories total about **11.6 GiB apparent**. Even if
all were independently qualified and fully reclaimable, that alone would not
restore the 50-GiB floor. The V10/V11 worktrees could in principle supply
more, but the nominal 52 GiB is **not** a valid free-space forecast because
V10 includes shared hardlinks and potentially required historical artifacts.

Explicitly protected for this decision: the original pinned
Mistral-7B-Instruct-v0.3 cache/body, V22 final, both V23 scientific finals,
both V24 FT04 finals, their sealed receipts, and all other projects'
`q_space_runs`, Aether, `scratch` and Hugging Face model caches. Those other
projects account for much of the disk but were not considered deletion
targets. No workspace-wide cache purge or recursive removal is authorized by
this inventory. A retirement would need exact paths, active-use check, hashes,
Git/off-host provenance, expected *unique* byte recovery and a separate
post-delete `df` verification.
