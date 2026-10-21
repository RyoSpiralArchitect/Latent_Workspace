"""Analysis arithmetic regressions; not the frozen 216-case GPU qualification."""

import importlib.util
import itertools
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "state_publication", Path(__file__).with_name("summarize.py")
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class PublicationChecks(unittest.TestCase):
    def test_loss_and_repair_not_net_accuracy(self):
        value = REPORT.paired(dict(a=True, b=False), dict(a=False, b=True))
        self.assertEqual(value, dict(n=2, left_correct=1, right_correct=1, repairs=1, losses=1))
        with self.assertRaisesRegex(ValueError, "coverage"):
            REPORT.paired(dict(a=True), dict(b=True))

    def test_full_factorial_retains_interactions(self):
        cells = {}
        for w, q, r in itertools.product((0, 1), repeat=3):
            names = tuple("v22" if bit else "base" for bit in (w, q, r))
            value = -30 + w + 2 * q + 4 * r + 3 * w * q + 5 * w * r + 6 * q * r + 7 * w * q * r
            cells["world", "id", 0, *names] = dict(
                id="id",
                index=0,
                donor_token=None,
                score=dict(correct=bool(q), top1=5 if q else 6, gold_logprob=value),
            )
        for q, r in itertools.product((0, 1), repeat=2):
            cells["mmlu", "m1", 0, "none", "v22" if q else "base", "v22" if r else "base"] = dict(
                score=dict(prediction=q, correct=bool(q), strict_correct=bool(q), ties=1)
            )
        result = REPORT.aggregate(
            cells, dict(id=dict(answer="Nx.", answer_ids=[5, 6, 2], mode="unaffected"))
        )
        effects = result["token_weighted_logprob_interactions"]
        self.assertEqual(
            {k: v["mean"] for k, v in effects.items()}, dict(W=1, Q=2, R=4, WQ=3, WR=5, QR=6, WQR=7)
        )
        self.assertEqual(len(result["world_cells"]), 8)
        self.assertEqual(len(result["mmlu_cells"]), 4)

    def test_token_key_keeps_exact_order_and_extent(self):
        self.assertNotEqual(REPORT.token_key([1, 2]), REPORT.token_key([2, 1]))
        self.assertNotEqual(REPORT.token_key([1, 2]), REPORT.token_key([1, 2, 0]))


if __name__ == "__main__":
    unittest.main()
