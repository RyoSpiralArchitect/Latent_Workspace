import sys
from pathlib import Path

from test_recruitment_bank import Tokenizer

from latent_workspace import execution as ex
from latent_workspace import recruitment_bank as bank
from latent_workspace import recruitment_order as order

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_v24_order_control as probe  # noqa: E402


def test_schedule_includes_unchanged_preservation_rows(tmp_path):
    raw = bank.group_rows("recruit-20261023-order-probe", "arithmetic", "train", 47)
    tokenizer = Tokenizer()
    original = order.project_pair(raw, tokenizer, "answer_first")
    changed = order.project_pair(raw, tokenizer, "steps_first")
    key = next(r["key"] for r in original["inline"] if r["mode"] == "affected")
    preservation = dict(
        key="instruction/train/0",
        role="instruction",
        split="train",
        target_ids=[7, 2],
        supervised_tokens=2,
    )
    for route in bank.ROUTES:
        ex.write_gz(tmp_path / f"PRIVATE_{route}.json.gz", original[route] + [preservation])
    ex.write_gz(tmp_path / "PUBLIC_SYNTHETIC.json.gz", raw)
    ex.write_new(
        tmp_path / "SCHEDULE.json",
        dict(training=[[key, preservation["key"]]], canary=[], development=[]),
    )
    ex.write_new(tmp_path / "MANIFEST.json", dict(files=ex.manifest(tmp_path)))
    left = {r["key"]: r for r in original["inline"]}[key]
    right = {r["key"]: r for r in changed["inline"]}[key]
    old_tokens = left["supervised_tokens"] + preservation["supervised_tokens"]
    new_tokens = right["supervised_tokens"] + preservation["supervised_tokens"]
    plan = dict(
        source_bank_manifest_sha256=ex.digest(tmp_path / "MANIFEST.json"),
        source_bank_public_sha256=ex.digest(tmp_path / "PUBLIC_SYNTHETIC.json.gz"),
        source_schedule_sha256=ex.digest(tmp_path / "SCHEDULE.json"),
        expected_baseline_scheduled_rows=2,
        expected_baseline_scheduled_targets=old_tokens,
        expected_steps_first_scheduled_targets=new_tokens,
        expected_token_delta=new_tokens - old_tokens,
    )
    result = probe.inspect(tmp_path, plan, tokenizer)
    assert result["status"] == "V24_ORDER_CONTROL_DATA_PILOT_COMPLETE_NOT_TRAINING"
    assert result["scheduled_rows"] == 2
    assert result["baseline_supervised_tokens"] == old_tokens
    assert result["steps_first_supervised_tokens"] == new_tokens
    assert result["native_weight_updates"] == result["checkpoint_saves"] == 0
