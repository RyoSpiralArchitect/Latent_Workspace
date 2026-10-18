#!/usr/bin/env python3
"""Blind pairwise LLM judging of the β's free-generation answers, through providers' APIs.

Reads ``generations.jsonl`` from ``generate_ltws_beta_examples.py`` and the same BoolQ file;
each passage is checked against its recorded SHA-256. Each question's answers are compared in
three pairs:

- latent memory vs closed book (the main comparison);
- latent memory vs the passage in the prompt (how close to the usual way);
- the passage in the prompt vs closed book (a control: the judge should see the passage used).

Each pair is judged in both presentation orders, AB and BA. The judge sees the passage, the
question, the gold answer and the two answers, never how the answers were produced.

A judge's preference on a pair counts only when both orders are valid and agree once mapped
back to conditions. Orders that disagree are an order conflict; an invalid or missing order
leaves the pair unjudged. Neither is a tie.

Keys come only from the provider's environment variable and are never recorded. Requests are
POSTed without following redirects. Transient failures (HTTP 408/409/425/429/5xx, timeouts,
connection errors) are retried with backoff, and every attempt is counted; any other HTTP error
stops that judge. A judgment the provider returns is recorded once, valid or invalid, and never
re-asked.

Subcommands:

- ``prepare``: write the plan and the request list into a new folder;
- ``models``: list a provider's model IDs (to pin a judge);
- ``run``: one judge, resumable (requests with a recorded judgment are skipped);
- ``summarize``: per judge and across the panel.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PAIRS = (("latent", "closed"), ("latent", "prompt"), ("prompt", "closed"))
ORDERS = ("AB", "BA")
TEMPLATE = """You are comparing two answers to a yes/no question about a passage.

Passage:
\"\"\"
{passage}
\"\"\"

Question: {question}
Correct answer: {gold}

Answer A:
\"\"\"
{answer_a}
\"\"\"

Answer B:
\"\"\"
{answer_b}
\"\"\"

Decide which answer is better.
- First, correctness: an answer that reaches the correct yes/no verdict is better than one \
that does not.
- Then, faithfulness: prefer the explanation that agrees with the passage and makes fewer \
false or unsupported claims.
- Style and length matter only if the answers are otherwise equal.
- Some answers stop mid-sentence at a length limit; do not count that against them.
- If neither answer is better, answer "tie".

Reply with only a JSON object: {{"better": "A" or "B" or "tie", "reason": "<one sentence>"}}"""
SCHEMA = {
    "type": "object",
    "properties": {
        "better": {"type": "string", "enum": ["A", "B", "tie"]},
        "reason": {"type": "string"},
    },
    "required": ["better", "reason"],
    "additionalProperties": False,
}
PROVIDERS = {
    "openai": dict(
        env="OPENAI_API_KEY",
        endpoint="https://api.openai.com/v1/responses",
        models="https://api.openai.com/v1/models",
    ),
    "gemini": dict(
        env="GEMINI_API_KEY",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        models="https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
    ),
    "anthropic": dict(
        env="ANTHROPIC_API_KEY",
        endpoint="https://api.anthropic.com/v1/messages",
        models="https://api.anthropic.com/v1/models?limit=1000",
    ),
    "mistral": dict(
        env="MISTRAL_API_KEY",
        endpoint="https://api.mistral.ai/v1/chat/completions",
        models="https://api.mistral.ai/v1/models",
    ),
}
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}
ATTEMPTS = 6


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def now():
    return datetime.now(UTC).isoformat()


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def prompts(generations, boolq):
    """Every request, in a fixed order, with its prompt (rebuilt from the inputs)."""
    rows = read_jsonl(boolq)
    out = []
    for record in read_jsonl(generations):
        passage = rows[record["index"]]["passage"]
        if sha256(passage) != record["passage_sha256"]:
            raise SystemExit(f"Passage {record['index']} differs from the generation run's")
        for x, y in PAIRS:
            for order in ORDERS:
                a, b = (x, y) if order == "AB" else (y, x)
                prompt = TEMPLATE.format(
                    passage=passage,
                    question=record["question"],
                    gold=record["label"].capitalize(),
                    answer_a=record["answers"][a]["text"],
                    answer_b=record["answers"][b]["text"],
                )
                request = dict(
                    request_id=f"q{record['index']:04d}-{x}-{y}-{order}",
                    index=record["index"],
                    pair=f"{x}-vs-{y}",
                    order=order,
                    a=a,
                    b=b,
                    prompt_sha256=sha256(prompt),
                )
                out.append((request, prompt))
    return out


def headers(provider, key):
    if provider == "gemini":
        return {"x-goog-api-key": key}
    if provider == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": "Bearer " + key}


def body(provider, model, prompt, options):
    limit = options["max_output_tokens"]
    if provider == "openai":
        out = dict(
            model=model,
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=limit,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "judgment",
                    "strict": True,
                    "schema": SCHEMA,
                }
            },
        )
        if options.get("effort"):
            out["reasoning"] = {"effort": options["effort"]}
        return out
    if provider == "gemini":
        config = dict(
            candidateCount=1,
            maxOutputTokens=limit,
            responseMimeType="application/json",
            responseJsonSchema=SCHEMA,
        )
        if options.get("effort"):
            config["thinkingConfig"] = {
                "thinkingLevel": options["effort"].upper(),
                "includeThoughts": False,
            }
        return dict(
            contents=[{"role": "user", "parts": [{"text": prompt}]}], generationConfig=config
        )
    if provider == "anthropic":
        out = dict(model=model, max_tokens=limit, messages=[{"role": "user", "content": prompt}])
        if options.get("temperature") is not None:
            out["temperature"] = options["temperature"]
        return out
    out = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=limit,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "judgment", "strict": True, "schema": SCHEMA},
        },
    )
    if options.get("temperature") is not None:
        out["temperature"] = options["temperature"]
    return out


def reply(provider, raw):
    """(text, finish, finished, returned model, usage, response id) from a provider's response."""
    if provider == "openai":
        text = "".join(
            part.get("text", "")
            for item in raw.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        finish = raw.get("status")
        return (
            text,
            finish,
            finish == "completed",
            raw.get("model"),
            raw.get("usage"),
            raw.get("id"),
        )
    if provider == "gemini":
        candidate = (raw.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        finish = candidate.get("finishReason")
        return (
            text,
            finish,
            finish == "STOP",
            raw.get("modelVersion"),
            raw.get("usageMetadata"),
            raw.get("responseId"),
        )
    if provider == "anthropic":
        text = "".join(
            part.get("text", "") for part in raw.get("content", []) if part.get("type") == "text"
        )
        finish = raw.get("stop_reason")
        return text, finish, finish == "end_turn", raw.get("model"), raw.get("usage"), raw.get("id")
    choice = (raw.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if part.get("type") == "text")
    finish = choice.get("finish_reason")
    return text, finish, finish == "stop", raw.get("model"), raw.get("usage"), raw.get("id")


def judgment(text):
    """The judge's JSON object, read strictly first, then from the first {...} in the text."""
    lenient = False
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        lenient = True
        try:
            data = json.loads(match.group(0)) if match else None
        except ValueError:
            data = None
    if (
        not isinstance(data, dict)
        or data.get("better") not in ("A", "B", "tie")
        or not isinstance(data.get("reason"), str)
    ):
        return None, lenient
    return dict(better=data["better"], reason=data["reason"]), lenient


def opener():
    try:
        import certifi
    except ImportError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))


def call(url, payload, extra_headers, timeout=240, method="POST"):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **extra_headers}
    )
    with opener().open(request, timeout=timeout) as response:
        return json.loads(response.read())


def key_for(provider):
    key = os.environ.get(PROVIDERS[provider]["env"])
    if not key:
        raise SystemExit(f"{PROVIDERS[provider]['env']} is not set; no request was sent")
    return key


def judge_label(provider, model):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}_{model}")


def prepare(args):
    if args.out.exists():
        raise SystemExit(f"Refusing to write into an existing path: {args.out}")
    items = prompts(args.generations, args.boolq)
    args.out.mkdir(parents=True)
    with (args.out / "REQUESTS.jsonl").open("w") as handle:
        for request, _ in items:
            handle.write(json.dumps(request, sort_keys=True) + "\n")
    write_json(
        args.out / "PLAN.json",
        dict(
            generations_sha256=sha256(args.generations.read_bytes()),
            boolq_sha256=sha256(args.boolq.read_bytes()),
            template=TEMPLATE,
            template_sha256=sha256(TEMPLATE),
            schema=SCHEMA,
            pairs=[f"{x}-vs-{y}" for x, y in PAIRS],
            orders=list(ORDERS),
            questions=len(items) // (len(PAIRS) * len(ORDERS)),
            requests=len(items),
            requests_sha256=sha256((args.out / "REQUESTS.jsonl").read_bytes()),
            prompt_characters=sum(len(prompt) for _, prompt in items),
            prepared_at=now(),
        ),
    )
    print(f"{len(items)} requests, {sum(len(p) for _, p in items):,} prompt characters")


def models(args):
    provider = args.provider
    raw = call(
        PROVIDERS[provider]["models"], None, headers(provider, key_for(provider)), method="GET"
    )
    rows = raw.get("data") or raw.get("models") or []
    for row in rows:
        print(row.get("id") or row.get("name"), row.get("created") or row.get("created_at") or "")


def run(args):
    plan = json.loads((args.folder / "PLAN.json").read_text())
    if sha256(args.generations.read_bytes()) != plan["generations_sha256"]:
        raise SystemExit("The generations file differs from the plan's")
    if sha256(args.boolq.read_bytes()) != plan["boolq_sha256"]:
        raise SystemExit("The BoolQ file differs from the plan's")
    if sha256(TEMPLATE) != plan["template_sha256"]:
        raise SystemExit("The judge template differs from the plan's")
    planned = read_jsonl(args.folder / "REQUESTS.jsonl")
    items = prompts(args.generations, args.boolq)
    if [request for request, _ in items] != planned:
        raise SystemExit("The rebuilt requests differ from the plan's")
    provider, model = args.provider, args.model
    key = key_for(provider)
    label = judge_label(provider, model)
    options = dict(
        max_output_tokens=args.max_output_tokens,
        effort=args.effort,
        temperature=args.temperature,
    )
    folder = args.folder / "judges" / label
    folder.mkdir(parents=True, exist_ok=True)
    setting = dict(
        provider=provider,
        model=model,
        options=options,
        endpoint=PROVIDERS[provider]["endpoint"].format(model=model),
        key_source=PROVIDERS[provider]["env"] + " (environment only, not recorded)",
    )
    setting_path = folder / "SETTING.json"
    if setting_path.exists():
        if json.loads(setting_path.read_text()) != setting:
            raise SystemExit("This judge's setting differs from its recorded one")
    else:
        write_json(setting_path, setting)
    calls_path, raw_path = folder / "calls.jsonl", folder / "raw.jsonl"
    done = set()
    if calls_path.exists():
        done = {row["request_id"] for row in read_jsonl(calls_path) if row["status"] != "failed"}
    pending = [(r, p) for r, p in items if r["request_id"] not in done][: args.limit]
    print(f"{label}: {len(done)} recorded, dispatching {len(pending)}", flush=True)
    lock, stop = threading.Lock(), threading.Event()
    counts = Counter()
    url = setting["endpoint"]
    extra = headers(provider, key)

    def one(item):
        request, prompt = item
        if stop.is_set():
            return
        payload = body(provider, model, prompt, options)
        started, attempts, raw, failure = now(), 0, None, None
        while attempts < ATTEMPTS and not stop.is_set():
            attempts += 1
            try:
                raw = call(url, payload, extra)
                break
            except urllib.error.HTTPError as error:
                if error.code not in TRANSIENT:
                    failure = f"http_{error.code}"
                    stop.set()
                    break
                failure = f"http_{error.code}"
                wait = error.headers.get("retry-after") if error.headers else None
                delay = float(wait) if wait and wait.replace(".", "", 1).isdigit() else 0
            except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as error:
                failure = type(error).__name__
                delay = 0
            if attempts < ATTEMPTS:
                time.sleep(max(delay, min(60, 2**attempts)))
        row = dict(
            request,
            judge=label,
            provider=provider,
            model_requested=model,
            attempts=attempts,
            started_at=started,
            finished_at=now(),
        )
        if raw is None:
            row.update(status="failed", failure=failure)
        else:
            text, finish, finished, returned, usage, response_id = reply(provider, raw)
            verdict, lenient = judgment(text)
            row.update(
                status="valid" if verdict and finished else "invalid",
                finish=finish,
                model_returned=returned,
                usage=usage,
                response_id=response_id,
                text=text,
                lenient_parse=lenient,
                **(verdict or {}),
            )
        with lock:
            with calls_path.open("a") as handle:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            if raw is not None:
                with raw_path.open("a") as handle:
                    handle.write(
                        json.dumps(
                            dict(request_id=request["request_id"], response=raw),
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            counts[row["status"]] += 1
            total = sum(counts.values())
            if total % 50 == 0 or total == len(pending):
                print(f"{label}: {total}/{len(pending)} {dict(counts)}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, pending))
    print(json.dumps(dict(judge=label, counts=dict(counts), halted=stop.is_set())), flush=True)
    if stop.is_set():
        raise SystemExit(1)


def outcome(calls, request_ids):
    """One judge's result on one pair: x, y, tie, conflict or unjudged."""
    winners = []
    for request_id in request_ids:
        row = calls.get(request_id)
        if not row or row["status"] != "valid":
            return "unjudged"
        winners.append({"A": row["a"], "B": row["b"], "tie": "tie"}[row["better"]])
    return winners[0] if winners[0] == winners[1] else "conflict"


def tokens(usage):
    """(input, output) tokens from any provider's usage record."""
    usage = usage or {}
    taken = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount")))
    given = usage.get(
        "output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount"))
    )
    given = (given or 0) + (usage.get("thoughtsTokenCount") or 0)
    return taken or 0, given


def summarize(args):
    plan = json.loads((args.folder / "PLAN.json").read_text())
    planned = read_jsonl(args.folder / "REQUESTS.jsonl")
    generations = {r["index"]: r for r in read_jsonl(args.generations)}
    if sha256(args.generations.read_bytes()) != plan["generations_sha256"]:
        raise SystemExit("The generations file differs from the plan's")
    judges = {}
    for folder in sorted((args.folder / "judges").iterdir()):
        rows = read_jsonl(folder / "calls.jsonl") if (folder / "calls.jsonl").exists() else []
        latest = {}
        for row in rows:
            if row["status"] != "failed" or row["request_id"] not in latest:
                latest[row["request_id"]] = row
        judges[folder.name] = latest
    indices = sorted({r["index"] for r in planned})
    per_item = {}
    report = dict(plan_requests=len(planned), judges={}, panel={})
    for name, calls in judges.items():
        statuses = Counter(
            calls[r["request_id"]]["status"] if r["request_id"] in calls else "missing"
            for r in planned
        )
        returned = sorted(
            {str(row.get("model_returned")) for row in calls.values() if row["status"] != "failed"}
        )
        used = [tokens(row.get("usage")) for row in calls.values() if row["status"] != "failed"]
        report["judges"][name] = dict(
            calls=dict(statuses),
            models_returned=returned,
            input_tokens=sum(u[0] for u in used),
            output_tokens=sum(u[1] for u in used),
            pairs={},
        )
        for x, y in PAIRS:
            pair = f"{x}-vs-{y}"
            tally = Counter()
            for index in indices:
                ids = [f"q{index:04d}-{x}-{y}-{order}" for order in ORDERS]
                result = outcome(calls, ids)
                tally[result] += 1
                per_item.setdefault((index, pair), {})[name] = result
            report["judges"][name]["pairs"][pair] = {
                key: tally.get(key, 0) for key in (x, y, "tie", "conflict", "unjudged")
            }
    for x, y in PAIRS:
        pair = f"{x}-vs-{y}"
        majority, unanimous = Counter(), Counter()
        for index in indices:
            results = per_item.get((index, pair), {})
            votes = Counter(results.values())
            top, count = votes.most_common(1)[0] if votes else ("unjudged", 0)
            majority[top if count * 2 > len(judges) else "no_majority"] += 1
            if len(results) == len(judges) and count == len(judges):
                unanimous[top] += 1
        keys = (x, y, "tie", "conflict", "unjudged", "no_majority")
        report["panel"][pair] = dict(
            majority={key: majority.get(key, 0) for key in keys},
            unanimous={key: unanimous.get(key, 0) for key in (x, y, "tie", "conflict")},
        )
    main = "latent-vs-closed"
    by_verdicts = {}
    for index in indices:
        record = generations[index]
        right = tuple(
            record["answers"][c]["verdict"] == record["label"] for c in ("latent", "closed")
        )
        cell = {
            (True, True): "both right",
            (True, False): "only latent right",
            (False, True): "only closed right",
            (False, False): "both wrong",
        }[right]
        for name in judges:
            result = per_item.get((index, main), {}).get(name, "unjudged")
            by_verdicts.setdefault(name, {}).setdefault(cell, Counter())[result] += 1
    report["latent_vs_closed_by_verdicts"] = {
        name: {cell: dict(tally) for cell, tally in cells.items()}
        for name, cells in by_verdicts.items()
    }
    report["per_item"] = {
        f"q{index:04d}": {
            pair: per_item.get((index, pair), {}) for pair in (f"{x}-vs-{y}" for x, y in PAIRS)
        }
        for index in indices
    }
    write_json(args.folder / "SUMMARY.json", report)
    print(json.dumps({k: report[k] for k in ("judges", "panel")}, indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    step = commands.add_parser("prepare")
    step.add_argument("--generations", type=Path, required=True)
    step.add_argument("--boolq", type=Path, required=True)
    step.add_argument("--out", type=Path, required=True)
    step = commands.add_parser("models")
    step.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    step = commands.add_parser("run")
    step.add_argument("--folder", type=Path, required=True)
    step.add_argument("--generations", type=Path, required=True)
    step.add_argument("--boolq", type=Path, required=True)
    step.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    step.add_argument("--model", required=True)
    step.add_argument("--effort", default=None, help="reasoning effort or thinking level")
    step.add_argument("--temperature", type=float, default=None)
    step.add_argument("--max-output-tokens", type=int, default=4000)
    step.add_argument("--workers", type=int, default=8)
    step.add_argument("--limit", type=int, default=None, help="dispatch at most this many")
    step = commands.add_parser("summarize")
    step.add_argument("--folder", type=Path, required=True)
    step.add_argument("--generations", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "models": models, "run": run, "summarize": summarize}[args.command](args)


if __name__ == "__main__":
    main()
