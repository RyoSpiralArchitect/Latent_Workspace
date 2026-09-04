from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
canary = importlib.import_module("run_v14_portability_canary")


class TinyModel(torch.nn.Module):
    functional_num_layers = 2

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(model_type="tiny_custom", _attn_implementation="eager")
        self.embedding = torch.nn.Embedding(16, 4)
        self.layers = torch.nn.ModuleList([torch.nn.Linear(4, 4) for _ in range(2)])
        self.norm = torch.nn.LayerNorm(4)
        self.head = torch.nn.Linear(4, 16)

    def functional_forward_to_boundary(self, input_ids, attention_mask, boundary):
        value = self.embedding(input_ids)
        for layer in self.layers[:boundary]:
            value = torch.tanh(layer(value))
        return value

    def functional_forward_from_boundary(self, hidden, attention_mask, boundary):
        for layer in self.layers[boundary:]:
            hidden = torch.tanh(layer(hidden))
        return self.head(self.norm(hidden))

    def forward(self, input_ids, attention_mask, use_cache, return_dict):
        assert use_cache is False and return_dict is True
        hidden = self.functional_forward_to_boundary(input_ids, attention_mask, 2)
        return SimpleNamespace(
            logits=self.functional_forward_from_boundary(hidden, attention_mask, 2)
        )


class TinyTokenizer:
    pad_token_id = 0
    eos_token_id = 1
    eos_token = "<eos>"
    padding_side = "left"

    def __call__(self, texts, *, padding, truncation, add_special_tokens, return_tensors):
        assert texts == list(canary.PROMPTS)
        assert padding is True and truncation is False and add_special_tokens is True
        assert return_tensors == "pt" and self.padding_side == "right"
        return {
            "input_ids": torch.tensor([[1, 2, 3, 4], [1, 5, 0, 0], [1, 6, 7, 0]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1], [1, 1, 0, 0], [1, 1, 1, 0]]),
        }

    def decode(self, ids, *, skip_special_tokens):
        assert skip_special_tokens is False
        return " ".join(str(token) for token in ids)


@pytest.fixture(autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_in_memory_native_split_and_full_gradient_identity(dtype) -> None:
    model = TinyModel().to(dtype=dtype)
    before = {name: value.clone() for name, value in model.state_dict().items()}
    result = canary.run_canary(model, TinyTokenizer(), check_gradients=True)
    assert result["status"] == "COMPLETE"
    assert result["boundary_layers"] == [0, 1, 2]
    assert all(row["max_abs_difference"] == 0.0 for row in result["boundaries"])
    assert result["gradient_check"]["all_parameter_gradients_within_tolerance"] is True
    assert result["gradient_check"]["finite_parameter_gradient_count"] == len(
        list(model.parameters())
    )
    assert result["gradient_check"]["max_abs_gradient_difference"] == 0.0
    assert result["gradient_check"]["native_loss"] == result["gradient_check"]["split_loss"]
    assert len(result["generation"]) == 2
    assert all(
        len(row["native_token_ids"]) == 4 and row["token_ids_equal"] for row in result["generation"]
    )
    assert all(result["true_bypass"]["profiles"].values())
    assert result["parameter_identity_versions_unchanged"] is True
    assert result["gradients_cleared"] is True
    norm_trace = result["named_norm_observation"]
    assert norm_trace["selected_module_names"] == ["norm"]
    assert norm_trace["passthrough_numeric_exact"] is True
    assert norm_trace["observation_checks_passed"] is True
    assert norm_trace["counts"]["norm"] == {"invoked": 1, "recorded": 1, "dropped": 0}
    assert norm_trace["records"][0]["status"] == "COMPLETE"
    assert all(torch.equal(before[name], tensor) for name, tensor in model.state_dict().items())
    assert result["scientific_success"] is False
    json.dumps(result, allow_nan=False)


def test_gradient_check_not_implied_when_not_requested() -> None:
    result = canary.run_canary(TinyModel(), TinyTokenizer())
    assert result["gradient_check"] == {"status": "NOT_RUN"}
    assert result["padding_side"] == "right"
    assert result["attention_mask"][1] == [1, 1, 0, 0]
    assert result["tolerances"] == canary.TOLERANCES["float32"]


def test_injected_wrong_split_is_mismatch_not_capability_failure() -> None:
    class WrongBinding(canary.FunctionalBoundaryAdapter):
        def decode(self, hidden, mask, cut):
            return super().decode(hidden, mask, cut) + 1.0

    result = canary.run_canary(TinyModel(), TinyTokenizer(), binding_factory=WrongBinding)
    assert result["status"] == "MISMATCH"
    assert result["pipeline_checks_passed"] is False
    assert result["scientific_success"] is False
    assert all(not row["within_tolerance"] for row in result["boundaries"])


@pytest.mark.parametrize("fault", ["missing", "unsupported", "nonfinite", "uninvoked"])
def test_missing_or_unsupported_norm_observation_cannot_pass(monkeypatch, fault) -> None:
    class BrokenRecorder(canary.NamedNormRecorder):
        def to_dict(self):
            result = super().to_dict()
            if fault == "missing":
                result["records"] = []
            elif fault == "unsupported":
                result["records"][0]["status"] = "UNSUPPORTED"
            elif fault == "nonfinite":
                result["records"][0]["post"]["sample_finite"] = False
            else:
                result["counts"]["norm"]["invoked"] = 0
            return result

    monkeypatch.setattr(canary, "NamedNormRecorder", BrokenRecorder)
    result = canary.run_canary(TinyModel(), TinyTokenizer())
    assert result["status"] == "MISMATCH"
    assert result["pipeline_checks_passed"] is False
    assert result["named_norm_observation"]["passthrough_numeric_exact"] is True
    assert result["named_norm_observation"]["observation_checks_passed"] is False


def test_partial_in_memory_receipt_survives_split_failure() -> None:
    class BrokenBinding(canary.FunctionalBoundaryAdapter):
        def decode(self, hidden, mask, cut):
            if cut == 1:
                raise RuntimeError("injected middle failure")
            return super().decode(hidden, mask, cut)

    model, partial = TinyModel(), {}
    with pytest.raises(RuntimeError, match="injected middle"):
        canary.run_canary(model, TinyTokenizer(), binding_factory=BrokenBinding, receipt=partial)
    assert len(partial["boundaries"]) == 1
    assert partial["gradients_cleared"] is True
    assert all(parameter.grad is None for parameter in model.parameters())


def test_in_place_parameter_mutation_detected() -> None:
    class MutatingBinding(canary.FunctionalBoundaryAdapter):
        def encode(self, ids, mask, cut):
            with torch.no_grad():
                self.base_model.head.bias.add_(1.0)
            return super().encode(ids, mask, cut)

    partial = {}
    with pytest.raises(ValueError, match="parameters changed"):
        canary.run_canary(
            TinyModel(), TinyTokenizer(), binding_factory=MutatingBinding, receipt=partial
        )
    assert partial["status"] == "FAILED"
    assert partial["parameter_identity_versions_unchanged"] is False


def test_nonfinite_comparison_keeps_json_finite() -> None:
    result = canary._difference(
        torch.tensor([float("nan")]), torch.tensor([1.0]), atol=0.0, rtol=0.0
    )
    assert result["finite"] is False and result["max_abs_difference"] is None
    json.dumps(result, allow_nan=False)


def _snapshot(tmp_path: Path) -> Path:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_text('{"model_type":"tiny_custom"}')
    (snapshot / "tokenizer.json").write_text("{}")
    (snapshot / "model.safetensors").write_bytes(b"synthetic test placeholder; never deserialized")
    return snapshot


def test_snapshot_inventory_hashes_and_detects_changes(tmp_path) -> None:
    snapshot = _snapshot(tmp_path)
    inventory = canary.inventory(snapshot)
    assert {row["path"] for row in inventory} == {
        "config.json",
        "tokenizer.json",
        "model.safetensors",
    }
    assert all(len(row["sha256"]) == 64 for row in inventory)
    assert canary.check_inventory(snapshot, inventory)["manifest_stats_unchanged"] is True
    (snapshot / "model.safetensors").write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="Snapshot metadata changed"):
        canary.check_inventory(snapshot, inventory)


def test_standard_hf_snapshot_blob_links_are_supported(tmp_path) -> None:
    cache = tmp_path / "models--example"
    snapshot, blobs = cache / "snapshots" / "revision", cache / "blobs"
    snapshot.mkdir(parents=True)
    blobs.mkdir()
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        (blobs / name).write_bytes(b"synthetic test blob")
        (snapshot / name).symlink_to(Path("../../blobs") / name)
    rows = canary.inventory(snapshot)
    checked = canary.check_inventory(snapshot, rows)
    assert checked["all_payload_sha256_unchanged"] is True
    assert len(checked["payloads_rehashed"]) == 3
    assert checked["reconstructible_weight_backup"] is False


def test_non_hf_or_escaping_snapshot_symlinks_rejected(tmp_path) -> None:
    snapshot = _snapshot(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"not admitted")
    (snapshot / "extra.json").symlink_to(outside)
    with pytest.raises(ValueError, match="Only standard snapshot"):
        canary.inventory(snapshot)


def test_frozen_parameter_disallows_full_gradient_claim() -> None:
    model, partial = TinyModel(), {}
    next(model.parameters()).requires_grad_(False)
    with pytest.raises(ValueError, match="every parameter trainable"):
        canary.run_canary(model, TinyTokenizer(), check_gradients=True, receipt=partial)
    assert partial["gradient_check"]["status"] == "NOT_RUN"
    assert partial["gradients_cleared"] is True


def test_cli_no_network_loading_and_fresh_output(monkeypatch, tmp_path) -> None:
    snapshot, output = _snapshot(tmp_path), tmp_path / "output"
    called = []

    def local_load(path, *, device, dtype, attention_implementation):
        import os

        assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
        called.append((path, device, dtype))
        model = TinyModel()
        model.config._attn_implementation = attention_implementation
        return model, TinyTokenizer()

    monkeypatch.setattr(canary, "_load_local_model", local_load)
    args = [
        "--model-path",
        str(snapshot),
        "--output-dir",
        str(output),
        "--device",
        "cpu",
        "--dtype",
        "float32",
        "--check-gradients",
    ]
    assert canary.main(args) == 0
    report_path = output / "PORTABILITY_CANARY.json"
    report = json.loads(report_path.read_text())
    assert report["status"] == "COMPLETE"
    assert report["training_performed"] is False
    assert report["offline_loading"]["trust_remote_code"] is False
    assert report["model_payload_inventory"]
    assert report["source_sha256"]
    assert report["implementation_fingerprint"]["sha256"]
    assert "normalizer_inventory" in report
    assert report["snapshot_postcheck"]["manifest_stats_unchanged"] is True
    assert report["snapshot_postcheck"]["all_payload_sha256_unchanged"] is True
    assert report["actual_attention_implementation"] == "sdpa"
    assert report["runtime"]["torch_threads"] == 2
    assert report["runtime"]["transformers"]
    assert report["runtime"]["effective_sdpa_backend"] == "UNKNOWN"
    assert report["runtime"]["sdpa_policy_is_executed_backend_evidence"] is False
    assert (
        report["runtime"]["cuda_matmul_policy"]["allow_tf32"]
        == torch.backends.cuda.matmul.allow_tf32
    )
    assert report["cuda_memory"]["status"] == "NOT_MEASURED"
    assert report["elapsed_seconds"] >= 0
    assert "not a speed comparison" in report["timing_scope"]
    before = report_path.read_bytes()
    assert canary.main(args) == 1
    assert report_path.read_bytes() == before
    assert len(called) == 1


def test_failed_load_leaves_partial_receipt_and_snapshot_postcheck(monkeypatch, tmp_path) -> None:
    snapshot, output = _snapshot(tmp_path), tmp_path / "failed"

    def fail(*args, **kwargs):
        raise RuntimeError("injected offline load failure")

    monkeypatch.setattr(canary, "_load_local_model", fail)
    assert (
        canary.main(
            [
                "--model-path",
                str(snapshot),
                "--output-dir",
                str(output),
                "--device",
                "cpu",
                "--dtype",
                "float32",
            ]
        )
        == 1
    )
    report = json.loads((output / "PORTABILITY_CANARY.json").read_text())
    assert report["status"] == "FAILED"
    assert report["model_payload_inventory"]
    assert report["snapshot_postcheck"]["manifest_stats_unchanged"] is True
    assert "injected offline load failure" in report["error"]
    assert report["runtime"]["transformers"]
    assert report["elapsed_seconds"] >= 0


def test_observed_gpu_identity_and_bounded_allocator_counters(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "current_device", lambda: 0)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda index: "Mock GPU")
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda index: (8, 6))
    monkeypatch.setattr(
        torch.cuda, "get_device_properties", lambda index: SimpleNamespace(total_memory=8192)
    )
    runtime = canary._observed_runtime("cuda", "sdpa")
    assert runtime["gpu"] == {
        "device_index": 0,
        "name": "Mock GPU",
        "capability": [8, 6],
        "total_memory_bytes": 8192,
    }
    assert runtime["effective_sdpa_backend"] == "UNKNOWN"
    assert runtime["sdpa_backend_instrumented"] is False
    assert (
        runtime["cuda_matmul_policy"]["allow_bf16_reduced_precision_reduction"]
        == torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction
    )
    for name, value in (
        ("max_memory_allocated", 20),
        ("max_memory_reserved", 40),
        ("memory_allocated", 10),
        ("memory_reserved", 30),
    ):
        monkeypatch.setattr(torch.cuda, name, lambda value=value: value)
    peak = canary._cuda_peak_memory()
    assert peak["peak_allocated_bytes"] == 20
    assert peak["peak_reserved_bytes"] == 40
    assert peak["final_allocated_bytes"] == 10
    assert peak["final_reserved_bytes"] == 30
    assert "not all GPU memory" in peak["scope"]


@pytest.mark.parametrize("attention_implementation", ["sdpa", "eager"])
def test_loader_forces_local_files_and_disables_remote_code(
    monkeypatch, tmp_path, attention_implementation
) -> None:
    import transformers

    model, tokenizer = TinyModel(), TinyTokenizer()
    calls = []

    def load_tokenizer(path, **kwargs):
        calls.append(kwargs)
        return tokenizer

    def load_model(path, **kwargs):
        calls.append(kwargs)
        return model

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", load_tokenizer)
    monkeypatch.setattr(transformers.AutoModelForCausalLM, "from_pretrained", load_model)
    result = canary._load_local_model(
        tmp_path,
        device="cpu",
        dtype=torch.float32,
        attention_implementation=attention_implementation,
    )
    assert result == (model, tokenizer)
    assert all(
        kwargs["local_files_only"] is True and kwargs["trust_remote_code"] is False
        for kwargs in calls
    )
    assert calls[1]["attn_implementation"] == attention_implementation


def test_relative_paths_rejected_before_creating_output(tmp_path) -> None:
    output = tmp_path / "uncreated"
    assert (
        canary.main(
            [
                "--model-path",
                "relative",
                "--output-dir",
                str(output),
                "--device",
                "cpu",
                "--dtype",
                "float32",
            ]
        )
        == 1
    )
    assert not output.exists()
