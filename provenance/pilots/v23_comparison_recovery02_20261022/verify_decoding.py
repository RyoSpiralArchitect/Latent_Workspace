"""Local pinned-tokenizer-only literal verification, never instantiate a model."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
import v23_recovered_bank as bank  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402


def verify(tokenizer_path):
    folder = Path(__file__).resolve().parent
    original = ROOT / "provenance/pilots/v23_comparison01_20261022/furnace"
    arms, _ = bank.verify(original, folder / "furnace", published_copy=True)
    revision = "c170c708c41dac9275d15a8fff4eca08d52bab71"
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path,
        trust_remote_code=False,
        local_files_only=True,
    )
    counts = {}
    for arm, rows in arms.items():
        for kind in ("worlds", "free"):
            for row in rows[kind]:
                assert tokenizer.decode(row["token_ids"], skip_special_tokens=True) == row["text"]
            counts[f"{arm}/{kind}"] = len(rows[kind])
    result = dict(
        status="OFFLINE_ALL_648_LITERAL_DECODING_PASS",
        literal_rows=counts,
        model_calls=0,
        new_sequences=0,
        tokenizer_revision=revision,
        tokenizer_files={
            n: bank.ex.digest(tokenizer_path / n)
            for n in (
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "tokenizer.model",
            )
        },
    )
    output = folder / "OFFLINE_DECODING.json"
    if output.exists():
        assert bank.ex.read(output) == result
    else:
        bank.ex.write_new(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().tokenizer), indent=2))
