import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
import prepare_v24_recruitment as prep  # noqa: E402
from test_recruitment_bank import PLAN, Tokenizer  # noqa: E402


def inputs():
    # A tokenizer double tests schedule/mask contracts; real token bounds are
    # checked during the separately sealed offline preparation on Furnace.
    raw = prep.bank.build(PLAN)
    other = []
    for row in raw:
        item = copy.deepcopy(row)
        item.update(
            row_id="world-" + row["row_id"], group_id="world-" + row["group_id"], role="world"
        )
        other.append(item)
    pres = []
    for role in ("instruction", "prose", "code"):
        for split, count in (("train", 40), ("dev", 8)):
            for i in range(count):
                key = f"{role}/{split}/{i}"
                pres.append(
                    dict(
                        key=key,
                        group_id=key,
                        split=split,
                        role=role,
                        language="en",
                        memory_ids=[],
                        input_ids=[1] + [10 + i] * 100,
                        labels=[-100] + [10 + i] * 100,
                        supervised_tokens=100,
                        parent_record_sha256=prep.ex.plan_hash(key),
                    )
                )
    return pres, raw + other


def test_same_complete_rows_targets_and_training_budget():
    pres, raw = inputs()
    routes, canary, schedule, summary = prep.assemble(pres, raw, Tokenizer(), PLAN)
    assert summary["training_updates_per_arm"] == 32
    assert summary["canary_backward_rows"] == 8
    assert all(r["split"] == "train" for r in canary)
    assert len({r["key"] for r in canary}) == len(canary)
    for route in prep.bank.ROUTES:
        lookup = {r["key"]: r for r in routes[route]}
        assert all(lookup[k]["split"] == "dev" for k in schedule["development"])
        assert (
            sum(lookup[k]["supervised_tokens"] for w in schedule["training"] for k in w)
            == summary["training_tokens_per_arm"]
        )
    assert set(summary["training_tokens_by_role"]) == set(PLAN["target_supervised_token_shares"])


def test_nontraining_or_memory_bearing_preservation_rejected():
    pres, raw = inputs()
    for field, value in (("split", "confirmation"), ("memory_ids", [10]), ("language", "ja")):
        bad = copy.deepcopy(pres)
        bad[0][field] = value
        with pytest.raises(ValueError):
            prep.assemble(bad, raw, Tokenizer(), PLAN)
