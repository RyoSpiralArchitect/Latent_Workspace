"""Stat-only inventory: never changes source files; writes one metadata receipt."""
import datetime
import json
import os
import pathlib
import subprocess
import sys

expected = "https://github.com/RyoSpiralArchitect/Latent_Workspace.git"
origin = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
if origin != expected:
    raise SystemExit("Wrong repository")
listing = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
roots = [pathlib.Path(line[9:]) for line in listing.splitlines() if line.startswith("worktree ")]
prefix = pathlib.Path("/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees")
rows, scopes, errors = [], [], []
for root in roots:
    if root.parent != prefix or not root.name.startswith("latent-workspace-") or root.is_symlink():
        errors.append({"root": str(root), "error": "outside explicit project worktree scope"})
        continue
    for folder in ("runs", "experiments", "resume_gates"):
        scope = root / folder
        if not scope.is_dir() or scope.is_symlink():
            continue
        scopes.append(str(scope))
        # rg is not installed on this host; find is the read-only fallback.
        command = ["find", str(scope), "-type", "f", "(", "-name", "*.pt", "-o", "-name",
                   "*.pth", "-o", "-name", "*.bin", "-o", "-name", "*.safetensors", ")", "-print"]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode not in (0, 1):
            errors.append({"root": str(scope), "error": result.stderr})
            continue
        for name in sorted(result.stdout.splitlines()):
            path = pathlib.Path(name)
            if path.is_symlink() or any(part.lower() in
                    {".venv", "cache", ".cache", "model_cache", "hf", "huggingface", "hf_cache"}
                    for part in path.relative_to(scope).parts):
                continue
            st = path.stat(follow_symlinks=False)
            rows.append({"path": str(path), "scope": str(scope), "bytes": st.st_size,
                         "allocated_bytes": st.st_blocks * 512, "links": st.st_nlink,
                         "device": st.st_dev, "inode": st.st_ino,
                         "mtime_utc": datetime.datetime.fromtimestamp(
                             st.st_mtime, datetime.timezone.utc).isoformat()})
unique = {(r["device"], r["inode"]): r["allocated_bytes"] for r in rows}
fs = os.statvfs(prefix)
value = {"schema": "latent-weight-stat-inspection-v1", "remote": origin,
                  "observed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "scopes": scopes, "weights": rows, "errors": errors,
                  "count": len(rows), "logical_bytes": sum(r["bytes"] for r in rows),
                  "unique_allocated_bytes": sum(unique.values()),
                  "persistent_available_bytes": fs.f_bavail * fs.f_frsize,
                  "deleted": 0, "weight_contents_read": False, "hashes_verified": False,
                  "base_and_model_caches": "excluded and protected; not inventoried"}
with pathlib.Path(sys.argv[1]).open("x") as stream:
    json.dump(value, stream, indent=2)
print(json.dumps({k: v for k, v in value.items() if k not in ("weights", "scopes")}))
