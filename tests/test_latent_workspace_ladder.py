"""The Availability ladder instrument recovers planted content and stays at chance on noise."""

import torch

from latent_workspace import ladder


def planted_memory(rows, seed, slots=4, dim=8):
    """Each query names a slot; the answer is the sign that slot carries along ``u``."""
    generator = torch.Generator().manual_seed(seed)
    u = torch.zeros(dim)
    u[0] = 1.0
    kind = torch.randint(0, slots, (rows,), generator=generator)
    signs = torch.randint(0, 2, (rows, slots), generator=generator) * 2 - 1
    memory = 0.3 * torch.randn(rows, slots, dim, generator=generator)
    memory += signs[..., None] * u
    memory[:, :, 1:5] += torch.eye(slots)[None, :, :4]  # slot identity features
    query = torch.eye(slots)[kind]
    label = (signs[torch.arange(rows), kind] > 0).long()
    return dict(query=query, memory=memory, mask=torch.ones(rows, slots), label=label)


def accuracy(predictions, labels):
    return sum(int(p) == int(y) for p, y in zip(predictions, labels.tolist(), strict=True)) / len(
        predictions
    )


def test_attention_probe_recovers_planted_memory_content_and_not_without_it():
    train, test = planted_memory(600, 1), planted_memory(300, 2)
    predictions, _ = ladder.fit_attention_probe(train, test, seed=3, width=16, steps=400, lr=1e-2)
    assert accuracy(predictions, test["label"]) > 0.9
    blind = {**train, "memory": torch.zeros_like(train["memory"])}
    blind_test = {**test, "memory": torch.zeros_like(test["memory"])}
    predictions, _ = ladder.fit_attention_probe(blind, blind_test, seed=3, width=16, steps=400)
    assert 0.35 < accuracy(predictions, test["label"]) < 0.65


def test_attention_probe_is_deterministic_per_seed():
    train, test = planted_memory(100, 4), planted_memory(50, 5)
    first = ladder.fit_attention_probe(train, test, seed=7, width=8, steps=20)
    assert first == ladder.fit_attention_probe(train, test, seed=7, width=8, steps=20)


def test_contrast_probe_finds_a_planted_direction_and_not_noise():
    generator = torch.Generator().manual_seed(6)
    direction = torch.randn(64, generator=generator)

    def contrasts(rows):
        y = torch.randint(0, 2, (rows,), generator=generator)
        x = (2 * y - 1)[:, None] * direction + 2.0 * torch.randn(rows, 64, generator=generator)
        return x, y

    (train_x, train_y), (test_x, test_y) = contrasts(300), contrasts(200)
    predictions = ladder.fit_contrast_probe(train_x, train_y, test_x)
    assert accuracy(predictions, test_y) > 0.9
    assert predictions == ladder.fit_contrast_probe(train_x, train_y, test_x)
    noise = torch.randn(300, 64, generator=generator)
    predictions = ladder.fit_contrast_probe(
        noise, train_y, torch.randn(200, 64, generator=generator)
    )
    assert 0.35 < accuracy(predictions, test_y) < 0.65


def test_pairs_worlds_and_sign_tests_are_exact():
    correct = [True, True, False, True, True, False]
    pairs = {("w0", 0): (0, 1), ("w0", 1): (2, 3), ("w1", 0): (4, 5)}
    assert ladder.pair_following(correct, pairs) == {
        ("w0", 0): True,
        ("w0", 1): False,
        ("w1", 0): False,
    }
    counts = ladder.world_counts([True, True, False, True], [0, 0, 1, 1])
    assert counts == {0: 2, 1: 1}
    test = ladder.sign_test({0: 2, 1: 1, 2: 0}, {0: 1, 1: 1, 2: 1})
    assert test == {"positive": 1, "negative": 1, "zero": 1, "p_one_sided": 0.75}
    chance = ladder.chance_sign_test({0: 2, 1: 2, 2: 1, 3: 2}, 2)
    assert chance == {"positive": 3, "negative": 0, "zero": 1, "p_one_sided": 0.125}


def test_distinguishability_is_a_median_ratio():
    content = [torch.tensor([3.0, 4.0]), torch.tensor([0.0, 1.0]), torch.tensor([6.0, 8.0])]
    form = [torch.tensor([0.0, 1.0]), torch.tensor([0.0, 1.0]), torch.tensor([0.0, 2.0])]
    assert ladder.distinguishability(content, form) == 5.0


def test_ladder_verdict_names_the_lost_rung():
    assert ladder.ladder_verdict(False, True) == "CONTENT_ABSENT_IN_MEMORY"
    assert ladder.ladder_verdict(True, False) == "LOST_IN_READING"
    assert ladder.ladder_verdict(True, True) == "LOST_IN_TRANSPORT"
