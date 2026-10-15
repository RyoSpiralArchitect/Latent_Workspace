#!/usr/bin/env python3
"""Selected numerical/literal/link checks, not independent model replication."""

from __future__ import annotations

import json
import re

import analyze_mechanism as mechanism

HERE, REPO, replay = mechanism.HERE, mechanism.REPO, mechanism.replay


def main():
    summary, derived = replay.build(HERE), mechanism.build()
    replay.require(summary == replay.read(HERE / "SUMMARY.json"), "Frozen summary")
    replay.require(derived == replay.read(HERE / "MECHANISM.json"), "Derived summary")
    index = {
        p.name: {"sha256": replay.digest(p), "bytes": p.stat().st_size}
        for p in sorted((HERE / "raw").iterdir())
        if p.is_file()
    }
    replay.require(index == replay.read(HERE / "ARTIFACT_INDEX.json"), "Raw index")
    replay.require(
        len(index) == 8 and sum(r["bytes"] for r in index.values()) == 897674,
        "Inventory denominator",
    )
    paths = [
        HERE / "README.md",
        HERE / "EXECUTION_HANDOFF.md",
        REPO / "README.md",
        REPO / "docs/v15/NEXT_STEPS.md",
    ]
    documents = {p: p.read_text() for p in paths}
    body = documents[HERE / "README.md"]
    numbers = []
    for arm in replay.ARMS:
        result, cell = derived["arms"][arm], summary["cells"][arm]
        replay.require(
            cell["correct"] == 16 and cell["truth_rows"] == 32 and cell["correct_donor_flips"] == 0,
            "Truth denominator",
        )
        for stage in replay.STAGES:
            numbers += [f"{value:.6e}" for value in result["mean_factor_l2"][stage].values()]
        for b in result["affected"]:
            numbers += [
                f"{b['capped_binding'][key]:.6e}"
                for key in ("memory_axis", "interaction_axis", "signed_interaction_over_bias")
            ]
        numbers.append(f"{100 * result['mean_common_output_top1_energy_fraction']:.6f}%")
        for variant in replay.VARIANTS:
            i = cell["by_variant"][variant]["factors"]["d"]["interaction"]["l2"]["mean"]
            if i:
                numbers.append(f"{i:.6e}")
        cap = cell["by_variant"]["actual"]["cap"]
        numbers += [f"{cap[key]['mean']:.6f}" for key in ("tangential_scale", "radial_scale")]
        numbers += [
            f"{cap[key]['mean']:.6e}"
            for key in ("ideal64_minus_linearization_l2", "production_minus_ideal64_l2")
        ]
    candidate = derived["arms"]["query_modulated"]
    for b in candidate["affected"]:
        numbers.append(f"{b['raw_signed_axis_interaction_over_memory_bias']:.6e}")
    numbers += [f"{v:.6e}" for v in candidate["affected"][0]["cap64_interaction_axis_interval"]]
    numbers += [
        f"{s[k]:.6e}"
        for s in candidate["mean_modulation_sources_actual"].values()
        for k in ("z_l2", "projected_l2")
    ]
    numbers += [
        f"{candidate['max_modulation_rounding_error']:.6e}",
        f"{candidate['max_modulation_error_over_bound']:.6f}",
    ]
    spec = summary["spectrum"]
    numbers += [f"{spec[k]:.6f}" for k in ("participation_rank", "entropy_effective_rank")]
    numbers += [f"{100 * spec['top_k_frobenius_energy_fraction'][k]:.6f}%" for k in ("1", "4")]
    numbers += [
        f"{summary[k]:.6f}"
        for k in (
            "elapsed_seconds",
            "peak_cuda_allocated_gib",
            "peak_cuda_reserved_gib",
            "sampled_min_free_gib",
        )
    ]
    for number in numbers:
        replay.require(number in body, f"Published number absent: {number}")
    percentage = f"{100 * candidate['common_slot_over_actual_mean_interaction_l2']:.6f}%"
    for path in (HERE / "README.md", REPO / "README.md", REPO / "docs/v15/NEXT_STEPS.md"):
        replay.require(
            percentage in documents[path]
            and f"{100 * spec['top_k_frobenius_energy_fraction']['1']:.6f}%" in documents[path],
            "Root/next numbers",
        )
    features = replay.read(HERE / "raw/FEATURES.json")["renderings"]
    panel = replay.read(HERE / "raw/legacy_FACTORS.json")["rows"]
    literal = 0
    for w in (0, 1):
        for q in (0, 1):
            question = next(r for r in features if (r["world"], r["query"]) == (w, q))["span"][
                "question"
            ]
            scores = next(
                r
                for r in panel
                if (r["world"], r["query"], r["variant"], r["side"]) == (w, q, "actual", 0)
            )["native_scores"]
            replay.require(question in body and str(scores) in body, "Literal native panel")
            literal += 1
    links = 0
    for path, text in documents.items():
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if not target.startswith(("http://", "https://", "#")):
                replay.require(
                    (path.parent / target.split("#", 1)[0]).resolve().is_file(),
                    f"Broken link: {target}",
                )
                links += 1
    print(
        json.dumps(
            {
                "status": "VERIFIED_SELECTED_PUBLICATION_NUMBERS_LITERALS_AND_LINKS",
                "numerical_occurrence_checks": len(numbers),
                "literal_rows": literal,
                "local_links": links,
                "scope": "Recorded scalars/prose, not independent model recomputation",
            }
        )
    )


if __name__ == "__main__":
    main()
