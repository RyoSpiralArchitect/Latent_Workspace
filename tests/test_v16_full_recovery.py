"""Repair selection/provenance tests; synthetic terminal is NOT 7B evidence."""

import ast
import copy
import json
import shutil
import sys
from types import SimpleNamespace

import pytest

from scripts import run_v16_adapter_full_recovery_02 as run

sys.path.insert(0, str(run.ROOT / "scripts"))
from scripts import verify_v16_adapter_full_recovery_02 as verifier  # noqa: E402


def preparation():
    from latent_workspace_ft_v10.native_training_preparation import METHOD_HASHES

    return {
        "schema": "native-hf-owned-checkpoint-preparation-v1",
        "transformers": "5.15.0",
        "native_method_source_sha256": METHOD_HASHES,
        "checkpoint_policy": [
            {
                "module": name,
                "enabled": True,
                "function": "torch.utils.checkpoint.checkpoint",
                "keywords": {"use_reentrant": False},
            }
            for name in ["model", *(f"model.layers.{i}" for i in range(32))]
        ],
        "input_gradient_hook": {
            "module": "model.embed_tokens",
            "registered": 1,
            "tracked": 1,
            "owner": "installed_PreTrainedModel.enable_input_require_grads",
        },
        "legacy_difference": "one_tracked_input_grad_hook_instead_of_duplicate_with_stale_handle",
        "weights_losses_optimizers": "unchanged",
    }


def test_history_verifies_both_incomplete_bundles_without_relabeling():
    result = run.verify_history()
    assert result["original_status"] == result["run_status"] == "INCOMPLETE_NO_RETRY"
    assert result["combined_backward_pairs"] == 112
    assert result["file_count"] == 20


def test_preparation_schema_includes_actual_native_container_and_32_layers():
    from test_readout_adapters import model

    from latent_workspace_ft_v10.native_training_preparation import (
        prepare_native_gradient_checkpointing,
    )

    tiny = model("mistral")
    config = copy.deepcopy(tiny.config)
    config.num_hidden_layers = 32
    actual = prepare_native_gradient_checkpointing(type(tiny)(config))
    run.exact(actual, preparation(), "actual HF root-container and decoder-layer policy")


@pytest.mark.parametrize("mutation", ["edit", "add", "remove", "symlink"])
def test_complete_previous_bundle_is_immutable(tmp_path, mutation):
    bundle = tmp_path / "previous"
    shutil.copytree(run.ROOT / run.PREVIOUS, bundle)
    if mutation == "edit":
        (bundle / "README.md").write_text("changed")
    elif mutation == "add":
        (bundle / "raw/full_adapter_v2_INITIAL.json").write_text("{}")
    elif mutation == "remove":
        (bundle / "EXECUTION_HANDOFF.md").unlink()
    else:
        (bundle / "extra").symlink_to(bundle / "README.md")
    with pytest.raises(ValueError):
        run.verify_history(bundle)


@pytest.mark.parametrize(
    "key,value",
    [
        ("selected_mode", "frozen"),
        ("selected_implementation", "legacy"),
        ("planned_backward_pairs", 80),
        ("planned_unique_windows", 4),
        ("planned_replay_windows", 0),
        ("retained_reference_pairs", 0),
        ("no_retry", False),
        ("judge_calls", 1),
        ("new_sequences", 1),
        ("weight_deletions", 1),
        ("old_expression_gate", "PASS"),
        ("tiny_cases", 21),
    ],
)
def test_scope_cannot_widen_or_drop_gate(key, value):
    plan = run.read(run.ROOT / run.PLAN)
    run.validate_selection(plan)
    plan[key] = value
    with pytest.raises(ValueError, match="selection"):
        run.validate_selection(plan)


@pytest.mark.parametrize("failure", [None, "adapter", "replay"])
def test_only_adapter_and_replay_dispatch_once(monkeypatch, tmp_path, failure):
    calls = []

    def action(name):
        def invoke(*args):
            calls.append(name)
            if failure == name:
                raise RuntimeError("terminal, no retry")
            return {}

        return invoke

    monkeypatch.setattr(run, "adapter_arm", action("adapter"))
    monkeypatch.setattr(run, "replay", action("replay"))
    core = SimpleNamespace(clean_between_arms=lambda: None, write_new=lambda *a: None)
    invoke = lambda: run.work(  # noqa: E731
        core,
        SimpleNamespace(output=tmp_path),
        {"storage_forecast_bytes": 64 * 2**30},
        {},
        {},
        {},
        [],
        lambda *a, **kw: None,
        {},
    )
    if failure:
        with pytest.raises(RuntimeError, match="no retry"):
            invoke()
    else:
        invoke()
    assert calls == (["adapter"] if failure == "adapter" else ["adapter", "replay"])


@pytest.mark.parametrize("mutation", [None, "seed", "source", "extra", "hook", "policy", "binding"])
def test_only_declared_provenance_changes_are_allowed(mutation):
    left = run.reference()["context"]
    right = copy.deepcopy(left)
    right["contract"].update(source_commit="a" * 40, preparation=preparation())
    right["binding"] = {"checkpointing": copy.deepcopy(preparation()["checkpoint_policy"])}
    if mutation == "seed":
        right["contract"]["objective"]["terms"]["seed"] += 1
    elif mutation == "source":
        right["contract"]["source_commit"] = "b" * 40
    elif mutation == "extra":
        right["contract"]["ignored"] = "not allowed"
    elif mutation == "hook":
        right["contract"]["preparation"]["input_gradient_hook"]["registered"] = 2
    elif mutation == "policy":
        right["contract"]["preparation"]["checkpoint_policy"][0]["enabled"] = False
    elif mutation == "binding":
        right["binding"]["checkpointing"] = []
    if mutation:
        with pytest.raises(ValueError):
            run.compare_context(left, right, "a" * 40)
    else:
        run.compare_context(left, right, "a" * 40)


def test_live_entry_top_level_is_stdlib_only():
    tree = ast.parse((run.ROOT / run.ENTRY).read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "torch" not in ast.unparse(node) and "scripts" not in ast.unparse(node)


@pytest.fixture
def terminal(tmp_path):
    old = run.load("continue_v16_adapter_full")
    core = run.load("run_v16_adapter_migration")
    raw, tiny = tmp_path / "raw", tmp_path / "tiny_cuda"
    raw.mkdir()
    tiny.mkdir()
    seal = core.identity()
    for name in (
        run.ENTRY,
        run.PLAN,
        "scripts/verify_v16_adapter_full_recovery_02.py",
        "src/latent_workspace_ft_v10/native_training_preparation.py",
        *run.TESTS,
    ):
        seal["source_hashes"][name] = run.digest(run.ROOT / name)
    core.write_new(tmp_path / "SOURCE_SEAL.json", seal)
    selection = run.read(run.ROOT / run.PLAN)
    check = {
        "schema": "pre-import-source-check-v1",
        "source_commit": seal["source_commit"],
        "entry": run.ENTRY,
        "source_files": len(seal["source_hashes"]),
        "untracked_check": "all",
        "isolated_python": True,
        "fresh_bytecode_cache": True,
    }
    core.write_new(
        tiny / "STARTED.json",
        {
            "seal": seal,
            "source_check": check,
            "selection": selection,
            "device": "cuda",
            "test_files": run.TESTS,
        },
    )
    (tiny / "TESTS.xml").write_text(
        '<testsuites><testsuite tests="22" failures="0" errors="0" skipped="0"/></testsuites>'
    )
    core.write_new(
        tiny / "FINISHED.json",
        {
            "status": run.TINY_PASS,
            "pytest_exit_code": 0,
            "real_model_updates": 0,
            "counts": {"tests": 22, "failures": 0, "errors": 0, "skipped": 0},
            "runtime": run.read(run.ROOT / core.PLAN)["expected_runtime"],
            "files": old.manifest(tiny),
            **run.CEILING,
        },
    )
    core.write_new(
        raw / "STARTED.json",
        {
            "seal": seal,
            "source_check": check,
            "selection": selection,
            "history": run.verify_history(),
            "plan": run.read(run.ROOT / core.PLAN),
            "qualification": run.verify_qualification(tiny, seal),
        },
    )
    ref = run.reference()
    core.write_new(raw / "full_adapter_v2_INITIAL.json", ref["initial"])
    context = copy.deepcopy(ref["context"])
    context["contract"].update(source_commit=seal["source_commit"], preparation=preparation())
    context["binding"] = {"checkpointing": preparation()["checkpoint_policy"]}
    context["metadata"] = {
        "source_commit": seal["source_commit"],
        "seal_sha256": run.digest(tmp_path / "SOURCE_SEAL.json"),
        "plan_sha256": run.digest(run.ROOT / core.PLAN),
        "selection_sha256": run.digest(run.ROOT / run.PLAN),
        "reference_bundle_sha256": run.PREVIOUS_HASH,
        "mode": "full",
        "implementation": "adapter_v2",
    }
    core.write_new(raw / "full_adapter_v2_CONTEXT.json", context)
    for stem, window in [
        ("full_adapter_v2_step1", ref["windows"][0]),
        ("full_adapter_v2_step2", ref["windows"][1]),
        ("full_replay_step2", ref["windows"][1]),
    ]:
        core.write_new(raw / f"{stem}.json", window)
        (raw / f"{stem}_pairs.jsonl").write_text(
            "".join(run.canonical(p) + "\n" for p in window["pairs"])
        )
    for step in (1, 2):
        core.write_new(
            raw / f"full_adapter_v2_step{step}_CHECKPOINT.json", {"state_sha256": "c" * 64}
        )
    core.write_new(
        raw / "full_EQUIVALENCE.json",
        {
            "exact": True,
            "steps": [1, 2],
            "ordered_backward_pairs_per_arm": 32,
            "reference_bundle_sha256": run.PREVIOUS_HASH,
            "reference_recomputed": False,
            "candidate": "adapter_v2",
            "provenance_differences": ["source_commit", "preparation"],
        },
    )
    core.write_new(
        raw / "full_REPLAY.json",
        {
            "exact": True,
            "from_step": 1,
            "execute_step": 2,
            "compared_pairs": 16,
            "state_sha256": "c" * 64,
        },
    )
    for name in ("RESOURCES.jsonl", "HOST_RESOURCES.jsonl"):
        (raw / name).write_text("")
    core.write_new(
        raw / "FINISHED.json",
        {
            "status": run.PASS,
            "completed_modes": ["full"],
            "complete_unique_windows": 2,
            "complete_replay_windows": 1,
            "complete_backward_pairs": 48,
            "files": old.manifest(raw),
            **run.CEILING,
        },
    )
    return raw


def test_offline_preserves_all_three_provenances_and_scientific_fail(terminal):
    result = verifier.verify(terminal)
    assert result["combined_backward_pairs"] == 160
    assert result["combined_unique_windows"] == 8
    assert result["combined_replay_windows"] == 2
    assert result["original_status"] == result["previous_status"] == "INCOMPLETE_NO_RETRY"
    assert result["old_expression_gate"] == "FAIL"
    assert result["checkpoint_bytes_reloaded_offline"] is False


@pytest.mark.parametrize(
    "mutation", ["pair", "state", "initial", "missing", "legacy", "count", "seal"]
)
def test_offline_rejects_tampering_even_with_new_terminal_manifest(terminal, mutation):
    if mutation == "pair":
        path = terminal / "full_replay_step2_pairs.jsonl"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    elif mutation in ("state", "initial"):
        path = terminal / (
            "full_adapter_v2_step1.json" if mutation == "state" else "full_adapter_v2_INITIAL.json"
        )
        data = run.read(path)
        (data["state"] if mutation == "state" else data)["rng"] = "0" * 64
        path.write_text(json.dumps(data))
    elif mutation == "missing":
        (terminal / "full_adapter_v2_step1_CHECKPOINT.json").unlink()
    elif mutation == "legacy":
        (terminal / "full_legacy_step1_pairs.jsonl").write_text("{}\n")
    elif mutation == "seal":
        path = terminal / "STARTED.json"
        data = run.read(path)
        data["seal"]["source_hashes"] = {}
        path.write_text(json.dumps(data))
    path = terminal / "FINISHED.json"
    data = run.read(path)
    data["files"] = run.load("continue_v16_adapter_full").manifest(terminal)
    data["files"].pop("FINISHED.json")
    if mutation == "count":
        data["complete_backward_pairs"] = 32
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verifier.verify(terminal)
