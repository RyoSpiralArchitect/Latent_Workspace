"""Architecture-owned native and FP32 choice readout from one decoder state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F


@dataclass(frozen=True, slots=True)
class ChoiceReadoutState:
    """Two readout precisions sharing one upper-decoder execution."""

    native_logits: torch.Tensor
    native_choice_scores: torch.Tensor
    fp32_choice_scores: torch.Tensor
    normalized_last_hidden: torch.Tensor


class MistralChoiceReadoutAdapter:
    """Keep Mistral upper-layer and final-head details outside the assay core."""

    def __init__(self, boundary_adapter: Any) -> None:
        if getattr(boundary_adapter, "_kind", None) != "mistral":
            raise TypeError("MistralChoiceReadoutAdapter requires a Mistral boundary adapter")
        base_model = getattr(boundary_adapter, "base_model", None)
        decoder = getattr(base_model, "model", None)
        if decoder is None or any(
            getattr(decoder, name, None) is None for name in ("layers", "norm")
        ):
            raise TypeError("Mistral decoder layout is incomplete")
        head = getattr(base_model, "lm_head", None)
        if head is None or not isinstance(getattr(head, "weight", None), torch.Tensor):
            raise TypeError("Mistral language-model head is unavailable")
        if not callable(getattr(boundary_adapter, "_run_mistral_layers", None)):
            raise TypeError("Mistral split-layer runner is unavailable")
        self.boundary_adapter = boundary_adapter
        self.base_model = base_model
        self.decoder = decoder
        self.head = head

    def describe(self) -> dict[str, Any]:
        return {
            "architecture": "mistral",
            "upper_decoder": "native_split_adapter_layers",
            "normalization": type(self.decoder.norm).__name__,
            "native_head": "model_lm_head_under_active_autocast",
            "fp32_choice_head": "same_normalized_hidden_and_selected_lm_head_rows_fp32",
        }

    def decode_choices(
        self,
        hidden: torch.Tensor,
        attention_mask: torch.Tensor,
        boundary_layer: int,
        candidate_ids: Sequence[int],
    ) -> ChoiceReadoutState:
        if hidden.ndim != 3 or attention_mask.ndim != 2:
            raise ValueError("Choice readout expects rank-3 hidden and rank-2 attention mask")
        if hidden.shape[:2] != attention_mask.shape:
            raise ValueError("Choice readout hidden and attention shapes differ")
        candidates = tuple(int(value) for value in candidate_ids)
        if len(candidates) != 2 or candidates[0] == candidates[1]:
            raise ValueError("Choice readout requires two distinct candidate token IDs")
        layer_count = len(self.decoder.layers)
        if not 0 <= int(boundary_layer) <= layer_count:
            raise ValueError("Boundary layer lies outside the Mistral decoder")
        if min(candidates) < 0 or max(candidates) >= int(self.head.weight.shape[0]):
            raise ValueError("Candidate token ID lies outside the language-model head")

        upper = self.boundary_adapter._run_mistral_layers(
            hidden,
            attention_mask,
            self.decoder.layers[int(boundary_layer) :],
        )
        normalized = self.decoder.norm(upper)
        normalized_last = normalized[:, -1:].contiguous()
        # Preserve the predecessor's complete sequence/full-vocabulary GEMM shape
        # before selecting the final answer position.  This makes native
        # replication sensitive to any accidental CUDA-kernel shape drift.
        native_logits = self.head(normalized)
        native_choices = (
            native_logits[:, -1:]
            .index_select(
                -1,
                torch.tensor(candidates, device=native_logits.device, dtype=torch.long),
            )
            .float()
        )

        device_type = normalized_last.device.type
        with torch.autocast(device_type=device_type, enabled=False):
            selected_weight = self.head.weight.index_select(
                0,
                torch.tensor(candidates, device=self.head.weight.device, dtype=torch.long),
            ).float()
            selected_bias = None
            if isinstance(getattr(self.head, "bias", None), torch.Tensor):
                selected_bias = self.head.bias.index_select(
                    0,
                    torch.tensor(candidates, device=self.head.bias.device, dtype=torch.long),
                ).float()
            fp32_choices = F.linear(
                normalized_last.float(),
                selected_weight,
                selected_bias,
            )
        if fp32_choices.dtype != torch.float32:
            raise RuntimeError("FP32 choice head did not return float32 scores")
        return ChoiceReadoutState(
            native_logits=native_logits,
            native_choice_scores=native_choices,
            fp32_choice_scores=fp32_choices,
            normalized_last_hidden=normalized_last,
        )
