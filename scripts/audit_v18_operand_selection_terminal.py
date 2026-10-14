#!/usr/bin/env python3
"""Supplement the frozen V18 toy replay, offline and without model forwards.

This new auditor does not change the sealed experiment. Control booleans are
checked against saved observations, not re-observed: control logits were not
archived. Recipe replay permits only 1e-6 absolute cross-runtime QR identity
rounding; labels, ranks, layout, and repeated uses of each identity are exact.
That predeclared data-validation bound does not alter an experimental gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "dd10b20a8fbb0e32e5ac89bcec939802e6940f8b"
ENTRY = "scripts/assay_v18_operand_selection.py"
SOURCE_SCOPE = ("src", "scripts", "configs", "tests", "pyproject.toml")
SEAL_SCOPE = (*SOURCE_SCOPE, "data/v10")
IDENTITY_ATOL = 1e-6
TENSOR_FIELDS = {"states", "memory", "mask", "twin_memory", "labels", "twin_labels"}
SPLITS = {"train", "dev", "held_out"}
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def number(text):
        value = float(text)
        require(math.isfinite(value), "Nonfinite JSON number")
        return value

    def constant(text):
        raise ValueError(f"Nonfinite JSON constant: {text}")

    return json.loads(text, object_pairs_hook=unique, parse_float=number, parse_constant=constant)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mapping(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), f"{label} schema")


def text(value):
    return type(value) is str and bool(value) and all(ord(char) >= 32 for char in value)


def finite(value, label, *, minimum=0):
    require(type(value) in (float, int) and math.isfinite(value) and value >= minimum,
            f"{label} must be a finite numeric scalar")


def safe_file(root, name):
    require(type(name) is str, "Artifact/source path type")
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and str(relative) == name and "\\" not in name
            and ".." not in relative.parts and ".git" not in relative.parts,
            "Noncanonical or escaping path")
    target = root / name
    require(target.is_file() and target.resolve().is_relative_to(root.resolve())
            and not any(p.is_symlink() for p in (target, *target.parents) if p != root),
            "Artifacts/sources must be regular nonsymlink files")
    return target


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def verify_source(seal):
    """Bind the old seal to old commit bytes and still-unchanged local files."""
    mapping(seal, {"source_commit", "source_hashes"}, "Source seal")
    require(seal["source_commit"] == SOURCE_COMMIT, "Unexpected execution source commit")
    hashes = seal["source_hashes"]
    require(type(hashes) is dict and hashes, "Source hashes")
    require(all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in hashes.values()), "Source hash syntax")
    require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
            == ROOT.resolve(), "Exact checkout root")
    records = git("ls-tree", "-rz", "--full-tree", SOURCE_COMMIT, "--", *SEAL_SCOPE)
    blobs = {}
    for record in filter(None, records.split(b"\0")):
        meta, name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        require(mode in ("100644", "100755") and kind == "blob", "Nonregular source blob")
        blobs[name.decode()] = oid
    require(set(blobs) == set(hashes), "Source seal does not cover exact committed scope")
    names = sorted(blobs)
    response = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=ROOT,
        input="".join(blobs[name] + "\n" for name in names).encode(),
        capture_output=True, check=True,
    ).stdout
    cursor = 0
    for name in names:
        end = response.index(b"\n", cursor)
        oid, kind, size = response[cursor:end].decode().split()
        require(oid == blobs[name] and kind == "blob", "Committed blob identity")
        size = int(size)
        require(size >= 0, "Committed blob size")
        content = response[end + 1:end + 1 + size]
        cursor = end + 1 + size
        require(response[cursor:cursor + 1] == b"\n", "Truncated committed source")
        cursor += 1
        require(hashlib.sha256(content).hexdigest() == hashes[name], "Committed source hash")
        require(sha(safe_file(ROOT, name)) == hashes[name], f"Current source changed: {name}")
    require(cursor == len(response), "Trailing committed source output")
    return {name: value for name, value in hashes.items() if not name.startswith("data/v10/")}


def read_artifacts(directory):
    require(directory.is_dir() and not directory.is_symlink(), "Bundle directory")
    documents = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Symlink in bundle")
        if path.is_file() and path.suffix in (".json", ".jsonl"):
            relative = path.relative_to(directory).as_posix()
            safe_file(directory, relative)
            if path.suffix == ".jsonl":
                # Validate every line before the older replay parser is invoked.
                for line in path.read_text().splitlines():
                    strict_json(line)
            else:
                documents[relative] = strict_json(path.read_text())
    required = {"PLAN.json", "SOURCE.json", "PREIMPORT.json", "STARTED.json",
                "IMPORTS_BEFORE.json", "IMPORTS_AFTER.json", "POPULATIONS.json",
                "RESULTS.json", "FINISHED.json"}
    require(required <= set(documents), "Missing terminal artifact")
    require("FAILED.json" not in documents, "Failed study is not a complete terminal result")
    safe_file(directory, "CASES.jsonl")
    safe_file(directory, "POPULATIONS.pt")
    return documents


def verify_imports(imports, hashes):
    require(type(imports) is dict and imports, "Imported-source map")
    for name, path in imports.items():
        require(text(name) and type(path) is str and path in hashes, "Unsealed import")
        if name in ("__main__", "__mp_main__"):
            expected = {ENTRY}
        elif name == "latent_workspace_ft_v10" or name.startswith("latent_workspace_ft_v10."):
            base = "src/" + name.replace(".", "/")
            expected = {base + ".py", base + "/__init__.py"}
        else:
            require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name), "Import module syntax")
            expected = {f"scripts/{name}.py", f"tests/{name}.py"}
        require(path in expected, "Import module/source identity mismatch")
    for name, path in {
        "__main__": ENTRY,
        "latent_workspace_ft_v10": "src/latent_workspace_ft_v10/__init__.py",
        "latent_workspace_ft_v10.v18_selection_reader":
            "src/latent_workspace_ft_v10/v18_selection_reader.py",
        "latent_workspace_ft_v10.precision_bridge":
            "src/latent_workspace_ft_v10/precision_bridge.py",
    }.items():
        require(imports.get(name) == path, "Critical imported-source identity missing")


def verify_identity(documents, seal, seal_path, source_files):
    source = documents["SOURCE.json"]
    mapping(source, {"commit", "files", "aggregate_sha256"}, "Source receipt")
    require(source["commit"] == SOURCE_COMMIT and source["files"] == source_files
            and source["aggregate_sha256"] == digest(source_files), "Source receipt identity")
    require(canonical(documents["PREIMPORT.json"]) == canonical({
        "schema": "pre-import-source-check-v1", "source_commit": SOURCE_COMMIT,
        "entry": ENTRY, "source_files": len(seal["source_hashes"]),
        "untracked_check": "all", "isolated_python": True, "fresh_bytecode_cache": True,
    }), "Pre-import source proof mismatch")
    started = documents["STARTED.json"]
    mapping(started, {"pid", "device", "plan_sha256", "source_sha256", "hostname", "python",
                      "torch", "offline_environment", "external_seal_sha256"}, "Started")
    require(type(started["pid"]) is int and started["pid"] > 0, "Process identity")
    require(started["device"] in ("cpu", "cuda"), "Runtime device")
    require(all(text(started[key]) for key in ("hostname", "python", "torch")), "Runtime text")
    require(canonical(started["offline_environment"]) == canonical(OFFLINE_ENV), "Offline flags")
    require(started["external_seal_sha256"] == sha(seal_path), "External seal identity")
    result = documents["RESULTS.json"]
    for receipt in (started, result):
        require(receipt["plan_sha256"] == digest(documents["PLAN.json"])
                and receipt["source_sha256"] == source["aggregate_sha256"],
                "Source/plan receipt identity")
    require(result["device"] == started["device"], "Cross-receipt runtime identity")
    before, after = (documents[f"IMPORTS_{when}.json"] for when in ("BEFORE", "AFTER"))
    for imports in (before, after):
        verify_imports(imports, seal["source_hashes"])
    require(all(after.get(name) == path for name, path in before.items()), "Import closure shrank")


def verify_controls(value, factor, plan):
    booleans = {"same_memory_exact", "zero_memory_exact_zero_delta", "equal_slot_exact_zero_delta",
                "equal_slot_gate_applicable", "pass"}
    scalars = {"permutation_max_logit_error", "permutation_atol", "unrelated_delta_norm_mean",
               "unrelated_absolute_logit_change_mean", "max_delta_norm"}
    mapping(value, booleans | scalars | {"renaming_scope", "unrelated_accuracy"}, "Control")
    require(all(type(value[key]) is bool for key in booleans), "Control boolean type")
    for key in scalars:
        finite(value[key], key)
        require(type(value[key]) is float, "Control scalar must retain float type")
    atol = plan["evaluation"]["control_atol"]
    require(value["permutation_atol"] == atol, "Control tolerance changed")
    require(value["equal_slot_gate_applicable"] is (factor != "raw_ordered"), "Control factor")
    require(value["renaming_scope"] == (
        "Synthetic alias codebook preserves identical features by construction; "
        "tokenizer binding is not tested here."
    ) and value["unrelated_accuracy"] == "UNDEFINED_QUERY_ENTITIES_ABSENT", "Control scope")
    expected = (value["same_memory_exact"] and value["zero_memory_exact_zero_delta"]
                and (factor == "raw_ordered" or value["equal_slot_exact_zero_delta"])
                and value["permutation_max_logit_error"] <= atol
                and value["max_delta_norm"] <= 0.25 + atol)
    require(value["pass"] is expected, "Control pass disagrees with saved scalars")
    return expected


def verify_populations(realized, manifest, plan, assay):
    """No model construction: only exact tensors, metadata, and QR data recipe."""
    import torch

    mapping(realized, SPLITS, "Realized population splits")
    mapping(manifest, SPLITS | {"file", "file_sha256"}, "Population manifest")
    require(manifest["file"] == "POPULATIONS.pt", "Population filename")
    identity_sets, report = {}, {}
    for split in sorted(SPLITS):
        payload, item = realized[split], manifest[split]
        mapping(payload, TENSOR_FIELDS | {"rows", "frames"}, "Population payload")
        mapping(item, {"tensors", "rows_sha256", "frames", "unique_queries"}, "Split manifest")
        mapping(item["tensors"], TENSOR_FIELDS, "Population fingerprints")
        frames = plan["splits"][split]["frames"]
        count = frames * 36
        require(type(payload["frames"]) is int and payload["frames"] == frames
                and type(item["frames"]) is int and item["frames"] == frames
                and type(item["unique_queries"]) is int and item["unique_queries"] == count,
                "Population frame/row counts")
        require(type(payload["rows"]) is list and len(payload["rows"]) == count,
                "Population row schema")
        for field in TENSOR_FIELDS:
            value = payload[field]
            shape = (count,) if field in ("labels", "twin_labels") else (
                (count, 3) if field == "mask" else (count, 3, 32)
            )
            dtype = torch.int64 if field in ("mask", "labels", "twin_labels") else torch.float32
            require(type(value) is torch.Tensor and value.device.type == "cpu"
                    and value.layout == torch.strided and value.dtype == dtype
                    and tuple(value.shape) == shape and not value.requires_grad,
                    f"Population tensor schema: {split}/{field}")
            require(bool(torch.isfinite(value).all()), f"Nonfinite population: {split}/{field}")
            require(assay.tensor_fingerprint(value) == item["tensors"][field],
                    "Population tensor fingerprint")
        require(digest(payload["rows"]) == item["rows_sha256"], "Population row digest")
        expected = assay.population(**plan["splits"][split])
        require(canonical(payload["rows"]) == canonical(list(expected.rows)),
                "Population row/rank/question recipe mismatch")
        for field, value in (("mask", expected.inputs.mask), ("labels", expected.labels),
                             ("twin_labels", expected.twin_labels)):
            require(torch.equal(payload[field], value), "Population label/mask/rank mismatch")
        identities = payload["memory"][::36, :, :8].clone()
        expected_identities = expected.inputs.memory[::36, :, :8]
        error = float((identities - expected_identities).abs().max())
        require(error <= IDENTITY_ATOL, "Population identity differs from frozen QR recipe")
        # Derive all features from the realized frame identity. No fuzzy bound
        # is allowed for label leakage, nonidentity coordinates, or reuse.
        for index, row in enumerate(expected.rows):
            identity = identities[row["frame"]]
            memory = expected.inputs.memory[index].clone()
            twin_memory = expected.twin.memory[index].clone()
            memory[:, :8] = twin_memory[:, :8] = identity
            states = torch.zeros(3, 32, dtype=torch.float32)
            subject, obj = row["subject"], row["object"]
            states[0, :8], states[1, :8] = identity[subject], identity[obj]
            states[2, :8], states[2, 8:16] = identity[subject], identity[obj]
            states[:, 31] = 1
            require(torch.equal(payload["states"][index], states)
                    and torch.equal(payload["memory"][index], memory)
                    and torch.equal(payload["twin_memory"][index], twin_memory),
                    "Population identity reuse/rank/layout mismatch")
        identity_sets[split] = identities
        report[split] = {"frames": frames, "rows": count,
                         "recipe_identity_max_abs_error": error,
                         "affected_rows": int((payload["labels"] != payload["twin_labels"]).sum())}
    # Frames are units of separation; entity codes may not be reused either.
    codes = []
    for split, frames in identity_sets.items():
        for frame, identities in enumerate(frames):
            for entity, identity in enumerate(identities):
                for _, _, _, previous in codes:
                    require(not torch.allclose(identity, previous, atol=IDENTITY_ATOL, rtol=0),
                            "Population identity overlaps across frames/splits")
                codes.append((split, frame, entity, identity))
    return report


def frozen_modules():
    sys.path.insert(0, str(ROOT / "scripts"))
    return (importlib.import_module("assay_v18_operand_selection"),
            importlib.import_module("replay_v18_operand_selection"))


def audit(directory, seal_path):
    directory, seal_path = Path(directory), Path(seal_path)
    require(not directory.is_symlink(), "Bundle directory must not be a symlink")
    directory = directory.resolve()
    require(not seal_path.is_symlink() and seal_path.is_file(), "External source seal file")
    seal = strict_json(seal_path.read_text())
    source_files = verify_source(seal)
    documents = read_artifacts(directory)
    verify_identity(documents, seal, seal_path, source_files)
    assay, replay = frozen_modules()
    plan, result = documents["PLAN.json"], documents["RESULTS.json"]
    require(canonical(plan) == canonical(assay.load_plan()), "Frozen plan changed")
    require(result["schema"] == "v18-controlled-operand-selection-result-v1", "Result schema")
    expected_cells = {
        f"{seed}:{factor}" for seed in plan["model_seeds"] for factor in assay.FACTORS
    }
    mapping(result["results"], expected_cells, "Fitting cell population")
    controls = {key: verify_controls(fit["controls"], key.split(":")[1], plan)
                for key, fit in result["results"].items()}
    import torch

    torch.set_num_threads(2)
    manifest = documents["POPULATIONS.json"]
    require(canonical(manifest) == canonical(result["populations"]), "Population manifest binding")
    require(sha(directory / "POPULATIONS.pt") == manifest["file_sha256"],
            "Population artifact hash")
    realized = torch.load(directory / "POPULATIONS.pt", map_location="cpu", weights_only=True)
    populations = verify_populations(realized, manifest, plan, assay)
    require(canonical(assay.gates(result["results"], plan)) == canonical(result["gates"]),
            "Recomputed gates mismatch")
    # Includes terminal hashes, all case metrics, saved tiny-weight digests,
    # fitted-cell denominators, initial matching, and unchanged gate thresholds.
    raw_replay = replay.replay(directory)
    return {
        "schema": "v18-operand-selection-supplemental-terminal-audit-v1",
        "status": "OFFLINE_TERMINAL_AUDIT_PASS", "source_commit": SOURCE_COMMIT,
        "source_seal_sha256": sha(seal_path), "device": result["device"],
        "control_pass_recomputed": controls, "populations": populations,
        "identity_recipe_atol": IDENTITY_ATOL, "identity_recipe_rtol": 0,
        "identity_bound_scope": "QR FP32 identity coordinates only; all structural reuse exact",
        "raw_replay": raw_replay, "forward_calls": 0, "training_updates": 0,
        "control_forward_replay": "NOT_PERFORMED_saved_observations_only",
        "gates": result["gates"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output must be exclusive; an existing receipt will not be overwritten")
    receipt = audit(args.bundle, args.source_seal)
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
