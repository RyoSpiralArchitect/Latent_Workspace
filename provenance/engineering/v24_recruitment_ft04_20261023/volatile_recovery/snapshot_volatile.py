"""One-shot, private, same-host preservation; never executes or restores leftovers."""

import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time


DEST = Path("/home/ryospiralarchitect/spiralreality/SpiralReality/shutdown-recovery-20261023-volatile01")
BOOT = "66f9404a-e062-436f-82ce-0fc459a36143"
ROOTS = (Path("/tmp"), Path("/dev/shm"), Path("/run/user/1000"))
FLOOR = 50 * 1024**3
MAX_BYTES = 1024**3


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stamp(s):
    return dict(dev=s.st_dev, inode=s.st_ino, bytes=s.st_size,
                mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns,
                uid=s.st_uid, mode=stat.S_IMODE(s.st_mode))


def save(name, value):
    p = DEST / name
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
    with p.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def command(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def process_inventory():
    procs, denied, deleted, mapped, writers = [], [], [], [], []
    deleted_system = collections.Counter()
    for p in sorted(Path("/proc").iterdir()):
        if not p.name.isdigit():
            continue
        try:
            if p.stat().st_uid != 1000:
                continue
            name = (p / "comm").read_text().strip()
            entry = dict(pid=int(p.name), name=name)
            try:
                entry["cwd"] = os.readlink(p / "cwd")
            except OSError:
                entry["cwd"] = None
            procs.append(entry)
            try:
                for line in (p / "maps").read_text().splitlines():
                    fields = line.split(None, 5)
                    target = fields[5] if len(fields) == 6 else ""
                    if target.startswith(("/tmp/", "/dev/shm/", "/run/user/1000/")):
                        mapped.append(dict(**entry, target=target, perms=fields[1]))
                    if target.endswith(" (deleted)"):
                        if target.startswith(("/usr/", "/lib/", "/bin/")):
                            deleted_system[target] += 1
                        else:
                            deleted.append(dict(**entry, kind="mapping", target=target))
            except OSError as e:
                denied.append(dict(pid=int(p.name), part="maps", error=type(e).__name__))
            try:
                for fd in (p / "fd").iterdir():
                    try:
                        target = os.readlink(fd)
                        s = fd.stat()
                        if not stat.S_ISREG(s.st_mode):
                            continue
                        if s.st_nlink == 0 and s.st_size:
                            deleted.append(dict(**entry, kind="fd", fd=fd.name,
                                                target=target, bytes=s.st_size))
                        if target.startswith(("/tmp/", "/dev/shm/", "/run/user/1000/")):
                            info = dict(x.split(":", 1) for x in
                                        (p / "fdinfo" / fd.name).read_text().splitlines())
                            flags = int(info["flags"].strip(), 8)
                            if flags & os.O_ACCMODE:
                                writers.append(dict(**entry, target=target, fd=fd.name))
                    except (OSError, ValueError, KeyError):
                        continue
            except OSError as e:
                denied.append(dict(pid=int(p.name), part="fd", error=type(e).__name__))
        except OSError:
            continue
    return dict(utc=utc(), processes=procs, inaccessible=denied,
                deleted_non_system=deleted, deleted_system_paths=dict(deleted_system),
                volatile_mappings=mapped, volatile_writers=writers)


def select_files():
    selected, skipped, errors = [], [], []
    for base in ROOTS:
        for root, dirs, files in os.walk(base, followlinks=False,
                onerror=lambda e: errors.append(dict(path=e.filename, error=type(e).__name__))):
            for name in dirs[:]:
                p = Path(root) / name
                s = p.lstat()
                reason = None
                if p.is_symlink():
                    reason = "symlink_not_followed"
                elif s.st_uid != 1000:
                    reason = "other_owner_not_entered"
                elif p == Path("/tmp/tiktoken-rs-cache"):
                    reason = "recreatable_tokenizer_cache"
                elif p.parts[-1] in ("credentials", "gnupg", "keyring", "ssh"):
                    reason = "credential_runtime_not_copied"
                if reason:
                    dirs.remove(name)
                    skipped.append(dict(path=str(p), reason=reason))
            for name in files:
                p = Path(root) / name
                s = p.lstat()
                reason = None
                if s.st_uid != 1000:
                    reason = "other_owner"
                elif not stat.S_ISREG(s.st_mode):
                    reason = "non_regular_not_copied"
                elif name in (".env", "credentials.json", "id_rsa", "id_ed25519"):
                    reason = "credential_filename_not_copied"
                elif base == ROOTS[2] and not (
                    p.parent == base / "systemd/transient"
                    and (name.startswith("spiral-") or name.startswith("tmux-spawn-"))
                ):
                    reason = "regenerable_systemd_runtime_not_a_result"
                elif base == ROOTS[1] and not name.startswith("sm_segment.spiralreality.1000."):
                    reason = "unreviewed_shared_memory_kind"
                if reason:
                    skipped.append(dict(path=str(p), bytes=s.st_size, reason=reason))
                else:
                    selected.append(dict(source=str(p), root=str(base), **stamp(s)))
    return dict(selected=sorted(selected, key=lambda r: r["source"]), skipped=skipped, errors=errors)


def copy_entry(entry):
    src = Path(entry["source"])
    dst = DEST / "files" / src.relative_to("/")
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    assert all(not p.is_symlink() for p in src.parents)
    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        before = stamp(os.fstat(source.fileno()))
        assert before == {k: entry[k] for k in before}, f"Source changed before copy: {src}"
        h = hashlib.sha256()
        with dst.open("xb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
                h.update(block)
            target.flush()
            os.fsync(target.fileno())
        after = stamp(os.fstat(source.fileno()))
        source.seek(0)
        reread_hash = hashlib.file_digest(source, "sha256").hexdigest()
        final = stamp(os.fstat(source.fileno()))
    dst_hash = digest(dst)
    stable = before == after == final == stamp(src.lstat())
    matched = h.hexdigest() == reread_hash == dst_hash
    return dict(source=str(src), destination=str(dst.relative_to(DEST)),
                bytes=dst.stat().st_size, sha256=dst_hash,
                source_stamp=before, source_stable=stable, hashes_match=matched,
                status="VERIFIED" if stable and matched else "INCONSISTENT_SNAPSHOT")


def main():
    os.umask(0o077)
    assert os.getuid() == 1000 and os.uname().nodename == "spiralreality"
    assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() == BOOT
    assert DEST.is_dir() and not DEST.is_symlink()
    assert stat.S_IMODE(DEST.stat().st_mode) == 0o700
    mount = command(["findmnt", "-n", "-T", str(DEST), "-o", "SOURCE,FSTYPE"])
    assert mount["returncode"] == 0 and "ext4" in mount["stdout"]
    before = process_inventory()
    inventory = select_files()
    total = sum(e["bytes"] for e in inventory["selected"])
    assert total <= MAX_BYTES and all(e["bytes"] <= 128 * 1024**2 for e in inventory["selected"])
    assert shutil.disk_usage(DEST).free - total > FLOOR
    save("STARTED.json", dict(utc=utc(), uid=1000, host=os.uname().nodename,
         boot_id=BOOT, destination=str(DEST), mount=mount, selected_bytes=total,
         helper_sha256=digest(__file__), free_before=shutil.disk_usage(DEST).free))
    save("PROCESS_BEFORE.json", before)
    save("INVENTORY.json", inventory)
    busy = {e["target"] for e in before["volatile_mappings"] + before["volatile_writers"]}
    copied, blocked = [], []
    for entry in inventory["selected"]:
        if entry["source"] in busy:
            blocked.append(dict(source=entry["source"], reason="active_mapping_or_writer"))
            continue
        copied.append(copy_entry(entry))
    panes = command(["tmux", "list-panes", "-a", "-F",
                    "#{session_name}|#{pane_id}|#{pane_pid}|#{pane_dead}|#{history_size}"])
    save("TMUX_INVENTORY.json", panes)
    captures = []
    for line in panes["stdout"].splitlines():
        session, pane, pid, dead, history = line.split("|", 4)
        raw = subprocess.run(["tmux", "capture-pane", "-p", "-S", "-", "-t", pane],
                             capture_output=True, timeout=30)
        record = dict(session=session, pane=pane, pid=pid, dead=dead,
                      history=history, returncode=raw.returncode)
        if raw.returncode == 0:
            target = DEST / "tmux" / (pane.lstrip("%") + ".txt")
            target.parent.mkdir(mode=0o700, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw.stdout)
                stream.flush()
                os.fsync(stream.fileno())
            record.update(destination=str(target.relative_to(DEST)), bytes=len(raw.stdout),
                          sha256=digest(target), kind="screen_and_retained_scrollback_not_session_checkpoint")
        captures.append(record)
    save("TMUX_BUFFER_INVENTORY.json", command(["tmux", "list-buffers", "-F", "#{buffer_name}|#{buffer_size}"]))
    manifest = dict(files=copied, tmux=captures, blocked=blocked)
    mh = save("COPY_MANIFEST.json", manifest)
    after = process_inventory()
    save("PROCESS_AFTER.json", after)
    free = shutil.disk_usage(DEST).free
    assert free > FLOOR
    os.sync()
    summary = dict(status="COPIED_VERIFIED_WITH_SCOPE_LIMITS", utc=utc(), destination=str(DEST),
        selected_regular_files=len(inventory["selected"]), copied_regular_files=len(copied),
        copied_regular_bytes=sum(e["bytes"] for e in copied),
        hash_or_stability_failures=[e["source"] for e in copied if e["status"] != "VERIFIED"],
        blocked=blocked, tmux_panes=len(captures), tmux_bytes=sum(e.get("bytes", 0) for e in captures),
        capture_errors=sum(e["returncode"] != 0 for e in captures),
        manifest=mh, free_after=free, filesystem_sync="COMPLETED", permissions="directories 0700, files 0600",
        scope_limits=["Only accessible uid-1000 regular files in the three enumerated volatile roots",
          "No root or foreign-user memory inspection, no credential runtime collection",
          "No arbitrary heap, anonymous-memory, editor-buffer, shell-history, or interactive-session checkpoint",
          "Opaque SHM copies are quarantine data, not restartable application state",
          "Terminal captures are private, may include private text, and must not enter Git or be executed",
          "No live session, workload, source, weight, or original temporary file was modified or terminated",
          "SMB write status and inaccessible process state remain unknown",
          "No poweroff was requested or issued by this script; no off-host backup of copied payloads"],
        processes_with_inaccessible_parts=len(after["inaccessible"]),
        deleted_non_system_observed=after["deleted_non_system"],
        volatile_mappings_observed=after["volatile_mappings"],
        volatile_writers_observed=after["volatile_writers"])
    save("SUMMARY.json", summary)
    os.sync()
    print(json.dumps(summary, indent=2))
    if summary["hash_or_stability_failures"] or blocked or summary["capture_errors"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
