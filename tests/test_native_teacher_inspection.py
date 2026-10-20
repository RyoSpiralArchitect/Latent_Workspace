"""Offline contracts only; never load weights or call a teacher."""

import copy
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_native_teacher_inspection as teacher  # noqa: E402

from latent_workspace import world_bank as wb  # noqa: E402


def plan():
    return json.loads((teacher.ROOT / teacher.PLAN).read_text())


def item():
    return dict(kind="world", row=wb.group_rows("candidate", "location", "train", 1)[0])


def response(finish="stop"):
    row = item()["row"]
    return dict(
        choices=[
            dict(
                finish_reason=finish,
                message=dict(
                    content=json.dumps(
                        dict(
                            question=row["query"],
                            answer=row["answer"],
                            answer_value=row["answer_value"],
                            evidence_ids=row["evidence_ids"],
                        )
                    )
                ),
            )
        ],
        usage=dict(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )


def test_fixed_plan_and_request_identity():
    selected = plan()
    teacher.validate_plan(selected)
    body = teacher.request_body(item(), 3, selected)
    assert body["seed"] == 50 and body["max_tokens"] == 256
    assert body["model"] == "ltws-teacher" and body["stream"] is False
    assert len(body["messages"]) == 2
    assert sum(size for _, size, _ in selected["weights"]) == 23262157568


def test_evaluation_exposure_is_rejected():
    selected = item()
    selected["row"]["split"] = "test"
    with pytest.raises(ValueError, match="evaluation"):
        teacher.request_body(selected, 0, plan())


@pytest.mark.parametrize(
    "field,value",
    [
        ("retries", 1),
        ("planned_requests", 65),
        ("host", "0.0.0.0"),
        ("training_admissions", 1),
    ],
)
def test_no_expansion_of_inspection_scope(field, value):
    selected = plan()
    selected[field] = value
    with pytest.raises(ValueError):
        teacher.validate_plan(selected)


@pytest.mark.parametrize(
    "reason,status",
    [
        ("stop", "STRUCTURE_PASS_SEMANTICS_UNREVIEWED"),
        ("length", "TRUNCATED"),
        ("tool_calls", "NON_STOP"),
        (None, "NON_STOP"),
    ],
)
def test_completion_semantics_not_just_parseability(reason, status):
    result = teacher.classify(response(reason), item())
    assert result["status"] == status
    assert result["training_approved"] is False


def test_invalid_json_and_schema_are_retained_as_invalid():
    raw = response()
    raw["choices"][0]["message"]["content"] = "not json"
    assert teacher.classify(raw, item())["status"] == "INVALID_JSON"
    raw["choices"][0]["message"]["content"] = "{}"
    assert teacher.classify(raw, item())["status"] == "STRUCTURE_FAIL"
    raw["choices"] = []
    assert teacher.classify(raw, item())["status"] == "INVALID_RESPONSE"


def test_usage_denominators_and_missingness_are_separate():
    outcomes = [teacher.classify(response(), item()), teacher.classify(response("length"), item())]
    summary = teacher.summarize(outcomes)
    assert summary["attempted_requests"] == 2 and summary["unattempted_requests"] == 62
    assert summary["usage"]["total_tokens"] == 300
    assert summary["training_admissions"] == 0


def test_weight_hash_typo_fails_before_dispatch():
    selected = copy.deepcopy(plan())
    selected["weights"][0][2] += "deadbeef"
    with pytest.raises(ValueError, match="SHA-256"):
        teacher.validate_plan(selected)


def test_extracted_runtime_must_match_pinned_archives(tmp_path):
    runtime = {}
    for key in ("binary_archive", "cuda_archive"):
        name = key + ".tar.gz"
        payload = key.encode()
        with tarfile.open(tmp_path / name, "w:gz") as archive:
            member = tarfile.TarInfo(key + ".bin")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        (tmp_path / (key + ".bin")).write_bytes(payload)
        runtime[key] = name
        runtime[key + "_sha256"] = teacher.ex.digest(tmp_path / name)
    assert len(teacher.verify_runtime_files(tmp_path, runtime)) == 2
    (tmp_path / "binary_archive.bin").write_bytes(b"altered code")
    with pytest.raises(ValueError, match="Extracted runtime changed"):
        teacher.verify_runtime_files(tmp_path, runtime)


def test_runtime_escape_is_rejected(tmp_path):
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    runtime = {
        "binary_archive": archive_path.name,
        "binary_archive_sha256": teacher.ex.digest(archive_path),
    }
    with pytest.raises(ValueError, match="Archive path"):
        teacher.verify_runtime_files(tmp_path, runtime)
