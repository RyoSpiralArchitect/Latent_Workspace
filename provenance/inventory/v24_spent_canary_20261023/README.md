# Prepared spent-canary retirement helper: BLOCKED, NOT EXECUTED

The helper was prepared while the V24 R1 canary was running. That attempt
[stopped after its first saved update](../../engineering/v24_recruitment_ft01_20261023/README.md)
when another GPU client appeared. Exact next-update replay never ran.

`retire.py` requires a successful two-update canary and exact fresh-process
replay, the original complete role manifests, 570/570 qualification on each
device, CPU isolation, and no scientific arm. It then requires a complete
body hash, stable identity, no open handles, protected comparison identities,
and a published ledger before any unlink. It targets exactly the single
FT01 canary, never a glob or a directory.

**Its first gate rejects the actual failed FT01 bundle.** No inventory or
deletion action was run, and no `CANARY_RETIREMENT.json` exists. The helper
must not be used to portray this interrupted checkpoint as successfully
replayed or spent. Tests cover that actual failure as well as exact scope,
receipt/body/ledger changes, symlinks, open handles, protected files and
repeated invocation. A new-attempt cleanup policy is a separate decision.
