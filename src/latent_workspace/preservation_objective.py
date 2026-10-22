"""Frozen full-vocabulary targets for the native owner, independent of host layout.

Private contexts stay on CPU; only the current selected target reaches the
device. Registration includes NON-preservation rows: an unknown key may never
silently become a world control. This is not a teacher or a second trainer.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import torch
from safetensors import safe_open

from .execution import digest, plan_hash, require
from .objective_audit import full_vocab_kl_sum
from .optimizer_state import tree_hash
from .preservation_binding import bind_preservation_targets

CE = "query_only_token_weighted_causal_nll"
SCHEMA = "ltws-native-ce-preservation-kl-v1"
BANK_SCHEMA = "ltws-owned-preservation-targets-v1"


def objective(coefficient, targets=None):
    """Zero is the unchanged legacy path, with no target object or target read."""
    require(
        type(coefficient) in (int, float) and math.isfinite(coefficient) and coefficient >= 0,
        "Finite nonnegative preservation coefficient",
    )
    if coefficient == 0:
        require(targets is None, "Disabled preservation must not open a target bank")
        return CE
    require(type(targets) is PreservationTargets, "Owned preservation targets required")
    return dict(
        schema=SCHEMA,
        coefficient=float(coefficient),
        ce_normalization="whole_window_supervised_tokens",
        kl_normalization="whole_window_preservation_tokens",
        direction="teacher_to_student",
        bank=targets.manifest(),
    )


def validate_objective(value):
    if value == CE:
        return False
    require(
        type(value) is dict
        and set(value)
        == {"schema", "coefficient", "ce_normalization", "kl_normalization", "direction", "bank"}
        and value["schema"] == SCHEMA,
        "Unknown objective",
    )
    coefficient = value["coefficient"]
    require(
        type(coefficient) in (int, float) and math.isfinite(coefficient) and coefficient > 0,
        "Positive finite preservation coefficient",
    )
    require(
        value["ce_normalization"] == "whole_window_supervised_tokens"
        and value["kl_normalization"] == "whole_window_preservation_tokens"
        and value["direction"] == "teacher_to_student"
        and type(value["bank"]) is dict
        and value["bank"].get("schema") == BANK_SCHEMA,
        "Preservation normalization/target policy",
    )
    return True


def _context(row, vocabulary):
    require(row["split"] == "train" and row["language"] == "en", "English train-only registry")
    ids, labels, memory = row["input_ids"], row["labels"], row["memory_ids"]
    require(type(ids) is list and len(ids) >= 2 and type(memory) is list, "Complete context")
    require(all(type(x) is int and 0 <= x < vocabulary for x in ids + memory), "Native token IDs")
    require(
        type(labels) is list
        and len(labels) == len(ids)
        and labels[0] == -100
        and all(type(y) is int and (y == -100 or y == x) for x, y in zip(ids, labels)),
        "Complete causal labels",
    )
    n = sum(y != -100 for y in labels)
    require(
        type(row["supervised_tokens"]) is int and n == row["supervised_tokens"] > 0,
        "Registered target count",
    )
    require(row.get("attention_mask", [1] * len(ids)) == [1] * len(ids), "No query padding")
    require(row.get("memory_mask", [1] * len(memory)) == [1] * len(memory), "No memory padding")
    return dict(input_ids=tuple(ids), labels=tuple(labels), memory_ids=tuple(memory), tokens=n)


class PreservationTargets:
    """File-verified targets and the exact registry for a frozen training schedule.

    Construct through ``load``. A receipt's input_sha256 is the canonical hash
    of ALL registered rows (including world controls), not a JSON byte digest.
    The explicit eligible-key list fixes membership, independently of memory
    presence. Each admitted tensor is hashed and checked for full-vocabulary
    log normalization; each use rechecks its bytes and actual forwarded context.
    """

    @classmethod
    def load(cls, path, receipt, rows, eligible_keys, *, expected_receipt_plan_sha256):
        require(type(rows) in (list, tuple) and rows, "Frozen complete row registry")
        indexed = {r["key"]: r for r in rows}
        require(len(indexed) == len(rows), "Unique registered rows")
        require(type(eligible_keys) in (list, tuple) and eligible_keys, "Explicit eligibility")
        require(
            len(set(eligible_keys)) == len(eligible_keys) and set(eligible_keys) <= indexed.keys(),
            "Eligible key coverage",
        )
        require(receipt["input_sha256"] == plan_hash(rows), "Complete registry input identity")
        binding = bind_preservation_targets(
            receipt,
            [indexed[k] for k in eligible_keys],
            expected_receipt_plan_sha256=expected_receipt_plan_sha256,
        )
        path = Path(path).resolve(strict=True)
        require(
            path.is_file()
            and path.stat().st_size == binding.target_file_bytes
            and digest(path) == binding.target_file_sha256,
            "Frozen target body identity",
        )
        instance = cls()
        instance._path = path
        instance._binding = binding
        instance._contexts = {k: _context(r, binding.vocabulary) for k, r in indexed.items()}
        instance._bound = {r.key: r for r in binding.rows}
        instance._tensor_hashes = {}
        with safe_open(path, framework="pt", device="cpu") as archive:
            require(
                set(archive.keys()) == {r.tensor_key for r in binding.rows}, "Exact tensor keys"
            )
            for row in binding.rows:
                tensor = archive.get_tensor(row.tensor_key)
                instance._validate_tensor(tensor, row)
                instance._tensor_hashes[row.key] = tree_hash(tensor)
        # Verify again after admission to reject concurrent mutation while mapping.
        require(digest(path) == binding.target_file_sha256, "Target changed during admission")
        instance._file_stat = instance._stat()
        instance._manifest = dict(
            schema=BANK_SCHEMA,
            receipt_plan_sha256=binding.receipt_plan_sha256,
            source_commit=binding.source_commit,
            original_base_sha256=binding.native_sha256,
            registered_rows_sha256=plan_hash(rows),
            registered_rows=len(rows),
            eligible_keys=list(eligible_keys),
            eligible_targets=sum(r.supervised_tokens for r in binding.rows),
            target_file_sha256=binding.target_file_sha256,
            target_file_bytes=binding.target_file_bytes,
            vocabulary=binding.vocabulary,
            teacher_policy=binding.teacher_policy,
            target_dtype="float32",
            temperature=1.0,
            causal_layout="logits[j-1]_for_active_label[j]",
        )
        instance._integrity = instance._identity()
        return instance

    def _stat(self):
        s = self._path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def _identity(self):
        return plan_hash(
            (
                self._manifest,
                self._contexts,
                self._tensor_hashes,
                self._binding.manifest(),
                str(self._path),
            )
        )

    @staticmethod
    def _validate_tensor(value, row):
        require(
            value.dtype == torch.float32
            and tuple(value.shape) == row.shape
            and not value.requires_grad
            and bool(torch.isfinite(value).all()),
            "Finite detached FP32 full-vocabulary targets",
        )
        require(
            torch.allclose(value.logsumexp(-1), torch.zeros(value.shape[0]), atol=2e-6, rtol=0),
            "Normalized teacher log probabilities",
        )

    def validate(self, *, full=False):
        require(self._identity() == self._integrity, "Owned target registry changed")
        require(self._bound == {r.key: r for r in self._binding.rows}, "Target index changed")
        require(self._stat() == self._file_stat, "Target file changed")
        if full:
            require(
                digest(self._path) == self._binding.target_file_sha256,
                "Target body changed at lifecycle boundary",
            )

    def manifest(self):
        self.validate()
        return copy.deepcopy(self._manifest)

    def window(self, rows):
        self.validate()
        result = []
        for key, tokens in rows:
            require(key in self._contexts, "Unknown registered row; no missing-target fallback")
            require(self._contexts[key]["tokens"] == tokens, "Registered denominator mismatch")
            if key in self._bound:
                result.append((key, tokens))
        require(result, "Positive preservation window needs eligible targets")
        return result

    def require_batch(self, key, batch):
        self.validate()
        require(key in self._contexts, "Unknown registered row")
        context = self._contexts[key]
        require(
            type(batch) is dict
            and set(batch)
            <= {"input_ids", "labels", "attention_mask", "memory_ids", "memory_mask"},
            "Only registered causal batch fields",
        )
        for field in ("input_ids", "labels", "memory_ids"):
            expected = context[field]
            value = batch.get(field)
            if field == "memory_ids" and not expected and value is None:
                continue
            require(
                isinstance(value, torch.Tensor)
                and value.dtype == torch.long
                and value.shape == (1, len(expected))
                and value.detach().cpu().tolist() == [list(expected)],
                f"Actual batch differs from registered {field}",
            )
        for field, length in (
            ("attention_mask", len(context["input_ids"])),
            ("memory_mask", len(context["memory_ids"])),
        ):
            mask = batch.get(field)
            require(
                mask is None
                or (
                    isinstance(mask, torch.Tensor)
                    and mask.shape == (1, length)
                    and bool((mask == 1).all())
                ),
                f"Actual batch differs from registered {field}",
            )

    def kl_sum(self, key, logits):
        """None is an explicitly registered NON-eligible row, never a missing one."""
        self.validate()
        require(key in self._contexts, "Unknown registered row")
        if key not in self._bound:
            return None
        row = self._bound[key]
        require(
            logits.shape == (1, row.query_tokens, self._binding.vocabulary),
            "Student causal extent/vocabulary changed",
        )
        with safe_open(self._path, framework="pt", device="cpu") as archive:
            value = archive.get_tensor(row.tensor_key)
            require(tree_hash(value) == self._tensor_hashes[key], "Selected target bytes changed")
            target = value.to(device=logits.device, copy=True)[None]
        pred = logits[:, row.causal_logit_positions, :]
        return full_vocab_kl_sum(pred, target, torch.ones_like(pred[..., 0], dtype=torch.bool))
