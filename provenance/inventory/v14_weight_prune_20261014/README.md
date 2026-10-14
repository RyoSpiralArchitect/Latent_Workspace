# Authorized Furnace V14 weight cleanup

2026-10-14 JST. **PRE-DELETION RECORD; deletion has not yet been performed.**

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

The inventory, pruner and every metadata copy must be committed and pushed before
deletion. Execution verifies their bytes from that exact Git commit, rehashes all
source metadata and weights, checks visible same-user open handles, then unlinks
only the exact allowlist with no-follow parent descriptors and per-file stat
checks. It rechecks metadata hashes and 98 protected out-of-scope weight stats
afterward. There is no recursive deletion or automatic retry after a terminal
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

## Prospective capacity and claim ceiling

Before the new inventory, persistent available space was 201,816,498,176 bytes
(about 187.956 GiB). Reclaiming the 44 logical payload sizes suggests about
270.794 GiB available, but actual filesystem availability must be measured after
deletion. Logical bytes are not an exact prediction of reclaimed blocks.

The prior conservative planning envelope is **three arms × 64 GiB retained
outputs + 50 GiB remaining = 242 GiB**, with two retained checkpoints per arm.
This is a storage screen, not a frozen V16 run contract or proof that the new
reader fits the CUDA/host-memory envelope. Full training/evaluation still needs
the final isolated source, precise schedule and runtime admission.

No new training, generation, judge request or scientific acceptance is part of
this cleanup. Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** remains.
The historical judge status remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`.

Deletion results and measured post-cleanup capacity will be added only after
the separate terminal receipt exists. This pre-deletion Git commit remains the
historical evidence that the records were preserved first.
