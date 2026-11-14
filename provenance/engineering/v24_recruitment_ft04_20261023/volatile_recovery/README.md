# Furnace cross-project volatile-data preservation

Completed **2026-10-23 19:47–19:48 JST**, following Ryō's request to check
volatile leftovers beyond Latent Workspace before moving Furnace.

**Later update, recorded 20:19 JST:** Ryō confirmed having powered Furnace off
for relocation. The state is now **USER_REPORTED_POWERED_OFF**, with the exact
shutdown time/method unknown. No additional remote calls followed that message.
The completed recovery was already synchronized before the later connection
failure. See [the relocation handoff](../RESUME_AFTER_MOVE.md).

## Preserved on the same Furnace SSD

Private capsule:
`/home/ryospiralarchitect/spiralreality/SpiralReality/shutdown-recovery-20261023-volatile01`

This destination is on the verified persistent **ext4** filesystem, not tmpfs.
Directories are **0700**, all capsule files **0600**, independently checked.
Nothing in the capsule is installed, executed, or restored automatically.

| Category | Files | Bytes |
|---|---:|---:|
| Temporary work files: diffs, logs, diagnostic scripts, publication staging | 50 | 3,483,890 |
| Temporary feature tensors, provenance not inferred from filenames | 3 | 93,687,864 |
| Test fixtures, retained conservatively as data rather than discarded | 2,722 | 37,901,144 |
| Opaque named shared-memory files, quarantined rather than interpreted | 28 | 469,762,048 |
| Transient QSpace/tmux unit definitions, data only | 61 | 37,447 |
| Aether/QSpace tmux screens and retained scrollback | 17 | 13,770 |
| **Total copied content** | **2,881** | **604,886,163** |

The first five categories are **2,864 pre-existing regular files / 604,872,393 bytes**.
The total including terminal captures is approximately **576.86 MiB**.
Post-copy free space was **74,764,189,696 bytes**, above the 50-GiB floor.

Every regular-file copy has source metadata, a copy-stream SHA-256, a second
source read, and a destination SHA-256. No source size/inode/mtime/ctime change,
hash mismatch, active accessible writer/mapping, or capture error was recorded.
A separate pass reread all 2,881 saved content files and verified hashes, sizes,
and private permissions; filesystems were synchronized after verification.
This is same-host durable storage, **not an off-host backup**.

The local [summary](receipts/SUMMARY.json), [copy manifest](receipts/COPY_MANIFEST.json),
[inventory](receipts/INVENTORY.json), and [independent verification](COPY_REVERIFICATION.json)
are metadata only. Raw payloads and screen text remain private on Furnace and
must not be added to Git or a publication bundle.
Manifest SHA-256: `390e3eccafd73722c4f9b032e6b8742b20ccf000e898cf996bd00f2752a9e33e`.

## Observed scope and limits

- `/tmp`, `/dev/shm`, and `/run/user/1000` are tmpfs. The scan covered accessible
  uid-1000 regular files in these roots, including files unrelated to LTWS.
- No non-system deleted-but-open/mapped result file was observed among accessible
  user processes. Deleted library mappings were system binaries/libraries, not
  evidence of missing research results. The SysV shared-memory list was empty.
- No accessible user process mapped or held a writable descriptor to the selected
  files at the two sampled inventories. This is not a continuous writer lock.
- `/var/tmp` and `/var/log` are already persistent ext4. `/run/log/journal` was
  empty; existing journals are on persistent `/var/log/journal`.
- Tokenizer cache was excluded as recreatable. Symlinks, sockets, other owners'
  directories, credential-runtime locations, and regenerable systemd internals
  were not copied. Skip reasons and access failures remain in the inventory.
- Seventeen tmux panes were captured; one was a live shell. No keys were sent,
  processes signaled, or sessions ended. tmux's paste-buffer list was empty.
- Existing Codex/Claude/login/SMB sessions remain. An unsubmitted prompt, an
  application's anonymous heap/editor buffer, another user's process, or an
  inaccessible SMB write is **not** covered by this file-and-screen recovery.
  Opaque shared-memory copies are not resumable process checkpoints.

**No shutdown command was issued.** The previous
[authentication-required handoff](../SHUTDOWN_HANDOFF.json) still applies.
After recovery, a later read-only connection check failed with an SSH
`Address already in use` error; `spiral status` also reported unreachable by
**20:16:55 JST**. See [the connectivity receipt](FOLLOWUP_CONNECTIVITY.json).
The independent saved-copy verification and sync had already succeeded at
**19:48:07 JST**. A connection failure does not confirm poweroff; no new power
state or authorization observation was obtained. The transport was not changed.
If Furnace is still on, Ryō should finish/check live interactive input or shared
transfers before authenticating ordinary graceful shutdown. No inhibitors or
authentication policies were bypassed. The completed heartbeat remains deleted.

No originals, weights, project checkouts, or existing logs were deleted or
changed. Only this private capsule and local receipts/report were added.
No GPU work, model call, judge, Git push, or PR was started.
