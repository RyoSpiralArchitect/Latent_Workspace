"""Offline controls only; never dispatch to an API from tests."""

import copy
import json
import urllib.error

import pytest
import v23_behavior_judge as j


def response(request, better="A"):
    result = dict(
        better=better,
        correctness_A="correct",
        correctness_B="incorrect",
        complete_A=True,
        complete_B=True,
        reason="A is factually correct.",
        quote_A=request["shown"]["A"]["text"],
        quote_B=request["shown"]["B"]["text"],
    )
    return dict(
        model="mistral-large-4",
        id="mock-only",
        usage=dict(total_tokens=7),
        choices=[
            dict(finish_reason="stop", message=dict(role="assistant", content=json.dumps(result)))
        ],
    )


def test_frozen_calibration_counts_and_blinding(tmp_path):
    p = tmp_path / "calibration"
    assert j.freeze(p, "calibration")["requests"] == 32
    seal, cases, requests = j.verify(p)
    assert len(cases) == 8 and seal["phase"] == "calibration"
    assert len({r["id"] for r in requests}) == 32
    for c in cases:
        a = j.request(c, "AB", 0, j.plan())
        again = j.request(c, "AB", 1, j.plan())
        reverse = j.request(c, "BA", 0, j.plan())
        assert a["body"] == again["body"] and a["id"] != again["id"]
        assert a["shown"]["A"] == reverse["shown"]["B"]
        assert "expected" not in a["body"]["messages"][1]["content"]
    blind = j.ex.read(p / "BLIND_PACKET.json")
    assert all(set(r) == {"id", "task", "A", "B"} for r in blind["rows"])


@pytest.mark.parametrize(
    "damage",
    [
        "quote",
        "field",
        "duplicate",
        "length",
        "refusal",
        "model",
        "tool",
        "open_thinking",
        "nonobject",
    ],
)
def test_invalid_responses_not_success(damage):
    r = j.request(j.fixtures()[0], "AB", 0, j.plan())
    raw = response(r)
    msg = raw["choices"][0]["message"]
    value = json.loads(msg["content"])
    if damage == "quote":
        value["quote_A"] = "not present"
        msg["content"] = json.dumps(value)
    elif damage == "field":
        value["extra"] = True
        msg["content"] = json.dumps(value)
    elif damage == "duplicate":
        msg["content"] = msg["content"][:-1] + ', "better": "B"}'
    elif damage == "length":
        raw["choices"][0]["finish_reason"] = "length"
    elif damage == "refusal":
        msg["refusal"] = "refused"
    elif damage == "model":
        raw["model"] = "other"
    elif damage == "tool":
        msg["tool_calls"] = [{}]
    elif damage == "open_thinking":
        msg["content"] = [dict(type="thinking", thinking=[], closed=False)]
    elif damage == "nonobject":
        raw = []
    assert j.observe(raw, r, j.plan())["status"] != "VALID"


def test_closed_thinking_is_not_used_as_final_answer():
    r = j.request(j.fixtures()[0], "AB", 0, j.plan())
    raw = response(r)
    msg = raw["choices"][0]["message"]
    msg["content"] = [
        dict(type="thinking", closed=True, thinking=[dict(type="text", text='{"better":"B"}')]),
        dict(type="text", text=msg["content"]),
    ]
    assert j.observe(raw, r, j.plan())["judgment"]["better"] == "A"


@pytest.mark.parametrize("failure", [TimeoutError, urllib.error.HTTPError])
def test_ambiguous_or_http_failure_stops_and_never_resumes(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("MISTRAL_API_KEY", "offline-dummy-not-a-key")
    folder = tmp_path / "frozen"
    j.freeze(folder, "calibration")
    calls = []

    def dispatch(url, key, body=None, timeout=0):
        if body is None:
            return dict(id="mistral-large-4")
        calls.append(copy.deepcopy(body))
        if failure is TimeoutError:
            raise TimeoutError()
        raise urllib.error.HTTPError(url, 429, "test", None, None)

    out = j.run(folder, execute_api=True, dispatch=dispatch)
    assert len(calls) == 1 and out["statuses"]["NOT_DISPATCHED"] == 31
    assert out["calibration_gate"] == "FAIL_OR_INCOMPLETE"
    with pytest.raises(FileExistsError):
        j.run(folder, execute_api=True, dispatch=dispatch)
    assert len(calls) == 1


def test_mock_calibration_pass_and_terminal_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "offline-dummy-not-a-key")
    folder = tmp_path / "frozen"
    j.freeze(folder, "calibration")
    _, cases, requests = j.verify(folder)
    expected = {c["id"]: c["expected"] for c in cases}
    lookup = {r["body_sha256"]: r for r in requests}

    def dispatch(url, key, body=None, timeout=0):
        if body is None:
            return dict(id="mistral-large-4")
        r = lookup[j.ex.plan_hash(body)]
        better = j.normalized(dict(better=expected[r["case_id"]]), r["order"])
        return response(r, better)

    out = j.run(folder, execute_api=True, dispatch=dispatch)
    assert out["statuses"] == {"VALID": 32}
    assert out["calibration_gate"] == "PASS"
    assert j.replay(folder)["calibration_gate"] == "PASS"
    (folder / "run/MODEL_METADATA.json").write_text("{}")
    with pytest.raises(ValueError, match="Terminal run manifest"):
        j.replay(folder)


def test_no_study_after_failed_calibration_or_without_execute_flag(tmp_path):
    folder = tmp_path / "calibration"
    j.freeze(folder, "calibration")
    with pytest.raises(ValueError, match="Explicit API"):
        j.run(folder)
    assert not (folder / "run").exists()


def test_missing_generation_terminal_never_makes_a_study(tmp_path):
    with pytest.raises(FileNotFoundError):
        j.study_cases(tmp_path, j.plan())


def test_study_denominator_is_all_pairs_plus_prespecified_repeats_and_controls():
    p = j.plan()
    assert 12 * 2 * 3 * 2 + 4 * 3 * 2 + 3 * 2 == p["study_requests"] == 174
    assert p["calibration_required_expected"] == p["calibration_requests"] == 32
