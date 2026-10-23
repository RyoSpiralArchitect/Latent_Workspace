# Superseded V15 engineering condition: two-body retirement

2026-10-23. **Pre-delete ledger; not yet a deletion receipt.** Ryō authorized
removing no-longer-needed artifacts to make room for the next full FT. The
bounded selection is the completed two-update V15 full engineering condition,
not V18's later comparator or any V22/V23 scientific final. Current `src/`,
`scripts/`, and `configs/` contain no references to these V15 body paths.

| V15 engineering body | Bytes | Complete SHA256 |
| --- | ---: | --- |
| `full/step1.pt` | 29,054,758,918 | `df0382eed7c1f657858699f26027ed67a04baebc8d621d1c48b3c2a0d2269b19` |
| `full/step2.pt` | 29,054,758,918 | `60e7de1b43a8599bcc616b1ba1aef5c410035cc9cfe2131dcc84bbe8d9f0b2ce` |

The [inventory](INVENTORY.json) binds exact absolute paths, filesystem
identities, newly recomputed complete hashes, original checkpoint receipts,
the original terminal/report digest and exact-replay evidence. The
[historical pilot](../../pilots/v15_native_learner_20261010/README.md) remains
unchanged: engineering replay passed, semantic promotion did not, old gate
`FAIL`, winner `none`, non-regression `NOT_ESTABLISHED`.

Expected reclamation: **58,109,517,836 bytes (54.1187 GiB)**. Inventory available
space was 70,715,494,400 bytes; the shared-disk free-space result must be read
from the later deletion receipt, not assumed from this sum.

Publish this ledger before running [the bounded helper](retire.py). It rehashes
both entire files immediately before deletion, checks no process has either
open, refuses symlinks/hardlinks/path or receipt changes, and journals the exact
unlinks. Tests cover exact scope, changed bodies/receipts/ledger, in-use checks,
protected-file changes and no repeated execution (**18/18** including the
unchanged primitive-helper tests). Failure stops without expanding targets.

Retain original Mistral, both V18 checkpoints, V22 step32, V23 P-off/P-on step32,
the P-on teacher bank, every non-weight receipt, all datasets, and all source
worktrees. No Aether or Q-space artifact is in scope. This retires the entire
obsolete V15 full engineering pair; it is not a new global retention rule.

**Git preserves metadata, not the tensor bodies. Deleted weights cannot be
restored from Git.** Re-running that historical experiment would be a new,
separately recorded experiment, not recovery of the exact deleted bytes.
