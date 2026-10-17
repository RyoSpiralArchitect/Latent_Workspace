"""The LTWS inference package: rendering, export/load and the latent-memory API (tiny)."""

import json

import pytest
import torch
from test_v15_full_update import tiny

from latent_workspace import DecoderHost, composition, package
from scripts import v15_assay_summary


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(before)


FACTS = (
    "World facts. The ranking is transitive.\n- Cy is ranked above Di.\n- Ann is ranked above Bo."
)


def test_canonical_facts_are_v15s():
    cases = [FACTS, FACTS + "\n", "H\n- b\n- a\n- c"]
    for text in cases:
        for reverse in (False, True):
            ours = package.canonical_facts(text, reverse)
            assert ours == v15_assay_summary.canonical_facts(text, reverse)
    for bad in ("H", "H\n- a\n- a", "H\n a", " H\n- a", "H\r\n- a"):
        with pytest.raises(ValueError):
            package.canonical_facts(bad)
        with pytest.raises(ValueError):
            v15_assay_summary.canonical_facts(bad)


class StubTokenizer:
    """A chat tokenizer over a 43-token vocabulary: BOS is 1, characters map to 2..41."""

    bos_token_id = 1

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        assert len(messages) == 1 and messages[0]["role"] == "user" and add_generation_prompt
        text = "<s>[INST] " + messages[0]["content"] + " [/INST]"
        return self.encode(text, add_special_tokens=False) if tokenize else text

    def encode(self, text, add_special_tokens):
        assert add_special_tokens is False
        head = [1] if text.startswith("<s>") else []
        body = text[3:] if head else text
        return head + [2 + ord(c) % 40 for c in body]


def test_questions_and_memories_render_by_the_contract():
    tokenizer = StubTokenizer()
    query = "Is Ann ranked above Di? Answer:"
    ids = package.render_question(tokenizer, query)
    text = "<s>[INST] " + package.INSTRUCTION + "\n\n" + query + " [/INST]"
    assert ids == tokenizer.encode(text, add_special_tokens=False)
    with pytest.raises(ValueError, match="Answer"):
        package.render_question(tokenizer, "Is Ann ranked above Di?")
    memory = package.render_memory(tokenizer, FACTS)
    assert memory == tokenizer.encode(package.canonical_facts(FACTS), add_special_tokens=False)


def tiny_route(seed):
    route = composition.DeliberationRoute(
        16, 43, (6, 7), steps=2, seed=seed, workspace_dim=8, heads=2, rank=4
    )
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for name in ("adapter.up.weight", "gate.weight", "lattice.attention.out.weight"):
            parameter = route.get_parameter(name)
            parameter.copy_(0.3 * torch.randn(parameter.shape, generator=generator))
    return route.eval()


def descriptor(cut=1):
    return dict(
        name="tiny",
        host=dict(repository="tiny", revision="none", layers=2),
        memory=dict(cut=cut),
        candidates=[" no", " yes"],
        candidate_ids=[6, 7],
        prompt=dict(instruction=package.INSTRUCTION, query_suffix=package.QUERY_SUFFIX),
        route=dict(
            hidden_dim=16,
            vocab_size=43,
            steps=2,
            workspace_dim=8,
            attention_heads=2,
            ff_multiplier=2.0,
            dropout=0.05,
            rank=4,
            gate_init_bias=-2.0,
        ),
    )


def test_export_and_load_reproduce_the_routes_and_reject_tampering(tmp_path):
    routes = {"s1": (tiny_route(1), "seed 1"), "s2": (tiny_route(2), "seed 2")}
    written = package.export(tmp_path / "pkg", routes, descriptor())
    assert [m["name"] for m in written["members"]] == ["s1", "s2"]
    loaded_descriptor, loaded = package.load(tmp_path / "pkg")
    assert loaded_descriptor == json.loads((tmp_path / "pkg" / "descriptor.json").read_text())
    hidden = torch.randn(3, 5, 16, generator=torch.Generator().manual_seed(4))
    mask = torch.ones(3, 5, dtype=torch.long)
    for name, (route, _) in routes.items():
        assert torch.equal(loaded[name](hidden, mask)[0], route(hidden, mask)[0])
        assert not loaded[name].training
    with pytest.raises(FileExistsError):
        package.export(tmp_path / "pkg", routes, descriptor())
    (tmp_path / "pkg" / "extra.txt").write_text("x")
    with pytest.raises(ValueError, match="manifest"):
        package.load(tmp_path / "pkg")
    (tmp_path / "pkg" / "extra.txt").unlink()
    path = tmp_path / "pkg" / "route_s2.safetensors"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="route_s2"):
        package.load(tmp_path / "pkg")
    with pytest.raises(ValueError, match="schema"):
        package.export(tmp_path / "other", routes, dict(descriptor(), schema="x"))


def test_latent_memory_reads_like_the_composition():
    base, _, _ = tiny(torch.float32)
    host = DecoderHost(base.eval().requires_grad_(False))
    routes = {"s1": tiny_route(1), "s2": tiny_route(2)}
    reader = package.LatentMemory(host, StubTokenizer(), descriptor(cut=1), routes)
    query = "Is Ann ranked above Di? Answer:"
    memory = reader.write(FACTS)
    result = reader.read(query, memory)
    ids = torch.tensor([package.render_question(StubTokenizer(), query)])
    q = host.to_cut(ids, torch.ones_like(ids), 1)
    memory_ids = torch.tensor([package.render_memory(StubTokenizer(), FACTS)])
    m = host.to_cut(memory_ids, torch.ones_like(memory_ids), 1)
    prefix = composition.CutPrefixRoute(host, 1)
    with torch.no_grad():
        final, logits, _ = prefix(
            q, torch.ones_like(ids), m, torch.ones(m.shape[:2], dtype=torch.long)
        )
    states = final[0, m.shape[1] :]
    assert torch.equal(result["host"], logits[0, -1, [6, 7]].float())
    assert torch.equal(result["question_states"], states)
    for name, route in routes.items():
        with torch.no_grad():
            expected = (
                result["host"]
                + route(states[None].float(), torch.ones(1, states.shape[0], dtype=torch.long))[0][
                    0
                ]
            )
        assert torch.equal(result["members"][name], expected)
    assert torch.allclose(result["mean"], (result["members"]["s1"] + result["members"]["s2"]) / 2)
    assert result["answer"] in ("no", "yes")
    alone = reader.read(query)
    with torch.no_grad():
        native = host.logits(ids, torch.ones_like(ids))[0, -1, [6, 7]].float()
    assert torch.equal(alone["host"], native)
    assert not torch.equal(alone["host"], result["host"])
