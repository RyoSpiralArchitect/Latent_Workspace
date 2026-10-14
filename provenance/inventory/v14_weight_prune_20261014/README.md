# Authorized Furnace V14 weight cleanup

2026-10-14 JST / 2026-10-14 03:16 UTC. **COMPLETE; permanent weight deletion.**

Ryō explicitly authorized recording the V14 experiment weights in Git and
deleting their payloads to make room for the prospective three-arm V16 pilot.
This is a V14-only exception to latest/previous-per-condition retention, not a
new general retention rule. V15/V16 checkpoints, the original Mistral cache,
other projects, old scientific results and their failure statuses are protected.

## Exact target and publication order

The sole deletion root is Furnace's
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat/runs/v14`.
The exact allowlist contains **44 files / 88,946,458,314 logical bytes
(82.837845 GiB)**:

- 24 exported base shards, six workspace states and six trainer states for
  semantic/task seed47, checkpoint4/checkpoint8/final;
- eight small centered/precision-bridge states, semantic/task at step128/256.

The other three scoped V14 worktrees (cache trajectory, instrument return gates,
portable boundaries) contained no eligible experiment weights in the live
read-only screen. This is not a disk-wide search or authorization to delete any
unlisted copy. Names are not used as proof that checkpoint8 and final are equal.

The new [narrow pruner](../../../scripts/prune_v14_recorded_weights.py) uses the
unchanged, hash-pinned V12 no-follow/stat/hash filesystem helpers. It first hashes
all 44 targets and copies all **502 metadata files** byte-for-byte, including
configurations, manifests, learning/evaluation records and existing answer banks.
Flat metadata backup names avoid generated-checkpoint ignore rules; the inventory
maps each copy back to its exact source path. No tensor file is deserialized.

[INVENTORY.json](INVENTORY.json) SHA-256:
`ea3a0cec9df0bf7534eb43c13b592c53c893b7e6d6e33954eaccc8bc47115977`.
The 502 metadata copies total 133,606,488 bytes. All copied bytes have passed
both Furnace and local hash checks. [PREDELETE_VERIFY.json](PREDELETE_VERIFY.json)
also confirms all 526 previously sealed source files remain unchanged.
[39 local safety tests](PRUNE_TESTS_FINAL.xml) pass: 27 V14 toy-file cases plus
12 retained V12 cases. No test touches real experiment weights.

An additional pre-publication screen found no credential-pattern matches in the
502 metadata files. Thirty credential-like JSON keys were verified to be integer
tokenizer vocabulary IDs, not secret values. This is a bounded pattern/key screen,
not a general security audit. Literal metadata bytes are not sanitized or rewritten.

The inventory, pruner and every metadata copy were committed and pushed before
deletion in `98e79a6b3acb3ac071ced497cc4b6dd9d73f4e23`. Execution verified their
bytes from that exact Git commit, rehashed all source metadata and weights,
checked visible same-user open handles, then unlinked
only the exact allowlist with no-follow parent descriptors and per-file stat
checks. All metadata hashes and 98 protected out-of-scope weight stats matched
afterward. There was no recursive deletion or automatic retry after a terminal
or partial attempt. Global crash atomicity and protection against a concurrent
malicious writer are not claimed; exclusive use is required.

The first read-only preflight stopped before creating the remote inventory or
deleting anything because Linux hides some systemd/PAM/SMB/SSH service handles.
The [preflight record](HANDLE_SCREEN_PREFLIGHT.json) retains that limitation.
Visible target handles and unreadable non-service processes block execution;
privileged service handles are recorded as **UNKNOWN**, not counted as verified
closed. No privilege escalation or service interruption is used. The separately
observed idle GPU and per-file hash/stat checks do not eliminate this visibility
limitation or provide concurrency/crash atomicity.

**No weight backups are created. SHA-256 fingerprints and metadata cannot
reconstruct the deleted weights.** Re-creation would require retraining and
cannot promise byte equality. Original metadata remains on Furnace as well as
in the new Git record; previous evidence bundles are not edited.

## Terminal result and measured capacity

[DELETE_STARTED.json](DELETE_STARTED.json), [DELETIONS.jsonl](DELETIONS.jsonl),
and [DELETE_FINISHED.json](DELETE_FINISHED.json) record all **44/44 deletions**.
The [offline terminal verifier](../../../scripts/verify_v14_weight_prune.py)
replays path/hash/byte accounting, metadata integrity and the unchanged historical
source seal; its output is [TERMINAL_VERIFY.json](TERMINAL_VERIFY.json).

| Quantity | Bytes | GiB |
| --- | ---: | ---: |
| Available immediately before deletion | 201,673,814,016 | 187.823376 |
| Deleted logical weight payloads | 88,946,458,314 | 82.837845 |
| Available in terminal receipt | 290,620,477,440 | 270.661411 |
| Observed increase in available space | 88,946,663,424 | 82.838036 |
| Prospective three-arm outputs plus remaining-space floor | 259,845,521,408 | 242.000000 |
| Surplus beyond that forecast and floor | 30,774,956,032 | 28.661411 |

Filesystem allocation/metadata effects explain why observed free-space change
is not exactly logical payload size. The later read-only `df` check reported
290,620,469,248 bytes available (8,192 bytes less than the terminal sample).
The inventory/metadata copy and Git transfer also consumed some space between
the earlier screen below and deletion admission; the samples are not conflated.

All **502 original metadata files** retain their SHA-256 hashes, and all **98
protected out-of-scope weight files** retain their stat signatures. Those 98
include the four frozen/full V16 migration checkpoints. This is not a fresh
content-hash audit of other weights. The original Mistral model/cache was never
a deletion target. All 526 historical sealed source files remain byte-identical.

## Earlier forecast and claim ceiling

Before the new inventory, persistent available space was 201,816,498,176 bytes
(about 187.956 GiB). Reclaiming the 44 logical payload sizes suggests about
270.794 GiB available, but actual filesystem availability must be measured after
deletion. Logical bytes are not an exact prediction of reclaimed blocks.

The conservative planning envelope is **three arms × 64 GiB retained
outputs + 50 GiB remaining = 242 GiB**, with two retained checkpoints per arm.
The measured terminal capacity passes this **storage screen**: after the 192-GiB
output forecast, 78.661 GiB would remain, exceeding the unchanged 50-GiB floor.
This is not a frozen V16 run contract or proof that the new reader fits the
CUDA/host-memory envelope. Full training/evaluation still needs the final
isolated source, precise schedule and runtime admission.

No new training, generation, judge request or scientific acceptance is part of
this cleanup. Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** remains.
The historical judge status remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`.

The pre-deletion Git commit remains the historical evidence that the records
were preserved first. This later publication adds the terminal result; it does
not rewrite the original inventory's `deletion_performed:false` into a new claim.
