from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from latent_workspace_ft_v10.choice_readout import MistralChoiceReadoutAdapter


class _FakeBoundaryAdapter:
    def __init__(self) -> None:
        torch.manual_seed(7)
        self._kind = "mistral"
        self.base_model = SimpleNamespace(
            model=SimpleNamespace(
                layers=torch.nn.ModuleList([torch.nn.Identity(), torch.nn.Identity()]),
                norm=torch.nn.LayerNorm(4),
            ),
            lm_head=torch.nn.Linear(4, 6, bias=False),
        )

    @staticmethod
    def _run_mistral_layers(
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        layers: torch.nn.ModuleList,
    ) -> torch.Tensor:
        del attention_mask
        for layer in layers:
            hidden = layer(hidden)
        return hidden


def test_native_and_fp32_choices_share_one_normalized_hidden() -> None:
    boundary = _FakeBoundaryAdapter()
    adapter = MistralChoiceReadoutAdapter(boundary)
    hidden = torch.tensor(
        [[[1.0, 2.0, 3.0, 4.0], [4.0, 2.0, 1.0, -1.0]]],
        dtype=torch.float32,
    )
    mask = torch.ones((1, 2), dtype=torch.long)
    state = adapter.decode_choices(hidden, mask, 1, (1, 4))
    normalized_all = boundary.base_model.model.norm(hidden)
    normalized = normalized_all[:, -1:]
    full = boundary.base_model.lm_head(normalized_all)
    expected = full[:, -1:, [1, 4]]
    torch.testing.assert_close(state.native_choice_scores, expected)
    torch.testing.assert_close(state.fp32_choice_scores, expected.float())
    torch.testing.assert_close(state.normalized_last_hidden, normalized)
    assert state.native_logits.shape == (1, 2, 6)
    assert state.fp32_choice_scores.dtype == torch.float32


def test_adapter_rejects_wrong_architecture_and_candidate_contract() -> None:
    boundary = _FakeBoundaryAdapter()
    boundary._kind = "olmo2"
    with pytest.raises(TypeError, match="requires a Mistral"):
        MistralChoiceReadoutAdapter(boundary)

    boundary._kind = "mistral"
    adapter = MistralChoiceReadoutAdapter(boundary)
    hidden = torch.ones((1, 2, 4))
    mask = torch.ones((1, 2), dtype=torch.long)
    with pytest.raises(ValueError, match="two distinct"):
        adapter.decode_choices(hidden, mask, 1, (1, 1))
