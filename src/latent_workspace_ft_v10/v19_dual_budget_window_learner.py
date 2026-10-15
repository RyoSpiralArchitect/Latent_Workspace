"""V19 dual-budget window/reference envelope; reuse qualified window arithmetic.

Derived from the V18 split-query window owner with only the native owner,
reader binding, policy and format names replaced. The outer schedule, supplied
reference bank and independent workspace policy are validated before any target
tensor or process RNG publication. Input provenance is still the runner's job.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import torch

from .v15_native_learner import require, restore_rng, tree_hash
from .v18_reference_bank import ReferenceBank
from .v18_window_learner import V18WindowLearner, _objective_terms
from .v18_window_objective import WindowReductionSpec
from .v19_dual_budget_learner import CONTRACT_KEY as WORKSPACE_KEY
from .v19_dual_budget_learner import PAYLOAD_KEYS as INNER_KEYS
from .v19_dual_budget_learner import DualBudgetNativeLearner, validate_workspace_policy
from .v19_dual_budget_pipeline import DualBudgetWorkspacePipeline
from .v19_dual_budget_state import DualBudgetStateBinding

FORMAT = "v19-dual-budget-window-reference-resume-v1"
CONTRACT_KEY = "v19_dual_budget_window_reference"
PAYLOAD_KEYS = {"format", "policy", "schedule", "reference_bank", "inner"}


def _policy(binding, bridge, workspace_policy, schedule, bank, eos_weight,
            eos_token_id, run_contract):
    validate_workspace_policy(workspace_policy)
    require(type(run_contract) is dict
            and CONTRACT_KEY not in run_contract and "v18_window_reference" not in run_contract,
            "Independent base run contract without an outer envelope required")
    require(tree_hash(run_contract.get(WORKSPACE_KEY)) == tree_hash(workspace_policy),
            "Independent V19 workspace policy/run contract mismatch")
    require(type(schedule) is tuple and bool(schedule)
            and all(type(spec) is WindowReductionSpec for spec in schedule),
            "Nonempty immutable exact window schedule required")
    require(len({spec.window_id for spec in schedule}) == len(schedule), "Duplicate window ID")
    require(type(eos_weight) in (int, float) and math.isfinite(eos_weight) and eos_weight >= 0,
            "Finite nonnegative EOS weight")
    require(type(eos_token_id) is int and 0 <= eos_token_id < binding.base.config.vocab_size,
            "EOS token outside native vocabulary")
    _objective_terms(run_contract, eos_weight)
    binding.validate()
    reader = DualBudgetStateBinding(
        bridge, DualBudgetWorkspacePipeline(bridge, binding.readout,
                                          workspace_policy["workspace_query"]),
    ).describe()
    if bank is not None:
        require(type(bank) is ReferenceBank, "Exact immutable reference bank required")
        require(tree_hash(run_contract.get("reference_source"))
                == tree_hash(dict(bank.source._asdict())),
                "Reference model/tokenizer source mismatch")
        require(bank.source.model_content_sha256 == run_contract.get("original_base_sha256")
                and bank.source.execution_policy_sha256 == tree_hash(binding.describe()),
                "Reference source/native execution identity mismatch")
        require(bank.vocab_size == binding.base.config.vocab_size,
                "Reference vocabulary mismatch")
        require({str(p.dtype).removeprefix("torch.") for p in binding.base.parameters()}
                == {bank.capture_policy.native_dtype}, "Reference native dtype mismatch")
    return {
        "schema": FORMAT,
        "workspace_policy": copy.deepcopy(workspace_policy),
        "schedule": [spec.descriptor() for spec in schedule],
        "reference": None if bank is None else bank.descriptor_payload(),
        "reference_role": "reference_only_no_preservation_loss",
        "eos_weight": float(eos_weight),
        "eos_token_id": eos_token_id,
        "reader_guard": reader,
        "input_identity": "caller-declared-data-and-tokenizer-hashes-not-independent-capture-proof",
    }


class V19DualBudgetWindowLearner(V18WindowLearner):
    """Own the new envelope; inherit only unchanged complete-window operations."""

    def __init__(self, binding, bridge, *, workspace_policy, full_update,
                 optimizer_config, run_contract, schedule, reference_bank=None,
                 eos_weight=0.0, eos_token_id=2):
        require(type(self) is V19DualBudgetWindowLearner, "Exact V19 window owner required")
        policy = _policy(binding, bridge, workspace_policy, schedule, reference_bank,
                         eos_weight, eos_token_id, run_contract)
        bound = copy.deepcopy(run_contract)
        bound[CONTRACT_KEY] = copy.deepcopy(policy)
        inner = DualBudgetNativeLearner(
            binding, bridge, workspace_policy=workspace_policy, full_update=full_update,
            optimizer_config=optimizer_config, run_contract=bound,
        )
        self._attach(inner, run_contract, schedule, reference_bank, policy, inner.reader_binding)

    def _validate(self):
        require(type(self._inner) is DualBudgetNativeLearner and id(self._inner) == self._inner_id,
                "V19 native owner replaced")
        self._inner._validate_ownership()
        require(self._guard is self._inner.reader_binding
                and tree_hash(self._guard.describe()) == tree_hash(self._policy["reader_guard"]),
                "V19 reader guard changed")
        require(tree_hash(self._policy) == self._policy_hash, "V19 window policy mutated")
        require(type(self._schedule) is tuple
                and all(type(spec) is WindowReductionSpec for spec in self._schedule)
                and [spec.descriptor() for spec in self._schedule] == self._policy["schedule"],
                "V19 window schedule changed")
        require((None if self._bank is None else self._bank.descriptor_payload())
                == self._policy["reference"], "Reference bank changed")
        bound = copy.deepcopy(self._base_contract)
        bound[CONTRACT_KEY] = self._policy
        require(tree_hash(self._inner.run_contract) == tree_hash(bound)
                and tree_hash(self._inner.workspace_policy)
                == tree_hash(self._policy["workspace_policy"]),
                "V19 window/base run contract changed")
        require(type(self.completed_steps) is int
                and self.completed_steps == self._expected_steps
                and 0 <= self.completed_steps <= len(self._schedule),
                "Unexpected V19 schedule step/cursor")
        if self._active:
            require(id(self._inner.window) == self._window_id
                    and self._inner.keys == self.current_spec.ids
                    and self._inner.cursor == self._cursor,
                    "Window identity/order changed outside V19 owner")
        else:
            require(self._inner.window is None and self._inner.keys == ()
                    and self._inner.cursor == 0, "Unowned active V19 window")

    def payload(self, metadata):
        self._validate()
        require(not self._active, "Save only at complete-window boundary")
        return {
            "format": FORMAT,
            "policy": copy.deepcopy(self._policy),
            "schedule": [spec.payload() for spec in self._schedule],
            "reference_bank": None if self._bank is None else self._bank.snapshot(),
            "inner": self._inner.payload(metadata),
        }

    def save(self, path, metadata):
        path = Path(path)
        payload = self.payload(metadata)
        with path.open("xb") as stream:
            torch.save(payload, stream)
        return {"path": path.name, "bytes": path.stat().st_size,
                "state_sha256": tree_hash(payload), "completed_steps": self.completed_steps,
                "format": FORMAT}

    @classmethod
    def restore(cls, binding, bridge, payload, *, expected_workspace_policy,
                expected_metadata, expected_run_contract, expected_schedule,
                expected_state_sha256, expected_reference_bank=None,
                eos_weight=0.0, eos_token_id=2):
        try:
            require(cls is V19DualBudgetWindowLearner, "Exact V19 window owner required")
            require(type(payload) is dict and set(payload) == PAYLOAD_KEYS
                    and payload["format"] == FORMAT, "V19 window checkpoint format/keys")
            require(tree_hash(payload) == expected_state_sha256,
                    "V19 window content receipt mismatch")
            policy = _policy(binding, bridge, expected_workspace_policy, expected_schedule,
                             expected_reference_bank, eos_weight, eos_token_id,
                             expected_run_contract)
            require(type(payload["schedule"]) is list, "Schedule payload type")
            schedule = tuple(WindowReductionSpec.from_payload(row) for row in payload["schedule"])
            bank = (None if payload["reference_bank"] is None
                    else ReferenceBank.from_payload(payload["reference_bank"]))
            require(type(payload["policy"]) is dict
                    and tree_hash(payload["policy"]) == tree_hash(policy),
                    "Independent V19 window policy mismatch")
            require(schedule == expected_schedule and bank == expected_reference_bank,
                    "V19 window schedule/reference evidence mismatch")
            bound = copy.deepcopy(expected_run_contract)
            bound[CONTRACT_KEY] = policy
            saved = payload["inner"]
            require(type(saved) is dict and set(saved) == INNER_KEYS,
                    "V19 nested checkpoint field ownership")
            require(tree_hash(saved["run_contract"]) == tree_hash(bound),
                    "Typed V19 run contract mismatch")
            require(type(saved["completed_steps"]) is int
                    and 0 <= saved["completed_steps"] <= len(schedule),
                    "V19 resume schedule cursor")
            # No values or global RNG are published by native preflight.
            inner = DualBudgetNativeLearner._prepare_restore(
                binding, bridge, saved, expected_metadata=expected_metadata,
                expected_run_contract=bound, expected_state_sha256=tree_hash(saved),
            )
            result = cls.__new__(cls)
            result._attach(inner, expected_run_contract, schedule, bank, policy,
                           inner.reader_binding)
        except (
            KeyError, TypeError, IndexError, RuntimeError, OverflowError, AttributeError,
        ) as exc:
            raise ValueError(f"Invalid V19 window checkpoint: {exc}") from exc

        # Same qualified publication order, after all outer and inner checks.
        with torch.no_grad():
            for name, target in bridge.state_dict(keep_vars=True).items():
                target.copy_(saved["bridge"][name], non_blocking=False)
            if inner.full_update:
                for name, native in inner.base_named:
                    native.copy_(inner.masters[name].detach().to(native.dtype), non_blocking=False)
        restore_rng(saved["rng"])
        return result
