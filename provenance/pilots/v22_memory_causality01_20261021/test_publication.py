"""Offline helper regressions; separate from the frozen 187-case qualification."""

import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "causal_publication", Path(__file__).with_name("summarize.py")
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class PublicationChecks(unittest.TestCase):
    def test_pair_denominators_and_token_identity(self):
        a = {
            "a": dict(exact_match=True, token_ids=[1, 2]),
            "b": dict(exact_match=False, token_ids=[4, 2]),
        }
        b = {
            "a": dict(exact_match=False, token_ids=[3, 2]),
            "b": dict(exact_match=True, token_ids=[4, 2]),
        }
        self.assertEqual(
            REPORT.paired(a, b),
            dict(n=2, left_correct=1, right_correct=1, losses=1, repairs=1, changed_tokens=1),
        )
        with self.assertRaisesRegex(ValueError, "coverage"):
            REPORT.paired(a, {})

    def test_activation_body_and_tensor_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            data = b"\x80\x3f\x00\x40"
            header = json.dumps(
                dict(k=dict(dtype="BF16", shape=[1, 1, 2], data_offsets=[0, 4]))
            ).encode()
            path = folder / "memory_states.safetensors"
            path.write_bytes(struct.pack("<Q", len(header)) + header + data)
            receipt = dict(
                tensors=1,
                file_sha256=REPORT.sha(path),
                rows=dict(
                    r=dict(key="k", shape=[1, 1, 2], sha256=hashlib.sha256(data).hexdigest())
                ),
            )
            (folder / "MEMORY_BANK.json").write_text(json.dumps(receipt))
            self.assertEqual(REPORT.check_bank(folder), receipt)
            path.write_bytes(path.read_bytes()[:-1] + b"\x41")
            with self.assertRaisesRegex(ValueError, "Activation body"):
                REPORT.check_bank(folder)
            receipt["file_sha256"] = REPORT.sha(path)
            (folder / "MEMORY_BANK.json").write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "Activation content"):
                REPORT.check_bank(folder)

    def test_literal_panel_preserves_exact_text(self):
        source = dict(memory_ids=[1], mode="affected", answer="yes", memory="FACT  ", query="Q?")
        observed = {r: {} for r in REPORT.ROLES}
        observed["base"]["id", "zero"] = dict(
            text="answer  \nnext",
            stop_reason="eos",
            generated_tokens=3,
            exact_match=False,
            donor_match=False,
        )
        panel = REPORT.literal_panel(dict(id=source), observed)
        self.assertIn("```text\nanswer  \nnext\n```", panel)
        self.assertIn("```text\nFACT  \n```", panel)


if __name__ == "__main__":
    unittest.main()
