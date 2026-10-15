#!/usr/bin/env python3
"""Capture deterministic free-form and task-native behavior before pruning.

The receipt deliberately separates general-language generation from the
functional-workspace task contract. General prompts exercise each saved base
trunk directly. Task-native traces exercise the complete saved wrapper and
record the decoded constrained answer for selected world/query cases.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import torch

FORMAT = "latent-workspace-v10-generation-behavior-v1"
PROMPT_FORMAT = "latent-workspace-v10-behavior-prompt-suite-v1"
LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class BehaviorCaptureError(RuntimeError):
    """A capture input, execution, stability, or parity gate failed."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _plain_file(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if path.is_symlink() or not resolved.is_file():
        raise BehaviorCaptureError(f"{label} must be a regular non-symlink file.")
    return resolved


def _plain_directory(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if path.is_symlink() or not resolved.is_dir():
        raise BehaviorCaptureError(f"{label} must be a non-symlink directory.")
    return resolved


def _inside(repo_root: Path, path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise BehaviorCaptureError(f"{label} must stay inside --repo-root.") from exc
    return resolved


def _relative(repo_root: Path, path: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise BehaviorCaptureError(f"{label} is outside --repo-root.") from exc


def _repo_input(repo_root: Path, path: Path, *, label: str) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    return _inside(repo_root, candidate, label=label)


def parse_labeled_path(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise BehaviorCaptureError("Labeled paths must use LABEL=PATH syntax.")
    label, path = raw.split("=", 1)
    if LABEL_PATTERN.fullmatch(label) is None:
        raise BehaviorCaptureError(f"Invalid model label: {label!r}.")
    if not path:
        raise BehaviorCaptureError(f"Model label {label!r} has an empty path.")
    return label, Path(path)


def parse_label_pair(raw: str) -> tuple[str, str]:
    left, right_path = parse_labeled_path(raw)
    right = str(right_path)
    if LABEL_PATTERN.fullmatch(right) is None:
        raise BehaviorCaptureError(f"Invalid parity label: {right!r}.")
    if left == right:
        raise BehaviorCaptureError("A transport parity pair must use distinct labels.")
    return left, right


def load_prompt_suite(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BehaviorCaptureError("Prompt suite is not readable JSON.") from exc
    if not isinstance(value, dict) or value.get("format") != PROMPT_FORMAT:
        raise BehaviorCaptureError(f"Prompt suite format must be {PROMPT_FORMAT!r}.")
    prompts = value.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise BehaviorCaptureError("Prompt suite must contain a non-empty prompts list.")
    seen: set[str] = set()
    for index, prompt in enumerate(prompts):
        if not isinstance(prompt, dict):
            raise BehaviorCaptureError(f"Prompt {index} must be an object.")
        prompt_id = prompt.get("id")
        text = prompt.get("prompt")
        category = prompt.get("category")
        if not isinstance(prompt_id, str) or LABEL_PATTERN.fullmatch(prompt_id) is None:
            raise BehaviorCaptureError(f"Prompt {index} has an invalid id.")
        if prompt_id in seen:
            raise BehaviorCaptureError(f"Duplicate prompt id: {prompt_id!r}.")
        if not isinstance(text, str) or not text.strip():
            raise BehaviorCaptureError(f"Prompt {prompt_id!r} has no text.")
        if not isinstance(category, str) or not category.strip():
            raise BehaviorCaptureError(f"Prompt {prompt_id!r} has no category.")
        seen.add(prompt_id)
    task = value.get("task_native")
    if not isinstance(task, dict):
        raise BehaviorCaptureError("Prompt suite task_native must be an object.")
    dataset = task.get("dataset")
    world_indices = task.get("world_indices")
    query_indices = task.get("query_indices")
    if not isinstance(dataset, str) or not dataset:
        raise BehaviorCaptureError("task_native.dataset must be a path string.")
    for name, values in (
        ("world_indices", world_indices),
        ("query_indices", query_indices),
    ):
        if (
            not isinstance(values, list)
            or not values
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in values
            )
            or len(values) != len(set(values))
        ):
            raise BehaviorCaptureError(
                f"task_native.{name} must contain unique non-negative integers."
            )
    selection_contract = task.get("selection_contract")
    required_selection_gates = (
        "require_balanced_expected_choices",
        "require_affected_and_unaffected",
        "require_heldout_and_non_heldout",
    )
    if not isinstance(selection_contract, dict):
        raise BehaviorCaptureError("task_native.selection_contract must be an object.")
    if set(selection_contract) != set(required_selection_gates) or any(
        selection_contract[name] is not True for name in required_selection_gates
    ):
        raise BehaviorCaptureError(
            "task_native.selection_contract must enable every required selection gate."
        )
    return value


def tree_inventory(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_dir():
            continue
        if not path.is_file():
            raise BehaviorCaptureError("Model inventory contains a non-file entry.")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": int(path.stat().st_size),
                "sha256": sha256_file(path.resolve()),
                "source_entry": "symlink" if path.is_symlink() else "regular_file",
            }
        )
    if not records:
        raise BehaviorCaptureError("Model inventory is empty.")
    return {
        "files": records,
        "file_count": len(records),
        "logical_bytes": sum(int(record["bytes"]) for record in records),
        "inventory_sha256": stable_hash(records),
    }


def _tensor_bytes_sha256(tensor: torch.Tensor) -> str:
    byte_view = tensor.detach().contiguous().view(torch.uint8).cpu()
    return sha256_bytes(byte_view.numpy().tobytes())


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _load_transformers() -> tuple[Any, Any]:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise BehaviorCaptureError("transformers is required for behavior capture.") from exc
    return AutoModelForCausalLM, AutoTokenizer


def _load_base_model(
    source: str | Path,
    *,
    revision: str | None,
    device: torch.device,
) -> torch.nn.Module:
    AutoModelForCausalLM, _ = _load_transformers()
    kwargs: dict[str, Any] = {
        "local_files_only": True,
        "trust_remote_code": False,
        "dtype": torch.bfloat16 if device.type == "cuda" else torch.float32,
        "attn_implementation": "sdpa",
        "low_cpu_mem_usage": True,
    }
    if revision is not None:
        kwargs["revision"] = revision
    model = AutoModelForCausalLM.from_pretrained(source, **kwargs)
    model.to(device)
    model.eval()
    return model


def _render_chat_prompt(tokenizer: Any, prompt: str) -> str:
    if not getattr(tokenizer, "chat_template", None):
        raise BehaviorCaptureError("The canonical tokenizer has no chat template.")
    rendered = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False,
        add_generation_prompt=True,
    )
    if not isinstance(rendered, str) or not rendered:
        raise BehaviorCaptureError("Chat template produced no text.")
    return rendered


@torch.inference_mode()
def capture_freeform(
    model: torch.nn.Module,
    tokenizer: Any,
    prompts: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
    max_new_tokens: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prompt in prompts:
        rendered = _render_chat_prompt(tokenizer, str(prompt["prompt"]))
        encoded = tokenizer(
            rendered,
            return_tensors="pt",
            add_special_tokens=False,
        )
        input_ids = encoded["input_ids"].to(device)
        attention_mask = encoded["attention_mask"].to(device)
        generated = model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            do_sample=False,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            eos_token_id=getattr(tokenizer, "eos_token_id", None),
            pad_token_id=getattr(tokenizer, "pad_token_id", None),
        )
        completion_ids = generated[0, input_ids.shape[1] :].detach().cpu()
        completion = tokenizer.decode(
            completion_ids.tolist(),
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        rows.append(
            {
                "id": str(prompt["id"]),
                "category": str(prompt["category"]),
                "prompt": str(prompt["prompt"]),
                "rendered_prompt_sha256": sha256_bytes(rendered.encode("utf-8")),
                "input_token_ids_sha256": stable_hash(input_ids[0].detach().cpu().tolist()),
                "completion": completion,
                "completion_utf8_sha256": sha256_bytes(completion.encode("utf-8")),
                "completion_token_ids": completion_ids.tolist(),
                "completion_token_ids_sha256": stable_hash(completion_ids.tolist()),
                "completion_tokens": int(completion_ids.numel()),
                "ended_with_eos": bool(
                    completion_ids.numel() > 0
                    and getattr(tokenizer, "eos_token_id", None) is not None
                    and int(completion_ids[-1].item()) == int(tokenizer.eos_token_id)
                ),
            }
        )
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BehaviorCaptureError(
                    f"Task dataset line {line_number} is invalid JSON."
                ) from exc
            if not isinstance(value, dict):
                raise BehaviorCaptureError(f"Task dataset line {line_number} is not an object.")
            rows.append(value)
    return rows


def _selected_task_cases(
    raw_records: Sequence[Mapping[str, Any]],
    *,
    world_indices: Sequence[int],
    query_indices: Sequence[int],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for world_index in world_indices:
        if world_index >= len(raw_records):
            raise BehaviorCaptureError(f"Task world index {world_index} exceeds the dataset.")
        record = raw_records[world_index]
        contexts = record.get("contexts")
        queries = record.get("queries")
        answers = record.get("answers")
        choices = record.get("choices")
        if (
            not isinstance(contexts, list)
            or len(contexts) != 2
            or not isinstance(queries, list)
            or not isinstance(answers, list)
            or len(answers) != 2
            or not isinstance(choices, list)
            or len(choices) < 2
        ):
            raise BehaviorCaptureError(
                f"Task world {world_index} does not satisfy the functional record contract."
            )
        affected = record.get("affected", [False] * len(queries))
        heldout = record.get("heldout_queries", [False] * len(queries))
        for side in range(2):
            for query_index in query_indices:
                if query_index >= len(queries) or query_index >= len(answers[side]):
                    raise BehaviorCaptureError(
                        f"Task query index {query_index} exceeds world {world_index}."
                    )
                expected = answers[side][query_index]
                if (
                    isinstance(expected, bool)
                    or not isinstance(expected, int)
                    or expected < 0
                    or expected >= len(choices)
                ):
                    raise BehaviorCaptureError(
                        f"Task answer index is invalid in world {world_index}."
                    )
                cases.append(
                    {
                        "world_index": int(world_index),
                        "side": side,
                        "query_index": int(query_index),
                        "context": str(contexts[side]),
                        "query": str(queries[query_index]),
                        "choices": [str(value) for value in choices],
                        "expected_index": int(expected),
                        "affected": bool(affected[query_index]),
                        "heldout": bool(heldout[query_index]),
                    }
                )
    return cases


def _task_case_profile(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not cases:
        raise BehaviorCaptureError("Task selection contains no cases.")
    expected_counts: dict[int, int] = {}
    for case in cases:
        expected = int(case["expected_index"])
        expected_counts[expected] = expected_counts.get(expected, 0) + 1
    affected = sum(bool(case["affected"]) for case in cases)
    heldout = sum(bool(case["heldout"]) for case in cases)
    if len(expected_counts) < 2 or len(set(expected_counts.values())) != 1:
        raise BehaviorCaptureError(
            "Task selection must have exactly balanced expected-choice counts."
        )
    if affected == 0 or affected == len(cases):
        raise BehaviorCaptureError("Task selection must include affected and unaffected cases.")
    if heldout == 0 or heldout == len(cases):
        raise BehaviorCaptureError("Task selection must include heldout and non-heldout cases.")
    return {
        "case_count": len(cases),
        "expected_choice_counts": {
            str(index): count for index, count in sorted(expected_counts.items())
        },
        "affected_cases": affected,
        "unaffected_cases": len(cases) - affected,
        "heldout_cases": heldout,
        "non_heldout_cases": len(cases) - heldout,
    }


@torch.inference_mode()
def capture_original_task_views(
    model: torch.nn.Module,
    tokenizer: Any,
    cases: Sequence[Mapping[str, Any]],
    *,
    data_config: Any,
    device: torch.device,
) -> dict[str, Any]:
    from latent_workspace_ft_v10 import engine

    views: dict[str, Any] = {}
    for view in ("query_only", "inline"):
        prompts: list[str] = []
        for case in cases:
            elicited_query = engine._functional_elicitation_query(
                str(case["query"]),
                data_config,
            )
            prompt = (
                elicited_query
                if view == "query_only"
                else (f"{case['context']}{data_config.prompt_separator}{elicited_query}")
            )
            prompts.append(prompt)
        encoded = tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            add_special_tokens=False,
        )
        input_ids = encoded["input_ids"].to(device)
        attention_mask = encoded["attention_mask"].to(device)
        outputs = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
            return_dict=True,
        )
        positions = attention_mask.sum(dim=1).to(torch.long) - 1
        rows = torch.arange(input_ids.shape[0], device=device)
        source_logits = outputs.logits[rows, positions]
        candidate_ids: list[list[int]] = []
        for prompt, case in zip(prompts, cases, strict=True):
            ids = [
                engine._functional_suffix_token_ids(
                    tokenizer,
                    prompt,
                    str(choice),
                    require_one=True,
                )[2]
                for choice in case["choices"]
            ]
            if any(len(value) != 1 for value in ids):
                raise BehaviorCaptureError(
                    "Task-native behavior capture requires one-token choices."
                )
            candidate_ids.append([value[0] for value in ids])
        candidate_tensor = torch.tensor(candidate_ids, dtype=torch.long, device=device)
        choice_logits = source_logits.gather(1, candidate_tensor)
        predicted = choice_logits.argmax(dim=1)
        view_cases: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            prediction = int(predicted[index].item())
            values = [float(value) for value in choice_logits[index].float().cpu().tolist()]
            row = dict(case)
            row.update(
                {
                    "predicted_index": prediction,
                    "generated_choice": str(case["choices"][prediction]).strip(),
                    "correct": prediction == int(case["expected_index"]),
                    "choice_logits": values,
                }
            )
            view_cases.append(row)
        views[view] = {
            "functional_elicitation": str(data_config.functional_elicitation),
            "prompt_separator": str(data_config.prompt_separator),
            "cases": view_cases,
            "accuracy": sum(bool(row["correct"]) for row in view_cases) / len(view_cases),
            "predictions_sha256": stable_hash([int(row["predicted_index"]) for row in view_cases]),
            "choice_logits_tensor_sha256": _tensor_bytes_sha256(choice_logits),
        }
    return views


@torch.inference_mode()
def capture_functional_task_trace(
    wrapper: torch.nn.Module,
    tokenizer: Any,
    config: Any,
    raw_records: Sequence[Mapping[str, Any]],
    *,
    task_dataset: Path,
    world_indices: Sequence[int],
    query_indices: Sequence[int],
    device: torch.device,
) -> dict[str, Any]:
    from latent_workspace_ft_v10 import engine

    dataset = engine.JsonlFineTuningDataset(
        [str(task_dataset)],
        tokenizer,
        config.data,
    )
    features = [dataset[index] for index in world_indices]
    collator = engine.CausalFineTuningCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=config.data.pad_to_multiple_of,
    )
    batch = engine.move_batch_to_device(collator(features), device)
    precision = engine.resolve_mixed_precision(config.train.mixed_precision, device)
    with engine.autocast_context(device, precision):
        output = wrapper(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"],
            prompt_mask=batch["prompt_mask"],
            context_mask=batch.get("context_mask"),
            query_mask=batch.get("query_mask"),
            example_group_ids=batch.get("example_group_ids"),
            world_group_ids=batch.get("world_group_ids"),
            counterfactual_group_ids=batch.get("counterfactual_group_ids"),
            answer_classes=batch.get("answer_classes"),
            **engine.bridge_batch_kwargs(batch),
            **engine.functional_batch_kwargs(batch),
            compute_workspace_loss=False,
            compute_spectral=False,
            bypass_workspace=False,
            memory_intervention="intact",
        )
    logits = output.get("logits")
    if not isinstance(logits, torch.Tensor):
        raise BehaviorCaptureError("Functional task trace received no logits.")
    answers = batch["functional_answer_classes"]
    valid = batch["functional_query_valid_mask"]
    batch_size, _sides, query_count = answers.shape
    valid_grid = valid[:, None, :].expand(batch_size, 2, query_count)
    positions = torch.nonzero(valid_grid.reshape(-1), as_tuple=False).flatten()
    if config.functional.route_mode in {"inline", "inline_sidecar"}:
        labels = batch["functional_inline_labels"]
        choices = batch["functional_inline_choice_ids"]
    else:
        labels = batch["functional_query_labels"]
        choices = batch["functional_query_choice_ids"]
    flat_labels = labels.reshape(batch_size * 2 * query_count, -1)[positions]
    flat_choices = choices.reshape(batch_size * 2 * query_count, -1)[positions]
    flat_answers = answers.reshape(batch_size * 2 * query_count)[positions]
    _nll, choice_logits, _targets, _source_positions = wrapper._functional_answer_rows(
        logits,
        flat_labels,
        flat_choices,
    )
    predicted = choice_logits.argmax(dim=1)

    selected_query_set = set(int(value) for value in query_indices)
    trace_cases: list[dict[str, Any]] = []
    flat_index = 0
    for local_world, world_index in enumerate(world_indices):
        record = raw_records[world_index]
        for side in range(2):
            for query_index in range(query_count):
                if not bool(valid[local_world, query_index].item()):
                    continue
                prediction = int(predicted[flat_index].item())
                expected = int(flat_answers[flat_index].item())
                if query_index in selected_query_set:
                    values = [
                        float(value) for value in choice_logits[flat_index].float().cpu().tolist()
                    ]
                    choices_text = [str(value) for value in record["choices"]]
                    trace_cases.append(
                        {
                            "world_index": int(world_index),
                            "side": side,
                            "query_index": query_index,
                            "context": str(record["contexts"][side]),
                            "query": str(record["queries"][query_index]),
                            "choices": choices_text,
                            "expected_index": expected,
                            "predicted_index": prediction,
                            "generated_choice": choices_text[prediction].strip(),
                            "correct": prediction == expected,
                            "affected": bool(record["affected"][query_index]),
                            "heldout": bool(record["heldout_queries"][query_index]),
                            "choice_logits": values,
                        }
                    )
                flat_index += 1
    if not trace_cases:
        raise BehaviorCaptureError("Functional task selection produced no cases.")
    return {
        "route_mode": str(config.functional.route_mode),
        "cases": trace_cases,
        "accuracy": sum(bool(row["correct"]) for row in trace_cases) / len(trace_cases),
        "predictions_sha256": stable_hash([int(row["predicted_index"]) for row in trace_cases]),
        "selected_choice_logits_sha256": stable_hash([row["choice_logits"] for row in trace_cases]),
        "all_choice_logits_tensor_sha256": _tensor_bytes_sha256(choice_logits),
    }


def _checkpoint_binding(repo_root: Path, checkpoint: Path) -> dict[str, Any]:
    manifest_path = _plain_file(checkpoint / "manifest.json", label="checkpoint manifest")
    config_path = _plain_file(
        checkpoint / "experiment_config.json", label="checkpoint experiment config"
    )
    workspace_path = _plain_file(
        checkpoint / "workspace_state.pt", label="checkpoint workspace state"
    )
    base_root = _plain_directory(checkpoint / "base_model", label="checkpoint base model")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise BehaviorCaptureError("Checkpoint final manifest is not complete.")
    return {
        "checkpoint": _relative(repo_root, checkpoint, label="checkpoint"),
        "manifest_sha256": sha256_file(manifest_path),
        "experiment_config_sha256": sha256_file(config_path),
        "workspace_state_sha256": sha256_file(workspace_path),
        "source_sha256": manifest.get("source_sha256"),
        "config_sha256": manifest.get("config_sha256"),
        "global_step": manifest.get("global_step"),
        "run_id": manifest.get("run_id"),
        "base_model_inventory": tree_inventory(base_root),
    }


def _validate_transformers_snapshot(snapshot: Path) -> dict[str, Any]:
    required = ["config.json", "tokenizer_config.json"]
    missing = [name for name in required if not (snapshot / name).is_file()]
    tokenizer_files = [
        name for name in ("tokenizer.json", "tokenizer.model") if (snapshot / name).is_file()
    ]
    if not tokenizer_files:
        missing.append("tokenizer.json or tokenizer.model")

    index_path = snapshot / "model.safetensors.index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = index["weight_map"]
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise BehaviorCaptureError("Original model safetensors index is invalid.") from exc
        if not isinstance(weight_map, dict) or not weight_map:
            raise BehaviorCaptureError("Original model safetensors index is empty.")
        weight_files = sorted(set(weight_map.values()))
        if any(
            not isinstance(name, str)
            or not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            for name in weight_files
        ):
            raise BehaviorCaptureError(
                "Original model safetensors index contains an unsafe shard path."
            )
        missing.extend(name for name in weight_files if not (snapshot / name).is_file())
        model_layout = "sharded_safetensors"
    elif (snapshot / "model.safetensors").is_file():
        weight_files = ["model.safetensors"]
        model_layout = "single_safetensors"
    elif (snapshot / "pytorch_model.bin").is_file():
        weight_files = ["pytorch_model.bin"]
        model_layout = "single_pytorch_bin"
    else:
        weight_files = []
        missing.append("supported model weight file or index")

    if missing:
        raise BehaviorCaptureError(
            "Original pinned snapshot lacks runtime files: " + ", ".join(missing)
        )
    return {
        "validation_scope": "transformers_runtime_files",
        "model_layout": model_layout,
        "weight_files": weight_files,
        "tokenizer_files": tokenizer_files,
    }


def _original_snapshot_binding(
    model_id: str,
    revision: str,
) -> tuple[Path, dict[str, Any]]:
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError as exc:
        raise BehaviorCaptureError("huggingface_hub is required for original binding.") from exc
    cached_config = try_to_load_from_cache(
        repo_id=model_id,
        filename="config.json",
        revision=revision,
    )
    if not isinstance(cached_config, str):
        raise BehaviorCaptureError(
            "The original model config is not cached at the pinned revision."
        )
    snapshot = _plain_directory(
        Path(cached_config).parent,
        label="original pinned snapshot",
    )
    runtime_validation = _validate_transformers_snapshot(snapshot)
    return snapshot, {
        "model_id": model_id,
        "revision": revision,
        "cache_scope": (
            "Pinned local Transformers runtime snapshot; this does not claim that "
            "every non-runtime file in the Hub repository is cached."
        ),
        "runtime_validation": runtime_validation,
        "snapshot_inventory": tree_inventory(snapshot),
    }


def _completion_groups(model_results: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    prompt_ids = [str(row["id"]) for row in next(iter(model_results.values()))["freeform"]]
    result: list[dict[str, Any]] = []
    for prompt_id in prompt_ids:
        groups: dict[str, list[str]] = {}
        for label, model in model_results.items():
            row = next(item for item in model["freeform"] if item["id"] == prompt_id)
            groups.setdefault(str(row["completion_token_ids_sha256"]), []).append(label)
        result.append(
            {
                "prompt_id": prompt_id,
                "exact_completion_groups": [
                    {"completion_token_ids_sha256": digest, "labels": sorted(labels)}
                    for digest, labels in sorted(groups.items())
                ],
                "unique_completion_count": len(groups),
            }
        )
    return result


def atomic_write_json(path: Path, value: Mapping[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise BehaviorCaptureError(
                    "Behavior receipt already exists; pass --overwrite to replace it."
                ) from exc
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def release_device_cache(device: torch.device) -> None:
    gc.collect()
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        torch.cuda.empty_cache()


def capture(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _plain_directory(args.repo_root, label="repo root")
    implementation = _plain_file(Path(__file__), label="capture implementation")
    implementation_sha256 = sha256_file(implementation)
    prompt_path = _repo_input(
        repo_root,
        args.prompt_suite,
        label="prompt suite",
    )
    prompt_path = _plain_file(prompt_path, label="prompt suite")
    prompt_sha256 = sha256_file(prompt_path)
    prompt_suite = load_prompt_suite(prompt_path)
    task_path = _repo_input(
        repo_root,
        Path(str(prompt_suite["task_native"]["dataset"])),
        label="task dataset",
    )
    task_path = _plain_file(task_path, label="task dataset")
    task_sha256 = sha256_file(task_path)
    raw_task_records = _read_jsonl(task_path)
    world_indices = [int(value) for value in prompt_suite["task_native"]["world_indices"]]
    query_indices = [int(value) for value in prompt_suite["task_native"]["query_indices"]]
    task_cases = _selected_task_cases(
        raw_task_records,
        world_indices=world_indices,
        query_indices=query_indices,
    )
    task_case_profile = _task_case_profile(task_cases)

    labeled_checkpoints = [parse_labeled_path(value) for value in args.checkpoint]
    labels = [label for label, _path in labeled_checkpoints]
    if len(labels) != len(set(labels)):
        raise BehaviorCaptureError("Checkpoint labels must be unique.")
    if "original" in labels:
        raise BehaviorCaptureError("Checkpoint label 'original' is reserved.")
    checkpoints: dict[str, Path] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for label, raw_path in labeled_checkpoints:
        checkpoint = _repo_input(
            repo_root,
            raw_path,
            label=f"checkpoint {label}",
        )
        checkpoint = _plain_directory(checkpoint, label=f"checkpoint {label}")
        checkpoints[label] = checkpoint
        bindings[label] = _checkpoint_binding(repo_root, checkpoint)
    parity_pairs = [parse_label_pair(value) for value in args.transport_pair]
    for left, right in parity_pairs:
        if left not in checkpoints or right not in checkpoints:
            raise BehaviorCaptureError(
                f"Transport pair {left}={right} references an unknown checkpoint label."
            )

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise BehaviorCaptureError("CUDA was requested but is unavailable.")
    if args.max_new_tokens < 1:
        raise BehaviorCaptureError("--max-new-tokens must be positive.")
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)

    original_snapshot, original_binding = _original_snapshot_binding(
        args.original_model,
        args.original_revision,
    )
    _AutoModel, AutoTokenizer = _load_transformers()
    tokenizer = AutoTokenizer.from_pretrained(
        original_snapshot,
        local_files_only=True,
        trust_remote_code=False,
    )
    if getattr(tokenizer, "pad_token_id", None) is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    tokenizer_binding = {
        "vocab_size": int(len(tokenizer)),
        "chat_template_sha256": sha256_bytes(
            str(getattr(tokenizer, "chat_template", "")).encode("utf-8")
        ),
        "pad_token_id": int(tokenizer.pad_token_id),
        "eos_token_id": int(tokenizer.eos_token_id),
    }

    from latent_workspace_ft_v10 import engine

    checkpoint_configs = {
        label: engine.ExperimentConfig.from_json(checkpoints[label] / "experiment_config.json")
        for label in labels
    }
    prompt_contracts = {
        (
            str(config.data.functional_elicitation),
            str(config.data.prompt_separator),
            bool(config.data.use_chat_template),
            bool(config.data.add_bos),
            bool(config.data.add_eos),
        )
        for config in checkpoint_configs.values()
    }
    if len(prompt_contracts) != 1:
        raise BehaviorCaptureError("All checkpoints must share one task-native prompt contract.")
    reference_config = checkpoint_configs[labels[0]]

    model_results: dict[str, dict[str, Any]] = {}
    original = _load_base_model(
        original_snapshot,
        revision=None,
        device=device,
    )
    model_results["original"] = {
        "binding": original_binding,
        "freeform": capture_freeform(
            original,
            tokenizer,
            prompt_suite["prompts"],
            device=device,
            max_new_tokens=args.max_new_tokens,
        ),
        "task_native_baselines": capture_original_task_views(
            original,
            tokenizer,
            task_cases,
            data_config=reference_config.data,
            device=device,
        ),
    }
    del original
    release_device_cache(device)

    for label in labels:
        checkpoint = checkpoints[label]
        config = checkpoint_configs[label]
        base_model = _load_base_model(
            checkpoint / "base_model",
            revision=None,
            device=device,
        )
        freeform = capture_freeform(
            base_model,
            tokenizer,
            prompt_suite["prompts"],
            device=device,
            max_new_tokens=args.max_new_tokens,
        )
        wrapper = engine.LatentWorkspaceCausalLM(
            base_model=base_model,
            hidden_dim=engine.infer_hidden_size(base_model),
            vocab_size=engine.infer_vocab_size(base_model),
            config=config.workspace,
            functional_config=config.functional,
            hidden_capture=config.model.hidden_capture,
            base_activation_offload=config.train.base_activation_offload,
        )
        custom_state = engine._torch_load(
            checkpoint / "workspace_state.pt",
            weights_only=True,
        )
        wrapper.load_custom_state_dict(custom_state)
        wrapper.to(device)
        wrapper.eval()
        task_trace = capture_functional_task_trace(
            wrapper,
            tokenizer,
            config,
            raw_task_records,
            task_dataset=task_path,
            world_indices=world_indices,
            query_indices=query_indices,
            device=device,
        )
        model_results[label] = {
            "binding": bindings[label],
            "freeform": freeform,
            "task_native": task_trace,
        }
        del wrapper, base_model, custom_state, freeform, task_trace
        release_device_cache(device)

    parity: list[dict[str, Any]] = []
    for left, right in parity_pairs:
        left_result = model_results[left]
        right_result = model_results[right]
        freeform_equal = [
            row["completion_token_ids_sha256"] for row in left_result["freeform"]
        ] == [row["completion_token_ids_sha256"] for row in right_result["freeform"]]
        task_logits_equal = (
            left_result["task_native"]["all_choice_logits_tensor_sha256"]
            == right_result["task_native"]["all_choice_logits_tensor_sha256"]
        )
        task_predictions_equal = (
            left_result["task_native"]["predictions_sha256"]
            == right_result["task_native"]["predictions_sha256"]
        )
        passed = freeform_equal and task_logits_equal and task_predictions_equal
        parity.append(
            {
                "left": left,
                "right": right,
                "passed": passed,
                "freeform_completion_tokens_exact": freeform_equal,
                "task_choice_logits_exact": task_logits_equal,
                "task_predictions_exact": task_predictions_equal,
            }
        )
        if not passed:
            raise BehaviorCaptureError(f"Transport behavior parity failed for {left}={right}.")

    bindings_after = {label: _checkpoint_binding(repo_root, checkpoints[label]) for label in labels}
    if bindings_after != bindings:
        raise BehaviorCaptureError("A checkpoint changed during behavior capture.")
    if sha256_file(prompt_path) != prompt_sha256:
        raise BehaviorCaptureError("Prompt suite changed during behavior capture.")
    if sha256_file(task_path) != task_sha256:
        raise BehaviorCaptureError("Task dataset changed during behavior capture.")
    if sha256_file(implementation) != implementation_sha256:
        raise BehaviorCaptureError("Capture implementation changed during execution.")

    return {
        "format": FORMAT,
        "status": "PASS",
        "created_utc": datetime.now(UTC).isoformat(),
        "capture": {
            "implementation": _relative(repo_root, implementation, label="capture implementation"),
            "implementation_sha256": implementation_sha256,
            "torch": _package_version("torch"),
            "transformers": _package_version("transformers"),
            "device_type": device.type,
            "device_name": (
                torch.cuda.get_device_name(device) if device.type == "cuda" else str(device)
            ),
            "seed": int(args.seed),
        },
        "prompt_suite": {
            "path": _relative(repo_root, prompt_path, label="prompt suite"),
            "sha256": prompt_sha256,
            "task_dataset": _relative(repo_root, task_path, label="task dataset"),
            "task_dataset_sha256": task_sha256,
            "world_indices": world_indices,
            "query_indices": query_indices,
            "selection_contract": prompt_suite["task_native"]["selection_contract"],
            "task_case_profile": task_case_profile,
        },
        "decoding": {
            "freeform": {
                "chat_template": True,
                "do_sample": False,
                "max_new_tokens": int(args.max_new_tokens),
            },
            "task_native": {
                "mode": "one_token_constrained_choice",
                "memory_intervention": "intact",
            },
        },
        "tokenizer": tokenizer_binding,
        "task_native_prompt_contract": {
            "functional_elicitation": str(reference_config.data.functional_elicitation),
            "prompt_separator": str(reference_config.data.prompt_separator),
            "use_chat_template": bool(reference_config.data.use_chat_template),
            "add_bos": bool(reference_config.data.add_bos),
            "add_eos": bool(reference_config.data.add_eos),
        },
        "models": model_results,
        "transport_behavior_parity": parity,
        "cross_model_completion_groups": _completion_groups(model_results),
        "claim_boundary": (
            "PASS proves that the configured artifacts were stable, every requested "
            "deterministic generation completed, and each declared transport sentinel "
            "matched in free-form token output plus task-native choice logits and "
            "predictions. Free-form rows exercise saved base trunks only; task-native "
            "rows separately exercise the complete functional-workspace wrapper. This "
            "bounded prompt snapshot is qualitative engineering evidence, not a broad "
            "behavioral-equivalence, model-quality, safety, or scientific claim."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--prompt-suite", type=Path, required=True)
    parser.add_argument("--original-model", required=True)
    parser.add_argument("--original-revision", required=True)
    parser.add_argument(
        "--checkpoint",
        action="append",
        required=True,
        help="Repeat LABEL=FINAL_BUNDLE for every trained model.",
    )
    parser.add_argument(
        "--transport-pair",
        action="append",
        default=[],
        help="Repeat CANDIDATE=REFERENCE to require behavioral exactness.",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    output = args.output
    if not output.is_absolute():
        output = repo_root / output
    output = output.resolve()
    try:
        _inside(repo_root, output, label="output")
        if output.exists() and not args.overwrite:
            raise BehaviorCaptureError(
                "Behavior receipt already exists; pass --overwrite to replace it."
            )
        receipt = capture(args)
        atomic_write_json(output, receipt, overwrite=args.overwrite)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, BehaviorCaptureError)
            else ("Unexpected behavior-capture failure; no successful claim is available.")
        )
        error_receipt = {
            "format": FORMAT,
            "status": "ERROR",
            "created_utc": datetime.now(UTC).isoformat(),
            "error": {"type": type(exc).__name__, "message": message},
            "claim_boundary": (
                "This ERROR receipt is negative engineering evidence only and contains "
                "no successful generation, behavioral-equivalence, or scientific claim."
            ),
        }
        try:
            atomic_write_json(output, error_receipt, overwrite=args.overwrite)
        except Exception:
            pass
        print(f"ERROR: {message}", file=os.sys.stderr)
        return 2
    print(f"PASS: {_relative(repo_root, output, label='output')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
