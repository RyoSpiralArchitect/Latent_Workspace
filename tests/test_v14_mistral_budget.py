"""Synthetic terminal receipts reproduce budget failure without network calls."""

import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import diagnose_v14_mistral_budget as audit  # noqa: E402
from test_v14_mistral_extension import frozen_plan as extension_fixture  # noqa: E402
from test_v14_mistral_extension import parent_plan as parent_fixture  # noqa: E402
from test_v14_mistral_extension import response  # noqa: E402


@pytest.fixture
def finished(tmp_path, monkeypatch):
    parent = parent_fixture.__wrapped__(tmp_path, monkeypatch)
    _, plan, root = extension_fixture.__wrapped__(parent, monkeypatch)
    plan_path = root / audit.PLAN
    audit.runner.prior.write_json(plan_path, plan)
    monkeypatch.setitem(audit.runner.os.environ, "MISTRAL_API_KEY", "SYNTHETIC_SECRET")
    for replicate in range(5):
        index = 0

        def transport(provider, body, key):
            nonlocal index
            index += 1
            if (replicate == 0 and index == 6) or (replicate == 4 and index == 5):
                raise urllib.error.HTTPError("private-url", 500, "private-key", {}, None)
            raw = response(provider, body)
            raw["usage"].update(completion_tokens=4000, total_tokens=4100)
            if replicate == 1 and index == 21:
                raw["usage"].update(completion_tokens=3768, total_tokens=3868)
            else:
                raw["choices"][0]["finish_reason"] = "length"
                chunks = raw["choices"][0]["message"]["content"]
                if replicate == 1 and index <= 12:
                    chunks[1]["text"] = '{"winner": "ti'
                else:
                    del chunks[1:]
            return raw

        audit.runner.execute(
            plan_path, "mistral", replicate,
            root / audit.BUNDLE / "cells/mistral" / f"r{replicate}",
            execute_api=True, transport=transport,
        )
    monkeypatch.setattr(audit.runner, "dispatch", lambda *_: pytest.fail("Unexpected API call"))
    return root


def file_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file()}


def test_reconstruction_counts_and_boundaries_are_exact_and_read_only(finished):
    before = file_bytes(finished)
    value = audit.reconstruct(finished)
    assert before == file_bytes(finished)
    assert value == audit.reconstruct(finished)
    assert value["counts"] == {
        "planned_requests": 140, "reserved_requests": 95, "durable_responses": 93,
        "strict_valid_judgments": 1, "incomplete_responses": 92, "http_errors": 2,
        "not_dispatched_requests": 45, "complete_valid_order_pairs": 0,
        "changed_pair_valid_judgments": 0, "all_five_stable_pair_preferences": 0,
    }
    assert value["completion_token_counts"] == {"3768": 1, "4000": 92}
    assert value["envelope_counts"] == {
        "thinking_only_no_final_text": 80, "thinking_and_final_text": 13,
        "final_invalid_json_fragments": 12, "final_syntactically_valid_json": 1,
        "unknown_envelopes": 0, "at_requested_output_token_cap": 92,
        "length_termination_at_cap": 92,
    }
    assert value["usage"]["reported_output_tokens"] == 371768
    assert value["usage"]["reported_input_tokens"] == 9300
    assert value["usage"]["calls_without_reported_usage"] == 2
    assert value["usage"]["actual_billed_cost_usd"] is None
    assert len(value["artifact_bindings"]) == 5 * 4 + 95 + 93
    for bound in value["artifact_bindings"]:
        assert not Path(bound["path"]).is_absolute()
        assert audit.runner.prior.file_sha(finished / bound["path"]) == bound["sha256"]
    valid = value["valid_judgments"]
    assert len(valid) == 1 and valid[0]["calibration_only"] and valid[0]["winner"] == "tie"
    assert valid[0]["order"] == "AB" and valid[0]["replicate"] == 1
    assert all(row["http_status"] == 500 for row in value["unresolved_transport_failures"])
    serialized = json.dumps(value)
    assert "SYNTHETIC_THINKING_NOT_A_VERDICT" not in serialized
    assert "SYNTHETIC_SECRET" not in serialized
    assert "private-key" not in serialized and "private-url" not in serialized
    assert "Base answer" not in serialized


@pytest.mark.parametrize("target", ["raw", "receipt", "summary", "plan", "source"])
def test_reconstruction_rejects_tampering(finished, target):
    if target == "raw":
        path = next((finished / audit.BUNDLE / "cells/mistral/r1/responses").glob("*.json"))
    elif target == "receipt":
        path = next((finished / audit.BUNDLE / "cells/mistral/r1/requests").glob("*.json"))
    elif target == "summary":
        path = finished / audit.BUNDLE / "cells/mistral/r1/SUMMARY.json"
    elif target == "source":
        path = finished / "scripts/run_v14_mistral_extension.py"
        path.write_text(path.read_text() + "\n# drift\n")
        with pytest.raises(ValueError):
            audit.reconstruct(finished)
        return
    else:
        path = finished / audit.PLAN
    value = json.loads(path.read_text())
    if target == "receipt":
        value["order"] = "CHANGED"
    elif target == "plan":
        value["providers"]["mistral"]["max_output_tokens"] = 16000
    else:
        value["changed"] = True
    audit.runner.prior.write_json(path, value)
    with pytest.raises(ValueError):
        audit.reconstruct(finished)


def test_unfinished_cell_is_not_reported_as_final(finished):
    path = finished / audit.BUNDLE / "cells/mistral/r0/SUMMARY.json"
    path.unlink()
    with pytest.raises(ValueError, match="not finished"):
        audit.reconstruct(finished)


def test_extra_cell_directory_is_rejected(finished):
    (finished / audit.BUNDLE / "cells/mistral/r5").mkdir()
    with pytest.raises(ValueError, match="exactly five"):
        audit.reconstruct(finished)


def test_wrong_root_is_rejected(finished, tmp_path):
    with pytest.raises(ValueError, match="root must match"):
        audit.reconstruct(tmp_path / "unbound")


def test_envelope_never_accesses_thinking_field():
    class NoThinkingAccess(dict):
        def __getitem__(self, key):
            if key == "thinking":
                pytest.fail("Thinking field was accessed")
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key == "thinking":
                pytest.fail("Thinking field was accessed")
            return super().get(key, default)

    raw = {"choices": [{"finish_reason": "length", "message": {"content": [
        NoThinkingAccess(type="thinking", closed=True),
    ]}}]}
    result = audit.envelope(raw)
    assert result["thinking_chunk_count"] == 1
    assert result["final_json_syntax"] == "NO_FINAL_TEXT"


@pytest.mark.parametrize("raw,status", [
    ({}, "UNKNOWN_CHOICE_SHAPE"),
    ({"choices": [{}]}, "UNKNOWN_MESSAGE_SHAPE"),
    ({"choices": [{"message": {}}]}, "UNKNOWN_CONTENT_SHAPE"),
    ({"choices": [{"message": {"content": [{"type": "tool_call"}]}}]},
     "UNSUPPORTED_CONTENT_TYPE"),
])
def test_unknown_envelopes_are_explicit(raw, status):
    assert audit.envelope(raw) == {"envelope_status": status}
