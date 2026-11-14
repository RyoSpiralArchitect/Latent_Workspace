import copy
import json

import pytest
from test_recruitment_bank import PLAN, Tokenizer

from latent_workspace import recruitment_bank as bank
from latent_workspace import recruitment_order as order


@pytest.fixture(scope="module")
def raw():
    return bank.build(PLAN)


def test_default_projection_is_byte_identical_to_historical(raw):
    before = copy.deepcopy(raw)
    actual = order.project_pair(raw, Tokenizer(), "answer_first")
    for route in bank.ROUTES:
        assert actual[route] == bank.project(raw, Tokenizer(), route)
    assert raw == before


def test_steps_first_changes_only_present_reasoning_targets(raw):
    original = order.project_pair(raw, Tokenizer(), "answer_first")
    changed = order.project_pair(raw, Tokenizer(), "steps_first")
    for route in bank.ROUTES:
        baseline = {row["key"]: row for row in original[route]}
        revised = {row["key"]: row for row in changed[route]}
        assert baseline.keys() == revised.keys()
        for key, a in baseline.items():
            b = revised[key]
            for field in ("key", "group_id", "split", "family", "side", "mode", "memory_ids"):
                assert a[field] == b[field]
            # A changed training target never modifies query or external M.
            assert (
                a["input_ids"][: -len(a["target_ids"])] == b["input_ids"][: -len(b["target_ids"])]
            )
            assert (
                b["labels"]
                == [-100] * (len(b["input_ids"]) - len(b["target_ids"])) + b["target_ids"]
            )
            if a["mode"] in ("absent", "unrelated"):
                assert a == b
            else:
                assert a["target_ids"] != b["target_ids"]
    bank.match_routes(changed["inline"], changed["workspace"])
    assert all(row["split"] != "confirmation" for row in changed["inline"])


@pytest.mark.parametrize("family", bank.FAMILIES)
def test_semantic_oracle_and_first_field(family):
    rows = bank.group_rows("recruit-20261023-order-test", family, "train", 47)
    for row in rows:
        value = order.serialized_answer(row, "steps_first")
        assert json.loads(value) == row["oracle"]
        keys = list(json.loads(value))
        assert keys == (
            ["steps", "answer"] if row["mode"] in ("affected", "unaffected") else ["answer"]
        )
        assert row["answer"] == json.dumps(row["oracle"], sort_keys=True, separators=(",", ":"))


def test_rejects_unknown_order_or_source_drift():
    row = bank.group_rows("recruit-20261023-order-test", "arithmetic", "train", 47)[0]
    with pytest.raises(ValueError, match="Known target order"):
        order.serialized_answer(row, "other")
    row["answer"] = "{}"
    with pytest.raises(ValueError, match="Original source reference intact"):
        order.serialized_answer(row, "steps_first")
