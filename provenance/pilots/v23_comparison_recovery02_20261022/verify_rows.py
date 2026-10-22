"""Recompute every selected score/target/stop decision from frozen input rows."""

import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("complete_analysis", HERE / "analyze.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
bank, ROOT = analysis.bank, analysis.ROOT
spec = importlib.util.spec_from_file_location(
    "v22_replay", HERE.parent / "v22_base_comparison01_20261021/summarize.py"
)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


def verify():
    arms, _ = analysis.analyze()
    folder = HERE.parent / "v22_base_comparison01_20261021/furnace/inputs"
    manifest = bank.ex.read(folder / "MANIFEST.json")
    actual = bank.ex.manifest(folder)
    actual.pop("MANIFEST.json")
    assert actual == manifest["files"]
    assert bank.ex.digest(folder / "MANIFEST.json") == bank.ex.digest(
        ROOT / "configs/v22/comparison_20261021/MANIFEST.json"
    )
    data = bank.ex.read_gz(folder / "INPUTS.json.gz")
    policy = bank.ex.read(ROOT / "configs/v22/BASE_COMPARISON_01.json")
    worlds = {r["row_id"]: r for r in data["worlds"]}
    free = {r["id"]: r for r in data["free"]}
    for rows in arms.values():
        for r, src in zip(rows["mmlu"], data["mmlu"], strict=True):
            assert all(r[k] == src[k] for k in ("id", "subject", "target"))
            scores = r["logits"]
            assert len(scores) == 4 and all(math.isfinite(s) for s in scores)
            pred = max(range(4), key=scores.__getitem__)
            ties = scores.count(max(scores))
            assert r["prediction"] == pred and r["ties"] == ties
            assert r["correct"] == (pred == r["target"])
            assert r["strict_correct"] == (r["correct"] and ties == 1)
        assert {(r["id"], r["route"]) for r in rows["worlds"]} == {
            (i, route) for i in worlds for route in policy["world_routes"]
        }
        for r in rows["worlds"]:
            src = worlds[r["id"]]
            assert all(
                r[k] == src[k] for k in ("group_id", "family", "split", "mode", "side", "aliases")
            )
            assert r["target"] == src["answer"]
            assert r["exact_match"] == (old.norm(r["text"]) == old.norm(src["answer"]))
            assert r["teacher"]["supervised_tokens"] == len(src["answer_ids"])
            assert math.isfinite(r["teacher"]["nll_sum"])
            assert r["seed"] == policy["world_generation"]["seed"]
            old.generation_check(r, policy["world_generation"])
        assert {(r["id"], r["seed"]) for r in rows["free"]} == {
            (i, s) for i in free for s in policy["generation"]["seeds"]
        }
        for r in rows["free"]:
            assert all(r[k] == free[r["id"]][k] for k in ("prompt", "category"))
            old.generation_check(r, policy["generation"])
    result = dict(
        status="ALL_SELECTED_INPUT_SCORE_TARGET_AND_STOP_REPLAY_PASS",
        mmlu_rows=1710,
        world_rows=576,
        free_rows=72,
        model_calls=0,
        new_sequences=0,
        input_manifest_sha256=bank.ex.digest(folder / "MANIFEST.json"),
    )
    target = HERE / "ROW_REPLAY.json"
    if target.exists():
        assert bank.ex.read(target) == result
    else:
        bank.ex.write_new(target, result)
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
