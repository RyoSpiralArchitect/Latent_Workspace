"""Read-only tracing and causal interventions for the compact FP32 bridge.

The traced production call retains ``need_weights=False``. Attention weights
are reconstructed separately, not obtained by changing the production kernel.
Reconstruction errors must be checked on each runtime; a successful FP32
comparison is a bounded numerical check, not a claim of bitwise identity.
Candidate-head directions are analysis inputs only and never enter the reader.
"""

from __future__ import annotations

import math
from typing import Any

import torch
from torch.nn import functional as F

from .precision_bridge import PrecisionAwareWorkspaceBridge

Trace = dict[str, torch.Tensor]
RECONSTRUCTION_ATOL = 1e-5
RECONSTRUCTION_RTOL = 1e-5


def _supported(bridge: PrecisionAwareWorkspaceBridge) -> None:
    attention = bridge.attention
    if (
        not attention.batch_first
        or not attention._qkv_same_embed_dim
        or attention.in_proj_bias is not None
        or attention.out_proj.bias is not None
        or attention.bias_k is not None
        or attention.bias_v is not None
        or attention.add_zero_attn
        or attention.dropout != 0
        or bridge.up.bias is not None
    ):
        raise ValueError("Trace supports only the bias-free, dropout-free compact reader")


def _heads(value: torch.Tensor, heads: int) -> torch.Tensor:
    batch, tokens, width = value.shape
    return value.reshape(batch, tokens, heads, width // heads).transpose(1, 2)


def _project(
    bridge: PrecisionAwareWorkspaceBridge,
    projected_query: torch.Tensor,
    normalized_memory: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    q_weight, k_weight, v_weight = bridge.attention.in_proj_weight.chunk(3, dim=0)
    heads = bridge.attention.num_heads
    query = _heads(F.linear(projected_query, q_weight), heads)
    keys = _heads(F.linear(normalized_memory, k_weight), heads)
    values = _heads(F.linear(normalized_memory, v_weight), heads)
    logits = torch.matmul(query, keys.transpose(-1, -2)) / math.sqrt(query.shape[-1])
    logits = logits.masked_fill(~mask.bool()[:, None, None, :], -torch.inf)
    weights = logits.softmax(dim=-1)
    return query, keys, values, weights


def _read_from_weights(
    bridge: PrecisionAwareWorkspaceBridge,
    weights: torch.Tensor,
    values: torch.Tensor,
) -> torch.Tensor:
    read = torch.matmul(weights, values).transpose(1, 2).contiguous()
    read = read.reshape(read.shape[0], read.shape[1], bridge.workspace_dim)
    return bridge.attention.out_proj(read)


def _cap(
    bridge: PrecisionAwareWorkspaceBridge,
    raw_delta: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    scale = bridge.max_delta_norm / torch.sqrt(
        bridge.max_delta_norm**2 + raw_delta.square().sum(dim=-1, keepdim=True)
    )
    return raw_delta * scale, scale


@torch.no_grad()
def trace_reader(
    bridge: PrecisionAwareWorkspaceBridge,
    query: torch.Tensor,
    memory: torch.Tensor,
    mask: torch.Tensor,
) -> Trace:
    """Trace one actual reader call plus an independent manual reconstruction.

    Inputs are the production query [B,1,H] (or [B,H]), memory [B,S,D],
    and binary slot mask [B,S]. Returned tensors are detached clones. Hook
    registration is temporary and is removed even if the production call fails.
    The caller must not concurrently call this same bridge from another thread.
    """
    _supported(bridge)
    captured: Trace = {}

    def capture(name: str):
        def hook(_module: Any, _inputs: Any, output: Any) -> None:
            tensor = output[0] if isinstance(output, tuple) else output
            captured[name] = tensor.detach().clone()

        return hook

    handles = [
        bridge.query_norm.register_forward_hook(capture("projected_query")),
        bridge.memory_norm.register_forward_hook(capture("normalized_memory")),
        bridge.attention.register_forward_hook(capture("attention_output")),
        bridge.up.register_forward_hook(capture("raw_delta")),
    ]
    try:
        delta = bridge.read_delta(query, memory, mask)
    finally:
        for handle in handles:
            handle.remove()
    with torch.autocast(device_type=query.device.type, enabled=False):
        q, k, v, weights = _project(
            bridge,
            captured["projected_query"],
            captured["normalized_memory"],
            mask,
        )
        manual_read = _read_from_weights(bridge, weights, v)
        manual_delta, _ = _cap(bridge, bridge.up(manual_read))
        active = mask.float()[:, None, :, None]
        mean_v = (v * active).sum(dim=-2, keepdim=True) / active.sum(dim=-2, keepdim=True)
        mean_read = _read_from_weights(bridge, weights, mean_v.expand_as(v))
        centered_read = _read_from_weights(bridge, weights, v - mean_v)
        mean_raw = bridge.up(mean_read)
        centered_raw = bridge.up(centered_read)
        _, cap_scale = _cap(bridge, captured["raw_delta"])
    captured.update(
        {
            "query": query.unsqueeze(1) if query.ndim == 2 else query,
            "memory": memory,
            "mask": mask.bool(),
            "delta": delta,
            "cap_scale": cap_scale,
            "q_heads": q,
            "k_heads": k,
            "v_heads": v,
            "attention_weights": weights,
            "manual_attention_output": manual_read,
            "manual_delta": manual_delta,
            "mean_value_attention_output": mean_read,
            "centered_value_attention_output": centered_read,
            "mean_value_raw_delta": mean_raw,
            "centered_value_raw_delta": centered_raw,
        }
    )
    return {name: value.detach().clone() for name, value in captured.items()}


def _donor(trace: Trace, donor_trace: Trace | None) -> Trace:
    if donor_trace is None:
        raise ValueError("This intervention requires donor_trace")
    if donor_trace["projected_query"].shape != trace["projected_query"].shape:
        raise ValueError("Donor projected-query shape must match recipient")
    if donor_trace["projected_query"].device != trace["projected_query"].device:
        raise ValueError("Donor and recipient must share a device")
    return donor_trace


@torch.no_grad()
def intervention_delta(
    bridge: PrecisionAwareWorkspaceBridge,
    trace: Trace,
    mode: str,
    donor_trace: Trace | None = None,
    *,
    candidate_axis: torch.Tensor | None = None,
) -> torch.Tensor:
    """Return [B,1,H] under one explicitly localized, analysis-only intervention.

    ``query_zero``/``query_swap`` replace the *normalized projected query* at
    the actual MHA input and retain production ``need_weights=False``.
    ``alternate_query_attention`` transplants separately reconstructed donor
    weights and therefore requires identical recipient/donor memory and masks.
    ``centered_values`` subtracts each head's unmasked-slot V mean before
    attention readout, output projection, up projection, and the original cap.
    ``candidate_axis`` projects the already bounded production delta onto a
    fixed head-weight axis, and cannot increase its norm. No label is accepted.
    """
    _supported(bridge)
    with torch.autocast(device_type=trace["delta"].device.type, enabled=False):
        if mode == "original":
            return trace["delta"].clone()
        if mode == "candidate_axis":
            axis = candidate_axis
            if (
                axis is None
                or axis.ndim != 1
                or axis.shape[0] != bridge.hidden_dim
                or axis.device != trace["delta"].device
                or not torch.isfinite(axis).all()
            ):
                raise ValueError("candidate_axis must be a finite [H] tensor on the trace device")
            axis = axis.float()
            denominator = axis.square().sum()
            if denominator <= 0:
                raise ValueError("candidate_axis must be nonzero")
            return (trace["delta"] * axis).sum(dim=-1, keepdim=True) / denominator * axis
        if mode == "slot_permutation":
            # Reverse K/V slots together, including their mask: this changes no
            # mathematical correspondence and is a numerical negative control.
            permuted_memory = trace["normalized_memory"].flip(1)
            read, _ = bridge.attention(
                trace["projected_query"],
                permuted_memory,
                permuted_memory,
                key_padding_mask=~trace["mask"].flip(1),
                need_weights=False,
            )
        elif mode in {"query_zero", "query_swap"}:
            query = (
                torch.zeros_like(trace["projected_query"])
                if mode == "query_zero"
                else _donor(trace, donor_trace)["projected_query"]
            )
            read, _ = bridge.attention(
                query,
                trace["normalized_memory"],
                trace["normalized_memory"],
                key_padding_mask=~trace["mask"],
                need_weights=False,
            )
        else:
            weights = trace["attention_weights"]
            values = trace["v_heads"]
            if mode == "uniform_attention":
                active = trace["mask"].float()[:, None, None, :]
                weights = (active / active.sum(dim=-1, keepdim=True)).expand_as(weights)
            elif mode == "alternate_query_attention":
                donor = _donor(trace, donor_trace)
                if not torch.equal(
                    trace["normalized_memory"], donor["normalized_memory"]
                ) or not torch.equal(
                    trace["mask"],
                    donor["mask"],
                ):
                    raise ValueError("Alternate-query attention requires identical memory and mask")
                weights = donor["attention_weights"]
            elif mode in {"centered_values", "mean_values"}:
                active = trace["mask"].float()[:, None, :, None]
                mean = (values * active).sum(dim=-2, keepdim=True) / active.sum(
                    dim=-2, keepdim=True
                )
                values = values - mean if mode == "centered_values" else mean.expand_as(values)
            elif mode != "manual_original":
                raise ValueError(f"Unknown reader intervention: {mode}")
            read = _read_from_weights(bridge, weights, values)
        delta, _ = _cap(bridge, bridge.up(read))
    return delta


def _slot_stats(value: torch.Tensor, mask: torch.Tensor) -> dict[str, float | None]:
    # Input [B,S,D] or per-head [B,H,S,D]. All masked slots are excluded.
    if value.ndim == 3:
        value = value[:, None]
    active = mask.float()[:, None, :, None]
    mean = (value * active).sum(dim=-2, keepdim=True) / active.sum(dim=-2, keepdim=True)
    centered = (value - mean) * active
    rms = (centered.square().sum(dim=(-2, -1)) / active.sum(dim=(-2, -1))).sqrt()
    energy = (value.square() * active).sum(dim=(-2, -1)).sqrt()
    ratio = centered.square().sum(dim=(-2, -1)).sqrt() / energy.clamp_min(1e-30)
    with torch.autocast(device_type=value.device.type, enabled=False):
        normalized = F.normalize(value.float(), dim=-1)
        cosine = torch.matmul(normalized, normalized.transpose(-1, -2))
    nonzero = torch.linalg.vector_norm(value, dim=-1) > 0
    pairs = mask[:, None, :, None] & mask[:, None, None, :]
    pairs = pairs & nonzero[..., :, None] & nonzero[..., None, :]
    pairs = pairs & torch.triu(torch.ones_like(cosine, dtype=torch.bool), diagonal=1)
    selected = cosine[pairs]
    return {
        "within_mean_rms": float(rms.mean()),
        "within_mean_per_coordinate_std": float((rms / math.sqrt(value.shape[-1])).mean()),
        "centered_l2_fraction": float(ratio.mean()),
        "slot_mean_l2": float(torch.linalg.vector_norm(mean, dim=-1).mean()),
        "pairwise_cosine_mean": float(selected.mean()) if selected.numel() else None,
        "pairwise_cosine_min": float(selected.min()) if selected.numel() else None,
    }


def parameter_norms(bridge: PrecisionAwareWorkspaceBridge) -> dict[str, float]:
    """L2 norms of individual parameters, without changing their gradients."""
    return {
        name: float(torch.linalg.vector_norm(value.detach()))
        for name, value in bridge.named_parameters()
    }


@torch.no_grad()
def summarize_trace(
    trace: Trace,
    *,
    candidate_head_weight: torch.Tensor | None = None,
    atol: float = RECONSTRUCTION_ATOL,
    rtol: float = RECONSTRUCTION_RTOL,
) -> dict[str, Any]:
    """JSON-safe descriptive metrics; no outcomes or scientific gates inferred.

    ``candidate_head_weight`` is optional [2,H], with margin row1 minus row0.
    Raw/bounded delta scores isolate the bridge contribution, not base logits.
    """
    if not math.isfinite(atol) or not math.isfinite(rtol) or atol < 0 or rtol < 0:
        raise ValueError("Reconstruction tolerances must be finite and nonnegative")
    weights = trace["attention_weights"]
    entropy = -(weights * weights.clamp_min(torch.finfo(weights.dtype).tiny).log()).sum(dim=-1)
    maximum_entropy = trace["mask"].sum(dim=-1).float().log()
    result: dict[str, Any] = {
        "memory": _slot_stats(trace["memory"], trace["mask"]),
        "normalized_memory": _slot_stats(trace["normalized_memory"], trace["mask"]),
        "keys": _slot_stats(trace["k_heads"], trace["mask"]),
        "values": _slot_stats(trace["v_heads"], trace["mask"]),
        "projected_query_l2_mean": float(
            torch.linalg.vector_norm(trace["projected_query"], dim=-1).mean()
        ),
        "attention_entropy_mean": float(entropy.mean()),
        "attention_maximum_entropy_mean": float(maximum_entropy.mean()),
        "attention_entropy_deficit_mean": float((maximum_entropy[:, None, None] - entropy).mean()),
        "attention_max_weight_mean": float(weights.max(dim=-1).values.mean()),
        "attention_output_l2_mean": float(
            torch.linalg.vector_norm(trace["attention_output"], dim=-1).mean()
        ),
        "raw_delta_l2_mean": float(torch.linalg.vector_norm(trace["raw_delta"], dim=-1).mean()),
        "mean_value_raw_delta_l2_mean": float(
            torch.linalg.vector_norm(trace["mean_value_raw_delta"], dim=-1).mean()
        ),
        "centered_value_raw_delta_l2_mean": float(
            torch.linalg.vector_norm(trace["centered_value_raw_delta"], dim=-1).mean()
        ),
        "raw_mean_centered_decomposition_max_abs_error": float(
            (trace["raw_delta"] - trace["mean_value_raw_delta"] - trace["centered_value_raw_delta"])
            .abs()
            .max()
        ),
        "delta_l2_mean": float(torch.linalg.vector_norm(trace["delta"], dim=-1).mean()),
        "cap_scale_mean": float(trace["cap_scale"].mean()),
        "manual_attention_max_abs_error": float(
            (trace["manual_attention_output"] - trace["attention_output"]).abs().max()
        ),
        "manual_delta_max_abs_error": float((trace["manual_delta"] - trace["delta"]).abs().max()),
        "manual_attention_allclose": bool(
            torch.allclose(
                trace["manual_attention_output"], trace["attention_output"], atol=atol, rtol=rtol
            )
        ),
        "manual_delta_allclose": bool(
            torch.allclose(trace["manual_delta"], trace["delta"], atol=atol, rtol=rtol)
        ),
        "reconstruction_atol": atol,
        "reconstruction_rtol": rtol,
    }
    if candidate_head_weight is not None:
        head = candidate_head_weight
        if (
            head.shape != (2, trace["delta"].shape[-1])
            or head.device != trace["delta"].device
            or not torch.isfinite(head).all()
        ):
            raise ValueError("candidate_head_weight must be finite [2,H] on the trace device")
        with torch.autocast(device_type=head.device.type, enabled=False):
            for name in ("raw_delta", "delta"):
                scores = F.linear(trace[name], head.float()).squeeze(1)
                result[f"{name}_candidate_scores"] = scores.tolist()
                result[f"{name}_candidate_margin"] = (scores[:, 1] - scores[:, 0]).tolist()
    return result
