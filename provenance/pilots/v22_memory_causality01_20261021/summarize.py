#!/usr/bin/env python3
"""Offline source/receipt/literal replay and deterministic descriptive summaries."""

import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
import re
import struct
import subprocess
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / "v22_base_comparison01_20261021"
DIAGNOSTIC = HERE.parent / "v22_weight_diagnostics01_20261021"
SOURCE = "fd77ee4c84a99a99c22b28aa85d321e95caa843f"
ROLES = ("base", "v22", "base_cross")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(path):
    return {
        p.relative_to(path).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def journal(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def norm(text):
    return re.sub(r"\s+", " ", text.strip()).rstrip(".").strip().casefold()


def terminal(path, status):
    end = read(path / "FINISHED.json")
    files = manifest(path)
    files.pop("FINISHED.json")
    require(end["status"] == status and files == end["files"], f"Terminal: {path}")
    require(
        end["native_weight_updates"] == end["judge_calls"] == end["weight_deletions"] == 0,
        "No unauthorized activity",
    )
    require(
        end["old_expression_gate"] == "FAIL"
        and end["winner"] == "none"
        and end["non_regression"] == "NOT_ESTABLISHED",
        "Unchanged ceiling",
    )
    return end


def distribution(values):
    return dict(
        n=len(values), mean=sum(values) / len(values), minimum=min(values), maximum=max(values)
    )


def counts(rows):
    return dict(
        n=len(rows),
        exact=sum(r["exact_match"] for r in rows),
        abstained=sum(r["abstained"] for r in rows),
        eos=sum(r["stop_reason"] == "eos" for r in rows),
        capped=sum(r["stop_reason"] == "length" for r in rows),
        empty_text=sum(not r["text"].strip() for r in rows),
        generated_tokens=sum(r["generated_tokens"] for r in rows),
    )


def paired(a, b):
    require(set(a) == set(b), "Paired coverage")
    return dict(
        n=len(a),
        left_correct=sum(r["exact_match"] for r in a.values()),
        right_correct=sum(r["exact_match"] for r in b.values()),
        losses=sum(a[k]["exact_match"] and not b[k]["exact_match"] for k in a),
        repairs=sum(not a[k]["exact_match"] and b[k]["exact_match"] for k in a),
        changed_tokens=sum(a[k]["token_ids"] != b[k]["token_ids"] for k in a),
    )


def check_bank(folder):
    receipt = read(folder / "MEMORY_BANK.json")
    path = folder / "memory_states.safetensors"
    require(sha(path) == receipt["file_sha256"], "Activation body")
    raw = path.read_bytes()
    size = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8 : 8 + size])
    require(len(header) == receipt["tensors"], "Activation tensor count")
    for entry in receipt["rows"].values():
        meta = header[entry["key"]]
        a, b = meta["data_offsets"]
        require(meta["dtype"] == "BF16" and meta["shape"] == entry["shape"], "Activation schema")
        require(
            hashlib.sha256(raw[8 + size + a : 8 + size + b]).hexdigest() == entry["sha256"],
            "Activation content",
        )
    return receipt


def writer_bit_changes(bundle):
    """Bit-pattern census, once per unique token-memory, with no tensor library."""
    raw = [
        (bundle / "raw" / role / "memory_states.safetensors").read_bytes()
        for role in ("base", "v22")
    ]
    sizes = [struct.unpack("<Q", value[:8])[0] for value in raw]
    headers = [json.loads(value[8 : 8 + size]) for value, size in zip(raw, sizes, strict=True)]
    require(set(headers[0]) == set(headers[1]), "Same writer memory keys")
    changed, elements, tensors = 0, 0, 0
    for key in headers[0]:
        values = []
        for value, size, header in zip(raw, sizes, headers, strict=True):
            a, b = header[key]["data_offsets"]
            values.append(memoryview(value)[8 + size + a : 8 + size + b].cast("H"))
        require(len(values[0]) == len(values[1]), "Same writer tensor extent")
        n = sum(a != b for a, b in zip(*values, strict=True))
        changed += n
        elements += len(values[0])
        tensors += int(n > 0)
    return dict(
        unique_memories=len(headers[0]),
        changed_tensors=tensors,
        native_elements=elements,
        changed_elements=changed,
        changed_fraction=changed / elements,
    )


def compute():
    # Replay the prior diagnostic and its original comparison, not just their prose.
    spec = importlib.util.spec_from_file_location(
        "previous_diag_replay", DIAGNOSTIC / "summarize.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prior_summary, _ = module.compute(DIAGNOSTIC / "furnace")
    require(prior_summary == read(DIAGNOSTIC / "SUMMARY.json"), "Original diagnostic unchanged")
    bundle = HERE / "furnace"
    seal = read(bundle / "SOURCE_SEAL.json")
    require(seal["source_commit"] == SOURCE and len(seal["source_hashes"]) == 739, "Source")
    for name, digest in seal["source_hashes"].items():
        raw = subprocess.check_output(["git", "show", f"{SOURCE}:{name}"], cwd=ROOT)
        require(hashlib.sha256(raw).hexdigest() == digest, f"Source byte identity: {name}")
    plan = read(ROOT / "configs/v22/MEMORY_CAUSALITY_01.json")
    qualifications = {}
    for device in ("cpu", "cuda"):
        folder = bundle / "qualification" / device
        end = terminal(folder, "TINY_V22_CAUSALITY_PASS_NOT_7B")
        expected = dict(tests=187, errors=0, failures=0, skipped=0)
        suites = ElementTree.parse(folder / "TESTS.xml").getroot().iter("testsuite")
        actual = collections.Counter()
        for s in suites:
            actual.update({k: int(s.attrib.get(k, 0)) for k in expected})
        require(dict(actual) == expected == end["counts"], "Complete qualification")
        start = read(folder / "STARTED.json")
        require(start["seal"] == seal and start["plan"] == plan, "Qualification source/plan")
        qualifications[device] = dict(counts=end["counts"], elapsed_seconds=end["elapsed_seconds"])
    dispatch = terminal(bundle / "raw", "V22_CAUSALITY_COMPLETE_NOT_RELEASE")
    require(dispatch["completed_roles"] == list(ROLES), "All roles")
    restore = read(bundle / "raw/v22/RESTORE.json")
    training = HERE.parent / "v22_full_ft_recovery01_20261021/furnace/raw/train_b"
    require(
        restore["exact"]
        and restore["fingerprint"] == read(training / "STATE_training_step32.pt.json")
        and restore["checkpoint"] == read(training / "CHECKPOINT_training_step32.pt.json")
        and restore["training_contract"] == read(training / "CONTEXT.json")["contract"],
        "Exact historical full-owner restoration",
    )
    witness = read(bundle / "REMOTE_TERMINAL_CHECK.json")
    require(
        witness["status"] == "POST_TERMINAL_OFFLINE_CAUSALITY_CHECK_PASS"
        and witness["source"] == SOURCE
        and witness["no_checkpoint_writes"]
        and witness["model_calls"] == witness["new_sequences"] == 0
        and witness["literal_decoded"] == dict(base=384, v22=464, base_cross=80)
        and not any(r["process_exists"] for r in witness["workers"].values())
        and witness["verifier_sha256"]
        == sha(HERE / "verify_remote.py")
        == sha(bundle / "verify_remote.py"),
        "Offline witness",
    )
    data = json.loads(gzip.decompress((PREVIOUS / "furnace/inputs/INPUTS.json.gz").read_bytes()))
    inputs = {r["row_id"]: r for r in data["worlds"]}
    nonempty = {k for k, r in inputs.items() if r["memory_ids"]}
    observed, prefixes, outcomes, banks = {}, {}, {}, {}
    for role in ROLES:
        folder = bundle / "raw" / role
        end = terminal(folder, "V22_CAUSALITY_ARM_COMPLETE")
        start = read(folder / "STARTED.json")
        require(start["seal"] == seal and start["plan"] == plan, "Role source/plan")
        identity = read(folder / "WEIGHT_IDENTITY.json")
        require(identity["equal"] and identity["before"] == identity["after"], "Frozen weights")
        banks[role] = check_bank(folder)
        require(set(banks[role]["rows"]) == nonempty, "Activation coverage")
        records = journal(folder / "interventions.jsonl")
        expected = (
            {(k, "foreign_writer") for k in nonempty}
            if role == "base_cross"
            else {
                (k, c)
                for k in nonempty
                for c in plan["conditions"]
                if c != "twin" or inputs[k]["mode"] in ("affected", "unaffected")
            }
        )
        if role == "v22":
            expected |= {(k, "foreign_writer") for k in nonempty}
        require(
            len(records) == len(expected)
            and {(r["id"], r["condition"]) for r in records} == expected,
            "Complete unique intervention coverage",
        )
        original = {
            r["id"]: r
            for r in journal(
                PREVIOUS
                / "furnace/raw"
                / ("base" if role == "base_cross" else role)
                / "worlds.jsonl"
            )
            if r["route"] == "latent"
        }
        for row in records:
            source = inputs[row["id"]]
            require(
                all(row[k] == source[k] for k in ("group_id", "mode", "side", "family", "split")),
                "Keys",
            )
            require(
                row["target"] == source["answer"]
                and row["exact_match"] == (norm(row["text"]) == norm(source["answer"])),
                "Original match",
            )
            require(row["abstained"] == (norm(row["text"]) == "not specified"), "Abstention")
            donor = inputs.get(row["donor_id"])
            require(
                (donor is not None) == (source["mode"] in ("affected", "unaffected")),
                "Expected donor coverage",
            )
            if donor:
                require(
                    donor["group_id"] == source["group_id"]
                    and donor["side"] != source["side"]
                    and donor["mode"] == source["mode"]
                    and donor["prefixes"]["latent"] == source["prefixes"]["latent"],
                    "Donor",
                )
                require(
                    row["donor_target"] == donor["answer"]
                    and row["donor_match"] == (norm(row["text"]) == norm(donor["answer"])),
                    "Donor match",
                )
            expected_memory = (
                []
                if row["condition"] == "empty"
                else (donor["memory_ids"] if row["condition"] == "twin" else source["memory_ids"])
            )
            require(
                row["memory_tokens"] == len(expected_memory)
                and row["original_memory_tokens"] == len(source["memory_ids"]),
                "Memory extent",
            )
            j = (
                next(
                    (
                        j
                        for j, (a, b) in enumerate(
                            zip(source["answer_ids"], donor["answer_ids"], strict=False)
                        )
                        if a != b
                    ),
                    0,
                )
                if donor
                else 0
            )
            require(
                row["decision"]["index"] == j
                and row["decision"]["original"]["target"] == source["answer_ids"][j],
                "Oracle-defined decision position",
            )
            if source["mode"] == "affected":
                require(row["decision"]["donor"]["target"] == donor["answer_ids"][j], "Donor token")
            ids = row["token_ids"]
            require(
                row["generated_tokens"] == len(ids) and 0 < len(ids) <= 24 and 2 not in ids[:-1],
                "Tokens",
            )
            require(
                (row["stop_reason"] == "eos" and ids[-1] == 2)
                or (row["stop_reason"] == "length" and len(ids) == 24 and ids[-1] != 2),
                "Stop",
            )
            require(
                row["seed"] == 20261021
                and row["temperature"] == 0
                and row["top_p"] == 1
                and row["max_new_tokens"] == 24,
                "Generation policy",
            )
            replay = row["historical_replay_id"]
            expected_replay = (
                row["id"]
                if row["condition"] == "identity"
                else (row["donor_id"] if row["condition"] == "twin" else None)
            )
            require(replay == expected_replay, "Replay control identity")
            if replay:
                require(
                    ids == original[replay]["token_ids"]
                    and row["text"] == original[replay]["text"],
                    "Historical replay",
                )
        require(
            len(records) == end["outcome"]["new_sequences"] == end["new_sequences"],
            "Sequence activity",
        )
        require(
            sum(r["generated_tokens"] for r in records) == end["outcome"]["generated_tokens"],
            "Token activity",
        )
        observed[role] = {(r["id"], r["condition"]): r for r in records}
        outcomes[role] = dict(**end["outcome"], elapsed_seconds=end["elapsed_seconds"])
        if role != "base_cross":
            p = journal(folder / "prefix.jsonl")
            expected_p = {
                (k, route, j)
                for k, row in inputs.items()
                for route in ("latent", "inline")
                for j in range(len(row["answer_ids"]))
            }
            require(
                len(p) == len(expected_p) == 1246
                and {(r["id"], r["route"], r["index"]) for r in p} == expected_p,
                "Prefix coverage",
            )
            for record in p:
                require(
                    record["target"] == inputs[record["id"]]["answer_ids"][record["index"]],
                    "Gold token",
                )
                future = record["variants"]["changed_future"]
                require(
                    future["delta"]["exact"]
                    and future["sha256"] == record["full_sha256"]
                    and future["score"] == record["full"],
                    "Fixed extent future invariance",
                )
            require(
                read(folder / "PREFIX_GATE.json")
                == dict(positions=1246, fixed_extent_future_disagreements=0, gate="PASS"),
                "Prefix gate",
            )
            prefixes[role] = {}
            for route in ("latent", "inline", "all"):
                subset = [r for r in p if route == "all" or r["route"] == route]
                prefixes[role][route] = {
                    name: dict(
                        positions=len(subset),
                        exact=sum(r["variants"][name]["delta"]["exact"] for r in subset),
                        top1_changes=sum(
                            not r["variants"][name]["delta"]["top1_same"] for r in subset
                        ),
                        gold_correctness_changes=sum(
                            r["variants"][name]["score"]["correct"] != r["full"]["correct"]
                            for r in subset
                        ),
                        max_abs=max(r["variants"][name]["delta"]["max_abs"] for r in subset),
                    )
                    for name in ("cropped", "padded", "changed_future")
                }
    require(banks["base"]["rows"] == banks["base_cross"]["rows"], "Base writer repeat identity")
    require(
        sum(o["new_sequences"] for o in outcomes.values()) == 928
        and dispatch["new_sequences"] == 928,
        "Global sequence denominator",
    )
    require(
        sum(
            r["historical_replay_id"] is not None
            for records in observed.values()
            for r in records.values()
        )
        == 288,
        "Measured replay-control denominator",
    )
    require(dispatch["summary"]["prefix_positions"] == 2492, "Global prefix denominator")
    strata, direction = {}, {}
    for role in ROLES:
        rows = list(observed[role].values())
        strata[role] = {
            f"{condition}/{mode}": counts(
                [
                    r
                    for r in rows
                    if r["condition"] == condition and (mode == "all" or r["mode"] == mode)
                ]
            )
            for condition in sorted({r["condition"] for r in rows})
            for mode in ("all", "affected", "unaffected", "unrelated")
        }
        if role == "base_cross":
            continue
        direction[role] = {}
        for stratum in ("all", "equal_length", "unequal_length"):
            selected = [
                r
                for r in rows
                if r["condition"] == "twin"
                and r["mode"] == "affected"
                and (
                    stratum == "all"
                    or (r["memory_tokens"] == r["original_memory_tokens"])
                    == (stratum == "equal_length")
                )
            ]
            effects = [
                r["decision"]["donor_minus_original"]
                - observed[role][r["id"], "identity"]["decision"]["donor_minus_original"]
                for r in selected
            ]
            direction[role][stratum] = dict(
                directed_rows=len(selected),
                independent_groups=len({r["group_id"] for r in selected}),
                donor_directed_margin_positive=sum(v > 0 for v in effects),
                margin_delta=distribution(effects),
                donor_answers=sum(r["donor_match"] for r in selected),
                original_answers_after_swap=sum(r["exact_match"] for r in selected),
                correct_to_correct_donor_switches=sum(
                    r["donor_match"] and observed[role][r["id"], "identity"]["exact_match"]
                    for r in selected
                ),
                changed_token_sequences=sum(
                    r["token_ids"] != observed[role][r["id"], "identity"]["token_ids"]
                    for r in selected
                ),
            )
        selected = [r for r in rows if r["condition"] == "twin" and r["mode"] == "unaffected"]
        direction[role]["unaffected"] = dict(
            directed_rows=len(selected),
            independent_groups=16,
            exact_token_preserved=sum(
                r["token_ids"] == observed[role][r["id"], "identity"]["token_ids"] for r in selected
            ),
            both_correct=sum(
                r["exact_match"] and observed[role][r["id"], "identity"]["exact_match"]
                for r in selected
            ),
        )
    cells = {
        "writer_base_reader_base": {k: observed["base"][k, "identity"] for k in nonempty},
        "writer_v22_reader_base": {
            k: observed["base_cross"][k, "foreign_writer"] for k in nonempty
        },
        "writer_base_reader_v22": {k: observed["v22"][k, "foreign_writer"] for k in nonempty},
        "writer_v22_reader_v22": {k: observed["v22"][k, "identity"] for k in nonempty},
    }
    bb, vb, bv, vv = cells.values()
    factorial = dict(
        cells={k: counts(list(v.values())) for k, v in cells.items()},
        writer_change_base_reader=paired(bb, vb),
        writer_change_v22_reader=paired(bv, vv),
        reader_change_base_writer=paired(bb, bv),
        reader_change_v22_writer=paired(vb, vv),
    )

    def metric(r):
        return r["decision"]["original"]["gold_logprob"]  # Same oracle prefix per cell.

    factorial["decision_logprob_effects"] = {
        "writer_at_base_reader": distribution(
            [metric(vb[k]) - metric(bb[k]) for k in sorted(nonempty)]
        ),
        "reader_at_base_writer": distribution(
            [metric(bv[k]) - metric(bb[k]) for k in sorted(nonempty)]
        ),
        "interaction": distribution(
            [
                metric(vv[k]) - metric(vb[k]) - metric(bv[k]) + metric(bb[k])
                for k in sorted(nonempty)
            ]
        ),
    }
    summary = dict(
        schema="ltws-v22-memory-causality-summary-v1",
        source=SOURCE,
        qualifications=qualifications,
        planned=plan["planned"],
        outcomes=outcomes,
        prefix=prefixes,
        strata=strata,
        natural_twin=direction,
        writer_reader=factorial,
        writer_activation_bits=writer_bit_changes(bundle),
        new_sequences=928,
        generated_tokens=sum(o["generated_tokens"] for o in outcomes.values()),
        historical_replay_sequences=288,
        invalid_rows=0,
        retries=0,
        old_expression_gate="FAIL",
        winner="none",
        non_regression="NOT_ESTABLISHED",
    )
    return summary, inputs, observed


def literal_panel(inputs, observed):
    lines = [
        "# V22 causal answer bank — all 80 nonempty rows",
        "",
        "Exact decoded outputs; greedy cap 24; all inputs already exposed. Zero/reverse",
        "are off-manifold controls, not alternate gold labels. No quality judge.",
        "Every question also uses the frozen suffix:",
        "' Reply with just the answer, without an explanation.'",
        "The exact chat-template token IDs remain in the original comparison's sealed input bank.",
        "",
    ]
    for key, source in sorted(inputs.items()):
        if not source["memory_ids"]:
            continue
        lines += [
            f"## {key}",
            "",
            f"Mode: {source['mode']}; target: `{source['answer']}`.",
            "",
            "Memory:",
            "",
            "```text",
            source["memory"],
            "```",
            "",
            "Question:",
            "",
            "```text",
            source["query"],
            "```",
            "",
        ]
        for role in ROLES:
            for (rid, condition), row in observed[role].items():
                if rid != key:
                    continue
                lines += [
                    f"### {role} / {condition}",
                    "",
                    f"Stop: {row['stop_reason']}; tokens: {row['generated_tokens']}; "
                    f"original-match: {row['exact_match']}; donor-match: {row['donor_match']}.",
                    "",
                    "```text",
                    row["text"],
                    "```",
                    "",
                ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    summary, inputs, observed = compute()
    panel = literal_panel(inputs, observed)
    if args.verify:
        require(read(HERE / "SUMMARY.json") == summary, "Summary replay")
        require((HERE / "ANSWER_BANK.md").read_text() == panel, "Literal panel replay")
    else:
        with (HERE / "SUMMARY.json").open("x") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        with (HERE / "ANSWER_BANK.md").open("x") as stream:
            stream.write(panel)
    print(
        json.dumps(
            dict(
                status="OFFLINE_CAUSALITY_REPLAY_PASS",
                source=SOURCE,
                new_sequences=0,
                model_calls=0,
                observed_sequences=928,
            )
        )
    )


if __name__ == "__main__":
    main()
