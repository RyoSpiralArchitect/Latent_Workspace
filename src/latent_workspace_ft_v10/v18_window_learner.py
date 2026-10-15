"""Additive complete-window and reference ownership over qualified native owners.

This does not introduce a new optimizer, preservation loss, or slot mechanism.
The bank is immutable supplied evidence, not proof of original-model capture.
Restore validates all external contracts before publishing any target tensor or
global RNG state. Publication requires exclusive ownership and a healthy device;
it is not a transaction against process death or out-of-band concurrent writes.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import torch

from .adapter_native_learner_v2 import AdapterNativeLearnerV2
from .precision_bridge import PrecisionAwareWorkspaceBridge
from .query_modulated_bridge import QueryModulatedWorkspaceBridge
from .slot_contrast_learner import PAYLOAD_KEYS as INNER_KEYS
from .slot_contrast_learner import SlotContrastNativeLearner
from .slot_contrast_state import _SOURCES, _structure, storage_keys
from .v15_native_learner import reader_descriptor, require, restore_rng, tree_hash
from .v16_slot_contrast import SlotContrastWorkspaceBridge
from .v18_reference_bank import ReferenceBank
from .v18_window_objective import WindowReductionSpec, reduced_pair_objective

FORMAT = "v18-window-reference-resume-v1"
CONTRACT_KEY = "v18_window_reference"
PAYLOAD_KEYS = {"format", "policy", "schedule", "reference_bank", "inner"}


class _ReaderGuard:
    """Canonical reader policy and storage, including the historical common arm."""

    def __init__(self, bridge):
        require(
            type(bridge)
            in (
                PrecisionAwareWorkspaceBridge,
                QueryModulatedWorkspaceBridge,
                SlotContrastWorkspaceBridge,
            ),
            "Unqualified reader class",
        )
        common = bridge.common if type(bridge) is SlotContrastWorkspaceBridge else bridge
        descriptor = reader_descriptor(common)
        with torch.device("meta"):
            template = type(common)(
                descriptor["hidden_dim"],
                descriptor["workspace_dim"],
                descriptor["heads"],
                descriptor["slots"],
                descriptor["cap"],
                **(
                    {"modulation_strength": descriptor["strength"]}
                    if type(common) is QueryModulatedWorkspaceBridge
                    else {}
                ),
            )
            if type(bridge) is SlotContrastWorkspaceBridge:
                template = SlotContrastWorkspaceBridge(
                    template,
                    mode=bridge.mode,
                    interaction_fraction=bridge.interaction_fraction,
                )
        structure = _structure(bridge)
        require(structure == _structure(template), "Noncanonical V18 reader graph/policy")
        self.bridge = bridge
        self.structure = copy.deepcopy(structure)
        self.modules = [(n, id(m)) for n, m in bridge.named_modules(remove_duplicate=False)]
        self.parameters = [(n, id(p)) for n, p in bridge.named_parameters()]
        self.storage = storage_keys(bridge.parameters())
        require(len(set(self.storage)) == len(self.storage), "Shared reader storage")
        self.descriptor = {
            "schema": "v18-canonical-reader-guard-v1",
            "structure": structure,
            "implementation_sha256": copy.deepcopy(_SOURCES),
            "torch_version": str(torch.__version__),
        }
        self.digest = tree_hash(self.descriptor)

    def validate(self, bridge, base):
        require(bridge is self.bridge, "Reader object changed")
        require(tree_hash(self.descriptor) == self.digest, "Reader guard descriptor changed")
        require(self.structure == self.descriptor["structure"], "Reader guard structure changed")
        require(
            [(n, id(m)) for n, m in bridge.named_modules(remove_duplicate=False)] == self.modules
            and [(n, id(p)) for n, p in bridge.named_parameters()] == self.parameters
            and storage_keys(bridge.parameters()) == self.storage,
            "Reader module/parameter/storage replacement",
        )
        require(_structure(bridge) == self.structure, "Reader execution policy changed")
        require(
            not (set(storage_keys(base.parameters())) & set(self.storage)),
            "Cross-owned native/reader storage",
        )


def _objective_terms(run_contract, eos_weight):
    objective = run_contract.get("objective")
    require(type(objective) is dict, "Explicit objective contract required")
    if "terms" in objective:
        require(
            set(objective) == {"terms", "eos_weight", "query_mode"}
            and objective["query_mode"] == "final"
            and type(objective["eos_weight"]) in (int, float)
            and objective["eos_weight"] == eos_weight,
            "Nested objective/EOS/query policy mismatch",
        )
        objective = objective["terms"]
    require(type(objective) is dict, "Objective terms must be a mapping")
    for name in (
        "donor_margin",
        "direction_weight",
        "stability_weight",
        "unrelated_weight",
        "residual_penalty",
    ):
        value = objective.get(name)
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"Finite nonnegative objective term required: {name}",
        )
    return objective


def _policy(binding, bridge, schedule, bank, eos_weight, eos_token_id, run_contract):
    require(type(schedule) is tuple and bool(schedule), "Nonempty immutable schedule required")
    require(all(type(spec) is WindowReductionSpec for spec in schedule), "Window spec type")
    windows = [spec.descriptor() for spec in schedule]
    require(len({spec.window_id for spec in schedule}) == len(schedule), "Duplicate window ID")
    require(
        type(eos_weight) in (int, float) and math.isfinite(eos_weight) and eos_weight >= 0,
        "Finite nonnegative EOS weight",
    )
    require(
        type(eos_token_id) is int and 0 <= eos_token_id < binding.base.config.vocab_size,
        "EOS token outside native vocabulary",
    )
    require(type(run_contract) is dict and CONTRACT_KEY not in run_contract, "Base run contract")
    _objective_terms(run_contract, eos_weight)
    guard = _ReaderGuard(bridge)
    guard.validate(bridge, binding.base)
    if bank is not None:
        require(type(bank) is ReferenceBank, "Exact immutable reference bank required")
        require(
            tree_hash(run_contract.get("reference_source"))
            == tree_hash(dict(bank.source._asdict())),
            "Reference model revision/tokenizer must match the explicit run source",
        )
        require(
            bank.source.model_content_sha256 == run_contract.get("original_base_sha256")
            and bank.source.execution_policy_sha256 == tree_hash(binding.describe()),
            "Reference source does not match original/native execution identity",
        )
        require(bank.vocab_size == binding.base.config.vocab_size, "Reference vocabulary mismatch")
        require(
            {str(p.dtype).removeprefix("torch.") for p in binding.base.parameters()}
            == {bank.capture_policy.native_dtype},
            "Reference capture/native dtype mismatch",
        )
    return {
        "schema": FORMAT,
        "schedule": windows,
        "reference": None if bank is None else bank.descriptor_payload(),
        "reference_role": "reference_only_no_preservation_loss",
        "eos_weight": float(eos_weight),
        "eos_token_id": eos_token_id,
        "reader_guard": copy.deepcopy(guard.descriptor),
        "input_identity": "caller-declared-data-and-tokenizer-hashes-not-independent-capture-proof",
    }, guard


def _owner_class(bridge):
    return (
        SlotContrastNativeLearner
        if type(bridge) is SlotContrastWorkspaceBridge
        else AdapterNativeLearnerV2
    )


class V18WindowLearner:
    """Own the ordered objective schedule; retain legacy update arithmetic exactly.

    ``inner`` is exposed for diagnostics, not as an alternate mutation API.
    Bypassing this owner invalidates its cursor checks. Input hashes and the
    declared original-reference provenance remain the caller's responsibility.
    """

    def __init__(
        self,
        binding,
        bridge,
        *,
        full_update,
        optimizer_config,
        run_contract,
        schedule,
        reference_bank=None,
        eos_weight=0.0,
        eos_token_id=2,
    ):
        policy, guard = _policy(
            binding,
            bridge,
            schedule,
            reference_bank,
            eos_weight,
            eos_token_id,
            run_contract,
        )
        bound = copy.deepcopy(run_contract)
        bound[CONTRACT_KEY] = copy.deepcopy(policy)
        inner = _owner_class(bridge)(
            binding,
            bridge,
            full_update=full_update,
            optimizer_config=optimizer_config,
            run_contract=bound,
        )
        self._attach(inner, run_contract, schedule, reference_bank, policy, guard)

    def _attach(self, inner, run_contract, schedule, bank, policy, guard):
        self._inner = inner
        self._inner_id = id(inner)
        self._schedule, self._bank = schedule, bank
        self._base_contract = copy.deepcopy(run_contract)
        self._policy = copy.deepcopy(policy)
        self._policy_hash = tree_hash(policy)
        self._guard = guard
        self._expected_steps = inner.completed_steps
        self._active = False
        self._cursor = 0
        self._window_id = None
        self._validate()

    @property
    def inner(self):
        return self._inner

    @property
    def binding(self):
        return self._inner.binding

    @property
    def base(self):
        return self._inner.base

    @property
    def bridge(self):
        return self._inner.bridge

    @property
    def pipeline(self):
        return self._inner.pipeline

    @property
    def full_update(self):
        return self._inner.full_update

    @property
    def completed_steps(self):
        return self._inner.completed_steps

    @property
    def run_contract(self):
        return copy.deepcopy(self._inner.run_contract)

    @property
    def base_run_contract(self):
        return copy.deepcopy(self._base_contract)

    @property
    def current_spec(self):
        require(self.completed_steps < len(self._schedule), "Declared schedule exhausted")
        return self._schedule[self.completed_steps]

    def _validate(self):
        require(id(self._inner) == self._inner_id, "Native owner replaced")
        self._inner._validate_ownership()
        self._guard.validate(self.bridge, self.base)
        require(tree_hash(self._policy) == self._policy_hash, "V18 policy mutated")
        require(
            type(self._schedule) is tuple
            and [spec.descriptor() for spec in self._schedule] == self._policy["schedule"],
            "Window schedule changed",
        )
        require(
            (None if self._bank is None else self._bank.descriptor_payload())
            == self._policy["reference"],
            "Reference bank changed",
        )
        bound = copy.deepcopy(self._base_contract)
        bound[CONTRACT_KEY] = self._policy
        require(
            tree_hash(self._inner.run_contract) == tree_hash(bound), "V18/base run contract changed"
        )
        require(
            type(self.completed_steps) is int
            and self.completed_steps == self._expected_steps
            and 0 <= self.completed_steps <= len(self._schedule),
            "Unexpected schedule step/cursor",
        )
        if self._active:
            require(
                id(self._inner.window) == self._window_id
                and self._inner.keys == self.current_spec.ids
                and self._inner.cursor == self._cursor,
                "Window identity/order changed outside V18 owner",
            )
        else:
            require(
                self._inner.window is None and self._inner.keys == () and self._inner.cursor == 0,
                "Unowned active window",
            )

    def context(self, ids):
        # Called from the owned objective while its readout graph is active.
        return self._inner.context(ids)

    def begin_window(self):
        self._validate()
        require(not self._active, "Window already active")
        self._inner.begin_window(self.current_spec.ids)
        self._active, self._cursor, self._window_id = True, 0, id(self._inner.window)

    def backward_pair(self, occurrence_id, *, write_memory, prefix_ids, span, candidate_ids):
        self._validate()
        require(
            self._active
            and self._cursor < len(self.current_spec.ids)
            and occurrence_id == self.current_spec.ids[self._cursor],
            "Pair ordering/duplication mismatch",
        )
        loss, components = reduced_pair_objective(
            self.pipeline,
            write_memory,
            spec=self.current_spec,
            occurrence_id=occurrence_id,
            prefix_ids=prefix_ids,
            span=span,
            candidate_ids=candidate_ids,
            contract=_objective_terms(self._inner.run_contract, self._policy["eos_weight"]),
            eos_weight=self._policy["eos_weight"],
            eos_token_id=self._policy["eos_token_id"],
        )
        receipt = self._inner.backward_pair(occurrence_id, loss)
        self._cursor += 1
        return components, receipt

    def step(self):
        self._validate()
        require(
            self._active and self._cursor == len(self.current_spec.ids), "Complete window required"
        )
        receipt = self._inner.step()
        self._expected_steps += 1
        self._active, self._cursor, self._window_id = False, 0, None
        return receipt

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
        return {
            "path": path.name,
            "bytes": path.stat().st_size,
            "state_sha256": tree_hash(payload),
            "completed_steps": self.completed_steps,
            "format": FORMAT,
        }

    @classmethod
    def restore(
        cls,
        binding,
        bridge,
        payload,
        *,
        expected_metadata,
        expected_run_contract,
        expected_schedule,
        expected_state_sha256,
        expected_reference_bank=None,
        eos_weight=0.0,
        eos_token_id=2,
    ):
        try:
            require(cls is V18WindowLearner, "Exact V18 owner required")
            require(type(payload) is dict and set(payload) == PAYLOAD_KEYS, "V18 checkpoint keys")
            require(payload["format"] == FORMAT, "V18 checkpoint format")
            require(
                tree_hash(payload) == expected_state_sha256, "Checkpoint content receipt mismatch"
            )
            require(type(payload["schedule"]) is list, "Schedule payload type")
            schedule = tuple(WindowReductionSpec.from_payload(row) for row in payload["schedule"])
            bank = (
                None
                if payload["reference_bank"] is None
                else ReferenceBank.from_payload(payload["reference_bank"])
            )
            policy, guard = _policy(
                binding,
                bridge,
                expected_schedule,
                expected_reference_bank,
                eos_weight,
                eos_token_id,
                expected_run_contract,
            )
            require(
                type(payload["policy"]) is dict
                and tree_hash(payload["policy"]) == tree_hash(policy),
                "External V18 policy mismatch",
            )
            require(
                schedule == expected_schedule and bank == expected_reference_bank,
                "V18 evidence mismatch",
            )
            bound = copy.deepcopy(expected_run_contract)
            bound[CONTRACT_KEY] = policy
            saved = payload["inner"]
            require(
                type(saved) is dict and set(saved) == INNER_KEYS,
                "Nested checkpoint field ownership",
            )
            require(
                tree_hash(saved["run_contract"]) == tree_hash(bound), "Typed run contract mismatch"
            )
            require(
                type(saved["completed_steps"]) is int
                and 0 <= saved["completed_steps"] <= len(schedule),
                "Resume schedule cursor",
            )
            inner = _owner_class(bridge)._prepare_restore(
                binding,
                bridge,
                saved,
                expected_metadata=expected_metadata,
                expected_run_contract=bound,
                expected_state_sha256=tree_hash(saved),
            )
            result = cls.__new__(cls)
            result._attach(inner, expected_run_contract, schedule, bank, policy, guard)
        except (
            KeyError,
            TypeError,
            IndexError,
            RuntimeError,
            OverflowError,
            AttributeError,
        ) as exc:
            raise ValueError(f"Invalid V18 checkpoint: {exc}") from exc

        # All fallible contract validation is complete. Same publication order as
        # the qualified V2 restore: bridge, native casts, then process RNG.
        with torch.no_grad():
            for name, target in bridge.state_dict(keep_vars=True).items():
                target.copy_(saved["bridge"][name], non_blocking=False)
            if inner.full_update:
                for name, native in inner.base_named:
                    native.copy_(inner.masters[name].detach().to(native.dtype), non_blocking=False)
        restore_rng(saved["rng"])
        return result
