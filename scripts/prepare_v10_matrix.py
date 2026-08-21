#!/usr/bin/env python3
"""Prepare the pinned Mistral/CUDA v10 condition and profile matrices.

This is a configuration compiler, not a launcher.  It consumes exact copied
v9 references, preserves their 19 condition deltas, resolves 12-layer
boundaries onto Mistral's 32 layers, and emits repository-relative artifacts.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

FORMAT = "latent-workspace-v10-matrix-contract-v1"
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
MODEL_REVISION = "c170c708c41dac9275d15a8fff4eca08d52bab71"
SOURCE_LAYER_COUNT = 12
TARGET_LAYER_COUNT = 32
BOUNDARY_MAP = {3: 8, 6: 16, 9: 24}
CANONICAL_ORDER = [
    "F0_query_only",
    "B_local_invariance",
    "F1_inline_upper",
    "F2_raw_b3",
    "F3_raw_b6",
    "F4_raw_b9",
    "F5_projected_b6",
    "O0_slots4_k1",
    "O1_slots4_k1_lw",
    "O2_slots4_k1_cf",
    "O3_slots4_k1_lw_cf",
    "R_slots1_k1",
    "R_slots1_k4",
    "R_slots2_k1",
    "R_slots2_k4",
    "R_slots4_k4",
    "R_slots4_k4_step1",
    "R_slots8_k1",
    "R_slots8_k4",
]
SMOKE_ORDER = [
    "F0_query_only",
    "B_local_invariance",
    "F1_inline_upper",
    "O3_slots4_k1_lw_cf",
]
PROFILE_SPECS = {
    "smoke": {"conditions": SMOKE_ORDER, "seeds": [42], "max_steps": 8},
    "n3": {
        "conditions": CANONICAL_ORDER,
        "seeds": list(range(42, 45)),
        "max_steps": 512,
    },
    "n10": {
        "conditions": CANONICAL_ORDER,
        "seeds": list(range(42, 52)),
        "max_steps": 512,
    },
}

# These are the byte hashes of the copied, completed v9 GPT-2 n=10 contract.
# A changed reference must be reviewed and deliberately re-pinned here.
EXPECTED_V9_HASHES = {
    "MATRIX.json": "02a77f5cf4c35a50610fc549899c4b44d124ee39f2bb4106f3499a72dea3f942",
    "config.json": "affe3bdb90b1238b69c58deb659f5905e9813a8a3a0c1768742f0e27e7b56b68",
    "config_B_local_invariance.json": (
        "2cc01d6261f4d89dced74a5731376ae5c340cbf2375366761f81efa8378a94ee"
    ),
    "config_F0_query_only.json": "fb8e12803fddbad701851b703ea40094ac2dccc16b9651781230b688fda2ad60",
    "config_F1_inline_upper.json": (
        "0a21b4e84bdfc56eca337f8d54f010a3f63348affa98f5f1eccb18de40f78ea7"
    ),
    "config_F2_raw_b3.json": "cd5841c5fe43319b771cbc1de90be4176fc40ca7bb1421d867d1e7f42ffd5267",
    "config_F3_raw_b6.json": "489f275d042f00aab346979730a30dfc3720c3484daa663b3d6ef034a0683607",
    "config_F4_raw_b9.json": "3b22a1e7b85b01ba4057aade0fa58c741038e5d7f3e13143892d913b17c95a2b",
    "config_F5_projected_b6.json": (
        "01e8bfcfacfadd91e4f2cf64683f7b6e9945ce0e298a84b981c068158c94e735"
    ),
    "config_O0_slots4_k1.json": "47acd90adca0c9e628cf51cb9bf4c166f32888f4589cdce03e71626ee9aaef83",
    "config_O1_slots4_k1_lw.json": (
        "f770f2d9e1a5905ca92283477d14142d74bdfd5bc847783dc143aa6eef856426"
    ),
    "config_O2_slots4_k1_cf.json": (
        "6f178e26730ad73438d02edba7d357ce431d8bcffea2b7937c4b75ecc6638726"
    ),
    "config_O3_slots4_k1_lw_cf.json": (
        "affe3bdb90b1238b69c58deb659f5905e9813a8a3a0c1768742f0e27e7b56b68"
    ),
    "config_R_slots1_k1.json": "75c7fa8d29e31a442dba758dedae3e9f5013cb9cbddbf0ceb29ffd12e83984c7",
    "config_R_slots1_k4.json": "99e2cb687ac3b9a9043be939dc9096a78ce0d8320ddb923ffa45789d531ddb3e",
    "config_R_slots2_k1.json": "5eb2093a881948f8eef6774420aa5f7ec45d765424ba0e257cad2a091f36e986",
    "config_R_slots2_k4.json": "fa1fc1bdccc32f2fc6d6257fb2e48b1d454a07ae6e525851ac0611f6d1f4b0dd",
    "config_R_slots4_k4.json": "59c7197e7a07838cf28cb7a83d693cb3cd680533ba316a59af3a411992736b2a",
    "config_R_slots4_k4_step1.json": (
        "dab37a440ae0a8c7636950c90c8a87b36ef71f9418bc08ad762135b39abc42ed"
    ),
    "config_R_slots8_k1.json": "04d09a5b7a9e37ece30777dee394dd109d3db17e2f6b954468543b96009b4913",
    "config_R_slots8_k4.json": "0d86a407f5b55d230c311559dba68e1d8e159f3c6c7bf95798a0ced8962b916c",
}
EXPECTED_DATA_INPUT_HASHES = {
    "train": "c7b012933a7a986e5cea80edf2ab87c45319a982bd500716206e71ee231ff855",
    "eval": "c50949f8e2618ef9b6159c5650a70a231008243433729d41f79b9482e977a156",
}


class ContractError(RuntimeError):
    """Raised when source pins or generated boundaries do not match."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read valid JSON from {path}: {exc}") from exc


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    flat: dict[str, Any] = {}
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else key
        flat.update(_flatten(value[key], path))
    return flat


def semantic_patch(base: Mapping[str, Any], condition: Mapping[str, Any]) -> list[dict[str, Any]]:
    left = _flatten(base)
    right = _flatten(condition)
    patch: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        if left.get(path) != right.get(path):
            patch.append({"path": path, "base": left.get(path), "condition": right.get(path)})
    return patch


def _patch_without_output(patch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in patch if entry["path"] != "train.output_dir"]


def profile_spec(name: str) -> dict[str, Any]:
    try:
        return copy.deepcopy(PROFILE_SPECS[name])
    except KeyError as exc:
        allowed = ", ".join(PROFILE_SPECS)
        raise ContractError(f"unknown profile {name!r}; expected one of: {allowed}") from exc


def resolve_profiles(names: Sequence[str] | None) -> list[str]:
    selected = list(PROFILE_SPECS) if not names else list(names)
    if not selected:
        raise ContractError("at least one profile is required")
    if len(selected) != len(set(selected)):
        raise ContractError("duplicate profile requested")
    for name in selected:
        profile_spec(name)
    return selected


def _validate_v9_sources(source_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    observed_names = {path.name for path in source_dir.glob("*.json")}
    expected_names = set(EXPECTED_V9_HASHES)
    if observed_names != expected_names:
        missing = sorted(expected_names - observed_names)
        extra = sorted(observed_names - expected_names)
        raise ContractError(f"v9 reference set mismatch; missing={missing}, extra={extra}")
    for name, expected in EXPECTED_V9_HASHES.items():
        observed = sha256_file(source_dir / name)
        if observed != expected:
            raise ContractError(
                f"v9 reference hash mismatch for {name}: {observed} != {expected}"
            )

    matrix = read_json(source_dir / "MATRIX.json")
    if matrix.get("canonical_order") != CANONICAL_ORDER:
        raise ContractError("copied v9 canonical condition order changed")
    if matrix.get("model") != "openai-community/gpt2":
        raise ContractError("copied v9 matrix model pin changed")
    base = read_json(source_dir / "config.json")
    conditions: dict[str, Any] = {}
    for condition in CANONICAL_ORDER:
        path = source_dir / f"config_{condition}.json"
        conditions[condition] = read_json(path)
    return base, conditions


def _validate_data_manifest(data_dir: Path) -> dict[str, Any]:
    manifest = read_json(data_dir / "MANIFEST.json")
    if manifest.get("format") != "latent-workspace-functional-choice-remap-v1":
        raise ContractError("unexpected data manifest format")
    transformation = manifest.get("transformation", {})
    if transformation.get("source_choices") != [" 0", " 1"]:
        raise ContractError("data source choices changed")
    if transformation.get("target_choices") != [" no", " yes"]:
        raise ContractError("data target choices changed")
    if transformation.get("all_other_json_values_unchanged") is not True:
        raise ContractError("data manifest does not prove choices-only mutation")
    for split, expected_input_hash in EXPECTED_DATA_INPUT_HASHES.items():
        entry = manifest.get("files", {}).get(split, {})
        if entry.get("input_sha256") != expected_input_hash:
            raise ContractError(f"{split} input hash is not the pinned v9 corpus")
        output_path = data_dir / f"functional_{split}.jsonl"
        if not output_path.is_file():
            raise ContractError(f"missing remapped {split} corpus")
        if sha256_file(output_path) != entry.get("output_sha256"):
            raise ContractError(f"{split} output hash does not match MANIFEST.json")
        expected_records = {"train": 256, "eval": 64}[split]
        if entry.get("structural_checks", {}).get("record_count") != expected_records:
            raise ContractError(
                f"{split} record count is not the pinned {expected_records}"
            )
    return manifest


def _configure_v10(source: Mapping[str, Any], *, condition: str) -> dict[str, Any]:
    config = copy.deepcopy(source)
    model = config["model"]
    model.update(
        {
            "name_or_path": MODEL_ID,
            "revision": MODEL_REVISION,
            "dtype": "bfloat16",
            "train_mode": "full",
            "gradient_checkpointing": True,
            "attn_implementation": "sdpa",
        }
    )
    data = config["data"]
    data["train_files"] = ["../../../data/v10/functional_train.jsonl"]
    data["eval_files"] = ["../../../data/v10/functional_eval.jsonl"]
    data["fingerprint_mode"] = "full"

    source_boundary = int(config["functional"]["boundary_layer"])
    if source_boundary not in BOUNDARY_MAP:
        raise ContractError(
            f"{condition}: source boundary {source_boundary} has no reviewed mapping"
        )
    config["functional"]["boundary_layer"] = BOUNDARY_MAP[source_boundary]

    train = config["train"]
    train.update(
        {
            "output_dir": f"../../../runs/v10/default/{condition}",
            "device": "cuda",
            "max_steps": 512,
            "batch_size": 1,
            "eval_batch_size": 1,
            "gradient_accumulation_steps": 8,
            "optimizer": "adafactor",
            "fused_adamw": "false",
            "mixed_precision": "bf16",
            "save_every": 64,
            "save_every_minutes": 20.0,
            "resume_from": "auto",
            "strict_resume": True,
            "strict_source_resume": True,
            "strict_torch_resume": True,
            "keep_last_checkpoints": 2,
            "save_optimizer": True,
            "save_frozen_base": False,
            "max_shard_size": "4GB",
            "minimum_free_disk_gb": 50.0,
        }
    )
    return config


def _expected_v10_patch(source_patch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected = copy.deepcopy(_patch_without_output(source_patch))
    for entry in expected:
        if entry["path"] == "functional.boundary_layer":
            entry["base"] = BOUNDARY_MAP[int(entry["base"])]
            entry["condition"] = BOUNDARY_MAP[int(entry["condition"])]
    return expected


def _assert_no_absolute_paths(value: Any, *, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_no_absolute_paths(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_absolute_paths(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if value.startswith(("/", "~", "file://")) or "/Users/" in value:
            raise ContractError(f"absolute path forbidden at {path}: {value}")


def _boundary_record(source_layer: int) -> dict[str, Any]:
    resolved = BOUNDARY_MAP[source_layer]
    divisor = {3: 4, 6: 2, 9: 4}[source_layer]
    numerator = 3 if source_layer == 9 else 1
    return {
        "label": f"b{source_layer}",
        "source_layer": source_layer,
        "source_layer_count": SOURCE_LAYER_COUNT,
        "fraction": f"{numerator}/{divisor}",
        "resolved_layer": resolved,
        "target_layer_count": TARGET_LAYER_COUNT,
    }


def _profile_matrix(
    name: str,
    spec: Mapping[str, Any],
    condition_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for condition in spec["conditions"]:
        boundary = condition_records[condition]["boundary"]
        for seed in spec["seeds"]:
            runs.append(
                {
                    "run_id": f"{condition}/seed_{seed}",
                    "condition": condition,
                    "condition_config": (
                        f"configs/v10/conditions/config_{condition}.json"
                    ),
                    "seed": seed,
                    "max_steps": spec["max_steps"],
                    "output_dir": f"runs/v10/{name}/{condition}/seed_{seed}",
                    "source_boundary_layer": boundary["source_layer"],
                    "resolved_boundary_layer": boundary["resolved_layer"],
                }
            )
    return {
        "format": "latent-workspace-v10-profile-matrix-v1",
        "profile": name,
        "path_base": "repository_root",
        "model": {"name_or_path": MODEL_ID, "revision": MODEL_REVISION},
        "runtime": {
            "device": "cuda",
            "dtype": "bfloat16",
            "attention": "sdpa",
            "optimizer": "adafactor",
            "trainability": "full",
            "gradient_checkpointing": True,
        },
        "condition_order": list(spec["conditions"]),
        "seeds": list(spec["seeds"]),
        "max_steps": spec["max_steps"],
        "expected_run_count": len(spec["conditions"]) * len(spec["seeds"]),
        "runs": runs,
    }


def build_artifacts(
    source_dir: Path,
    data_dir: Path,
    *,
    profile_names: Sequence[str] | None = None,
    repo_root: Path | None = None,
) -> dict[Path, bytes]:
    selected_profiles = resolve_profiles(profile_names)
    base_v9, source_conditions = _validate_v9_sources(source_dir)
    data_manifest = _validate_data_manifest(data_dir)

    base_v10 = _configure_v10(base_v9, condition="base")
    condition_configs: dict[str, dict[str, Any]] = {}
    condition_records: dict[str, dict[str, Any]] = {}
    for condition in CANONICAL_ORDER:
        source_config = source_conditions[condition]
        source_boundary = int(source_config["functional"]["boundary_layer"])
        v10_config = _configure_v10(source_config, condition=condition)
        source_delta = semantic_patch(base_v9, source_config)
        v10_delta = semantic_patch(base_v10, v10_config)
        if _patch_without_output(v10_delta) != _expected_v10_patch(source_delta):
            raise ContractError(f"{condition}: v9 condition semantics were not preserved")
        condition_configs[condition] = v10_config
        condition_records[condition] = {
            "condition": condition,
            "source_config": f"configs/v9_reference/config_{condition}.json",
            "generated_config": f"configs/v10/conditions/config_{condition}.json",
            "source_semantic_patch": source_delta,
            "boundary": _boundary_record(source_boundary),
        }

    boundaries = {
        "format": "latent-workspace-v10-boundary-map-v1",
        "policy": "preserve normalized depth from the 12-layer v9 GPT-2 matrix",
        "mappings": [_boundary_record(layer) for layer in sorted(BOUNDARY_MAP)],
    }
    conditions_document = {
        "format": "latent-workspace-v10-condition-semantics-v1",
        "canonical_order": CANONICAL_ORDER,
        "condition_count": len(condition_records),
        "conditions": [condition_records[name] for name in CANONICAL_ORDER],
    }
    profiles = {
        name: _profile_matrix(name, profile_spec(name), condition_records)
        for name in selected_profiles
    }

    root = repo_root or Path(__file__).resolve().parents[1]
    script_hashes: dict[str, str] = {}
    for relative in (
        "scripts/remap_functional_choices.py",
        "scripts/prepare_v10_matrix.py",
    ):
        candidate = root / relative
        if not candidate.is_file():
            raise ContractError(f"missing contract source script: {relative}")
        script_hashes[relative] = sha256_file(candidate)

    runtime_hashes: dict[str, str] = {}
    for relative in (
        "src/latent_workspace_ft_v10/engine.py",
        "src/latent_workspace_ft_v10/source_manifest.json",
    ):
        candidate = root / relative
        if not candidate.is_file():
            raise ContractError(f"missing runtime source: {relative}")
        runtime_hashes[relative] = sha256_file(candidate)

    model_pin_document = {
        "name_or_path": MODEL_ID,
        "revision": MODEL_REVISION,
        "layer_count": TARGET_LAYER_COUNT,
    }
    contract = {
        "format": FORMAT,
        "hash_algorithm": "sha256",
        "source": {
            "v9_reference_files": {
                f"configs/v9_reference/{name}": digest
                for name, digest in sorted(EXPECTED_V9_HASHES.items())
            },
            "preparation_scripts": script_hashes,
            "runtime_sources": runtime_hashes,
        },
        "model": {
            **model_pin_document,
            "pin_sha256": sha256_bytes(json_bytes(model_pin_document)),
            "dtype": "bfloat16",
            "attention_implementation": "sdpa",
            "train_mode": "full",
            "gradient_checkpointing": True,
        },
        "data": {
            "manifest": "data/v10/MANIFEST.json",
            "manifest_sha256": sha256_file(data_dir / "MANIFEST.json"),
            "source_input_sha256": {
                split: data_manifest["files"][split]["input_sha256"]
                for split in ("train", "eval")
            },
            "remapped_output_sha256": {
                split: data_manifest["files"][split]["output_sha256"]
                for split in ("train", "eval")
            },
            "choices": [" no", " yes"],
        },
        "matrix": {
            "condition_count": len(CANONICAL_ORDER),
            "canonical_order": CANONICAL_ORDER,
            "profiles": {
                name: {
                    "run_count": profiles[name]["expected_run_count"],
                    "seeds": profiles[name]["seeds"],
                    "max_steps": profiles[name]["max_steps"],
                }
                for name in selected_profiles
            },
            "boundary_map": {str(key): value for key, value in BOUNDARY_MAP.items()},
        },
        "runtime": {
            "backend": "cuda",
            "optimizer": "adafactor",
            "resume_from": "auto",
            "strict_resume": True,
            "checkpoint_optimizer_state": True,
        },
        "path_policy": {
            "all_persisted_paths_are_repository_relative": True,
            "absolute_paths_forbidden": True,
        },
        "execution": {"training_launched_by_this_script": False},
    }

    artifacts: dict[Path, bytes] = {
        Path("config_base.json"): json_bytes(base_v10),
        Path("BOUNDARY_MAP.json"): json_bytes(boundaries),
        Path("CONDITIONS.json"): json_bytes(conditions_document),
        Path("CONTRACT.json"): json_bytes(contract),
    }
    for condition, config in condition_configs.items():
        artifacts[Path("conditions") / f"config_{condition}.json"] = json_bytes(config)
    for profile, matrix in profiles.items():
        artifacts[Path("profiles") / profile / "MATRIX.json"] = json_bytes(matrix)

    for relative, payload in artifacts.items():
        _assert_no_absolute_paths(json.loads(payload), path=str(relative))
    return artifacts


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def prepare_matrix(
    source_dir: Path,
    data_dir: Path,
    output_dir: Path,
    *,
    profile_names: Sequence[str] | None = None,
    overwrite: bool = False,
    repo_root: Path | None = None,
) -> dict[Path, bytes]:
    artifacts = build_artifacts(
        source_dir.resolve(),
        data_dir.resolve(),
        profile_names=profile_names,
        repo_root=repo_root,
    )
    destinations = {
        output_dir.resolve() / relative: payload
        for relative, payload in artifacts.items()
    }
    existing = sorted(str(path) for path in destinations if path.exists())
    if existing and not overwrite:
        raise ContractError(
            "refusing to overwrite existing generated config(s): " + ", ".join(existing)
        )
    # Validation and serialization finish before the first destination mutation.
    for path, payload in destinations.items():
        _atomic_write(path, payload)
    return artifacts


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = _default_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=root / "configs" / "v9_reference",
    )
    parser.add_argument("--data-dir", type=Path, default=root / "data" / "v10")
    parser.add_argument("--output-dir", type=Path, default=root / "configs" / "v10")
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="profile to emit (repeatable); default: smoke, n3, n10",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing generated files after full validation",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifacts = prepare_matrix(
            args.source_dir,
            args.data_dir,
            args.output_dir,
            profile_names=args.profiles,
            overwrite=args.overwrite,
        )
    except ContractError as exc:
        raise SystemExit(f"matrix preparation blocked: {exc}") from exc
    summary = {
        "format": FORMAT,
        "artifact_count": len(artifacts),
        "profiles": resolve_profiles(args.profiles),
        "training_launched": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
