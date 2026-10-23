# V18 completed engineering pilot: published ledger and retirement

2026-10-23. Ryō authorized removing obsolete artifacts and confirmed a new
same-conditions V24 attempt. Shared disk free space fell to about 45.72 GiB
after the previous turn, below the 78-GiB canary admission requirement. The
bounded cleanup now selects the **entire completed two-update V18 engineering
condition**, not the original model or any V22/V23 scientific final.

| Body under `tmp/latent-v18-native-pilot-20261015/checkpoints/primary/` | Bytes | Complete SHA256 |
| --- | ---: | --- |
| `step1.pt` | 29,083,263,908 | `ed0bac210d5d89ecb1c58545f1e609c701ab6003914771e45c3feb1bea6115c4` |
| `step2.pt` | 29,083,263,908 | `8293eb6d808532c8703792bb1077da96b7e86ee278b0dd002ea460da452facb8` |

Potential recovery: **58,166,527,816 bytes (54.1718 GiB)**. The
[inventory](INVENTORY.json) contains exact absolute paths, filesystem identities,
fresh whole-file hashes, original save receipts, every raw/qualification
artifact digest, helper hashes and protected-body identities. It is published
before any unlink; this document alone does not claim deletion completed.

**Completed disposition, 2026-10-23 05:59:59 UTC:** the
[terminal journal](latent-v24-v18-retirement01-20261023/DELETE_FINISHED.json)
records both exact bodies retired after publication in commit
`67d4a1cec73fb36cd7ab67c228167bc9bd097c28`. Actual reclaimed bytes equal the
forecast above. Available space increased from 49,089,372,160 to
107,255,902,208 bytes (99.89 GiB); shared storage can change after this sample.
Per-file journals and the published inventory remain alongside the terminal.
No original model, V22/V23 final, FT01 canary, data or source worktree was removed.

The [original V18 pilot](../../pilots/v18_native_pilot_20261015/README.md)
already completed exact fresh-process step-2 replay from step 1. Its offline
verifier was rerun on Furnace from the clean original source
`fb409ed2ba6ff3b2be209f7a97894b02637f5b2f`: **599 source files, exact replay,
both entire checkpoint hashes PASS, zero forwards**. All original evidence
and negative results remain byte-for-byte unchanged. Its historical statements
about retained bodies describe the 2026-10-15 state; this dated ledger is the
later disposition, not a rewrite of that history.

Current V24 training and evaluation use original Mistral and V22/V23 finals,
not these two-update V18 bodies. Historical V18 verifiers and the old V16
retirement record still mention them; those are retained historical references,
not current runtime inputs. This is not a winner selection or a new global
retention policy. Preserve the interrupted V24 FT01 canary until recovery,
all three V22/V23 finals, original Mistral, teacher data and source worktrees.
No Aether/Q-space or unrelated artifact is targeted.

The [helper](retire.py) revalidates complete historical manifests and replay,
rehashes both bodies immediately before unlink, rejects changed/symlinked/
in-use targets and preserves protected identities. Its targeted and primitive
tests passed **18/18**; the additional external-launcher check makes **19/19**.
Deletion has exclusive start/per-file/terminal journals and no retry.

**Git retains metadata only. Deleted tensor bodies cannot be restored from Git.**
