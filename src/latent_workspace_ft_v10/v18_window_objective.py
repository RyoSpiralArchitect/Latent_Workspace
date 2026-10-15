"""Complete-window reductions without changing the historical paired forward.

The declared data hash identifies caller-supplied data; this contract does not
prove that those data were captured, disjoint, or semantically correct. Counts
come from the whole ordered window before any backward, never successful rows.
Both affected and unaffected strata are required by this initial version.
Window completion and checkpoint ownership belong to the learner, not this
single-occurrence objective. No preservation loss is introduced here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

import torch
from torch.nn import functional as F

from .adapted_workspace import adapted_answer_terms

SCHEMA = "v18-complete-window-reduction-v1"
REDUCTION = "sum-in-declared-order-divided-by-complete-family-count"
_COUNT_KEYS = (
    "answer_terms", "affected_pairs", "unaffected_pairs", "unrelated_pairs", "residual_terms",
)
_PAYLOAD_KEYS = {
    "schema", "reduction", "window_id", "occurrences", "data_sha256", "counts", "sha256",
}


def _text(value, name):
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"Invalid {name}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"Invalid {name}: not UTF-8 encodable") from error


def _sha(value, name):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Invalid {name}: expected lowercase SHA256")


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class WindowReductionSpec:
    """Immutable primitive inputs; all exported containers are fresh snapshots."""

    window_id: str
    occurrences: tuple[tuple[str, int, int], ...]
    data_sha256: str

    def __post_init__(self):
        self.validate()

    def validate(self):
        if type(self) is not WindowReductionSpec:
            raise ValueError("Expected exact WindowReductionSpec type")
        _text(self.window_id, "window ID")
        _sha(self.data_sha256, "data hash")
        if type(self.occurrences) is not tuple or not self.occurrences:
            raise ValueError("Expected a nonempty immutable occurrence tuple")
        seen, affected = set(), 0
        for row in self.occurrences:
            if type(row) is not tuple or len(row) != 3:
                raise ValueError("Expected (occurrence_id, label0, label1) tuples")
            identifier, label0, label1 = row
            _text(identifier, "occurrence ID")
            if identifier in seen:
                raise ValueError("Duplicate occurrence ID")
            seen.add(identifier)
            if any(type(label) is not int or label not in (0, 1) for label in row[1:]):
                raise ValueError("Expected two primitive binary labels")
            affected += label0 != label1
        if affected == 0 or affected == len(self.occurrences):
            raise ValueError("Both affected and unaffected strata are required")

    @property
    def ids(self):
        self.validate()
        return tuple(row[0] for row in self.occurrences)

    @property
    def counts(self):
        self.validate()
        n = len(self.occurrences)
        affected = sum(row[1] != row[2] for row in self.occurrences)
        return {
            "answer_terms": 2 * n,
            "affected_pairs": affected,
            "unaffected_pairs": n - affected,
            "unrelated_pairs": n,
            "residual_terms": 3 * n,
        }

    def labels_for(self, occurrence_id):
        self.validate()
        _text(occurrence_id, "occurrence ID")
        for identifier, label0, label1 in self.occurrences:
            if identifier == occurrence_id:
                return label0, label1
        raise ValueError("Occurrence is not in the complete window")

    def payload(self):
        self.validate()
        result = {
            "schema": SCHEMA,
            "reduction": REDUCTION,
            "window_id": self.window_id,
            "occurrences": [list(row) for row in self.occurrences],
            "data_sha256": self.data_sha256,
            "counts": self.counts,
        }
        result["sha256"] = _digest(result)
        return result

    def descriptor(self):
        """Fresh complete identity, including label order and reduction policy."""
        return self.payload()

    @classmethod
    def from_payload(cls, payload):
        if cls is not WindowReductionSpec:
            raise ValueError("Expected exact WindowReductionSpec type")
        if (
            type(payload) is not dict
            or any(type(key) is not str for key in payload)
            or set(payload) != _PAYLOAD_KEYS
        ):
            raise ValueError("Invalid window payload schema")
        if type(payload["schema"]) is not str or payload["schema"] != SCHEMA:
            raise ValueError("Invalid window schema version")
        if type(payload["reduction"]) is not str or payload["reduction"] != REDUCTION:
            raise ValueError("Invalid window reduction policy")
        rows = payload["occurrences"]
        if type(rows) is not list or any(type(row) is not list for row in rows):
            raise ValueError("Window occurrences must be JSON arrays")
        result = cls(
            payload["window_id"], tuple(tuple(row) for row in rows), payload["data_sha256"],
        )
        counts = payload["counts"]
        if (
            type(counts) is not dict
            or any(type(key) is not str for key in counts)
            or set(counts) != set(_COUNT_KEYS)
            or any(type(value) is not int or value <= 0 for value in counts.values())
            or counts != result.counts
        ):
            raise ValueError("Counts do not match the complete window")
        _sha(payload["sha256"], "window hash")
        if payload["sha256"] != result.payload()["sha256"]:
            raise ValueError("Window hash mismatch")
        return result


def reduced_pair_objective(
    pipeline,
    write_memory,
    *,
    spec,
    occurrence_id,
    prefix_ids,
    span,
    candidate_ids,
    contract,
    eos_weight=0.0,
    eos_token_id=2,
):
    """Historical graph/order, with only complete-window denominators replaced.

    Labels are selected solely from the immutable occurrence. They choose the
    loss and teacher-forced completion; writer/answer reader inputs gain no
    label, donor, or occurrence argument.
    """
    if type(spec) is not WindowReductionSpec:
        raise ValueError("Expected exact WindowReductionSpec type")
    labels, counts = spec.labels_for(occurrence_id), spec.counts
    if (
        len(candidate_ids) != 2
        or len(labels) != 2
        or any(type(v) is not int or v not in (0, 1) for v in labels)
    ):
        raise ValueError("Two binary labels and candidates required by paired objective")
    adapter = pipeline.adapter
    # Preserve the sealed objective's preparation and arithmetic order exactly.
    with adapter.objective() as graphs:
        graphs.prepare(prefix_ids)
        terms = []
        for side, label in enumerate(labels):
            memory, mask = write_memory(side)
            token = candidate_ids[label]
            graphs.prepare(prefix_ids + (token,))
            terms.append(
                adapted_answer_terms(
                    pipeline,
                    memory,
                    mask,
                    prefix_ids=prefix_ids,
                    completion_prefix_ids=prefix_ids + (token,),
                    span=span,
                    answer_token_id=token,
                    eos_token_id=eos_token_id,
                )
            )
        memory, mask = write_memory("unrelated")
        unrelated = pipeline(prefix_ids, memory, mask, span=span)
        with torch.no_grad():
            baseline = adapter.read(prefix_ids, lambda h: torch.zeros_like(h[:, -1:]).float())
        scores = [t.answer_output.readout.choice_scores(candidate_ids)[0] for t in terms]
        gap = [v[1] - v[0] for v in scores]
        difference = gap[1] - gap[0]
        donor = (2 * labels[1] - 1) * difference
        other = unrelated.readout.choice_scores(candidate_ids)[0]
        base = baseline.readout.choice_scores(candidate_ids)[0]
        affected, zero = labels[0] != labels[1], difference * 0
        components = {
            "answer_ce": (terms[0].answer_ce + terms[1].answer_ce) / counts["answer_terms"],
            "eos_ce": (terms[0].eos_ce + terms[1].eos_ce) / counts["answer_terms"],
            "donor_hinge": (
                F.relu(contract["donor_margin"] - donor) / counts["affected_pairs"]
                if affected else zero
            ),
            "unaffected_gap_square": (
                difference.square() / counts["unaffected_pairs"] if not affected else zero
            ),
            "unrelated_gap_square": (
                ((other[1] - other[0]) - (base[1] - base[0])).square()
                / counts["unrelated_pairs"]
            ),
            "residual_norm_square": sum(
                out.delta.square().sum()
                for out in (terms[0].answer_output, terms[1].answer_output, unrelated)
            )
            / counts["residual_terms"],
        }
        total = (
            components["answer_ce"]
            + eos_weight * components["eos_ce"]
            + contract["direction_weight"] * components["donor_hinge"]
            + contract["stability_weight"] * components["unaffected_gap_square"]
            + contract["unrelated_weight"] * components["unrelated_gap_square"]
            + contract["residual_penalty"] * components["residual_norm_square"]
        )
    return total, components
