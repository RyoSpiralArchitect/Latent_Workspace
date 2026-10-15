"""Offline replay parsing rejects ambiguous/nonfinite artifact values."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replay_v18_operand_selection as replay  # noqa: E402


@pytest.mark.parametrize("text", [
    '{"a":1,"a":2}', '{"x":{"a":1,"a":2}}',
    '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}',
])
def test_ambiguous_or_nonfinite_json_rejected(text):
    with pytest.raises(ValueError):
        replay.strict_json(text)


def test_scalar_and_array_values_preserved():
    assert replay.strict_json('{"n":2,"v":[0.125,-0.5],"b":false}') == {
        "n": 2, "v": [0.125, -0.5], "b": False,
    }
