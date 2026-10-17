#!/usr/bin/env bash
# Retire the 16 feature files listed in INVENTORY.json, for Ryō to run on Furnace.
# Every file's size and SHA-256 must match, and every kept file must be present, before
# anything is removed; a mismatch removes nothing. Writes DELETE_FINISHED.json next to
# this script.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=/home/ryospiralarchitect/spiralreality/SpiralReality/tmp
INVENTORY="$HERE/INVENTORY.json"
cd "$ROOT"
before=$(df -B1 --output=avail . | tail -1 | tr -d ' ')
python3 - "$INVENTORY" <<'PY'
import hashlib, json, os, sys
inventory = json.load(open(sys.argv[1]))
for entry in inventory["kept"]:
    if os.path.getsize(entry["path"]) != entry["bytes"]:
        sys.exit(f"kept file differs: {entry['path']}")
for entry in inventory["files"]:
    path = entry["path"]
    if os.path.getsize(path) != entry["bytes"]:
        sys.exit(f"size differs: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 24), b""):
            digest.update(block)
    if digest.hexdigest() != entry["sha256"]:
        sys.exit(f"sha256 differs: {path}")
print("all", len(inventory["files"]), "files match; removing")
PY
python3 - "$INVENTORY" <<'PY'
import json, os, sys
inventory = json.load(open(sys.argv[1]))
for entry in inventory["files"]:
    os.remove(entry["path"])
PY
after=$(df -B1 --output=avail . | tail -1 | tr -d ' ')
printf '{"status": "RETIRED", "files": 16, "bytes": %s, "available_before": %s, "available_after": %s, "finished_utc": "%s"}\n' \
  "$(python3 -c "import json; print(json.load(open('$INVENTORY'))['total_bytes'])")" "$before" "$after" "$(date -u +%FT%TZ)" \
  > "$HERE/DELETE_FINISHED.json"
cat "$HERE/DELETE_FINISHED.json"
