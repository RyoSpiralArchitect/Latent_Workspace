from __future__ import annotations

import json
from pathlib import Path

import prune_transport_v2_weights as pruning
import pytest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _build_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    implementation = root / "scripts" / "prune_transport_v2_weights.py"
    implementation.parent.mkdir()
    implementation.write_text("test implementation\n", encoding="utf-8")
    engine = root / "src" / "latent_workspace_ft_v10" / "engine.py"
    engine.parent.mkdir(parents=True)
    engine.write_text("test engine\n", encoding="utf-8")

    for run_index, run in enumerate(pruning.EXPECTED_RUN_NAMES):
        for role_index, role in enumerate(pruning.EXPECTED_ROLES):
            base = root / pruning.TRANSPORT_ROOT / run / role / "base_model"
            base.mkdir(parents=True)
            for shard_index, shard in enumerate(pruning.SHARD_NAMES):
                payload = f"{run_index}:{role_index}:{shard_index}\n".encode()
                (base / shard).write_bytes(payload)

    cache_file = root / pruning.MODEL_CACHE_ROOT / "pinned" / "model.safetensors"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"protected upstream model\n")

    generation = {
        "status": "PASS",
        "prompt_suite": {
            "task_case_profile": {
                "case_count": 32,
                "expected_choice_counts": {"0": 16, "1": 16},
            }
        },
        "transport_behavior_parity": [{"left": "B", "right": "B_reference", "passed": True}],
    }
    for relative in pruning.EVIDENCE_PATHS:
        path = root / relative
        if relative.endswith("BEHAVIOR_OBSERVATIONS.md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("negative behavior preserved\n", encoding="utf-8")
        elif (
            relative.endswith("GENERATION_BEHAVIOR_V1.json") and "negative_evidence" not in relative
        ):
            _write_json(path, generation)
        elif relative.endswith("ORACLE.json"):
            _write_json(path, {"status": "PASS", "result": {"passed": True}})
        else:
            _write_json(path, {"status": "PASS"})
    return root, implementation


def test_prepare_execute_and_verify_exact_tiny_transaction(tmp_path: Path) -> None:
    root, implementation = _build_root(tmp_path)
    intent = pruning.prepare_intent(
        root,
        github_evidence_commit="a" * 40,
        implementation=implementation,
    )
    assert intent["scope"]["target_file_count"] == 80
    assert len(intent["targets"]) == 80

    intent_path = root / "provenance" / "pruning" / "PRUNE_INTENT.json"
    pruning.atomic_create_json(intent_path, intent)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    receipt = pruning.execute_transaction(
        root,
        intent_path=intent_path,
        expected_intent_sha256=pruning.sha256_file(intent_path),
        published_intent_commit="b" * 40,
        quarantine_root=quarantine,
        implementation=implementation,
    )
    assert receipt["status"] == "transport_pilot_weights_pruned"
    assert receipt["transaction"]["deleted_file_count"] == 80
    assert receipt["transaction"]["quarantine"] == {
        "location_scope": "same_filesystem_outside_repository",
        "basename": "quarantine",
    }
    assert str(tmp_path) not in json.dumps(receipt)
    assert not any((root / pruning.TRANSPORT_ROOT).rglob("*.safetensors"))
    assert (root / pruning.MODEL_CACHE_ROOT / "pinned" / "model.safetensors").read_bytes() == (
        b"protected upstream model\n"
    )

    receipt_path = root / "provenance" / "pruning" / "PRUNE_RECEIPT.json"
    pruning.atomic_create_json(receipt_path, receipt)
    result = pruning.verify_receipt(root, receipt_path)
    assert result["status"] == "PASS"
    assert result["deleted_file_count"] == 80


def test_prepare_rejects_unexpected_transport_weight(tmp_path: Path) -> None:
    root, implementation = _build_root(tmp_path)
    unexpected = (
        root
        / pruning.TRANSPORT_ROOT
        / "unexpected_run"
        / "final"
        / "base_model"
        / pruning.SHARD_NAMES[0]
    )
    unexpected.parent.mkdir(parents=True)
    unexpected.write_bytes(b"unexpected\n")

    with pytest.raises(pruning.TransportPruneError, match="outside the frozen"):
        pruning.prepare_intent(
            root,
            github_evidence_commit="a" * 40,
            implementation=implementation,
        )


def test_execute_rejects_engine_change_after_intent(tmp_path: Path) -> None:
    root, implementation = _build_root(tmp_path)
    intent = pruning.prepare_intent(
        root,
        github_evidence_commit="a" * 40,
        implementation=implementation,
    )
    intent_path = root / "provenance" / "pruning" / "PRUNE_INTENT.json"
    pruning.atomic_create_json(intent_path, intent)
    (root / "src" / "latent_workspace_ft_v10" / "engine.py").write_text(
        "changed engine\n", encoding="utf-8"
    )
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    with pytest.raises(pruning.TransportPruneError, match="Engine source changed"):
        pruning.execute_transaction(
            root,
            intent_path=intent_path,
            expected_intent_sha256=pruning.sha256_file(intent_path),
            published_intent_commit="b" * 40,
            quarantine_root=quarantine,
            implementation=implementation,
        )
    assert len(list((root / pruning.TRANSPORT_ROOT).rglob("*.safetensors"))) == 80


def test_execute_rejects_symlink_quarantine(tmp_path: Path) -> None:
    root, implementation = _build_root(tmp_path)
    intent = pruning.prepare_intent(
        root,
        github_evidence_commit="a" * 40,
        implementation=implementation,
    )
    intent_path = root / "provenance" / "pruning" / "PRUNE_INTENT.json"
    pruning.atomic_create_json(intent_path, intent)
    quarantine_target = tmp_path / "quarantine-target"
    quarantine_target.mkdir()
    quarantine_link = tmp_path / "quarantine-link"
    quarantine_link.symlink_to(quarantine_target, target_is_directory=True)

    with pytest.raises(pruning.TransportPruneError, match="must not be a symlink"):
        pruning.execute_transaction(
            root,
            intent_path=intent_path,
            expected_intent_sha256=pruning.sha256_file(intent_path),
            published_intent_commit="b" * 40,
            quarantine_root=quarantine_link,
            implementation=implementation,
        )
    assert len(list((root / pruning.TRANSPORT_ROOT).rglob("*.safetensors"))) == 80
