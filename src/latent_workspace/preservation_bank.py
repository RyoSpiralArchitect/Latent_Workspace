"""CPU-only preservation candidates, not a training or quality approval.

Text and code are untrusted DATA and are never executed. Source train/eval
boundaries, root/tree groups, native tokenizer IDs and loss masks are explicit.
No network, model forwards, weights, teacher calls or trainer imports.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def ndjson(path):
    with Path(path).open() as f:
        return [json.loads(line) for line in f if line.strip()]


def safe_path(base, relative):
    base = Path(base).resolve()
    path = (base / relative).resolve()
    require(path.is_relative_to(base), "Source path escapes bundle")
    return path


def normalized(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def text_hash(text):
    return sha(normalized(text).encode())


def rank(seed, key):
    return sha(f"{seed}:{key}".encode())


def split_for(plan, group):
    return (
        "dev"
        if int(rank(plan["seed"], group)[:16], 16) % plan["dev_hash_modulus"] == 0
        else "train"
    )


class Exclusions:
    """Conservative exact/long-span filter; NOT a semantic contamination proof."""

    def __init__(self, texts, span=50):
        self.span = span
        self.exact = set()
        self.spans = set()
        for text in texts:
            norm = normalized(text)
            if norm:
                self.exact.add(sha(norm.encode()))
                self.spans.update(self._spans(norm))

    def _spans(self, norm):
        words = norm.split()
        return {
            hashlib.blake2b(" ".join(words[i : i + self.span]).encode(), digest_size=16).digest()
            for i in range(len(words) - self.span + 1)
        }

    def matches(self, text):
        norm = normalized(text)
        if not norm:
            return False
        return sha(norm.encode()) in self.exact or bool(self._spans(norm) & self.spans)


def verify_aether(bundle, eval_bundle, plan):
    bundle, eval_bundle = Path(bundle), Path(eval_bundle)
    require(digest(bundle / "manifest.json") == plan["aether_manifest_sha256"], "Aether manifest")
    manifest = read(bundle / "manifest.json")
    for field in ("documents", "file_inventory"):
        item = manifest[field]
        p = safe_path(bundle, item["path"])
        require(digest(p) == item["sha256"] and p.stat().st_size == item["bytes"], field)
    files = {}
    for item in ndjson(bundle / "files.ndjson"):
        require(item["path"] not in files, "Duplicate inventory path")
        p = safe_path(bundle, item["path"])
        require(p.stat().st_size == item["bytes"] and digest(p) == item["sha256"], "Aether payload")
        files[item["path"]] = item
    docs = ndjson(bundle / "documents.ndjson")
    eval_manifest = read(eval_bundle / "manifest.json")
    expected_eval = eval_manifest["documents"]
    eval_path = safe_path(eval_bundle, expected_eval["path"])
    require(digest(eval_path) == expected_eval["sha256"], "Aether evaluation index")
    require(digest(eval_path) == plan["aether_eval_documents_sha256"], "Pinned evaluation index")
    evaluation = ndjson(eval_path)
    roots = {x["root_work_id"] for x in evaluation}
    hashes = {x["content_sha256"] for x in evaluation}
    require(not roots & {x["root_work_id"] for x in docs}, "Aether train/eval root overlap")
    require(not hashes & {x["content_sha256"] for x in docs}, "Aether train/eval content overlap")
    for doc in docs:
        item = files.get(doc["content_path"], {})
        require(item.get("sha256") == doc["content_sha256"], "Unbound Aether content")
    allowed, excluded = [], Counter()
    for doc in docs:
        if doc["shard_id"] not in plan["aether_allowed_shards"]:
            excluded[doc["shard_id"]] += 1
            continue
        require(doc["split"] == "train", "Nontraining Aether material")
        require(doc["policy_decision"] == "eligible", "Aether policy not eligible")
        require(doc["derivation_kind"] in ("human_original", "human_translation"), "Not human")
        allowed.append(doc)
    return allowed, dict(
        manifest_sha256=digest(bundle / "manifest.json"),
        files_hashed=len(files),
        source_documents=len(docs),
        eligible_documents=len(allowed),
        excluded_by_shard=dict(excluded),
        evaluation_documents=len(evaluation),
        evaluation_roots=len(roots),
        train_eval_root_overlap=0,
        train_eval_content_overlap=0,
        rights="SOURCE_CLAIMS_ONLY_JURISDICTION_REVIEW_PENDING",
    )


def lm_candidates(bundle, docs, tokenizer, plan, exclusions):
    groups = defaultdict(list)
    for doc in docs:
        groups[doc["root_work_id"]].append(doc)
    rows, rejects = [], Counter()
    for group in sorted(groups):
        ordered = sorted(groups[group], key=lambda x: rank(plan["seed"], x["doc_id"]))
        for doc in ordered[: plan["aether_chunks_per_root"]]:
            text = safe_path(bundle, doc["content_path"]).read_text()
            if exclusions.matches(text):
                rejects["evaluation_text_overlap"] += 1
                continue
            tokens = tokenizer.encode(text, add_special_tokens=False)
            width = plan["lm_sequence_tokens"] - 1
            starts = list(range(0, len(tokens), width))
            starts = sorted(starts, key=lambda x: rank(plan["seed"], f"{doc['doc_id']}:{x}"))
            emitted = 0
            for start in starts:
                body = tokens[start : start + width]
                if len(body) < plan["min_lm_body_tokens"]:
                    continue
                ids = [tokenizer.bos_token_id, *body]
                rows.append(
                    dict(
                        row_id=f"aether/{doc['doc_id']}/{start}",
                        group_id=f"aether/{group}",
                        split=split_for(plan, group),
                        role="prose",
                        language=doc["text_language"],
                        memory=[],
                        input_ids=ids,
                        labels=[-100, *body],
                        text=tokenizer.decode(body, skip_special_tokens=False),
                        source=dict(
                            dataset="aether",
                            doc_id=doc["doc_id"],
                            root_work_id=group,
                            category=doc["content_category"],
                            content_sha256=doc["content_sha256"],
                            content_path=doc["content_path"],
                            token_start=start,
                            token_end=start + len(body),
                            source_tokens=len(tokens),
                            rights=doc["license_or_pd_basis"],
                        ),
                        artificial_eos=False,
                        training_approved=False,
                    )
                )
                emitted += 1
                if emitted == plan["aether_windows_per_chunk"]:
                    break
    return rows, dict(roots_available=len(groups), rejected_documents=dict(rejects))


def labels_dict(row):
    value = row.get("labels") or {}
    if isinstance(value, list):
        return {x["name"]: x for x in value}
    if "name" in value:  # HF parquet sequence-of-struct represented as columns
        return {
            name: dict(value=v, count=n)
            for name, v, n in zip(value["name"], value["value"], value["count"])
        }
    return value


def quality_reason(row, plan, assistant=False):
    if row.get("deleted") is not False or row.get("review_result") is not True:
        return "not_reviewed_or_deleted"
    if row.get("synthetic") is not False:
        return "synthetic_or_unknown"
    labels = labels_dict(row)
    if plan["oasst"]["require_pii_annotation"] and not labels.get("pii", {}).get("count"):
        return "missing_pii_annotation"
    for key in ("pii", "spam", "hate_speech", "sexual_content", "not_appropriate"):
        if labels.get(key, {}).get("value", 0) > 0:
            return f"flagged_{key}"
    if assistant:
        if row.get("rank") != 0:
            return "not_rank_zero"
        quality = labels.get("quality", {})
        if (
            not quality.get("count")
            or quality.get("value", -1) < plan["oasst"]["assistant_min_quality"]
        ):
            return "quality_missing_or_low"
    return None


def code_response(text):
    return bool(
        re.search(
            r"```(?:python|py|javascript|js|typescript|ts|java|c|cpp|csharp|go|rust|ruby|php|sql|bash)"
            r"\b|(?m:^\s*(?:def \w+\(|function \w+\(|class \w+[(:{]|SELECT .+ FROM ))",
            text,
            re.IGNORECASE,
        )
    )


def chat_tokens(tokenizer, prompt, answer):
    messages = [dict(role="user", content=prompt)]
    prefix = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=False,
    )
    full = tokenizer.apply_chat_template(
        messages + [dict(role="assistant", content=answer)],
        tokenize=True,
        add_generation_prompt=False,
        return_dict=False,
    )
    require(full[: len(prefix)] == prefix, "Chat template prefix is not token-exact")
    require(len(full) > len(prefix) and full[-1] == tokenizer.eos_token_id, "Assistant EOS")
    return full, [-100] * len(prefix) + full[len(prefix) :], len(prefix)


def oasst_candidates(train, validation, tokenizer, plan, exclusions):
    by_id = {r["message_id"]: r for r in train}
    require(len(by_id) == len(train), "Duplicate OASST source IDs")
    val_trees = {r["message_tree_id"] for r in validation}
    require(not val_trees & {r["message_tree_id"] for r in train}, "Official tree split overlap")
    selected, rejects, pool = [], Counter(), Counter()
    seen = set()
    for row in sorted(train, key=lambda r: rank(plan["seed"], r["message_id"])):
        if row["role"] != "assistant":
            continue
        parent = by_id.get(row["parent_id"])
        if not parent or parent["role"] != "prompter" or parent["parent_id"] is not None:
            rejects["not_complete_root_pair"] += 1
            continue
        require(parent["message_tree_id"] == row["message_tree_id"], "Parent tree mismatch")
        if row["lang"] not in plan["oasst"]["languages"] or row["lang"] != parent["lang"]:
            rejects["language"] += 1
            continue
        reason = quality_reason(parent, plan) or quality_reason(row, plan, assistant=True)
        if reason:
            rejects[reason] += 1
            continue
        prompt, answer = parent["text"], row["text"]
        if not prompt.strip() or not answer.strip():
            rejects["empty_text"] += 1
            continue
        if exclusions.matches(prompt) or exclusions.matches(answer):
            rejects["evaluation_text_overlap"] += 1
            continue
        key_hashes = {text_hash(prompt), text_hash(answer)}
        if key_hashes & seen:
            rejects["duplicate_prompt_or_answer"] += 1
            continue
        # De-duplicate before splitting/quota selection; siblings never cross splits.
        seen.update(key_hashes)
        ids, labels, prefix_len = chat_tokens(tokenizer, prompt, answer)
        if len(ids) > plan["chat_max_tokens"]:
            rejects["over_length_no_truncation"] += 1
            continue
        role = "code" if code_response(answer) else "instruction"
        group = row["message_tree_id"]
        split = split_for(plan, group)
        bucket = f"{split}/{role}/{row['lang']}"
        pool[bucket] += 1
        if pool[bucket] > plan["oasst"]["quotas"][bucket]:
            rejects["over_quota"] += 1
            continue
        selected.append(
            dict(
                row_id=f"oasst1/{row['message_id']}",
                group_id=f"oasst1/{group}",
                split=split,
                role=role,
                language=row["lang"],
                memory=[],
                input_ids=ids,
                labels=labels,
                prompt_tokens=prefix_len,
                messages=[
                    dict(role="user", content=prompt),
                    dict(role="assistant", content=answer),
                ],
                source=dict(
                    dataset=plan["oasst"]["repository"],
                    revision=plan["oasst"]["revision"],
                    source_split="train",
                    message_id=row["message_id"],
                    parent_id=parent["message_id"],
                    tree_id=group,
                    prompt_sha256=sha(prompt.encode()),
                    answer_sha256=sha(answer.encode()),
                    license=plan["oasst"]["declared_license"],
                    quality=labels_dict(row)["quality"],
                    code_tag="heuristic_not_functional_correctness" if role == "code" else None,
                ),
                training_approved=False,
            )
        )
    return selected, dict(
        official_train_messages=len(train),
        official_validation_messages=len(validation),
        official_validation_trees=len(val_trees),
        official_validation_used_for_training=0,
        source_tree_overlap=0,
        rejected=dict(rejects),
        available_by_bucket=dict(pool),
        quota_shortfalls={k: max(0, v - pool[k]) for k, v in plan["oasst"]["quotas"].items()},
    )


def audit(rows, plan):
    ids, groups, inputs = set(), {}, set()
    counts, tokens, lengths, long_rows = Counter(), Counter(), Counter(), Counter()
    components = {}
    for row in rows:
        require(row["row_id"] not in ids, "Duplicate row")
        ids.add(row["row_id"])
        require(row["memory"] == [] and row["training_approved"] is False, "Candidate policy")
        require(row["split"] in ("train", "dev"), "Unexpected split")
        group, split = row["group_id"], row["split"]
        require(groups.setdefault(group, split) == split, "Group split leakage")
        x, y = row["input_ids"], row["labels"]
        require(len(x) == len(y) and len(x) > 1, "Token/label dimensions")
        require(all(type(t) is int and t >= 0 for t in x), "Non-integer token")
        require(y[0] == -100, "Causal first-token loss")
        require(all(b == -100 or b == a for a, b in zip(x, y)), "Labels differ from tokens")
        target_count = sum(t != -100 for t in y[1:])
        require(target_count > 0, "No supervised targets")
        if row["role"] == "prose":
            require(len(x) <= plan["lm_sequence_tokens"], "LM length")
            require(y[1:] == x[1:] and row["artificial_eos"] is False, "LM mask/EOS")
        else:
            require(row["role"] in ("instruction", "code"), "Unexpected role")
            prefix = row["prompt_tokens"]
            require(0 < prefix < len(x) <= plan["chat_max_tokens"], "Chat length/prefix")
            require(y[:prefix] == [-100] * prefix and y[prefix:] == x[prefix:], "Assistant mask")
            for message in row["messages"]:
                h = text_hash(message["content"])
                require(components.setdefault(h, split) == split, "Prompt/answer split leakage")
        h = sha(canonical(x).encode())
        require(h not in inputs, "Duplicate token sequence")
        inputs.add(h)
        key = f"{split}/{row['role']}/{row['language']}"
        counts[key] += 1
        tokens[key] += target_count
        lengths[key] = max(lengths[key], len(x))
        if len(x) > 128:
            long_rows[key] += 1
    return dict(
        rows=len(rows),
        groups=len(groups),
        rows_by_bucket=dict(counts),
        supervised_tokens_by_bucket=dict(tokens),
        max_tokens_by_bucket=dict(lengths),
        outside_tested_128_query_axis=dict(long_rows),
        memory_tokens=0,
        duplicate_sequences=0,
        group_split_overlap=0,
        prompt_answer_split_overlap=0,
        truncations_of_chat_answers=0,
        training_admissions=0,
        mixture_weights="UNSET",
        functional_code_correctness="UNTESTED",
        preservation_quality="NOT_ESTABLISHED",
        **plan["claim_ceiling"],
    )
