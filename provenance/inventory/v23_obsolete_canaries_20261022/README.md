# Three obsolete engineering canaries — 2026-10-22

Ryō authorized recording and deleting weights no longer used for comparison.
The exact allowlist is [INVENTORY.json](INVENTORY.json): **3 files /
87,013,134,820 bytes (81.0373 GiB)**. The old two-step native identity canaries
and the V22 one-step engineering canary have completed exact restart checks;
the later scientific V22 step16 and step32 supersede them for current work.

Retain original Mistral, V22 step16/32, all scientific V18–V20 branches, all
activation banks, all data and other projects. This is not a blanket version
purge. The historical source seals, failure records, state fingerprints and
replay receipts stay unchanged in their original bundles and Git history.

The inventory rehashes the full bodies against their original checkpoint
receipts. Publish this ledger before executing [retire.py](retire.py). The
script then rechecks all three hashes, static filesystem identities, the
completed replay gates, and retained files before unlinking only those exact
three regular files. No recursive directory removal or retry is supported.

**No weight backup exists here. Git records hashes and metadata, not
reconstructable tensor bytes. Deleted bodies cannot be recovered from Git.**
Execution is not claimed until a separate `DELETE_FINISHED.json` is recorded.
