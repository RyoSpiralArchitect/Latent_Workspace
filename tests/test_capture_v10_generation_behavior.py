from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

behavior = importlib.import_module("capture_v10_generation_behavior")


def test_labeled_paths_and_pairs_fail_closed() -> None:
    assert behavior.parse_labeled_path("F0=runs/final") == (
        "F0",
        Path("runs/final"),
    )
    assert behavior.parse_label_pair("B=B_reference") == ("B", "B_reference")
    with pytest.raises(behavior.BehaviorCaptureError, match="LABEL=PATH"):
        behavior.parse_labeled_path("missing")
    with pytest.raises(behavior.BehaviorCaptureError, match="Invalid model label"):
        behavior.parse_labeled_path("bad label=path")
    with pytest.raises(behavior.BehaviorCaptureError, match="distinct labels"):
        behavior.parse_label_pair("B=B")


def test_repo_input_resolves_relative_to_declared_root(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    assert behavior._repo_input(tmp_path, Path("nested"), label="nested") == nested
    with pytest.raises(behavior.BehaviorCaptureError, match="inside --repo-root"):
        behavior._repo_input(tmp_path, Path("../outside"), label="outside")


def test_prompt_suite_validation_and_selected_cases(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    suite = {
        "format": behavior.PROMPT_FORMAT,
        "prompts": [
            {"id": "one", "category": "test", "prompt": "Hello"},
            {"id": "two", "category": "test", "prompt": "World"},
        ],
        "task_native": {
            "dataset": "data/eval.jsonl",
            "world_indices": [0],
            "query_indices": [0, 1],
            "selection_contract": {
                "require_balanced_expected_choices": True,
                "require_affected_and_unaffected": True,
                "require_heldout_and_non_heldout": True,
            },
        },
    }
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    assert behavior.load_prompt_suite(suite_path) == suite

    records = [
        {
            "contexts": ["left", "right"],
            "queries": ["q0", "q1"],
            "answers": [[0, 1], [1, 0]],
            "choices": [" no", " yes"],
            "affected": [True, False],
            "heldout_queries": [False, True],
        }
    ]
    cases = behavior._selected_task_cases(
        records,
        world_indices=[0],
        query_indices=[0, 1],
    )
    assert len(cases) == 4
    assert cases[0]["expected_index"] == 0
    assert cases[-1]["expected_index"] == 0
    assert cases[-1]["heldout"] is True
    assert behavior._task_case_profile(cases) == {
        "case_count": 4,
        "expected_choice_counts": {"0": 2, "1": 2},
        "affected_cases": 2,
        "unaffected_cases": 2,
        "heldout_cases": 2,
        "non_heldout_cases": 2,
    }

    with pytest.raises(behavior.BehaviorCaptureError, match="balanced"):
        behavior._task_case_profile([cases[0], cases[3]])


def test_completion_groups_preserve_exact_token_equivalence() -> None:
    def rows(first: str, second: str) -> list[dict[str, str]]:
        return [
            {"id": "p0", "completion_token_ids_sha256": first},
            {"id": "p1", "completion_token_ids_sha256": second},
        ]

    grouped = behavior._completion_groups(
        {
            "original": {"freeform": rows("a", "b")},
            "candidate": {"freeform": rows("a", "c")},
            "reference": {"freeform": rows("a", "c")},
        }
    )
    assert grouped[0]["unique_completion_count"] == 1
    assert grouped[1]["unique_completion_count"] == 2
    assert grouped[1]["exact_completion_groups"] == [
        {"completion_token_ids_sha256": "b", "labels": ["original"]},
        {
            "completion_token_ids_sha256": "c",
            "labels": ["candidate", "reference"],
        },
    ]


def test_transformers_snapshot_validation_follows_weight_index(tmp_path: Path) -> None:
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "model-00001-of-00002.safetensors").write_bytes(b"one")
    (tmp_path / "model-00002-of-00002.safetensors").write_bytes(b"two")
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    "layer.0": "model-00001-of-00002.safetensors",
                    "layer.1": "model-00002-of-00002.safetensors",
                }
            }
        ),
        encoding="utf-8",
    )

    result = behavior._validate_transformers_snapshot(tmp_path)
    assert result["model_layout"] == "sharded_safetensors"
    assert result["weight_files"] == [
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    ]

    (tmp_path / "model-00002-of-00002.safetensors").unlink()
    with pytest.raises(behavior.BehaviorCaptureError, match="runtime files"):
        behavior._validate_transformers_snapshot(tmp_path)
