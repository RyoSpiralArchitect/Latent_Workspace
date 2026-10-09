"""Frozen, text-only inputs for the V15 base elicitation diagnostic.

The 32 confirmation cases are fresh total-order families, not a qualified
benchmark. Rendering consumes only inference-available query/context strings;
labels, family identifiers, split membership, and graph metadata cannot enter it.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from numbers import Integral
from pathlib import Path
from typing import Any

from v13_task_fixture import HEADER, NAMES, TEMPLATES, _parse_context, _parse_query, symbolic_oracle

from latent_workspace_ft_v10 import engine
from latent_workspace_ft_v10.reader_query import bind_question_span

REPO = Path(__file__).resolve().parents[1]
SEED = 15001
FAMILIES = 8
WIDTH = 6
SUFFIXES = (" no", " yes")
RENDERERS = ("raw", "native_chat")
INFORMATION = ("query_only", "inline")
PROMPT_SEPARATOR = "\n\n"
SYMMETRIC_INSTRUCTION = (
    "Use the world facts to decide whether the ranking statement is true. "
    "If it is false, answer no; if it is true, answer yes. "
    "Output exactly one lowercase word: no or yes."
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _records(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    _require(bool(rows) and all(isinstance(row, dict) for row in rows), "Missing world records")
    return rows


def known_orders(repo: Path = REPO) -> set[tuple[str, ...]]:
    """Parse every train/eval context graph; ignore untrusted order metadata."""
    orders: set[tuple[str, ...]] = set()
    for split in ("train", "eval"):
        for record in _records(Path(repo) / f"data/v10/functional_{split}.jsonl"):
            contexts = record.get("contexts")
            _require(isinstance(contexts, list) and len(contexts) == 2, "Expected paired contexts")
            for context in contexts:
                order, _ = _parse_context(context)
                _require(len(order) == WIDTH, "Historical total order is not six entities")
                orders.add(tuple(order))
    return orders


def _context(order: Sequence[str], positions: Sequence[int]) -> str:
    return (
        HEADER
        + "\n"
        + "\n".join(f"- {order[index]} is ranked above {order[index + 1]}." for index in positions)
    )


def make_cases(repo: Path = REPO) -> list[dict[str, Any]]:
    """Return four exposed replay cases and 32 frozen fresh confirmation cases.

    Full-order sampling rejects all exact orders parsed from both historical
    corpora and previously accepted confirmation families. A separate RNG draws
    fact serialization; reciprocal labels share identical context bytes. This
    is exact-total-order exclusion, not a claim of disjoint names or relations.
    """
    root = Path(repo)
    historical = _records(root / "data/v10/functional_train.jsonl")
    _require(len(historical) >= 2, "Need the first two exposed worlds")
    excluded = known_orders(root)
    result: list[dict[str, Any]] = []
    for world, record in enumerate(historical[:2]):
        context = record["contexts"][0]
        order, _ = _parse_context(context)
        _require(record.get("choices") == list(SUFFIXES), "Historical answer suffixes changed")
        for query_index in (0, 1):
            query = record["queries"][query_index]
            left, right = _parse_query(query)
            label = symbolic_oracle(context, query)
            _require(
                type(record["answers"][0][query_index]) is int
                and label == record["answers"][0][query_index],
                "Historical label disagrees with the context graph",
            )
            result.append(
                {
                    "case_id": f"w{world}_q{query_index}",
                    "split": "exposed",
                    "family_id": f"historical_w{world}",
                    "view": "historical",
                    "query": query,
                    "context": context,
                    "target_label": label,
                    "hop": abs(order.index(left) - order.index(right)),
                    "wording": "ranked_above" if query.startswith("Is ") else "outrank",
                }
            )

    rng = random.Random(SEED)
    fact_rng = random.Random(SEED ^ 0x15FAC7)
    for family_index in range(FAMILIES):
        for _ in range(1024):
            order = tuple(rng.sample(NAMES, WIDTH))
            if order not in excluded:
                break
        else:
            raise ValueError("Fresh total-order rejection budget exhausted")
        excluded.add(order)
        adjacent = rng.randrange(WIDTH - 1)
        chain_start = rng.randrange(WIDTH - 3)
        fact_positions = list(range(WIDTH - 1))
        fact_rng.shuffle(fact_positions)
        wording = "ranked_above" if family_index % 2 == 0 else "outrank"
        family_id = f"v15-confirmation-seed{SEED}-family{family_index:04d}"
        for view, first, hop, context in (
            ("atomic", adjacent, 1, _context(order, [adjacent])),
            ("full_chain", chain_start, 3, _context(order, fact_positions)),
        ):
            pair = (order[first], order[first + hop])
            for direction, (left, right) in enumerate((pair, pair[::-1])):
                query = TEMPLATES[wording].format(left=left, right=right)
                result.append(
                    {
                        "case_id": f"{family_id}_{view}_d{direction}",
                        "split": "confirmation",
                        "family_id": family_id,
                        "view": view,
                        "query": query,
                        "context": context,
                        "target_label": symbolic_oracle(context, query),
                        "hop": hop,
                        "wording": wording,
                    }
                )
    _require(
        len(result) == 36 and len({row["case_id"] for row in result}) == 36, "Case grid changed"
    )
    return result


def _token_ids(values: Any, description: str) -> list[int]:
    _require(
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes))
        and bool(values)
        and all(
            isinstance(value, Integral) and not isinstance(value, bool) and value >= 0
            for value in values
        ),
        f"{description} must be a nonempty unbatched integer token sequence",
    )
    return [int(value) for value in values]


def render_case(
    tokenizer: Any,
    *,
    query: str,
    context: str,
    renderer: str,
    information: str,
) -> dict[str, Any]:
    """Render unchanged user content raw or through the tokenizer's native chat.

    The chat renderer adds no system message and changes no words. Explicit
    ``add_special_tokens=False`` prevents a second BOS. Full-prefix equality,
    exact one-token suffix extension, and question-span binding are fail-closed;
    neither truncation nor a candidate-boundary fallback is permitted.
    """
    _require(renderer in RENDERERS, "Unknown renderer")
    _require(information in INFORMATION, "Unknown information condition")
    _require(isinstance(query, str) and isinstance(context, str), "Expected query/context strings")
    _parse_query(query)
    _parse_context(context)
    config = engine.DataConfig(
        functional_elicitation="symmetric_instruction", prompt_separator=PROMPT_SEPARATOR
    )
    rendered_query = engine._functional_elicitation_query(query, config)
    _require(
        rendered_query == SYMMETRIC_INSTRUCTION + PROMPT_SEPARATOR + query.strip(),
        "Historical symmetric instruction changed",
    )
    user_content = (
        context + PROMPT_SEPARATOR + rendered_query if information == "inline" else rendered_query
    )
    template = (
        tokenizer.get_chat_template()
        if callable(getattr(tokenizer, "get_chat_template", None))
        else getattr(tokenizer, "chat_template", None)
    )
    _require(isinstance(template, str) and bool(template), "Missing pinned native chat template")
    messages = [{"role": "user", "content": user_content}]
    text = user_content
    native_ids = None
    if renderer == "native_chat":
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        _require(isinstance(text, str), "Native chat did not return text")
        _require(text.count(user_content) == 1, "Native chat changed or duplicated user content")
        encoded_chat = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True
        )
        native_ids = _token_ids(
            encoded_chat.get("input_ids") if isinstance(encoded_chat, Mapping) else encoded_chat,
            "Native chat IDs",
        )
    prompt_ids = _token_ids(tokenizer.encode(text, add_special_tokens=False), "Rendered prefix IDs")
    if native_ids is not None:
        _require(prompt_ids == native_ids, "Native chat text/tokenize routes disagree")
        bos = getattr(tokenizer, "bos_token_id", None)
        _require(
            bos is None or len(prompt_ids) < 2 or prompt_ids[:2] != [bos, bos],
            "Native chat contains a duplicate leading BOS",
        )
    candidate_ids = []
    for suffix in SUFFIXES:
        full = _token_ids(
            tokenizer.encode(text + suffix, add_special_tokens=False), "Answer-extended IDs"
        )
        _require(
            len(full) == len(prompt_ids) + 1 and full[:-1] == prompt_ids,
            f"Answer suffix {suffix!r} is not an exact one-token prefix extension",
        )
        candidate_ids.append(full[-1])
    _require(len(set(candidate_ids)) == 2, "Answer candidates must have distinct token IDs")
    span = bind_question_span(
        tokenizer, raw_query=query, rendered_prefix=text, expected_prefix_ids=prompt_ids
    )
    result = {
        "renderer": renderer,
        "information": information,
        "text": text,
        "user_content": user_content,
        "prompt_ids": prompt_ids,
        "span": asdict(span),
        "candidate_ids": candidate_ids,
        "candidate_suffixes": list(SUFFIXES),
        "chat_template": {
            "sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
            "applied": renderer == "native_chat",
            "add_generation_prompt": renderer == "native_chat",
            "messages": "single_user_no_system" if renderer == "native_chat" else None,
            "native_tokenization_exact": native_ids == prompt_ids if native_ids else None,
        },
    }
    _require(isinstance(result["span"], Mapping), "Missing question span receipt")
    return result
