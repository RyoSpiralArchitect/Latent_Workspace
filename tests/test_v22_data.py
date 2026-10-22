"""No pretrained model or network: selection, masks, denominators and split gates."""

import copy
from pathlib import Path

import pytest

from latent_workspace import execution as ex
from latent_workspace import v22_data as data
from latent_workspace import world_bank


class Tokenizer:
    eos_token_id = 2

    def encode(self, text, **kwargs):
        return [
            3 + int(ex.hashlib.sha256(w.encode()).hexdigest()[:8], 16) % 32765 for w in text.split()
        ]

    def apply_chat_template(self, messages, **kwargs):
        return [1, 11, 12, *self.encode(messages[0]["content"])]


def fixture():
    plan = ex.read(Path(__file__).resolve().parents[1] / "configs/v22/DATA_01.json")
    plan.update(
        unique_training_updates=4,
        minimum_window_supervised_tokens=25,
        dev_preservation_rows={"instruction": 1, "prose": 1, "code": 1},
    )
    preservation, worlds = [], []
    for split in ("train", "dev"):
        for i, role in enumerate(("instruction", "prose", "code")):
            for j in range(3):
                body = [11 + i * 3 + j + (split == "dev") * 9] * (8 + i + j)
                preservation.append(
                    dict(
                        row_id=f"p/{split}/{role}/{j}",
                        group_id=f"p/{split}/{role}/{j}",
                        split=split,
                        role=role,
                        language="en",
                        memory=[],
                        input_ids=[1, *body],
                        labels=[-100, *body],
                    )
                )
        for family in plan["world_families"]:
            group = f"fixture-{split}-{family}"
            worlds.extend(world_bank.group_rows(group, family, split, 47))
    japanese = {**preservation[0], "row_id": "p/ja", "group_id": "p/ja", "language": "ja"}
    preservation.append(japanese)
    rows, excluded = data.project(preservation, worlds, Tokenizer(), plan)
    return plan, rows, excluded, preservation, worlds


def test_projection_is_additive_english_only_and_deduplicates_world_controls():
    plan, rows, excluded, preservation, worlds = fixture()
    before = ex.plan_hash([preservation, worlds])
    again, _ = data.project(preservation, worlds, Tokenizer(), plan)
    assert rows == again and before == ex.plan_hash([preservation, worlds])
    assert all(r["language"] == "en" for r in rows)
    assert excluded["preservation/ja/train"] == 1
    assert excluded["world/duplicate/train"] == 12
    assert excluded["world/duplicate/dev"] == 12
    assert sum(len(r.get("duplicate_aliases", [])) for r in rows) == 24


def test_complete_labels_and_no_memory_preservation():
    plan, rows, *_ = fixture()
    for row in rows:
        data.validate_row(row, plan)
        if row["role"] == "world":
            assert row["labels"][:3] == [-100] * 3 and row["labels"][-1] == 2
        else:
            assert row["memory_ids"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "language",
        "split",
        "role",
        "first_label",
        "label_value",
        "token",
        "denominator",
        "memory",
        "length",
    ],
)
def test_invalid_admission_fails_closed(fault):
    plan, rows, *_ = fixture()
    row = copy.deepcopy(next(r for r in rows if r["role"] == "instruction"))
    if fault in ("language", "split", "role"):
        row[fault] = "invalid"
    elif fault == "first_label":
        row["labels"][0] = 1
    elif fault == "label_value":
        row["labels"][-1] = 42
    elif fault == "token":
        row["input_ids"][-1] = -1
    elif fault == "denominator":
        row["supervised_tokens"] += 1
    elif fault == "memory":
        row["memory_ids"] = [2]
    else:
        plan["maximum_query_tokens"] = 2
    with pytest.raises(ValueError):
        data.validate_row(row, plan)


def test_schedule_is_seeded_complete_row_and_train_only():
    plan, rows, *_ = fixture()
    schedule = data.schedule(rows, plan)
    assert schedule == data.schedule(list(reversed(rows)), plan)
    by_id = {r["key"]: r for r in rows}
    for window in schedule:
        assert len(window) == len(set(window))
        assert all(by_id[k]["split"] == "train" for k in window)
        assert sum(by_id[k]["supervised_tokens"] for k in window) >= 25
    changed = dict(plan, seed="another")
    assert schedule != data.schedule(rows, changed)


@pytest.mark.parametrize("fault", ["shares", "missing_pool", "row_limit"])
def test_scheduler_rejects_missing_or_unbounded_recipe(fault):
    plan, rows, *_ = fixture()
    if fault == "shares":
        plan["target_supervised_token_shares"]["world"] = 2
    elif fault == "missing_pool":
        rows = [r for r in rows if r["role"] != "code"]
    else:
        plan["maximum_window_rows"] = 1
    with pytest.raises(ValueError):
        data.schedule(rows, plan)


def test_dev_stratification_and_length_canary_are_fixed_before_model_execution():
    plan, rows, excluded, *_ = fixture()
    dev, canary = data.select_dev(rows, plan), data.select_canary(rows, plan)
    by_id = {r["key"]: r for r in rows}
    assert len(dev) == 27 and all(by_id[k]["split"] == "dev" for k in dev)
    assert list(map(len, canary)) == [4, 5]
    assert all(by_id[k]["split"] == "train" for w in canary for k in w)
    assert by_id[canary[0][1]]["group_id"] == by_id[canary[0][2]]["group_id"]
    result = data.summarize(rows, data.schedule(rows, plan), canary, dev, excluded, plan)
    assert result["training_tokens"] == sum(result["training_tokens_by_role"].values())
    assert sum(result["realized_supervised_token_shares"].values()) == pytest.approx(1)
    assert sum(result["mean_window_objective_shares"].values()) == pytest.approx(1)
    assert result["old_expression_gate"] == "FAIL" and result["quality_claim"] == "NOT_ESTABLISHED"


def test_group_leakage_rejected():
    plan, _, _, preservation, worlds = fixture()
    left = next(r for r in preservation if r["split"] == "train")
    right = next(r for r in preservation if r["split"] == "dev")
    right["group_id"] = left["group_id"]
    with pytest.raises(ValueError, match="Group leakage"):
        data.project(preservation, worlds, Tokenizer(), plan)


def test_test_and_ood_worlds_are_excluded():
    plan, _, _, preservation, worlds = fixture()
    worlds.extend(world_bank.group_rows("test-world", "location", "test", 47))
    worlds.extend(world_bank.group_rows("ood-world", "linked_location", "ood", 47))
    rows, excluded = data.project(preservation, worlds, Tokenizer(), plan)
    assert excluded["world/test"] == 8 and excluded["world/ood"] == 8
    assert not any(r["split"] in ("test", "ood") for r in rows)
