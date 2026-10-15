"""The V19 frozen-diagnostic verifier accepts exactly the V19 owner's checkpoint receipts.

Kept outside the plan's qualification files, whose pinned count is part of the
frozen diagnostic contract.
"""

import hashlib

import pytest

from latent_workspace_ft_v10.v19_dual_budget_window_learner import FORMAT
from scripts import verify_v19_frozen_diagnostic as verifier

V18_FORMAT = "v18-selection-window-reference-resume-v1"


def receipt(body, step=256, form=FORMAT):
    return {
        "path": f"step{step}.pt",
        "bytes": len(body),
        "completed_steps": step,
        "format": form,
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def test_checkpoint_format_is_the_v19_window_owner_format():
    assert verifier.CHECKPOINT_FORMAT == FORMAT != V18_FORMAT


def test_receipt_check_accepts_v19_and_rejects_v18_or_wrong_step():
    body = b"v19 checkpoint"
    verifier.verify_checkpoint_receipt(receipt(body), 256)
    with pytest.raises(ValueError, match="Checkpoint 256"):
        verifier.verify_checkpoint_receipt(receipt(body, form=V18_FORMAT), 256)
    with pytest.raises(ValueError, match="Checkpoint 512"):
        verifier.verify_checkpoint_receipt(receipt(body), 512)


def test_receipt_check_rehashes_the_body(tmp_path):
    body = b"v19 checkpoint"
    (tmp_path / "step256.pt").write_bytes(body)
    verifier.verify_checkpoint_receipt(receipt(body), 256, tmp_path)
    (tmp_path / "step256.pt").write_bytes(b"v19 checkpoinT")
    with pytest.raises(ValueError, match="Checkpoint 256 bytes"):
        verifier.verify_checkpoint_receipt(receipt(body), 256, tmp_path)
