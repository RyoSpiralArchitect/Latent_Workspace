"""Opt-in, parameter-matched question/value interaction for the workspace reader.

The historical attention-only reader remains unchanged. This candidate adds
``read * strength * tanh(projected_query)`` before the existing output projection.
It cannot produce a correction without memory, but a nonzero content-free carrier
CAN support query variation: zero-memory identity is not semantic selectivity.
Checkpoint tensor keys stay identical; callers must record the class and strength
separately. This module does not choose an optimizer, loss, model or deployment.
"""

from __future__ import annotations

import math

import torch

from .precision_bridge import PrecisionAwareWorkspaceBridge, _finite, _mask


class QueryModulatedWorkspaceBridge(PrecisionAwareWorkspaceBridge):
    """A bounded multiplicative question route, without new trainable parameters.

    With strength 0.25 each read channel is multiplied by a factor in [0.75,1.25].
    This bounds the pre-projection modulation, NOT the norm of its projected
    contribution relative to the old projected residual. The original smooth
    output cap still applies. Strength zero uses the historical forward exactly.
    Zero-initialized output weights still give zero upstream gradients initially.
    """

    def __init__(self, *args, modulation_strength: float = 0.25, **kwargs):
        if (
            isinstance(modulation_strength, bool)
            or not isinstance(modulation_strength, (int, float))
            or not math.isfinite(modulation_strength)
            or not 0 <= modulation_strength <= 1
        ):
            raise ValueError("modulation_strength must be finite in [0,1]")
        super().__init__(*args, **kwargs)
        self._modulation_strength = float(modulation_strength)

    @property
    def modulation_strength(self) -> float:
        return self._modulation_strength

    def read_delta(self, normalized_last_hidden, memory, mask):
        if self.modulation_strength == 0:
            return super().read_delta(normalized_last_hidden, memory, mask)
        # Keep the historical input/precision contract; never mutate the frozen
        # implementation merely to share an internal helper with this candidate.
        query = normalized_last_hidden
        if query.ndim == 2:
            query = query.unsqueeze(1)
        if query.ndim != 3 or query.shape[1:] != (1, self.hidden_dim):
            raise ValueError("Reader query must have shape [B,1,hidden_dim] or [B,hidden_dim]")
        if (
            memory.ndim != 3
            or memory.shape[0] != query.shape[0]
            or memory.shape[-1] != self.workspace_dim
        ):
            raise ValueError("Reader memory must have shape [B,S,workspace_dim]")
        if query.shape[0] < 1 or memory.shape[1] < 1:
            raise ValueError("Reader inputs must be nonempty")
        if (
            query.device != memory.device
            or not query.is_floating_point()
            or not memory.is_floating_point()
        ):
            raise ValueError("Reader inputs must be floating point on the same device")
        _mask(mask, tuple(memory.shape[:2]), memory.device)
        _finite(query, "Query")
        _finite(memory, "Memory")
        self._validate_parameters(query.device)
        with torch.autocast(device_type=query.device.type, enabled=False):
            projected_query = self.query_norm(self.query_projection(query.float()))
            normalized_memory = self.memory_norm(memory.float())
            read, _ = self.attention(
                projected_query,
                normalized_memory,
                normalized_memory,
                key_padding_mask=~mask.bool(),
                need_weights=False,
            )
            modulated = read * (1.0 + self.modulation_strength * projected_query.tanh())
            raw_delta = self.up(modulated)
            scale = self.max_delta_norm / torch.sqrt(
                self.max_delta_norm**2 + raw_delta.square().sum(dim=-1, keepdim=True)
            )
            delta = raw_delta * scale
        _finite(delta, "Bridge residual")
        return delta
