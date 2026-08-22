from __future__ import annotations

import importlib
import sys
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

gate = importlib.import_module("run_v12_noop_gate")


def test_bitwise_equal_distinguishes_signed_zero() -> None:
    positive = torch.tensor(0.0, dtype=torch.float32)
    negative = torch.tensor(-0.0, dtype=torch.float32)
    assert torch.equal(positive, negative)
    assert gate.bitwise_equal(positive, negative) is False
    assert gate.bitwise_equal(positive, positive.clone()) is True


def test_noop_checks_fail_closed_and_require_complete_eval() -> None:
    checks = gate.build_checks(
        expected_cases=1024,
        observed_cases=1023,
        full_logits_bitwise=True,
        choice_logits_bitwise=True,
        predictions_exact=True,
        metrics_exact=True,
        zero_delta=True,
        initialized_zero=True,
    )
    failed = [row["id"] for row in checks if not row["passed"]]
    assert failed == ["complete_eval_cases"]

    checks = gate.build_checks(
        expected_cases=1024,
        observed_cases=1024,
        full_logits_bitwise=True,
        choice_logits_bitwise=False,
        predictions_exact=True,
        metrics_exact=True,
        zero_delta=True,
        initialized_zero=True,
    )
    failed = [row["id"] for row in checks if not row["passed"]]
    assert failed == ["choice_logits_bitwise", "routed_amputated_exact"]
