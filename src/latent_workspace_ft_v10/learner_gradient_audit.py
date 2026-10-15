"""Read-only, loss-specific gradient diagnostics for the compact workspace bridge.

No optimizer, backwards-to-``.grad``, parameter update, or new loss is introduced.
Autograd differentiates the caller's production graph, including centered readers.
Missing gradients and zero gradients are different observations. Cosine is undefined
for a zero norm; neither zero nor missing is evidence of semantic understanding.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import combinations

import torch


def _groups(bridge, parameters):
    groups = {
        name: []
        for name in (
            "writer", "query_projection", "query_norm", "reader_q", "reader_k", "reader_v",
            "reader_out", "up",
        )
    }
    width = bridge.workspace_dim
    for index, (name, parameter) in enumerate(parameters):
        if name == "attention.in_proj_weight":
            if parameter.shape != (3 * width, width):
                raise ValueError("Unexpected packed reader Q/K/V shape")
            for offset, group in enumerate(("reader_q", "reader_k", "reader_v")):
                groups[group].append((index, slice(offset * width, (offset + 1) * width)))
        else:
            group = next(
                (key for key in ("writer", "query_projection", "query_norm", "up")
                 if name.startswith(f"{key}.")),
                None,
            )
            if name.startswith("attention.out_proj."):
                group = "reader_out"
            if group is None:
                raise ValueError(f"Unclassified trainable bridge parameter: {name}")
            groups[group].append((index, slice(None)))
    if any(not members for members in groups.values()):
        raise ValueError("All compact bridge parameter groups must be trainable and present")
    return groups


def _vectors(gradients, parameters, groups):
    result = {}
    for name, members in groups.items():
        values, missing, present = [], 0, 0
        for index, selection in members:
            size = parameters[index][1][selection].numel()
            gradient = gradients[index]
            if gradient is None:
                missing += size
                values.append(torch.zeros(size, dtype=torch.float64))
            else:
                value = gradient[selection].detach().reshape(-1).to("cpu", torch.float64)
                if not bool(torch.isfinite(value).all()):
                    raise ValueError(f"Nonfinite gradient in {name}")
                present += size
                values.append(value)
        result[name] = (torch.cat(values), present, missing)
    return result


def _metrics(vector, scale=1.0):
    values, present, missing = vector
    values = values * scale
    nonzero = int(torch.count_nonzero(values))
    status = "missing" if not present else ("nonzero" if nonzero else "zero")
    return {
        "status": status,
        "present_elements": present,
        "missing_elements": missing,
        "nonzero_elements": nonzero,
        "l2": float(values.norm()) if present else None,
        "max_abs": float(values.abs().max()) if present else None,
    }


def _pair(first, second, first_scale=1.0, second_scale=1.0):
    left, lp, _ = first
    right, rp, _ = second
    if not lp or not rp:
        return {"dot": None, "cosine": None, "cosine_status": "missing_gradient"}
    left, right = left * first_scale, right * second_scale
    dot = float(left @ right)
    product = float(left.norm() * right.norm())
    return {
        "dot": dot,
        "cosine": dot / product if product else None,
        "cosine_status": "defined" if product else "zero_norm",
    }


def audit_loss_gradients(
    bridge,
    components: Mapping[str, torch.Tensor],
    weights: Mapping[str, float],
    *,
    total_loss: torch.Tensor,
    diagnostic_components: Mapping[str, torch.Tensor] | None = None,
    frozen_tensors: Mapping[str, torch.Tensor] | None = None,
    reconstruction_atol: float = 1e-6,
    reconstruction_rtol: float = 1e-5,
) -> dict:
    """Audit one existing graph without changing state or populated ``.grad`` fields.

    ``components`` are unweighted scalar objective terms. ``weights`` must cover
    exactly those terms (including explicit zero weights). Diagnostic components,
    e.g. reciprocal donor margins, are differentiated but excluded from the total.
    The caller owns train-only selection and frozen-feature/checkpoint provenance.
    ``frozen_tensors`` checks that supplied backbone features/head weights cannot
    receive gradients. Omitting it makes no backbone-freezing claim.

    Reconstruction compares the weighted sum of term gradients against autograd
    of ``total_loss``; this is a bounded FP32-graph check, not bitwise equivalence.
    All gradient vectors are summarized on CPU in FP64 and never returned.
    """
    if not components or set(components) != set(weights):
        raise ValueError("Weights must cover exactly the nonempty objective component mapping")
    diagnostics = dict(diagnostic_components or {})
    if set(diagnostics) & set(components):
        raise ValueError("Diagnostic and objective component names must be disjoint")
    coefficients = {name: float(value) for name, value in weights.items()}
    if not all(math.isfinite(value) for value in coefficients.values()):
        raise ValueError("Objective weights must be finite")
    if any(
        not math.isfinite(value) or value < 0
        for value in (reconstruction_atol, reconstruction_rtol)
    ):
        raise ValueError("Reconstruction tolerances must be finite and nonnegative")
    for name, tensor in (frozen_tensors or {}).items():
        if tensor.requires_grad or tensor.grad is not None:
            raise ValueError(f"Expected detached frozen input: {name}")
    losses = {**components, **diagnostics}
    for name, value in {**losses, "__total__": total_loss}.items():
        if value.ndim != 0 or not value.is_floating_point() or not bool(torch.isfinite(value)):
            raise ValueError(f"Expected finite floating point scalar: {name}")
    parameters = [(name, p) for name, p in bridge.named_parameters() if p.requires_grad]
    if not parameters:
        raise ValueError("Bridge has no trainable parameters")
    groups = _groups(bridge, parameters)
    state = {name: tensor.detach().clone() for name, tensor in bridge.state_dict().items()}
    grad_snapshot = {
        name: (p.grad, None if p.grad is None else p.grad.detach().clone())
        for name, p in bridge.named_parameters()
    }
    modes = {name: module.training for name, module in bridge.named_modules()}

    def gradients(loss):
        if not loss.requires_grad:
            return (None,) * len(parameters)
        return torch.autograd.grad(
            loss, [p for _, p in parameters], retain_graph=True, allow_unused=True,
        )

    try:
        vectors = {
            name: _vectors(gradients(value), parameters, groups)
            for name, value in losses.items()
        }
        total_vectors = _vectors(gradients(total_loss), parameters, groups)
        terms = {
            name: {
                "value": float(value.detach()),
                "included_in_objective": name in components,
                "weight": coefficients.get(name),
                "raw": {group: _metrics(vector) for group, vector in vectors[name].items()},
                "weighted": (
                    {group: _metrics(vector, coefficients[name])
                     for group, vector in vectors[name].items()}
                    if name in components else None
                ),
            }
            for name, value in losses.items()
        }
        pairs = [
            {
                "first": first, "second": second,
                "raw": {group: _pair(vectors[first][group], vectors[second][group])
                        for group in groups},
                "weighted": (
                    {group: _pair(vectors[first][group], vectors[second][group],
                                  coefficients[first], coefficients[second]) for group in groups}
                    if first in components and second in components else None
                ),
            }
            for first, second in combinations(losses, 2)
        ]
        reconstruction = {}
        for group in groups:
            actual = total_vectors[group][0]
            summed = sum(
                (vectors[name][group][0] * coefficients[name] for name in components),
                torch.zeros_like(actual),
            )
            error = (summed - actual).abs()
            reconstruction[group] = {
                "max_abs_error": float(error.max()),
                "error_l2": float(error.norm()),
                "weighted_sum_l2": float(summed.norm()),
                "total": _metrics(total_vectors[group]),
                "passed": bool((error <= reconstruction_atol +
                                reconstruction_rtol * actual.abs()).all()),
            }
        result = {
            "format": "latent-workspace-loss-gradient-audit-v1",
            "optimizer_steps": 0,
            "terms": terms,
            "pairwise": pairs,
            "reconstruction": {
                "atol": reconstruction_atol, "rtol": reconstruction_rtol,
                "groups": reconstruction,
                "passed": all(row["passed"] for row in reconstruction.values()),
            },
            "frozen_input_names": sorted(frozen_tensors or {}),
            "claim_boundary": "Gradient geometry on the supplied graph, not learning efficacy",
        }
    finally:
        if set(state) != set(bridge.state_dict()) or any(
            not torch.equal(value, bridge.state_dict()[name]) for name, value in state.items()
        ):
            raise RuntimeError("Bridge state mutated during gradient audit")
        for name, parameter in bridge.named_parameters():
            original, saved = grad_snapshot[name]
            if parameter.grad is not original or (
                saved is not None and not torch.equal(saved, parameter.grad)
            ):
                raise RuntimeError("Existing parameter gradients mutated during audit")
        if modes != {name: module.training for name, module in bridge.named_modules()}:
            raise RuntimeError("Module training modes mutated during gradient audit")
    result["bridge_state_unchanged"] = True
    result["parameter_grads_unchanged"] = True
    result["module_modes_unchanged"] = True
    return result
