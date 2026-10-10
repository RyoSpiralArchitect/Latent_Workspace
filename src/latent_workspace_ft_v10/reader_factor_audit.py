"""Offline-style tensor diagnostics, not a new reader or evaluation policy.

Four corners are ordered [even/original, even/twin, odd/original, odd/twin].
Q and M use -1/+1 coding. I is one quarter of the mixed finite difference.
All arithmetic here is FP64 and must not be presented as native model output.
"""

from __future__ import annotations

import torch

NAMES = ("common", "question", "memory", "interaction")
SIGNS = ((1, 1, 1, 1), (-1, -1, 1, 1), (-1, 1, -1, 1), (1, -1, -1, 1))


def norm(value):
    return float(value.detach().double().norm())


def ratio(a, b):
    return a / b if b else None


def factors(corners):
    if corners.ndim != 2 or corners.shape[0] != 4 or not torch.isfinite(corners).all():
        raise ValueError("Four finite flattened corners required")
    values = corners.detach().double()
    return {
        name: sum(v * s for v, s in zip(values, signs, strict=True)) / 4
        for name, signs in zip(NAMES, SIGNS, strict=True)
    }


def reconstruct(parts):
    return torch.stack(
        [
            sum(parts[name] * signs[i] for name, signs in zip(NAMES, SIGNS, strict=True))
            for i in range(4)
        ]
    )


def cap64(value, cap):
    value = value.double()
    return value * cap / torch.sqrt(cap**2 + value.square().sum(-1, keepdim=True))


def cap_jvp64(point, direction, cap):
    point, direction = point.double(), direction.double()
    square = cap**2 + point.square().sum()
    scale = cap / square.sqrt()
    return scale * (direction - point * (point * direction).sum() / square)


def modulation_interaction(reads, gates):
    """Separate propagated old interaction from memory-main × question-gate.

    Gates are the exact two FP32 0.25*tanh(q) vectors captured on the execution
    device then promoted to FP64. The prediction ignores final FP32 add/multiply
    rounding, which must be recorded against the actual production z corners.
    """
    if gates.shape != (2, reads.shape[-1]):
        raise ValueError("One gate per question, no memory-side gate")
    parts = factors(reads)
    average, difference = (gates[0] + gates[1]) / 2, (gates[1] - gates[0]) / 2
    return {
        "propagated_interaction": parts["interaction"] * (1 + average),
        "memory_question_coupling": parts["memory"] * difference,
    }


def spectral(operator, axis):
    if operator.ndim != 2 or axis.shape != (operator.shape[0],):
        raise ValueError("Output operator and fixed head axis shape differ")
    if not torch.isfinite(operator).all() or not torch.isfinite(axis).all():
        raise ValueError("Nonfinite operator/axis")
    left, singular, right = torch.linalg.svd(operator.double(), full_matrices=False)
    energy = singular.square()
    total = float(energy.sum())
    probs = energy / total if total else torch.zeros_like(energy)
    positive = probs[probs > 0]
    ks = [k for k in (1, 2, 4, 8, 16, 32, 64, 128, 256) if k <= len(singular)]
    return (
        left,
        right,
        {
            "singular_values": singular.tolist(),
            "top_k_frobenius_energy_fraction": {
                str(k): ratio(float(energy[:k].sum()), total) for k in ks
            },
            "participation_rank": ratio(total**2, float(energy.square().sum())),
            "entropy_effective_rank": float((-(positive * positive.log()).sum()).exp())
            if total
            else None,
            "head_axis_l2": norm(axis),
            "head_pullback_l2": norm(operator.double().T @ axis.double()),
            "svd_max_abs_reconstruction_error": float(
                ((left * singular) @ right - operator.double()).abs().max()
            ),
        },
    )


def vector_stats(value, axis, basis):
    size, axis_size = norm(value), norm(axis)
    dot = float(value @ axis)
    return {
        "l2": size,
        "axis_dot": dot,
        "axis_alignment": ratio(dot, size * axis_size),
        "top1_energy_fraction": ratio(float((basis[:, :1].T @ value).square().sum()), size**2),
        "top8_energy_fraction": ratio(float((basis[:, :8].T @ value).square().sum()), size**2),
    }


def binding_condition(memory_axis, interaction_axis, odd_donor_sign):
    if odd_donor_sign not in (-1, 1):
        raise ValueError("Opposite reciprocal donor signs required")
    signed_interaction = odd_donor_sign * interaction_axis
    return {
        "memory_axis": memory_axis,
        "interaction_axis": interaction_axis,
        "signed_interaction": signed_interaction,
        "required_memory_bias_magnitude": abs(memory_axis),
        "signed_interaction_over_bias": ratio(signed_interaction, abs(memory_axis)),
        "both_donor_margins_positive": signed_interaction > abs(memory_axis),
        "even_donor_margin": 2 * odd_donor_sign * (interaction_axis - memory_axis),
        "odd_donor_margin": 2 * odd_donor_sign * (interaction_axis + memory_axis),
    }


def audit_block(traces, operator, axis, left, right, cap, modulated, odd_sign):
    stacks = {
        key: torch.stack([row[key].reshape(-1) for row in traces]).double()
        for key in ("r", "z", "x", "d")
    }
    parts = {key: factors(value) for key, value in stacks.items()}
    reconstruction = {
        key: float((reconstruct(parts[key]) - value).abs().max()) for key, value in stacks.items()
    }
    pullback = operator.T @ axis
    metrics = {
        key: {
            name: vector_stats(
                v, pullback if key in ("r", "z") else axis, right.T if key in ("r", "z") else left
            )
            for name, v in block.items()
        }
        for key, block in parts.items()
    }
    projection = {
        name: {
            "production_l2_gain": ratio(norm(parts["x"][name]), norm(parts["z"][name])),
            "fp64_projection_vs_production_max_abs": float(
                (operator @ parts["z"][name] - parts["x"][name]).abs().max()
            ),
        }
        for name in NAMES
    }
    cap_rows = []
    for start in (0, 2):
        a, b = stacks["x"][start : start + 2]
        midpoint, direction = (a + b) / 2, b - a
        ideal = cap64(b, cap) - cap64(a, cap)
        production = stacks["d"][start + 1] - stacks["d"][start]
        predicted = cap_jvp64(midpoint, direction, cap)
        scale = cap / float((cap**2 + midpoint.square().sum()).sqrt())
        cap_rows.append(
            {
                "query_offset": start // 2,
                "raw_memory_difference_l2": norm(direction),
                "production_memory_difference_l2": norm(production),
                "ideal64_memory_difference_l2": norm(ideal),
                "ideal64_minus_linearization_l2": norm(ideal - predicted),
                "production_minus_ideal64_l2": norm(production - ideal),
                "tangential_scale": scale,
                "radial_scale": scale**3,
                "raw_axis_gap_change": float(direction @ axis),
                "production_axis_gap_change": float(production @ axis),
            }
        )
    result = {
        "factors": metrics,
        "reconstruction_max_abs": reconstruction,
        "projection": projection,
        "cap": cap_rows,
        "binding": binding_condition(
            metrics["d"]["memory"]["axis_dot"], metrics["d"]["interaction"]["axis_dot"], odd_sign
        ),
    }
    if modulated:
        gates = torch.stack([traces[i]["gate"].reshape(-1) for i in (0, 2)]).double()
        sources = modulation_interaction(stacks["r"], gates)
        predicted = sum(sources.values())
        # A two-operation gamma bound covers FP32 (1 + gate) and multiplication.
        eps = torch.finfo(torch.float32).eps
        bound = 2 * eps / (1 - 2 * eps) * float(stacks["r"].abs().max()) * 1.25
        error = float((predicted - parts["z"]["interaction"]).abs().max())
        if error > bound:
            raise ValueError("Interaction decomposition exceeds prospective rounding bound")
        result["modulation_sources"] = {
            "rounding_error_max_abs": error,
            "rounding_bound_max_abs": bound,
            "sources": {
                name: {
                    "z_l2": norm(v),
                    "projected_l2": norm(operator @ v),
                    "projected_axis_dot": float(pullback @ v),
                }
                for name, v in sources.items()
            },
        }
    return result
