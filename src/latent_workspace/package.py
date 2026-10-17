"""The LTWS inference package: trained routes, their descriptor, and the latent-memory API.

A package is a folder made from a sealed run's routes. It never holds the host's weights:

- ``route_<name>.safetensors``: one ``composition.DeliberationRoute``'s parameters per
  member.
- ``descriptor.json``: everything needed to rebuild and use the routes. That is each
  route's architecture, the host it reads (repository, revision, base hash), the cut at
  which memory enters, the candidate tokens, the prompt contract, and each member's
  parameter fingerprint and source.
- ``MANIFEST.json``: every other file's bytes and SHA-256.

``load`` rebuilds the routes from the package alone, after checking the manifest and each
route's fingerprint.

``LatentMemory`` answers a yes/no question from facts held as latent memory, as V20 A5's
system does:

- ``write`` runs the canonical fact text alone through the host's layers below the cut,
  once. The result can be cached, and the facts never enter the question's context.
- ``read`` runs the rendered question alone through the same layers, enters the memory
  before it at the cut, and lets the host's remaining layers continue. It returns the
  host's own candidate logits, each member's (host plus its residual) and their mean.

The prompt contract reproduces V15's query-only rendering with the answer cue
(``scripts/v15_cue_contract.py``) and V15's canonical facts
(``scripts/v15_assay_summary.py``). Parity: ``test_canonical_facts_are_v15s`` and the
package check, which renders every final question with the pinned tokenizer and compares
the stored prompt ids.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch

from . import composition, training

SCHEMA = "ltws-package-v1"
INSTRUCTION = (
    "Use the world facts to decide whether the ranking statement is true. "
    "If it is false, answer no; if it is true, answer yes. "
    "Output exactly one lowercase word: no or yes."
)
QUERY_SUFFIX = " Answer:"
ROUTE_KEYS = (
    "hidden_dim",
    "vocab_size",
    "steps",
    "workspace_dim",
    "attention_heads",
    "ff_multiplier",
    "dropout",
    "rank",
    "gate_init_bias",
)


def canonical_facts(text, reverse=False):
    """Sort literal fact lines without labels, preserving their text and header (V15)."""
    if not isinstance(text, str) or type(reverse) is not bool or "\r" in text:
        raise ValueError("Expected LF-separated fact text and a boolean reverse flag")
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("Expected one header followed by nonempty fact lines")
    header, facts = lines[0], lines[1:]
    if not header or header != header.strip() or header.startswith("-"):
        raise ValueError("Expected one nonempty, unindented header")
    if any(
        not line.startswith("- ") or not line[2:] or line[2:] != line[2:].strip() for line in facts
    ):
        raise ValueError("Each fact must be an unmodified nonempty '- ' line")
    if len(set(facts)) != len(facts):
        raise ValueError("Fact lines must be unique")
    return "\n".join([header, *sorted(facts, reverse=reverse)]) + (
        "\n" if text.endswith("\n") else ""
    )


def render_question(tokenizer, query):
    """Token ids of a question as the routes were trained on it: the instruction and the
    query, which ends with the answer cue, as one user turn of the native chat template."""
    if not isinstance(query, str) or not query.endswith(QUERY_SUFFIX):
        raise ValueError(f"A question must end with {QUERY_SUFFIX!r}")
    content = INSTRUCTION + "\n\n" + query
    messages = [{"role": "user", "content": content}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    native = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    if isinstance(native, dict) or hasattr(native, "keys"):
        native = native["input_ids"]
    ids = list(tokenizer.encode(text, add_special_tokens=False))
    if text.count(content) != 1 or not 1 <= len(ids) <= 512:
        raise ValueError("Content/truncation contract")
    if ids != list(native):
        raise ValueError("Native tokenization mismatch")
    if len(ids) >= 2 and ids[:2] == [tokenizer.bos_token_id] * 2:
        raise ValueError("Double BOS")
    return ids


def render_memory(tokenizer, facts):
    """Token ids of a memory: the canonical fact text, without special tokens."""
    return list(tokenizer.encode(canonical_facts(facts), add_special_tokens=False))


# ---- export and load ----------------------------------------------------------------


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_route(spec, candidate_ids, seed=0):
    """A route with the descriptor's architecture (its initial values are overwritten)."""
    return composition.DeliberationRoute(
        spec["hidden_dim"],
        spec["vocab_size"],
        tuple(candidate_ids),
        steps=spec["steps"],
        seed=seed,
        workspace_dim=spec["workspace_dim"],
        heads=spec["attention_heads"],
        ff_multiplier=spec["ff_multiplier"],
        dropout=spec["dropout"],
        rank=spec["rank"],
        gate_init_bias=spec["gate_init_bias"],
    )


def export(path, routes, descriptor):
    """Write a fresh package: ``routes`` maps member name -> (route, source description)."""
    from safetensors.torch import save_file

    path = Path(path)
    if set(descriptor) & {"schema", "members"}:
        raise ValueError("The descriptor's schema and members are written by export")
    if not routes or set(descriptor["route"]) != set(ROUTE_KEYS):
        raise ValueError("Export needs routes and a complete route architecture")
    path.mkdir(parents=True, exist_ok=False)
    members = []
    for name, (route, source) in sorted(routes.items()):
        if not name.isidentifier():
            raise ValueError(f"Member name {name!r}")
        state = {k: v.detach().cpu().contiguous() for k, v in route.state_dict().items()}
        filename = f"route_{name}.safetensors"
        save_file(state, str(path / filename))
        fingerprint = training.fingerprint(training.trainable(route))
        members.append(dict(name=name, file=filename, fingerprint=fingerprint, source=source))
    full = dict(schema=SCHEMA, **descriptor, members=members)
    (path / "descriptor.json").write_text(json.dumps(full, indent=1, ensure_ascii=False) + "\n")
    files = {
        p.name: {"bytes": p.stat().st_size, "sha256": _digest(p)}
        for p in sorted(path.iterdir())
        if p.is_file()
    }
    (path / "MANIFEST.json").write_text(json.dumps(dict(files=files), indent=1) + "\n")
    return full


def load(path):
    """The descriptor and routes (member name -> route, CPU, eval mode) of a package."""
    from safetensors.torch import load_file

    path = Path(path)
    manifest = json.loads((path / "MANIFEST.json").read_text())["files"]
    present = {p.name for p in path.iterdir() if p.is_file()} - {"MANIFEST.json"}
    if present != set(manifest):
        raise ValueError("Package files differ from the manifest")
    for name, entry in manifest.items():
        actual = path / name
        if actual.stat().st_size != entry["bytes"] or _digest(actual) != entry["sha256"]:
            raise ValueError(f"Package file changed: {name}")
    descriptor = json.loads((path / "descriptor.json").read_text())
    if descriptor["schema"] != SCHEMA or descriptor["prompt"]["instruction"] != INSTRUCTION:
        raise ValueError("Package schema or prompt contract differs from this engine")
    routes = {}
    for member in descriptor["members"]:
        route = build_route(descriptor["route"], descriptor["candidate_ids"])
        route.load_state_dict(load_file(str(path / member["file"])), strict=True)
        if training.fingerprint(training.trainable(route)) != member["fingerprint"]:
            raise ValueError(f"Route {member['name']} differs from its fingerprint")
        routes[member["name"]] = route.eval()
    return descriptor, routes


# ---- the latent-memory API ----------------------------------------------------------


class LatentMemory:
    """Facts written into the host at the package's cut, read with the package's routes."""

    def __init__(self, host, tokenizer, descriptor, routes):
        self.host, self.tokenizer = host, tokenizer
        self.cut = int(descriptor["memory"]["cut"])
        self.prefix = composition.CutPrefixRoute(host, self.cut)
        self.candidates = list(descriptor["candidate_ids"])
        self.routes = dict(routes)
        self.device = host.head.weight.device

    def _to_cut(self, ids):
        x = torch.tensor([ids], device=self.device)
        return self.host.to_cut(x, torch.ones_like(x), self.cut)[0]

    @torch.no_grad()
    def write(self, facts):
        """The latent memory of ``facts``: their states at the cut, computed alone."""
        return self._to_cut(render_memory(self.tokenizer, facts))

    @torch.no_grad()
    def read(self, query, memory=None):
        """Candidate logits ([no, yes]) for ``query`` with ``memory`` (or none)."""
        query_states = self._to_cut(render_question(self.tokenizer, query))
        if memory is None:
            memory = query_states[:0]
        ones = torch.ones(1, query_states.shape[0], dtype=torch.long, device=self.device)
        memory_mask = torch.ones(1, memory.shape[0], dtype=torch.long, device=self.device)
        final, logits, _ = self.prefix(query_states[None], ones, memory[None], memory_mask)
        hidden = final[0, memory.shape[0] :].detach().cpu()
        host = logits[0, -1, self.candidates].float().cpu()
        members = {}
        mask = torch.ones(1, hidden.shape[0], dtype=torch.long)
        for name, route in self.routes.items():
            route.eval()
            residual = route(hidden[None].float(), mask)[0][0]
            members[name] = host + residual
        mean = sum(members.values()) / len(members) if members else host
        return dict(
            host=host,
            members=members,
            mean=mean,
            answer="yes" if mean[1] > mean[0] else "no",
            question_states=hidden,
        )
