"""Pre-import provenance regressions: temporary repositories, never model calls."""

import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout"
    (repo / "scripts").mkdir(parents=True)
    launcher = "scripts/run_source_sealed.py"
    shutil.copyfile(ROOT / launcher, repo / launcher)
    (repo / "scripts/entry.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        "import helper\nprint(helper.marker)\n"
        "print('AUTHORIZED_ENTRY', sys.flags.isolated, sys.argv[1:])\n"
    )
    (repo / "scripts/helper.py").write_text("marker = 'SOURCE_OK'\n")
    (repo / ".gitignore").write_text("__pycache__/\nignored*.py\n*.pyc\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    seal = {
        "source_commit": git(repo, "rev-parse", "HEAD").decode().strip(),
        "source_hashes": {
            n: hashlib.sha256((repo / n).read_bytes()).hexdigest()
            for n in (launcher, "scripts/entry.py", "scripts/helper.py")
        },
    }
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal))
    return repo, seal_path, seal


def invoke(checkout, *extra, isolated=True, env=None):
    repo, seal, _ = checkout
    command = [
        sys.executable,
        *(["-I"] if isolated else []),
        str(repo / "scripts/run_source_sealed.py"),
        "--seal",
        str(seal),
        "--entry",
        "scripts/entry.py",
        *extra,
    ]
    return subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)


def test_isolated_clean_entry_and_check_only(checkout):
    result = invoke(checkout, "--check-only")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["untracked_check"] == "all"
    assert "AUTHORIZED_ENTRY" not in result.stdout
    result = invoke(checkout, "--", "--bounded", "once")
    assert result.returncode == 0, result.stderr
    assert "AUTHORIZED_ENTRY 1 ['--bounded', 'once']" in result.stdout


@pytest.mark.parametrize(
    "path", ["scripts/torch.py", "scripts/extra.txt", "untracked.txt", "src/extra.py"]
)
def test_untracked_fails_before_any_entry_or_model_import(checkout, path):
    repo, _, _ = checkout
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("raise RuntimeError('SHADOW_EXECUTED')\n")
    result = invoke(checkout)
    assert result.returncode != 0
    assert "including untracked" in result.stderr
    assert "SHADOW_EXECUTED" not in result.stderr
    assert "AUTHORIZED_ENTRY" not in result.stdout


@pytest.mark.parametrize("path", ["scripts/ignored_torch.py", "scripts/shadow.pyc"])
def test_ignored_importable_files_fail_closed(checkout, path):
    (checkout[0] / path).write_text("unsealed source")
    result = invoke(checkout)
    assert result.returncode != 0 and "Ignored importable" in result.stderr


def test_pythonpath_and_stale_bytecode_cannot_supply_entry_imports(checkout, tmp_path):
    repo, _, _ = checkout
    helper = repo / "scripts/helper.py"
    source, stat = helper.read_text(), helper.stat()
    # Matching timestamp/size means an ordinary Python import WOULD trust this
    # stale bytecode. The guard must use source, not merely accept the clean Git tree.
    poisoned = "marker = 'CACHE_BAD'\n"
    assert len(poisoned) == len(source)
    helper.write_text(poisoned)
    os.utime(helper, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    py_compile.compile(str(helper), doraise=True)
    helper.write_text(source)
    os.utime(helper, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    ordinary = subprocess.check_output(
        [sys.executable, "-c", "import helper; print(helper.marker)"],
        cwd=helper.parent,
        text=True,
    )
    assert ordinary.strip() == "CACHE_BAD"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "torch.py").write_text("raise RuntimeError('SHADOW_EXECUTED')\n")
    result = invoke(checkout, env={**os.environ, "PYTHONPATH": str(unrelated)})
    assert result.returncode == 0, result.stderr
    assert "AUTHORIZED_ENTRY 1" in result.stdout
    assert "SOURCE_OK" in result.stdout and "CACHE_BAD" not in result.stdout


@pytest.mark.parametrize("failure", ["commit", "hash", "launcher_missing", "escape"])
def test_seal_mismatches_reject_before_launch(checkout, failure):
    _, path, seal = checkout
    if failure == "commit":
        seal["source_commit"] = "0" * 40
    elif failure == "hash":
        seal["source_hashes"]["scripts/entry.py"] = "0" * 64
    elif failure == "launcher_missing":
        del seal["source_hashes"]["scripts/run_source_sealed.py"]
    else:
        seal["source_hashes"]["../outside.py"] = "0" * 64
    path.write_text(json.dumps(seal))
    result = invoke(checkout)
    assert result.returncode != 0 and "AUTHORIZED_ENTRY" not in result.stdout


def test_nonisolated_entry_and_tracked_edits_rejected(checkout):
    assert invoke(checkout, isolated=False).returncode != 0
    (checkout[0] / "scripts/entry.py").write_text("print('MODIFIED_ENTRY')\n")
    result = invoke(checkout)
    assert result.returncode != 0 and "Dirty execution source" in result.stderr
    assert "MODIFIED_ENTRY" not in result.stdout
