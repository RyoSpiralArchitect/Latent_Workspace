"""A parameter-matched test of removing the compact reader's slot-mean path.

This changes the reader architecture, not the pretrained decoder or its head.
For bias-free value projection, centering normalized-memory values before that
projection equals per-head value centering in real arithmetic. Floating-point
projection order may differ; the equivalence is tested with explicit tolerances.
Removing this route is a hypothesis test, not a semantic-improvement guarantee.
"""

from __future__ import annotations

import torch

from .precision_bridge import PrecisionAwareWorkspaceBridge, _finite, _mask


class CenteredValueWorkspaceBridge(PrecisionAwareWorkspaceBridge):
    """Identical initialization/state schema, with masked slot-centered values.

    Queries and keys retain the original path. Only values lose the common
    slot mean, preventing the reader from carrying that query-independent mean
    directly into its residual. No parameters, labels, or answer IDs are added.
    A collapsed constant-slot memory consequently loses its signal, rather
    than acquiring an artificial query-dependent output.
    """

    def read_delta(
        self,
        normalized_last_hidden: torch.Tensor,
        memory: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        """Return the original FP32 bounded residual from centered slot values."""
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
            active = mask.float().unsqueeze(-1)
            slot_mean = (normalized_memory * active).sum(dim=1, keepdim=True) / active.sum(
                dim=1, keepdim=True
            )
            centered_values = normalized_memory - slot_mean
            read, _ = self.attention(
                projected_query,
                normalized_memory,
                centered_values,
                key_padding_mask=~mask.bool(),
                need_weights=False,
            )
            raw_delta = self.up(read)
            scale = self.max_delta_norm / torch.sqrt(
                self.max_delta_norm**2 + raw_delta.square().sum(dim=-1, keepdim=True)
            )
            delta = raw_delta * scale
        _finite(delta, "Bridge residual")
        return delta
