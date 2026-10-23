import copy
from pathlib import Path

import pytest

from latent_workspace import execution as ex
from latent_workspace import recruitment_bank as bank

PLAN = ex.read(Path(__file__).resolve().parents[1] / "configs/v24/RECRUITMENT_BANK_01.json")


class Tokenizer:
    eos_token_id = 2

    def encode(self, text, **kwargs):
        # Small deterministic tokenizer double, not a numerical/tokenizer parity claim.
        return [
            int(ex.plan_hash(text[i : i + 4])[:6], 16) % 32000 + 3 for i in range(0, len(text), 4)
        ]

    def apply_chat_template(self, messages, **kwargs):
        return [1] + self.encode(messages[0]["content"])


def test_full_frozen_bank_and_group_controls():
    rows = bank.build(PLAN)
    assert rows == bank.build(PLAN)
    assert bank.audit(rows) == dict(
        groups=264, rows=2112, rows_by_split=dict(train=1536, dev=192, confirmation=384)
    )
    assert len({r["group_id"] for r in rows}) == 264
    assert all(bank.score(r["answer"], r["oracle"])["exact"] for r in rows)


@pytest.mark.parametrize("family", bank.FAMILIES)
def test_route_parity_masks_aliases_and_heldout_exclusion(family):
    raw = [r for r in bank.build(PLAN) if r["family"] == family]
    a, b = [bank.project(raw, Tokenizer(), route) for route in bank.ROUTES]
    bank.match_routes(a, b)
    assert len(a) == 72 * 6  # four informative rows plus deduplicated missing controls
    for x, y in zip(a, b, strict=True):
        assert x["split"] != "confirmation"
        assert x["target_ids"] == y["target_ids"]
        for row in (x, y):
            assert row["labels"][0] == -100
            assert [t for t in row["labels"] if t != -100] == row["target_ids"]
            assert row["supervised_tokens"] == len(row["target_ids"])
        if x["mode"] == "absent":
            assert x["input_ids"] == y["input_ids"] and not y["memory_ids"]


@pytest.mark.parametrize(
    "field", ["target_ids", "key", "source_information_sha256", "duplicate_aliases"]
)
def test_changed_route_contract_rejected(field):
    raw = bank.group_rows("recruit-20261023-test-1", "arithmetic", "train", 47)
    a, b = [bank.project(raw, Tokenizer(), route) for route in bank.ROUTES]
    b[0][field] = "changed"
    with pytest.raises(ValueError):
        bank.match_routes(a, b)


@pytest.mark.parametrize(
    "damage", ["reference", "group", "duplicate", "missing", "semantic_duplicate"]
)
def test_bank_tampering_rejected(damage):
    rows = bank.build(PLAN)
    if damage == "reference":
        rows[0]["answer"] = "{}"
    elif damage == "group":
        rows[0]["split"] = "dev"
    elif damage == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif damage == "missing":
        rows.pop()
    else:
        # A duplicate problem cannot be laundered by changing only group identity.
        twin = copy.deepcopy(rows[:8])
        for r in twin:
            r["group_id"] = "new-group"
        rows.extend(twin)
    with pytest.raises(ValueError):
        bank.audit(rows)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{",
        "null",
        "[]",
        '{"answer":true}',
        '{"answer":NaN}',
        '{"answer":1,"answer":2}',
        '{"answer":1e999}',
    ],
)
def test_bad_outputs_remain_wrong(text):
    result = bank.score(text, dict(steps=[1], answer=1))
    assert not result["exact"] and not result["content_correct"]


def test_content_and_steps_are_separate_not_a_format_promotion():
    expected = dict(steps=[10, 20], answer=20)
    result = bank.score('{"steps":[8,20],"answer":20}', expected)
    assert result == dict(parsed=True, content_correct=True, steps_correct=False, exact=False)
    assert bank.score('{"answer":20,"steps":[10,20],"extra":"claim"}', expected)["exact"] is False
    assert bank.score('{ "answer" : 20, "steps" : [10,20] }', expected)["exact"] is True


def test_five_role_schedule_route_equal_and_train_only():
    rows = []
    for role in PLAN["target_supervised_token_shares"]:
        for i in range(40):
            rows.append(dict(key=f"{role}-{i}", role=role, split="train", supervised_tokens=10 + i))
    rows.append(dict(key="heldout", role="world", split="confirmation", supervised_tokens=1))
    schedule = bank.schedule(rows, PLAN)
    assert len(schedule) == 32 and all("heldout" not in w for w in schedule)
    assert schedule == bank.schedule(list(reversed(rows)), PLAN)
    lookup = {r["key"]: r for r in rows}
    assert all(sum(lookup[k]["supervised_tokens"] for k in w) >= 512 for w in schedule)
