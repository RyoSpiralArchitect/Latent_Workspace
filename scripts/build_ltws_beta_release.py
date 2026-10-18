#!/usr/bin/env python3
"""Build the LTWS β release-candidate folder from the checked rehearsal package; no upload.

The folder is complete: it loads with only its own code and the upstream model. The
script:

1. loads the rehearsal package, which checks its manifest and every route's fingerprint;
2. copies the three routes unchanged;
3. writes the release descriptor: the mean of the three routes as the default reading,
   Apache-2.0 (Ryō, 2026-10-18);
4. copies the engine package unchanged from this checkout, which must be clean;
5. adds the card, license, notice, example and requirements from ``release/ltws_beta/``;
6. writes the manifest, then loads the result once more.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from latent_workspace import package  # noqa: E402

TEMPLATES = ROOT / "release" / "ltws_beta"
ENGINE = ROOT / "src" / "latent_workspace"
UNRESOLVED = "{{COPYRIGHT_HOLDER}}"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean_commit():
    """The checkout's commit; the engine and the release templates must be committed."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/latent_workspace", "release/ltws_beta"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if status.strip():
        raise SystemExit(f"Uncommitted engine or release files:\n{status}")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearsal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--copyright-holder", default=UNRESOLVED)
    args = parser.parse_args()
    commit = clean_commit()
    descriptor, routes = package.load(args.rehearsal)
    rehearsal_manifest = json.loads((args.rehearsal / "MANIFEST.json").read_text())["files"]
    args.out.mkdir(parents=True, exist_ok=False)
    for member in descriptor["members"]:
        shutil.copyfile(args.rehearsal / member["file"], args.out / member["file"])
        copied = args.out / member["file"]
        if sha256(copied) != rehearsal_manifest[member["file"]]["sha256"]:
            raise SystemExit(f"Copy differs: {member['file']}")
    code = args.out / "latent_workspace"
    code.mkdir()
    for source in sorted(ENGINE.glob("*.py")):
        shutil.copyfile(source, code / source.name)
    loader = {
        f"latent_workspace/{p.name}": sha256(code / p.name) for p in sorted(code.glob("*.py"))
    }
    names = [m["name"] for m in descriptor["members"]]
    release = dict(
        descriptor,
        status=(
            "β RELEASE CANDIDATE (research preview). Not uploaded: publication, namespace "
            "and copyright holder await Ryō."
        ),
        default=dict(
            reading="mean",
            members=names,
            decided="Ryō, 2026-10-18: the mean of the three routes, Apache-2.0",
        ),
        license="apache-2.0",
        loader=dict(
            package="latent_workspace",
            source="https://github.com/RyoSpiralArchitect/Latent_Workspace",
            commit=commit,
            files=loader,
        ),
    )
    (args.out / "descriptor.json").write_text(
        json.dumps(release, indent=1, ensure_ascii=False) + "\n"
    )
    for name in ("README.md", "LICENSE", "example.py", "requirements.txt"):
        shutil.copyfile(TEMPLATES / name, args.out / name)
    notice = (TEMPLATES / "NOTICE").read_text()
    notice = notice.replace("{{SOURCE_COMMIT}}", commit)
    notice = notice.replace(UNRESOLVED, args.copyright_holder)
    (args.out / "NOTICE").write_text(notice)
    manifest = package.write_manifest(args.out)
    loaded, members = package.load(args.out)
    print(
        json.dumps(
            dict(
                out=str(args.out),
                commit=commit,
                files=len(manifest["files"]),
                members=list(members),
                copyright_resolved=args.copyright_holder != UNRESOLVED,
                status=loaded["status"],
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
