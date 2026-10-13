"""Read checkpoint metadata only, without loading or changing any tensor file."""
import hashlib
import json
import pathlib
import sys

inventory = json.loads(pathlib.Path(sys.argv[1]).read_text())
groups = {}
for row in inventory["weights"]:
    path = pathlib.Path(row["path"])
    parent = path.parent.parent if path.parent.name == "base_model" else path.parent
    groups.setdefault(str(parent), []).append(row)
result = []
for name, weights in sorted(groups.items()):
    row = {"directory": name, "files": len(weights), "bytes": sum(w["bytes"] for w in weights),
           "metadata": {}}
    for filename in ("manifest.json", "experiment_config.json", "base_update_coverage.json"):
        path = pathlib.Path(name) / filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 5_000_000:
            continue
        data = path.read_bytes()
        value = json.loads(data)
        if filename == "manifest.json":
            selected = {k: value.get(k) for k in ("global_step", "run_id", "train_mode",
                "base_storage", "config_sha256", "source_sha256", "resume_signature",
                "base_update_coverage_passed")}
        elif filename == "experiment_config.json":
            selected = {group: {k: value.get(group, {}).get(k) for k in keys}
                        for group, keys in {
                "model": ("name_or_path", "revision", "train_mode"),
                "train": ("seed", "max_steps", "base_release_step", "learning_rate",
                          "workspace_learning_rate", "base_learning_rate"),
                "functional": ("route_mode", "counterfactual_weight", "stability_weight")}.items()}
        else:
            selected = {k: v for k, v in value.items() if not isinstance(v, (list, dict))}
        row["metadata"][filename] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                                     "fields": selected}
    result.append(row)
with pathlib.Path(sys.argv[2]).open("x") as stream:
    json.dump({"groups": result, "deleted": 0, "weight_contents_read": False}, stream, indent=2)
print(json.dumps({"groups": len(result), "with_manifest": sum("manifest.json" in r["metadata"]
                  for r in result), "deleted": 0}))
