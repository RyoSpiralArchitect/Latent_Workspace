"""Publication sealing tests use temporary fixtures, never the real experiment."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "answer_bank_bundle_verify",
    REPO / "provenance/pilots/v14_answer_bank_20261009/verify.py",
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "repo"
    bundle = root / "provenance/pilots/v14_answer_bank_20261009"
    for relative in (
        verifier.PLAN,
        verifier.CASES,
        "configs/v14/ANSWER_BANK_PLAN.json",
        "scripts/render_v14_answer_bank.py",
        "tests/test_v14_answer_bank_bundle.py",
        "src/latent_workspace_ft_v10/answer_bank_generation.py",
        "provenance/pilots/v14_answer_bank_20261009/verify.py",
        "provenance/pilots/v14_answer_bank_20261009/reader/human_scores.csv",
        "provenance/pilots/v14_answer_bank_20261009/raw/report.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    return root, bundle


def test_inventory_is_closed_and_excludes_only_declared_receipts_and_bytecode(tree):
    root, bundle = tree
    for name in verifier.EXCLUDED:
        (bundle / name).write_text("{}\n")
    nested = bundle / "reader/VALIDATION.json"
    nested.write_text("{}\n")
    files = verifier.inventory(root, bundle)
    assert nested.relative_to(root).as_posix() in files
    assert all(
        (bundle / name).relative_to(root).as_posix() not in files for name in verifier.EXCLUDED
    )
    assert "scripts/render_v14_answer_bank.py" in files
    assert "tests/test_v14_answer_bank_bundle.py" in files
    verifier.check_index(verifier.index_document(files, root), files, root)


def test_only_python_bytecode_cache_ephemera_are_ignored(tree):
    root, bundle = tree
    files_before = verifier.inventory(root, bundle)
    cache = bundle / "__pycache__"
    cache.mkdir()
    bytecode = cache / "verify.cpython-313.pyc"
    bytecode.write_bytes(b"interpreter cache")
    assert verifier.inventory(root, bundle) == files_before
    index = verifier.index_document(files_before, root)
    assert index["excluded_ephemera"] == ["**/__pycache__/*.pyc"]
    verifier.check_index(index, verifier.inventory(root, bundle), root)
    bytecode.write_bytes(b"different interpreter cache")
    verifier.check_index(index, verifier.inventory(root, bundle), root)
    # Do not silently exclude arbitrary files in the cache or .pyc files elsewhere.
    for path in (cache / "evidence.json", bundle / "scientific.pyc"):
        path.write_bytes(b"must be indexed")
        assert path.relative_to(root).as_posix() in verifier.inventory(root, bundle)
    with pytest.raises(ValueError, match="path closure"):
        verifier.check_index(index, verifier.inventory(root, bundle), root)
    index["excluded_ephemera"] = ["**/*"]
    with pytest.raises(ValueError, match="exclusion rule"):
        verifier.check_index(index, verifier.inventory(root, bundle), root)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "bytes", "sha", "path"])
def test_index_rejects_changed_or_unclosed_artifacts(tree, mutation):
    root, bundle = tree
    files = verifier.inventory(root, bundle)
    index = verifier.index_document(files, root)
    if mutation == "missing":
        index["artifacts"].pop()
    elif mutation == "duplicate":
        index["artifacts"].append(dict(index["artifacts"][0]))
    elif mutation == "extra":
        (bundle / "unindexed.json").write_text("{}\n")
        files = verifier.inventory(root, bundle)
    elif mutation == "bytes":
        index["artifacts"][0]["bytes"] += 1
    elif mutation == "sha":
        index["artifacts"][0]["sha256"] = "0" * 64
    else:
        index["artifacts"][0]["path"] = "../outside"
    with pytest.raises(ValueError):
        verifier.check_index(index, files, root)


def test_symlinks_and_escaping_paths_are_rejected(tree):
    root, bundle = tree
    with pytest.raises(ValueError, match="Noncanonical"):
        verifier.safe_path(root, "../outside")
    (bundle / "link.json").symlink_to(root / verifier.PLAN)
    with pytest.raises(ValueError, match="Symlink"):
        verifier.inventory(root, bundle)
    with pytest.raises(ValueError, match="Symlink"):
        verifier.safe_path(root, (bundle / "link.json").relative_to(root).as_posix())


def test_exclusive_seal_and_receipt_preserve_existing_human_edits(tree, monkeypatch):
    root, bundle = tree
    monkeypatch.setattr(verifier, "evidence_checks", lambda *_: {"human_labels": "PENDING_BLANK"})
    monkeypatch.setattr(verifier.subprocess, "check_output", lambda *_, **__: "f" * 40 + "\n")
    result = verifier.verify(seal=True, write_receipt=True, root=root, bundle=bundle)
    assert result["status"] == "PASS"
    assert result["artifact_index_sha256"] == verifier.sha(bundle / "ARTIFACT_INDEX.json")
    assert verifier.verify(root=root, bundle=bundle) == result
    with pytest.raises(FileExistsError):
        verifier.verify(seal=True, root=root, bundle=bundle)
    with pytest.raises(FileExistsError):
        verifier.verify(write_receipt=True, root=root, bundle=bundle)
    human = bundle / "reader/human_scores.csv"
    human.write_text("A HUMAN EDIT\n")
    before = {path: path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="Artifact changed"):
        verifier.verify(root=root, bundle=bundle)
    assert before == {path: path.read_bytes() for path in bundle.rglob("*") if path.is_file()}


def test_failed_checks_never_create_index_or_receipt(tree, monkeypatch):
    root, bundle = tree

    def failed(*_):
        raise ValueError("incomplete primary evidence")

    monkeypatch.setattr(verifier, "evidence_checks", failed)
    with pytest.raises(ValueError, match="incomplete"):
        verifier.verify(seal=True, write_receipt=True, root=root, bundle=bundle)
    assert not (bundle / "ARTIFACT_INDEX.json").exists()
    assert not (bundle / "VALIDATION.json").exists()


def test_started_report_mismatch_stops_before_bank_or_judge(tree):
    root, bundle = tree
    started = {"source_commit": "a" * 40}
    (bundle / "raw/STARTED.json").write_text(json.dumps(started))
    (bundle / "raw/report.json").write_text(json.dumps({"source_commit": "b" * 40}))
    with pytest.raises(ValueError, match="STARTED/report mismatch: source_commit"):
        verifier.evidence_checks(root, bundle)
