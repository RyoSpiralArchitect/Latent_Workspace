"""Synthetic complete-window reductions; no real-model quality qualification."""

import copy
import hashlib
import inspect
import json
import os
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
import torch
from test_v15_native_learner import CONTRACT, OPT, SPAN, OwnedStore, owner

from latent_workspace_ft_v10 import v18_window_objective as new
from latent_workspace_ft_v10.adapted_pair_objective import adapted_pair_objective
from latent_workspace_ft_v10.adapter_native_learner import AdapterNativeLearner
from latent_workspace_ft_v10.training_binding import MistralTrainingBinding
from latent_workspace_ft_v10.v15_native_learner import tree_hash

DEVICE = os.environ.get("LATENT_SLOT_STATE_TEST_DEVICE", "cpu")


def new_owner(dtype, full, checkpointing):
    original = owner(dtype, full)
    original.base.to(DEVICE)
    original.bridge.to(DEVICE)
    if checkpointing:
        original.base.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
    binding = MistralTrainingBinding(original.base, 1)
    return AdapterNativeLearner(
        binding, original.bridge, full_update=full, optimizer_config=OPT,
        run_contract={
            "original_base_sha256": tree_hash(original.base.state_dict()),
            "objective": {"terms": CONTRACT, "eos_weight": 0.3},
            "data": "synthetic objective parity only",
        },
    )


def write_memory(learner, side):
    ids = (1, 8, 9) if side == 0 else (1, 9, 8) if side == 1 else (1, 10, 11)
    hidden = learner.context(ids)
    return learner.bridge.write_memory(
        hidden, torch.ones(hidden.shape[:2], dtype=torch.long, device=hidden.device),
    )


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def spec(n=16, affected=4):
    rows = tuple((f"pair{i}", 0, int(i < affected)) for i in range(n))
    return new.WindowReductionSpec("window0", rows, "a" * 64)


def rehash(payload):
    payload["sha256"] = hashlib.sha256(json.dumps(
        {key: value for key, value in payload.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def test_historical_counts_and_fresh_json_snapshots():
    value = spec()
    assert value.counts == {
        "answer_terms": 32, "affected_pairs": 4, "unaffected_pairs": 12,
        "unrelated_pairs": 16, "residual_terms": 48,
    }
    assert value.ids == tuple(f"pair{i}" for i in range(16))
    assert value.labels_for("pair0") == (0, 1)
    assert value.labels_for("pair4") == (0, 0)
    original = value.payload()
    assert new.WindowReductionSpec.from_payload(json.loads(json.dumps(original))) == value
    assert value.descriptor() == original
    value.counts["answer_terms"] = 900
    edited = value.descriptor()
    edited["counts"]["answer_terms"] = 900
    edited["occurrences"][0][1] = 1
    assert value.payload() == original
    with pytest.raises(FrozenInstanceError):
        value.window_id = "changed"
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize("field,bad", [
    ("window_id", ""), ("window_id", " padded"), ("window_id", True),
    ("window_id", "line\nfeed"), ("window_id", "\ud800"),
    ("data_sha256", "a" * 63), ("data_sha256", "A" * 64),
    ("data_sha256", "g" * 64), ("data_sha256", 1),
    ("occurrences", []), ("occurrences", ()),
    ("occurrences", (("one", 0, 1),)),
    ("occurrences", (("one", 0, 0),)),
    ("occurrences", (["one", 0, 1], ("two", 0, 0))),
    ("occurrences", (("same", 0, 1), ("same", 0, 0))),
    ("occurrences", (("one", True, 1), ("two", 0, 0))),
    ("occurrences", (("one", 0.0, 1), ("two", 0, 0))),
    ("occurrences", (("one", 0, 2), ("two", 0, 0))),
    ("occurrences", (("one", 0, 1, 1), ("two", 0, 0))),
    ("occurrences", ((1, 0, 1), ("two", 0, 0))),
])
def test_invalid_construction_is_closed(field, bad):
    kwargs = dict(window_id="window0", occurrences=spec(2, 1).occurrences, data_sha256="a" * 64)
    kwargs[field] = bad
    with pytest.raises(ValueError):
        new.WindowReductionSpec(**kwargs)


@pytest.mark.parametrize("failure", [
    "extra", "missing", "schema", "reduction", "outer_tuple", "inner_tuple",
    "count_wrong", "count_extra", "count_missing", "count_bool", "count_float",
    "hash_wrong", "hash_upper", "order_stale_hash", "data_stale_hash", "row_bool",
])
def test_exact_payload_schema_rejects_corruption_even_rehashed_counts(failure):
    payload = spec().payload()
    if failure == "extra":
        payload["unused"] = 1
    elif failure == "missing":
        del payload["counts"]
    elif failure == "schema":
        payload["schema"] = "old"
    elif failure == "reduction":
        payload["reduction"] = "divide-by-successful-rows"
    elif failure == "outer_tuple":
        payload["occurrences"] = tuple(payload["occurrences"])
    elif failure == "inner_tuple":
        payload["occurrences"][0] = tuple(payload["occurrences"][0])
    elif failure.startswith("count_"):
        if failure == "count_extra":
            payload["counts"]["extra"] = 1
        elif failure == "count_missing":
            del payload["counts"]["answer_terms"]
        else:
            payload["counts"]["answer_terms"] = {
                "count_wrong": 31, "count_bool": True, "count_float": 32.0,
            }[failure]
        rehash(payload)
    elif failure == "hash_wrong":
        payload["sha256"] = "0" * 64
    elif failure == "hash_upper":
        payload["sha256"] = payload["sha256"].upper()
    elif failure == "order_stale_hash":
        payload["occurrences"].reverse()
    elif failure == "data_stale_hash":
        payload["data_sha256"] = "b" * 64
    elif failure == "row_bool":
        payload["occurrences"][0][1] = False
        rehash(payload)
    with pytest.raises(ValueError):
        new.WindowReductionSpec.from_payload(payload)


def test_payload_aliases_are_not_retained_and_identity_binds_order_labels_data():
    payload = spec().payload()
    restored = new.WindowReductionSpec.from_payload(payload)
    payload["occurrences"][0][0] = "edited"
    payload["counts"]["affected_pairs"] = 1
    assert restored == spec()
    original = spec().payload()["sha256"]
    for changed in (
        new.WindowReductionSpec("window1", spec().occurrences, "a" * 64),
        new.WindowReductionSpec("window0", spec().occurrences[::-1], "a" * 64),
        new.WindowReductionSpec("window0", spec().occurrences, "b" * 64),
        new.WindowReductionSpec(
            "window0", (("pair0", 1, 0),) + spec().occurrences[1:], "a" * 64,
        ),
    ):
        assert changed.payload()["sha256"] != original


def test_boundary_revalidates_and_rejects_missing_occurrence_before_forward():
    value = spec()
    with pytest.raises(ValueError, match="not in"):
        value.labels_for("not-present")
    with pytest.raises(ValueError):
        value.labels_for(True)
    object.__setattr__(value, "occurrences", (("bad", True, 1),))
    for fn in (value.validate, value.payload, value.descriptor, lambda: value.ids):
        with pytest.raises(ValueError):
            fn()
    kwargs = dict(
        spec=spec(), occurrence_id="not-present", prefix_ids=(1,), span=None,
        candidate_ids=(6, 7), contract=CONTRACT,
    )
    with pytest.raises(ValueError, match="not in"):
        new.reduced_pair_objective(None, None, **kwargs)
    kwargs.update(spec={}, occurrence_id="pair0")
    with pytest.raises(ValueError, match="exact"):
        new.reduced_pair_objective(None, None, **kwargs)
    assert "labels" not in inspect.signature(new.reduced_pair_objective).parameters
    assert "donor" not in inspect.signature(new.reduced_pair_objective).parameters


class ScalarPipeline:
    """Independent differentiable numerator fixture and exact call-order spy."""

    def __init__(self, theta):
        self.theta, self.events, self.adapter = theta, [], self

    @contextmanager
    def objective(self):
        self.events.append("open")
        yield self
        self.events.append("close")

    def prepare(self, prefix):
        self.events.append(("prepare", prefix))

    def output(self, gap, delta):
        scores = torch.stack((self.theta * 0, self.theta * gap))[None]
        return SimpleNamespace(
            readout=SimpleNamespace(choice_scores=lambda _: scores),
            delta=(self.theta * delta).reshape(1, 1, 1),
        )

    def read(self, prefix, residual):
        self.events.append(("base", prefix))
        assert not torch.is_grad_enabled()
        assert not residual(torch.ones(1, 1, 1)).count_nonzero()
        return self.output(3, 0)

    def __call__(self, prefix, memory, mask, *, span):
        self.events.append(("unrelated", prefix, memory, mask, span))
        return self.output(5, 3)

    def write(self, side):
        self.events.append(("write", side))
        return side, "mask"


def scalar_answer_terms(pipeline, memory, mask, **kwargs):
    pipeline.events.append(("answer", memory, mask, copy.deepcopy(kwargs)))
    return SimpleNamespace(
        answer_ce=pipeline.theta * (memory + 2),
        eos_ce=pipeline.theta * (memory + 5),
        answer_output=pipeline.output(memory + 1, memory + 1),
    )


@pytest.mark.parametrize("n,affected", [(2, 1), (7, 2), (16, 4), (37, 11)])
def test_general_window_denominators_against_independent_scalar_oracle(monkeypatch, n, affected):
    monkeypatch.setattr(new, "adapted_answer_terms", scalar_answer_terms)
    window = spec(n, affected)
    theta = torch.tensor(0.5, dtype=torch.float64, requires_grad=True)
    reference = theta.detach().clone().requires_grad_()
    pipe = ScalarPipeline(theta)
    total, component_sums = theta * 0, {}
    contract = {**CONTRACT, "donor_margin": 2.0}
    for identifier, label0, label1 in window.occurrences:
        loss, components = new.reduced_pair_objective(
            pipe, pipe.write, spec=window, occurrence_id=identifier, prefix_ids=(1, 4),
            span="span", candidate_ids=(6, 7), contract=contract, eos_weight=0.3,
        )
        expected = {
            "answer_ce": 5 * reference / (2 * n),
            "eos_ce": 11 * reference / (2 * n),
            "donor_hinge": (
                (2 - reference).relu() / affected if label0 != label1 else reference * 0
            ),
            "unaffected_gap_square": (
                reference.square() / (n - affected) if label0 == label1 else reference * 0
            ),
            "unrelated_gap_square": (5 * reference - 3 * reference.detach()).square() / n,
            "residual_norm_square": 14 * reference.square() / (3 * n),
        }
        for name, value in components.items():
            torch.testing.assert_close(value, expected[name], rtol=1e-14, atol=1e-14)
            component_sums[name] = component_sums.get(name, theta * 0) + value
        total = total + loss
    independent = (
        2.5 * reference + 0.3 * 5.5 * reference
        + contract["direction_weight"] * (2 - reference).relu()
        + contract["stability_weight"] * reference.square()
        + contract["unrelated_weight"] * (5 * reference - 3 * reference.detach()).square()
        + contract["residual_penalty"] * 14 * reference.square() / 3
    )
    torch.testing.assert_close(total, independent, rtol=1e-14, atol=1e-14)
    total.backward()
    independent.backward()
    torch.testing.assert_close(theta.grad, reference.grad, rtol=1e-14, atol=1e-14)
    assert pipe.events[:5] == [
        "open", ("prepare", (1, 4)), ("write", 0), ("prepare", (1, 4, 6)),
        ("answer", 0, "mask", {
            "prefix_ids": (1, 4), "completion_prefix_ids": (1, 4, 6), "span": "span",
            "answer_token_id": 6, "eos_token_id": 2,
        }),
    ]
    assert [event[1] for event in pipe.events if event[0] == "write"] == [0, 1, "unrelated"] * n


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("checkpointing", [False, True])
@pytest.mark.parametrize("query", [0, 2])
def test_historical_pair_components_and_all_gradients_exact(dtype, full, checkpointing, query):
    legacy, candidate = new_owner(dtype, full, checkpointing), new_owner(dtype, full, checkpointing)
    labels = [OwnedStore(legacy).records[0]["answers"][side][query] for side in (0, 1)]
    occurrence_id = "pair0" if query == 0 else "pair4"
    results = []
    for learner, historical in ((legacy, True), (candidate, False)):
        kwargs = dict(
            prefix_ids=SPAN.prefix_ids, span=SPAN, candidate_ids=(6, 7),
            contract=CONTRACT, eos_weight=0.3,
        )
        if historical:
            results.append(adapted_pair_objective(
                learner.pipeline, lambda side: write_memory(learner, side),
                labels=labels, **kwargs,
            ))
        else:
            results.append(new.reduced_pair_objective(
                learner.pipeline, lambda side: write_memory(learner, side),
                spec=spec(), occurrence_id=occurrence_id, **kwargs,
            ))
    (left, left_parts), (right, right_parts) = results
    assert torch.equal(left, right)
    assert left_parts.keys() == right_parts.keys()
    for name in left_parts:
        assert torch.equal(left_parts[name], right_parts[name]), name
    left.backward()
    right.backward()
    for (name, a), (other_name, b) in zip(legacy.named, candidate.named, strict=True):
        assert name == other_name and a.grad is not None and b.grad is not None
        assert torch.equal(a.grad, b.grad), name
