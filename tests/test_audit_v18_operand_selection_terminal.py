"""Offline-only supplemental receipt checks: no reader construction or fits."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assay_v18_operand_selection as assay  # noqa: E402
import audit_v18_operand_selection_terminal as audit  # noqa: E402


@pytest.fixture(autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize("value", [
    '{"x": 1, "x": 2}', '{"x": {"y": 0, "y": 1}}', '{"x": NaN}',
    '{"x": Infinity}', '{"x": -Infinity}', '{"x": 1e309}', '{"x": [-1e309]}',
])
def test_strict_parser_rejects_ambiguous_and_nonfinite_values(value):
    with pytest.raises(ValueError):
        audit.strict_json(value)


def test_strict_parser_preserves_types():
    value = audit.strict_json('{"a": 1, "b": 1.0, "c": true, "d": null}')
    assert [type(value[key]) for key in ("a", "b", "c", "d")] == [int, float, bool, type(None)]


@pytest.fixture
def controls():
    return {
        "same_memory_exact": True, "zero_memory_exact_zero_delta": True,
        "equal_slot_exact_zero_delta": True, "equal_slot_gate_applicable": True,
        "permutation_max_logit_error": 0.0, "permutation_atol": 1e-6,
        "unrelated_delta_norm_mean": 0.1, "unrelated_absolute_logit_change_mean": 0.01,
        "max_delta_norm": 0.2, "unrelated_accuracy": "UNDEFINED_QUERY_ENTITIES_ABSENT",
        "renaming_scope": (
            "Synthetic alias codebook preserves identical features by construction; "
            "tokenizer binding is not tested here."
        ), "pass": True,
    }


def test_control_replay_recomputes_saved_observations_only(controls, monkeypatch):
    monkeypatch.setattr(assay, "forward", lambda *a, **k: pytest.fail("No model forward"))
    assert audit.verify_controls(controls, "centered_ordered", assay.load_plan())
    controls["equal_slot_exact_zero_delta"] = False
    controls["pass"] = False
    assert not audit.verify_controls(controls, "centered_ordered", assay.load_plan())
    controls["equal_slot_gate_applicable"] = False
    controls["pass"] = True
    assert audit.verify_controls(controls, "raw_ordered", assay.load_plan())


@pytest.mark.parametrize(("field", "value"), [
    ("same_memory_exact", 1), ("same_memory_exact", False),
    ("zero_memory_exact_zero_delta", False), ("equal_slot_exact_zero_delta", False),
    ("equal_slot_gate_applicable", False), ("pass", 1), ("pass", False),
    ("permutation_max_logit_error", 1e-4), ("permutation_max_logit_error", -0.1),
    ("permutation_max_logit_error", 0), ("permutation_max_logit_error", True),
    ("permutation_atol", 1e-3), ("max_delta_norm", 0.251),
    ("unrelated_delta_norm_mean", float("nan")),
    ("unrelated_absolute_logit_change_mean", float("inf")),
    ("renaming_scope", "real tokenizer accuracy"), ("unrelated_accuracy", 1.0),
])
def test_control_tampering_rejected(controls, field, value):
    controls[field] = value
    with pytest.raises(ValueError):
        audit.verify_controls(controls, "centered_ordered", assay.load_plan())


def test_control_unknown_fields_rejected(controls):
    controls["relaxed"] = True
    with pytest.raises(ValueError, match="schema"):
        audit.verify_controls(controls, "centered_ordered", assay.load_plan())


@pytest.fixture
def population_case():
    # Only data construction: three 36-row fixtures, no full study or forward.
    plan = assay.load_plan()
    payload, manifest = {}, {"file": "POPULATIONS.pt", "file_sha256": "0" * 64}
    for split, cfg in plan["splits"].items():
        cfg["frames"] = 1
        population = assay.population(**cfg)
        payload[split] = {
            "states": population.inputs.states, "memory": population.inputs.memory,
            "mask": population.inputs.mask, "twin_memory": population.twin.memory,
            "labels": population.labels, "twin_labels": population.twin_labels,
            "rows": list(population.rows), "frames": population.frames,
        }
        manifest[split] = {"frames": 1, "unique_queries": 36}
    refresh(payload, manifest)
    return payload, manifest, plan


def refresh(payload, manifest):
    for split, value in payload.items():
        manifest[split]["rows_sha256"] = audit.digest(value["rows"])
        manifest[split]["tensors"] = {
            field: assay.tensor_fingerprint(value[field])
            for field in audit.TENSOR_FIELDS if field in value
        }


def test_population_valid_recipe_and_no_model_calls(population_case, monkeypatch):
    monkeypatch.setattr(assay, "make_reader", lambda *a, **k: pytest.fail("No model creation"))
    monkeypatch.setattr(assay, "forward", lambda *a, **k: pytest.fail("No model forward"))
    payload, manifest, plan = population_case
    report = audit.verify_populations(payload, manifest, plan, assay)
    assert set(report) == {"train", "dev", "held_out"}
    assert all(row["rows"] == 36 and row["affected_rows"] == 12 for row in report.values())
    assert all(row["recipe_identity_max_abs_error"] == 0 for row in report.values())


@pytest.mark.parametrize("field", sorted(audit.TENSOR_FIELDS))
def test_population_missing_fields_rejected(population_case, field):
    payload, manifest, plan = population_case
    del payload["train"][field]
    with pytest.raises(ValueError, match="schema"):
        audit.verify_populations(payload, manifest, plan, assay)


@pytest.mark.parametrize("field", sorted(audit.TENSOR_FIELDS))
def test_population_wrong_dtype_rejected(population_case, field):
    payload, manifest, plan = population_case
    payload["train"][field] = payload["train"][field].double()
    refresh(payload, manifest)
    with pytest.raises(ValueError, match="tensor schema"):
        audit.verify_populations(payload, manifest, plan, assay)


@pytest.mark.parametrize("field", sorted(audit.TENSOR_FIELDS))
def test_population_wrong_shape_rejected(population_case, field):
    payload, manifest, plan = population_case
    payload["train"][field] = payload["train"][field][:35]
    refresh(payload, manifest)
    with pytest.raises(ValueError, match="tensor schema"):
        audit.verify_populations(payload, manifest, plan, assay)


@pytest.mark.parametrize("field", ["states", "memory", "twin_memory"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_population_nonfinite_rejected(population_case, field, value):
    payload, manifest, plan = population_case
    payload["train"][field][0, 0, 0] = value
    refresh(payload, manifest)
    with pytest.raises(ValueError, match="Nonfinite population"):
        audit.verify_populations(payload, manifest, plan, assay)


@pytest.mark.parametrize("mutation", [
    "extra_tensor", "extra_fingerprint", "extra_split", "bool_frames", "bool_queries",
    "bool_row", "row_question", "row_rank", "label", "twin_label", "mask", "identity",
    "identity_reuse", "rank_leak", "rank_wrong", "missing_fingerprint", "row_order",
])
def test_population_adversarial_mutations_rejected_even_when_rehashed(population_case, mutation):
    payload, manifest, plan = population_case
    item = payload["train"]
    if mutation == "extra_tensor":
        item["unsealed"] = torch.zeros(1)
    elif mutation == "extra_split":
        payload["extra"] = copy.deepcopy(item)
        manifest["extra"] = copy.deepcopy(manifest["train"])
    elif mutation == "bool_frames":
        item["frames"] = True
    elif mutation == "bool_queries":
        manifest["train"]["unique_queries"] = True
    elif mutation == "bool_row":
        item["rows"][0]["frame"] = False
    elif mutation == "row_question":
        item["rows"][0]["question"] = "Is E1 ranked above E0? Answer:"
    elif mutation == "row_rank":
        item["rows"][0]["ranks"] = [2, 1, 0]
    elif mutation in ("label", "twin_label"):
        field = "labels" if mutation == "label" else "twin_labels"
        item[field][0] = 1 - item[field][0]
    elif mutation == "mask":
        item["mask"][0, 0] = 0
    elif mutation == "identity":
        item["memory"][0, 0, 0] += 0.1
    elif mutation == "identity_reuse":
        item["states"][1, 0, 0] += 1e-8
    elif mutation == "rank_leak":
        item["states"][0, 0, 16] = 1e-8
    elif mutation == "rank_wrong":
        item["memory"][0, 0, 16] = 0.5
    elif mutation == "row_order":
        item["rows"][0], item["rows"][1] = item["rows"][1], item["rows"][0]
    refresh(payload, manifest)
    if mutation == "extra_fingerprint":
        manifest["train"]["tensors"]["mystery"] = "0" * 64
    elif mutation == "missing_fingerprint":
        del manifest["train"]["tensors"]["states"]
    with pytest.raises(ValueError):
        audit.verify_populations(payload, manifest, plan, assay)


def test_population_identity_bound_only_applies_to_consistent_identity_features(population_case):
    payload, manifest, plan = population_case
    data = payload["train"]
    identity = data["memory"][0, :, :8].clone()
    identity[0, 0] += 2e-7
    for index, row in enumerate(data["rows"]):
        data["memory"][index, :, :8] = identity
        data["twin_memory"][index, :, :8] = identity
        data["states"][index, 0, :8] = identity[row["subject"]]
        data["states"][index, 1, :8] = identity[row["object"]]
        data["states"][index, 2, :8] = identity[row["subject"]]
        data["states"][index, 2, 8:16] = identity[row["object"]]
    refresh(payload, manifest)
    report = audit.verify_populations(payload, manifest, plan, assay)
    assert 0 < report["train"]["recipe_identity_max_abs_error"] <= audit.IDENTITY_ATOL


def test_cross_split_identity_reuse_rejected_independently_of_recipe(population_case, monkeypatch):
    payload, manifest, plan = population_case
    original = assay.population
    shared = original(**plan["splits"]["train"])
    for split in ("dev", "held_out"):
        payload[split] = copy.deepcopy(payload["train"])
    refresh(payload, manifest)
    monkeypatch.setattr(assay, "population", lambda **kwargs: shared)
    with pytest.raises(ValueError, match="overlaps across frames/splits"):
        audit.verify_populations(payload, manifest, plan, assay)


@pytest.fixture
def identity_case(tmp_path):
    hashes = {
        audit.ENTRY: "1" * 64,
        "src/latent_workspace_ft_v10/__init__.py": "2" * 64,
        "src/latent_workspace_ft_v10/v18_selection_reader.py": "3" * 64,
        "src/latent_workspace_ft_v10/precision_bridge.py": "4" * 64,
    }
    seal = {"source_commit": audit.SOURCE_COMMIT, "source_hashes": hashes}
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal))
    imports = {
        "__main__": audit.ENTRY, "__mp_main__": audit.ENTRY,
        "latent_workspace_ft_v10": "src/latent_workspace_ft_v10/__init__.py",
        "latent_workspace_ft_v10.v18_selection_reader":
            "src/latent_workspace_ft_v10/v18_selection_reader.py",
        "latent_workspace_ft_v10.precision_bridge":
            "src/latent_workspace_ft_v10/precision_bridge.py",
    }
    docs = {
        "PLAN.json": {"fixture": True},
        "SOURCE.json": {"commit": audit.SOURCE_COMMIT, "files": hashes,
                        "aggregate_sha256": audit.digest(hashes)},
        "PREIMPORT.json": {
            "schema": "pre-import-source-check-v1", "source_commit": audit.SOURCE_COMMIT,
            "entry": audit.ENTRY, "source_files": len(hashes), "untracked_check": "all",
            "isolated_python": True, "fresh_bytecode_cache": True,
        },
        "STARTED.json": {
            "pid": 1, "device": "cpu", "plan_sha256": audit.digest({"fixture": True}),
            "source_sha256": audit.digest(hashes), "hostname": "fixture", "python": "3.12",
            "torch": "2.13.0", "offline_environment": audit.OFFLINE_ENV.copy(),
            "external_seal_sha256": audit.sha(seal_path),
        },
        "IMPORTS_BEFORE.json": imports.copy(), "IMPORTS_AFTER.json": imports.copy(),
        "RESULTS.json": {"plan_sha256": audit.digest({"fixture": True}),
                         "source_sha256": audit.digest(hashes), "device": "cpu"},
    }
    return docs, seal, seal_path, hashes


def test_identity_receipts_pass(identity_case):
    audit.verify_identity(*identity_case)


@pytest.mark.parametrize("mutation", [
    "source_commit", "source_map", "source_digest", "preimport_count", "preimport_bool",
    "preimport_entry", "pid_bool", "offline", "seal", "hostname", "device",
    "result_plan", "import_name", "import_critical", "import_path", "import_alias",
])
def test_identity_mutations_rejected(identity_case, mutation):
    docs, seal, seal_path, hashes = identity_case
    source, started = docs["SOURCE.json"], docs["STARTED.json"]
    if mutation == "source_commit":
        source["commit"] = "0" * 40
    elif mutation == "source_map":
        source["files"] = {}
    elif mutation == "source_digest":
        source["aggregate_sha256"] = "0" * 64
    elif mutation == "preimport_count":
        docs["PREIMPORT.json"]["source_files"] = 99
    elif mutation == "preimport_bool":
        docs["PREIMPORT.json"]["isolated_python"] = 1
    elif mutation == "preimport_entry":
        docs["PREIMPORT.json"]["entry"] = "other.py"
    elif mutation == "pid_bool":
        started["pid"] = True
    elif mutation == "offline":
        started["offline_environment"]["HF_HUB_OFFLINE"] = "0"
    elif mutation == "seal":
        started["external_seal_sha256"] = "0" * 64
    elif mutation == "hostname":
        started["hostname"] = ""
    elif mutation == "device":
        started["device"] = "cuda"
    elif mutation == "result_plan":
        docs["RESULTS.json"]["plan_sha256"] = "0" * 64
    elif mutation == "import_name":
        docs["IMPORTS_AFTER.json"]["other"] = audit.ENTRY
    elif mutation == "import_critical":
        del docs["IMPORTS_AFTER.json"]["__main__"]
    elif mutation == "import_path":
        docs["IMPORTS_AFTER.json"]["__main__"] = "/tmp/assay_v18_operand_selection.py"
    elif mutation == "import_alias":
        key = "latent_workspace_ft_v10.v18_selection_reader"
        docs["IMPORTS_AFTER.json"][key] = "src/latent_workspace_ft_v10/precision_bridge.py"
    with pytest.raises(ValueError):
        audit.verify_identity(docs, seal, seal_path, hashes)


def test_source_verification_pins_original_seal_and_current_files():
    path = audit.ROOT / "provenance/pilots/v18_operand_selection_20261015/SOURCE_SEAL.json"
    seal = audit.strict_json(path.read_text())
    result = audit.verify_source(seal)
    assert len(seal["source_hashes"]) == 572
    assert len(result) == 569
    seal["source_commit"] = "0" * 40
    with pytest.raises(ValueError, match="execution source"):
        audit.verify_source(seal)


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_artifact_scan_rejects_nonfinite_in_any_file(tmp_path, suffix):
    (tmp_path / ("untrusted" + suffix)).write_text('{"a":1e309}\n')
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.read_artifacts(tmp_path)


def test_artifact_scan_rejects_symlink(tmp_path):
    (tmp_path / "link.json").symlink_to("missing.json")
    with pytest.raises(ValueError, match="Symlink"):
        audit.read_artifacts(tmp_path)


def test_cli_refuses_overwriting_before_audit(tmp_path, monkeypatch):
    output = tmp_path / "receipt.json"
    output.write_text("retained")
    monkeypatch.setattr(sys, "argv", ["audit", "--bundle", str(tmp_path), "--source-seal",
                                    str(tmp_path / "seal"), "--output", str(output)])
    monkeypatch.setattr(audit, "audit", lambda *args: pytest.fail("Must fail before audit"))
    with pytest.raises(SystemExit):
        audit.main()
    assert output.read_text() == "retained"


def test_audit_bundle_symlink_rejected_before_source_read(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        audit.audit(link, tmp_path / "missing_seal")
