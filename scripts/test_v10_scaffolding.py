#!/usr/bin/env python3
"""Focused standard-library tests for the v10 data/config compiler."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import prepare_v10_matrix as matrix  # noqa: E402
import remap_functional_choices as remap  # noqa: E402


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


class ChoiceRemapTests(unittest.TestCase):
    def test_checked_choice_only_remap_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "data"
            output = source / "v10"
            source.mkdir(parents=True)
            for split in remap.SPLITS:
                shutil.copy2(
                    ROOT / "data" / f"functional_{split}.jsonl",
                    source / f"functional_{split}.jsonl",
                )

            first = remap.build_outputs(source, output, repo_root=repo)
            first_payloads = {
                path.name: path.read_bytes() for path in output.iterdir() if path.is_file()
            }
            with self.assertRaises(remap.ContractError):
                remap.build_outputs(source, output, repo_root=repo)
            second = remap.build_outputs(source, output, overwrite=True, repo_root=repo)
            second_payloads = {
                path.name: path.read_bytes() for path in output.iterdir() if path.is_file()
            }
            self.assertEqual(first, second)
            self.assertEqual(first_payloads, second_payloads)

            for split, expected_count in remap.SPLITS.items():
                source_bytes = (source / f"functional_{split}.jsonl").read_bytes()
                output_bytes = (output / f"functional_{split}.jsonl").read_bytes()
                restored = output_bytes.replace(remap.TARGET_FRAGMENT, remap.SOURCE_FRAGMENT)
                self.assertEqual(restored, source_bytes)
                self.assertEqual(output_bytes.count(remap.TARGET_FRAGMENT), expected_count)
                observed_count = first["files"][split]["structural_checks"][
                    "record_count"
                ]
                self.assertEqual(observed_count, expected_count)

    def test_bad_choices_fail_closed_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "data"
            output = source / "v10"
            source.mkdir(parents=True)
            for split in remap.SPLITS:
                shutil.copy2(
                    ROOT / "data" / f"functional_{split}.jsonl",
                    source / f"functional_{split}.jsonl",
                )
            train = source / "functional_train.jsonl"
            damaged = train.read_bytes().replace(remap.SOURCE_FRAGMENT, b'"choices": ["0", "1"]', 1)
            train.write_bytes(damaged)
            with self.assertRaises(remap.ContractError):
                remap.build_outputs(source, output, repo_root=repo)
            self.assertFalse(output.exists())


class MatrixPreparationTests(unittest.TestCase):
    def test_unknown_profile_fails_closed(self) -> None:
        with self.assertRaises(matrix.ContractError):
            matrix.profile_spec("n11")
        with self.assertRaises(matrix.ContractError):
            matrix.resolve_profiles(["smoke", "smoke"])

    def test_generated_artifacts_are_deterministic_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "configs" / "v10"
            artifacts = matrix.prepare_matrix(
                ROOT / "configs" / "v9_reference",
                ROOT / "data" / "v10",
                output,
                repo_root=ROOT,
            )
            for relative, expected in artifacts.items():
                self.assertEqual((output / relative).read_bytes(), expected)
                self.assertEqual((ROOT / "configs" / "v10" / relative).read_bytes(), expected)
            with self.assertRaises(matrix.ContractError):
                matrix.prepare_matrix(
                    ROOT / "configs" / "v9_reference",
                    ROOT / "data" / "v10",
                    output,
                    repo_root=ROOT,
                )

    def test_counts_boundaries_and_runtime_pins(self) -> None:
        conditions = _json(ROOT / "configs" / "v10" / "CONDITIONS.json")
        self.assertEqual(conditions["canonical_order"], matrix.CANONICAL_ORDER)
        self.assertEqual(conditions["condition_count"], 19)
        self.assertEqual(len(conditions["conditions"]), 19)

        expected_profiles = {
            "smoke": (4, [42], 8),
            "n3": (57, [42, 43, 44], 512),
            "n10": (190, list(range(42, 52)), 512),
        }
        for profile, (run_count, seeds, max_steps) in expected_profiles.items():
            document = _json(
                ROOT / "configs" / "v10" / "profiles" / profile / "MATRIX.json"
            )
            self.assertEqual(document["expected_run_count"], run_count)
            self.assertEqual(len(document["runs"]), run_count)
            self.assertEqual(document["seeds"], seeds)
            self.assertEqual(document["max_steps"], max_steps)
            self.assertEqual(len({run["run_id"] for run in document["runs"]}), run_count)
            for run in document["runs"]:
                self.assertFalse(Path(run["condition_config"]).is_absolute())
                self.assertTrue((ROOT / run["condition_config"]).is_file())
                self.assertTrue(run["output_dir"].startswith(f"runs/v10/{profile}/"))

        for condition in matrix.CANONICAL_ORDER:
            config = _json(
                ROOT / "configs" / "v10" / "conditions" / f"config_{condition}.json"
            )
            self.assertEqual(config["model"]["name_or_path"], matrix.MODEL_ID)
            self.assertEqual(config["model"]["revision"], matrix.MODEL_REVISION)
            self.assertEqual(config["model"]["dtype"], "bfloat16")
            self.assertEqual(config["model"]["attn_implementation"], "sdpa")
            self.assertEqual(config["model"]["train_mode"], "full")
            self.assertTrue(config["model"]["gradient_checkpointing"])
            self.assertEqual(config["train"]["device"], "cuda")
            self.assertEqual(config["train"]["mixed_precision"], "bf16")
            self.assertEqual(config["train"]["optimizer"], "adafactor")
            self.assertEqual(config["train"]["resume_from"], "auto")
            self.assertTrue(config["train"]["strict_resume"])
            self.assertTrue(config["train"]["save_optimizer"])

        for condition, expected_boundary in {
            "F2_raw_b3": 8,
            "F3_raw_b6": 16,
            "F4_raw_b9": 24,
        }.items():
            config = _json(
                ROOT / "configs" / "v10" / "conditions" / f"config_{condition}.json"
            )
            self.assertEqual(config["functional"]["boundary_layer"], expected_boundary)

    def test_contract_hashes_and_relative_paths(self) -> None:
        contract_path = ROOT / "configs" / "v10" / "CONTRACT.json"
        contract = _json(contract_path)
        for relative, expected in contract["source"]["v9_reference_files"].items():
            self.assertEqual(_sha(ROOT / relative), expected)
        for relative, expected in contract["source"]["preparation_scripts"].items():
            self.assertEqual(_sha(ROOT / relative), expected)
        self.assertEqual(
            _sha(ROOT / contract["data"]["manifest"]),
            contract["data"]["manifest_sha256"],
        )
        for split in ("train", "eval"):
            self.assertEqual(
                _sha(ROOT / "data" / "v10" / f"functional_{split}.jsonl"),
                contract["data"]["remapped_output_sha256"][split],
            )

        generated_json = list((ROOT / "configs" / "v10").rglob("*.json"))
        generated_json.append(ROOT / "data" / "v10" / "MANIFEST.json")
        for path in generated_json:
            for value in _strings(_json(path)):
                self.assertFalse(value.startswith(("/", "~", "file://")), (path, value))
                self.assertNotIn("/Users/", value, (path, value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
