"""Offline exact-closure tests for the additive evidence tree."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import seal_v14_judge_extension as seal  # noqa: E402


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    for relative in (
        *seal.EXPLICIT_FILES,
        *(f"{seal.BUNDLE}/{name}" for name in seal.REQUIRED_BUNDLE_FILES),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture artifact\n")
    monkeypatch.setattr(
        seal,
        "verify_payloads",
        lambda _: {
            "panel_status": "VERIFIED_PARTIAL_RECEIPTS_NOT_GOLD",
            "planned_requests": 420,
            "newly_planned_requests": 280,
            "reused_openai_requests": 140,
            "providers": {"gemini": {"not_dispatched_requests": 140}},
            "semantic_promotion": False,
            "winner": "none",
        },
    )
    return tmp_path


def test_scope_is_exact_sorted_and_original_index_referenced(bundle):
    index = seal.make_index(bundle)
    assert index == seal.make_index(bundle)
    paths = [row["path"] for row in index["artifacts"]]
    assert paths == sorted(set(paths))
    assert f"{seal.aggregator.ORIGINAL_BUNDLE}/INDEX.json" in paths
    assert not any("/cells/openai/" in path for path in paths)


def test_seal_and_validation_are_exclusive_and_missingness_survives(bundle):
    assert seal.seal(bundle)["status"] == "SEALED_INTEGRITY_ONLY"
    with pytest.raises(FileExistsError):
        seal.seal(bundle)
    result = seal.verify(bundle, write_receipt=True)
    assert result["planned_requests"] == 420
    assert result["providers"]["gemini"]["not_dispatched_requests"] == 140
    assert seal.verify(bundle) == result
    with pytest.raises(FileExistsError):
        seal.verify(bundle, write_receipt=True)


@pytest.mark.parametrize("mutation", ["extra", "missing", "changed", "duplicate", "original"])
def test_integrity_drift_rejected(bundle, mutation):
    seal.seal(bundle)
    if mutation == "extra":
        (bundle / seal.BUNDLE / "late.json").write_text("{}")
    elif mutation == "missing":
        (bundle / seal.BUNDLE / "README.md").unlink()
    elif mutation == "changed":
        (bundle / seal.BUNDLE / "README.md").write_text("changed")
    elif mutation == "original":
        (bundle / seal.aggregator.ORIGINAL_BUNDLE / "INDEX.json").write_text("changed")
    else:
        path = bundle / seal.BUNDLE / "INDEX.json"
        index = json.loads(path.read_text())
        index["artifacts"].append(index["artifacts"][0])
        path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        seal.verify(bundle)


def test_symlink_escape_and_validation_tampering_rejected(bundle):
    seal.seal(bundle)
    seal.verify(bundle, write_receipt=True)
    path = bundle / seal.BUNDLE / "VALIDATION.json"
    value = json.loads(path.read_text())
    value["planned_requests"] = 280
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="validation receipt"):
        seal.verify(bundle)
    with pytest.raises(ValueError, match="escapes"):
        seal.checked_file(bundle, "../outside")
    (bundle / seal.BUNDLE / "LINK").symlink_to(bundle / seal.BUNDLE / "README.md")
    with pytest.raises(ValueError, match="Symlink"):
        seal.make_index(bundle)


def test_payload_failure_prevents_sealing(bundle, monkeypatch):
    def fail(_):
        raise ValueError("Original bundle changed")

    monkeypatch.setattr(seal, "verify_payloads", fail)
    with pytest.raises(ValueError, match="Original bundle"):
        seal.seal(bundle)
    assert not (bundle / seal.BUNDLE / "INDEX.json").exists()


@pytest.fixture
def original_canaries(tmp_path):
    prefix = f"{seal.BUNDLE}/preflight"
    paths = [
        f"{prefix}/QUALIFICATION.json",
        f"{prefix}/PROBE_EXECUTED.py",
        "scripts/probe_v14_judge_extension.py",
    ]
    paths += [
        f"{prefix}/{directory}/{filename}.json"
        for directory in ("mistral", "gemini", "gemini_3_7")
        for filename in ("REQUEST", "RESPONSE")
    ]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_original_canaries_reconstruct_without_api_or_quote_repair(original_canaries):
    reports = seal.verify_original_canaries(original_canaries)
    assert [row["status"] for row in reports] == [
        "completed",
        "completed",
        "unexpected_model_identity",
    ]
    assert reports[-1]["requested_model"] == "gemini-3.7-flash"
    assert reports[-1]["returned_model"] == "gemini-3.8-flash"


@pytest.mark.parametrize("mutation", ["judgment", "raw", "source", "duplicate"])
def test_canary_qualification_is_not_only_hash_trusted(original_canaries, mutation):
    prefix = original_canaries / seal.BUNDLE / "preflight"
    if mutation in ("judgment", "duplicate"):
        path = prefix / "QUALIFICATION.json"
        document = json.loads(path.read_text())
        if mutation == "judgment":
            document["canaries"][0]["winner"] = "A"
        else:
            document["canaries"].append(document["canaries"][0])
        path.write_text(json.dumps(document))
    elif mutation == "raw":
        path = prefix / "mistral/RESPONSE.json"
        path.write_text(path.read_text() + " ")
    else:
        (prefix / "PROBE_EXECUTED.py").write_text("changed")
    with pytest.raises(ValueError):
        seal.verify_original_canaries(original_canaries)


@pytest.fixture
def gemini38_canary(tmp_path, monkeypatch):
    import probe_v14_gemini38 as probe
    from test_v14_gemini38_panel import response

    for name in (
        "probe_v14_gemini38.py",
        "run_v14_gemini38_panel.py",
        "probe_v14_judge_extension.py",
        "run_v14_judge_panel.py",
        "judge_v14_answer_bank.py",
    ):
        target = tmp_path / "scripts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "scripts" / name, target)
    monkeypatch.setattr(probe, "REPO", tmp_path)
    output = tmp_path / seal.BUNDLE / "preflight/gemini_3_8"
    receipt = probe.run(output, execute=False)
    raw = response(receipt["body"])
    raw_path = output / "RESPONSE.json"
    probe.prior.write_json(raw_path, raw, exclusive=True)
    receipt.update(
        status="response_recorded",
        response_sha256=seal.digest(raw_path),
        observation=probe.runner.response_observation(raw, receipt, probe.CONFIG),
        usage_receipt=probe.runner.usage_receipt(raw, receipt, probe.CONFIG),
        qualification_passed=True,
    )
    probe.prior.write_json(output / "REQUEST.json", receipt)
    return tmp_path


def test_gemini38_canary_reconstructs_strict_judgment_usage_and_sources(gemini38_canary):
    result = seal.verify_gemini38_canary(gemini38_canary)
    assert result["qualification_passed"] is True
    assert result["observation_status"] == "completed" and result["study_judgment"] is False
    assert result["requested_model"] == result["returned_model"] == "gemini-3.8-flash"


@pytest.mark.parametrize("mutation", ["judgment", "raw", "usage", "source", "body"])
def test_gemini38_qualification_tampering_is_rejected(gemini38_canary, mutation):
    prefix = gemini38_canary / seal.BUNDLE / "preflight/gemini_3_8"
    if mutation == "raw":
        path = prefix / "RESPONSE.json"
        path.write_text(path.read_text() + " ")
    elif mutation == "source":
        (gemini38_canary / "scripts/run_v14_gemini38_panel.py").write_text("changed")
    else:
        path = prefix / "REQUEST.json"
        document = json.loads(path.read_text())
        if mutation == "judgment":
            document["observation"]["judgment"]["winner"] = "A"
        elif mutation == "usage":
            document["usage_receipt"]["output_tokens"] += 1
        else:
            document["body"]["contents"][0]["parts"][0]["text"] += "changed"
        path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        seal.verify_gemini38_canary(gemini38_canary)
