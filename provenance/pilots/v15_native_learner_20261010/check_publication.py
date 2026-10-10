#!/usr/bin/env python3
"""Selected prose, source links, retained checkpoint and exact excerpt checks."""

import json
import re

import publish_receipts as pub


def verify_publication():
    bundle, root, v = pub.BUNDLE, pub.REPO, pub.verify
    summary = v.build(bundle)
    publication, bank = pub.derive(summary)
    readme = (bundle / "README.md").read_text()
    prose = re.sub(r"\s+", " ", readme.replace("**", "").replace("`", ""))
    claims = [
        "1,152 evaluation rows",
        "256 four-corner blocks / 1,024 corners",
        "160 greedy sequences",
        "20 distinct progression updates / 22 executed complete windows",
        "320 progression pair-backwards + 32 replay pair-backwards = 352",
    ]
    comparisons = publication["comparisons"]
    labels = [
        "Legacy reader, step 8",
        "Modulated reader, step 8",
        "Modulated frozen, step 2",
        "Modulated full, step 2",
    ]
    for label, row in zip(labels, comparisons, strict=True):
        line = (
            f"| {label} | {row['native_correct']}/32 | {row['positive_native_donor']}/4 / "
            f"{row['correct_native_donor_flips']}/4 | {row['workspace_strict']}/4 | "
            f"{row['same_twin_tokens']}/4 |"
        )
        v.require(line in readme, "Comparison table prose")
    full_comparison = comparisons[-1]["original_base_comparison_exposed_only"]
    workspace, current = full_comparison["workspace"], full_comparison["current_base"]
    claims.extend(
        [
            f"{workspace['repaired_errors']} repaired errors "
            f"and {workspace['new_errors']} new error",
            f"{current['correct']}/32",
            f"{current['repaired_errors']} repairs and {current['new_errors']} new errors",
        ]
    )
    for phase, label in (("reader", "Reader pair"), ("full", "Full pair, including both replays")):
        report = summary["phases"][phase]["report"]
        line = (
            f"| {label} | {report['elapsed_seconds']:.3f} | "
            + " | ".join(
                f"{report[key] / 2**30:.3f}"
                for key in (
                    "peak_cuda_allocated_bytes",
                    "peak_cuda_reserved_bytes",
                    "minimum_sampled_device_free_bytes",
                )
            )
            + " |"
        )
        v.require(line in readme, "Resource table prose")
    for update in summary["phases"]["full"]["arms"]["full"]["updates"]:
        norms = update["normalization_changes"]
        line = (
            f"| {update['step']} | {update['master_changed_tensors']}/291 | "
            f"{update['native_changed_tensors']}/291 | {update['native_changed_elements']:,} | "
            f"{sum(r['master_changed'] for r in norms)}/65 | "
            f"{sum(r['native_changed_elements'] for r in norms):,} |"
        )
        v.require(line in readme, "Precision table prose")
        v.require(
            sum(r["native_changed_elements"] > 0 for r in norms) == 11,
            "Native normalization tensor count",
        )
    for text in claims:
        v.require(text in prose, f"Missing selected numerical claim: {text}")
    snippets = [json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", readme, re.S)]
    coordinates = [
        ("reader", "legacy", 8, 0, 0, "base"),
        ("reader", "query_modulated", 8, 0, 0, "workspace"),
        ("full", "full", 2, 1, 0, "workspace"),
    ]
    keyed = {
        (r["phase"], r["arm"], r["step"], r["world"], r["query"], r["condition"]): r for r in bank
    }
    v.require(snippets == [keyed[key]["answer"] for key in coordinates], "Literal excerpt mismatch")
    v.require(
        all(keyed[key]["finish_reason"] == "length" for key in coordinates), "Excerpt termination"
    )
    checkpoint = v.read(bundle / "raw/CHECKPOINT_AUDIT.json")
    v.require(
        checkpoint["script_sha256"] == v.digest(bundle / "audit_checkpoints.py"),
        "Checkpoint audit source",
    )
    v.require(
        checkpoint["files"] == len(checkpoint["rows"]) == 8
        and checkpoint["total_bytes"] == sum(r["bytes"] for r in checkpoint["rows"]),
        "Checkpoint denominator",
    )
    v.require(f"{checkpoint['total_bytes']:,} bytes" in prose, "Checkpoint bytes prose")
    v.require(
        checkpoint["model_forwards"] == checkpoint["model_updates"] == 0,
        "Read-only checkpoint audit",
    )
    first = {}
    for r in checkpoint["rows"]:
        phase = summary["phases"][r["phase"]]
        expected = next(
            c for c in phase["arms"][r["arm"]]["checkpoint_receipts"] if c["path"] == r["path"]
        )
        v.require(
            all(r[k] == value for k, value in expected.items()) and r["file_hash_verified"],
            "Retained file receipt mismatch",
        )
        if r["phase"] == "full" and r["completed_steps"] == 1:
            first[r["arm"]] = (r["bridge_sha256"], r["bridge_optimizer_sha256"])
        if r["phase"] == "full" and r["arm"] == "full" and r["completed_steps"] == 2:
            v.require(
                r["reconstructed_native_matches_final_model"]
                and r["reconstructed_native_sha256"]
                == phase["arms"]["full"]["resume"]["native_base_sha256"],
                "Saved masters/native final identity",
            )
    v.require(
        first["frozen"] == first["full"] and checkpoint["step1_frozen_full_bridge_and_adamw_exact"],
        "First-update bridge/control equality",
    )
    links = 0
    for file in (
        bundle / "README.md",
        bundle / "EXECUTION_HANDOFF.md",
        bundle / "GENERATION_BANK.md",
        root / "README.md",
        root / "docs/v15/NEXT_STEPS.md",
    ):
        for target in re.findall(r"\]\(([^)]+)\)", file.read_text()):
            if target.startswith(("https://", "http://", "#")):
                continue
            relative = target.split("#", 1)[0]
            v.require(
                (file.parent / relative).exists(), f"Missing local link: {file.name}: {target}"
            )
            links += 1
    return dict(
        status="VERIFIED_PUBLICATION_PROSE_CHECKPOINTS_AND_LITERALS",
        selected_prose_claims=len(claims),
        literal_excerpts=len(snippets),
        local_links=links,
        retained_checkpoints=8,
        scope="Stored evidence; not independent model-quality qualification",
    )


if __name__ == "__main__":
    print(json.dumps(verify_publication()))
