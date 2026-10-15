"""Bounded grouped-wrapper qualification with a temporary, untrained sidecar probe.

No model loading, optimizer, global functional patches, or generation interface.
The caller owns fixture/model admission and immutable checkpoint receipts.
"""

from __future__ import annotations

import contextlib
import hashlib
import sys
from pathlib import Path
from typing import Any

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from latent_workspace_ft_v10.engine import functional_batch_kwargs  # noqa: E402
from latent_workspace_ft_v10.observability import NamedNormRecorder  # noqa: E402

PROBE_SEED = 1403
PROBE_STD = 0.01
MODES = ("intact", "counterfactual_twin", "zero", "hard_bypass")


def _hash(value: torch.Tensor) -> str:
    value = value.detach().cpu().contiguous().reshape(-1)
    return hashlib.sha256(value.view(torch.uint8).numpy().tobytes()).hexdigest()


def _workspace_hashes(wrapper: Any) -> dict[str, str]:
    return {
        name: _hash(value)
        for name, value in wrapper.state_dict().items()
        if not name.startswith("base_model.")
    }


def _base_identity(wrapper: Any) -> dict[str, tuple]:
    return {
        name: (id(p), p._version, str(p.dtype), str(p.device), p.requires_grad)
        for name, p in wrapper.base_model.named_parameters()
    }


def _stats(value: torch.Tensor) -> dict:
    values = value.detach().float()
    finite = bool(torch.isfinite(values).all())
    return {
        "dtype": str(value.dtype),
        "shape": list(value.shape),
        "elements": value.numel(),
        "finite": finite,
        "nonzero_elements": int(values.ne(0).sum()),
        "l2_fp32": float(values.norm()) if finite else None,
    }


def _same(left: torch.Tensor, right: torch.Tensor) -> bool:
    return (
        left.shape == right.shape and left.dtype == right.dtype and bool(torch.equal(left, right))
    )


class _Capture:
    """Local passthrough hooks; retains full GPU logits only until case reduction."""

    def __init__(self, wrapper, ids, mask, positions, choices):
        self.wrapper, self.ids, self.mask = wrapper, ids, mask
        self.positions, self.choices = positions, choices
        self.handles = []
        self.counts = dict(base=0, writer=0, reader=0, adapter=0)
        self.reader_args = None
        self.reader_final = self.adapter_input = None
        self.base_logits = self.sidecar_logits = self.sidecar_candidates = None

    def candidates(self, logits):
        rows = torch.arange(len(logits), device=logits.device)
        return logits[rows, self.positions].gather(1, self.choices)

    def _base_before(self, _module, _args, kwargs):
        if not _same(kwargs["input_ids"], self.ids) or not _same(
            kwargs["attention_mask"], self.mask
        ):
            raise ValueError("Recipient inline input IDs/masks changed")

    def _base(self, _module, _args, output):
        self.counts["base"] += 1
        self.base_logits = output.logits

    def _writer(self, _module, _args, output):
        self.counts["writer"] += 1
        self.memory, self.memory_mask = (x.detach() for x in output[:2])

    def _reader_before(self, _module, args):
        self.reader_args = tuple(x.detach() for x in args)

    def _reader(self, _module, _args, output):
        self.counts["reader"] += 1
        self.reader_final = output[0].detach()

    def _adapter_before(self, _module, args):
        self.adapter_input = args[0].detach()

    def _adapter(self, _module, _args, output):
        self.counts["adapter"] += 1
        self.sidecar_logits = output
        self.sidecar_candidates = self.candidates(output)

    def __enter__(self):
        w = self.wrapper
        try:
            self.handles.append(
                w.base_model.register_forward_pre_hook(self._base_before, with_kwargs=True)
            )
            for module, method, pre in (
                (w.base_model, self._base, False),
                (w.functional_writer, self._writer, False),
                (w.functional_reader, self._reader_before, True),
                (w.functional_reader, self._reader, False),
                (w.functional_sidecar_adapter, self._adapter_before, True),
                (w.functional_sidecar_adapter, self._adapter, False),
            ):
                register = module.register_forward_pre_hook if pre else module.register_forward_hook
                self.handles.append(register(method))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc):
        for handle in self.handles:
            handle.remove()
        self.handles.clear()


def _norms(wrapper):
    writer, reader, adapter = (
        wrapper.functional_writer,
        wrapper.functional_reader,
        wrapper.functional_sidecar_adapter,
    )
    return {
        "writer.context_norm": writer.context_norm,
        "writer.slot_norm": writer.slot_norm,
        "writer.ff_norm": writer.ff_norm,
        "reader.memory_norm": reader.memory_norm,
        "reader.query_norm": reader.query_norm,
        "adapter.norm": adapter.norm,
    }


def _gradients(wrapper):
    rows = []
    for name, p in wrapper.named_parameters():
        family = (
            "base"
            if name.startswith("base_model.")
            else "writer"
            if name.startswith("functional_writer.")
            else "reader"
            if name.startswith("functional_reader.")
            else "up"
            if name == "functional_sidecar_adapter.up.weight"
            else "adapter_upstream"
            if name.startswith("functional_sidecar_adapter.")
            else "inactive"
        )
        rows.append(
            {
                "name": name,
                "family": family,
                "requires_grad": p.requires_grad,
                "present": p.grad is not None,
                **(_stats(p.grad) if p.grad is not None else {}),
            }
        )
    groups = {}
    for family in ("base", "writer", "reader", "up", "adapter_upstream", "inactive"):
        selected = [row for row in rows if row["family"] == family]
        groups[family] = {
            "parameters": len(selected),
            "present": sum(row["present"] for row in selected),
            "nonzero_parameters": sum(row.get("nonzero_elements", 0) > 0 for row in selected),
            "all_present_gradients_finite": all(row.get("finite", True) for row in selected),
            "all_require_grad": all(row["requires_grad"] for row in selected),
        }
    return {"groups": groups, "parameters": rows}


def run_instrument(wrapper, batch, *, device, precision="bf16") -> dict[str, Any]:
    """Qualify one admitted paired batch; restore temporary state even on failure.

    Results concern finite-precision numerical equality, not bitwise equivalence,
    semantic donor direction, learned usefulness, K/V tracing, or free generation.
    ``precision='fp32'`` permits tiny CPU tests; CPU BF16 failures are not suppressed.
    """
    device = torch.device(device)
    if device.type == "cuda" and device.index is None:
        device = torch.device("cuda", torch.cuda.current_device())
    if precision not in ("bf16", "fp32"):
        raise ValueError("precision must be bf16 or fp32")
    report: dict[str, Any] = {
        "format": "v14-grouped-workspace-instrument-v1",
        "status": "RUNNING",
        "scientific_success": False,
        "training_performed": False,
        "claim_boundary": (
            "Synthetic route qualification only; no learned/semantic/generation claim."
        ),
        "precision": precision,
        "device": str(device),
        "cases": {},
        "gradients": {},
        "checks": {},
        "probe": {
            "seed": PROBE_SEED,
            "std": PROBE_STD,
            "scope": "temporary up.weight only",
            "learned": False,
            "selection": "fixed before observing outputs",
        },
    }
    up = wrapper.functional_sidecar_adapter.up.weight
    saved_up = up.detach().clone()
    flags = [(p, p.requires_grad) for p in wrapper.parameters()]
    modes = [(module, module.training) for module in wrapper.modules()]
    base_before = _base_identity(wrapper)
    workspace_before = _workspace_hashes(wrapper)
    input_hashes = {
        name: _hash(value) for name, value in batch.items() if isinstance(value, torch.Tensor)
    }
    report["workspace_state_sha256_before"] = workspace_before
    report["probe"]["original_up_was_zero"] = bool(up.detach().eq(0).all())

    def autocast():
        return torch.autocast(device.type, dtype=torch.bfloat16, enabled=precision == "bf16")

    try:
        cfg = wrapper.functional_config
        wrapper.functional_operator_contract()
        if (
            wrapper.workspace_config.route_topology != "functional_workspace"
            or not cfg.enabled
            or cfg.route_mode != "inline_sidecar"
            or cfg.memory_mode != "slots"
            or cfg.writer_steps != 1
            or cfg.reader_steps != 1
            or cfg.dropout != 0
            or cfg.counterfactual_weight != 0
            or cfg.stability_weight != 0
            or cfg.task_objective != "choice_normalized"
            or cfg.workspace_norm_kind != "layer_norm"
            or cfg.workspace_norm_eps != 1e-5
            or cfg.logit_composition != "fp32_accumulate"
        ):
            raise ValueError(
                "Instrument requires one-step slots inline_sidecar, LN1e-5, "
                "FP32 sum, no auxiliaries"
            )
        if cfg.boundary_layer != wrapper.functional_boundary_adapter.layer_count() // 2:
            raise ValueError("Instrument requires the middle decoder boundary")
        if any(p.device != device for p in wrapper.parameters()):
            raise ValueError("Caller must place the entire wrapper on the requested device")
        # The production collator also returns sample_indices and other
        # bookkeeping tensors that are not wrapper.forward arguments.
        kwargs = functional_batch_kwargs(batch)
        ids = kwargs["functional_inline_input_ids"]
        context = kwargs["functional_context_input_ids"]
        query = kwargs["functional_query_input_ids"]
        if (
            ids.shape[:3] != (1, 2, 2)
            or context.shape[:2] != (1, 2)
            or query.shape[:3] != (1, 2, 2)
            or ids.shape[-1] > 256
            or context.shape[-1] > 192
            or query.shape[-1] > 96
            or not bool(kwargs["functional_query_valid_mask"].all())
        ):
            raise ValueError("Expected bounded B1/two sides/two valid queries grouped tensors")
        ids = ids.reshape(4, -1)
        mask = kwargs["functional_inline_attention_mask"].reshape_as(ids)
        labels = kwargs["functional_inline_labels"].reshape_as(ids)
        supervised = labels[:, 1:].ne(-100)
        if not bool(supervised.sum(1).eq(1).all()):
            raise ValueError("Expected exactly one shifted answer target per query")
        positions = supervised.long().argmax(1)
        choices = kwargs["functional_inline_choice_ids"].reshape(4, -1)
        if choices.shape != (4, 2):
            raise ValueError("Instrument requires exactly two candidates per query")
        kwargs.update(
            input_ids=ids,
            attention_mask=mask,
            compute_workspace_loss=False,
            compute_spectral=False,
            rng_streams=None,
            memory_intervention_seed=PROBE_SEED,
        )
        report["inputs"] = {
            "inline_ids": ids.cpu().tolist(),
            "inline_mask": mask.cpu().tolist(),
            "answer_positions": positions.cpu().tolist(),
            "candidate_ids": choices.cpu().tolist(),
            "all_tensor_sha256": input_hashes,
        }
        report["operator_contract"] = wrapper.functional_operator_contract()
        report["parameter_dtypes"] = {
            "base": sorted({str(p.dtype) for p in wrapper.base_model.parameters()}),
            "workspace": sorted(
                {
                    str(p.dtype)
                    for name, p in wrapper.named_parameters()
                    if not name.startswith("base_model.")
                }
            ),
        }
        expected_base = "torch.bfloat16" if precision == "bf16" else "torch.float32"
        if report["parameter_dtypes"] != {"base": [expected_base], "workspace": ["torch.float32"]}:
            raise ValueError("Expected declared base precision and FP32 workspace parameters")
        wrapper.eval()
        for p, _flag in flags:
            p.requires_grad_(True)
        wrapper.zero_grad(set_to_none=True)

        def capture():
            return _Capture(wrapper, ids, mask, positions, choices)

        def forward(mode, *, bypass=False):
            return wrapper(**{**kwargs, "memory_intervention": mode, "bypass_workspace": bypass})

        def case(name, mode="intact", *, bypass=False, observe=False, native_cpu=None):
            recorder = (
                NamedNormRecorder(_norms(wrapper), max_records=16, max_tensor_elements=4096)
                if observe
                else None
            )
            with (
                torch.no_grad(),
                autocast(),
                capture() as captured,
                recorder or contextlib.nullcontext(),
            ):
                result = forward(mode, bypass=bypass)
                logits = result["logits"]
                if not bool(torch.isfinite(logits).all()):
                    raise ValueError(f"Nonfinite logits in {name}")
                base = captured.base_logits
                final = captured.candidates(logits)
                row = {
                    "mode": mode,
                    "bypass": bypass,
                    "counts": dict(captured.counts),
                    "output_dtype": str(logits.dtype),
                    "output_shape": list(logits.shape),
                    "base_candidates": captured.candidates(base).float().cpu().tolist(),
                    "final_candidates": final.float().cpu().tolist(),
                    "full_numeric_equal_base": _same(logits, base.to(logits.dtype)),
                    "base_object_returned": logits is base,
                }
                if native_cpu is not None:
                    row["full_numeric_equal_direct_native"] = _same(logits.cpu(), native_cpu)
                expected_counts = {
                    "base": 1,
                    "writer": 0 if bypass else 1,
                    "reader": 0 if bypass or mode == "hard_bypass" else 1,
                    "adapter": 0 if bypass else 1,
                }
                report["checks"][f"{name}.calls"] = row["counts"] == expected_counts
                if not bypass:
                    residual = captured.sidecar_candidates
                    row["sidecar_candidates"] = residual.float().cpu().tolist()
                    row["sidecar_full"] = _stats(captured.sidecar_logits)
                    row["raw_memory"] = captured.memory.float().cpu().tolist()
                    row["raw_memory_sha256"] = _hash(captured.memory)
                    expected = captured.candidates(base).float() + residual.float()
                    report["checks"][f"{name}.composition"] = (
                        logits.dtype == torch.float32 and _same(final, expected)
                    )
                    if mode == "hard_bypass":
                        report["checks"][f"{name}.zero_adapter_input"] = bool(
                            captured.adapter_input.eq(0).all()
                        )
                    else:
                        read_memory = captured.reader_args[2]
                        donor = (
                            captured.memory.flip(0)
                            if mode == "counterfactual_twin"
                            else captured.memory
                        )
                        if mode == "zero":
                            donor = torch.zeros_like(donor)
                        report["checks"][f"{name}.memory_assignment"] = _same(
                            read_memory, donor.repeat_interleave(2, dim=0)
                        )
                        expected_mask = captured.memory_mask.repeat_interleave(2, dim=0)
                        report["checks"][f"{name}.memory_mask"] = _same(
                            captured.reader_args[3], expected_mask
                        )
                        row["reader_memory"] = read_memory.float().cpu().tolist()
                report["cases"][name] = row
                final_cpu = final.detach().float().cpu().clone()
            # This replay is outside all capture hooks and uses the same dtype/autocast.
            if captured.reader_args is not None:
                with torch.no_grad(), autocast():
                    replay = wrapper.functional_reader.read_state(*captured.reader_args)
                recovered = replay.recovered_delta
                cumulative = replay.cumulative_update
                report["checks"][f"{name}.reader_replay"] = _same(
                    replay.final_state, captured.reader_final
                )
                report["checks"][f"{name}.adapter_delta"] = _same(recovered, captured.adapter_input)
                row["reader_state_replay"] = {
                    "scope": "replay_matched_to_actual_reader_output_not_direct_dataclass_capture",
                    "per_step_updates": [_stats(x) for x in replay.per_step_updates],
                    "cumulative_update": _stats(cumulative),
                    "recovered_delta": _stats(recovered),
                    "roundtrip_error": _stats(recovered.float() - cumulative.float()),
                }
            if recorder is not None:
                norm_report = recorder.to_dict()
                expected = {
                    "writer.context_norm": 1,
                    "writer.slot_norm": 4,
                    "writer.ff_norm": 1,
                    "reader.memory_norm": 1,
                    "reader.query_norm": 2,
                    "adapter.norm": 1,
                }
                report["checks"]["observer.records"] = (
                    all(
                        norm_report["counts"][key]
                        == {"invoked": count, "recorded": count, "dropped": 0}
                        for key, count in expected.items()
                    )
                    and len(norm_report["records"]) == 10
                    and all(
                        record["status"] == "COMPLETE"
                        and all(record[phase]["sample_finite"] for phase in ("pre", "post"))
                        for record in norm_report["records"]
                    )
                )
                report["norm_observation"] = norm_report
            return final_cpu

        def gradient_case(name, opened):
            wrapper.zero_grad(set_to_none=True)
            with torch.enable_grad(), autocast(), capture() as captured:
                result = forward("intact")
                residual = captured.sidecar_candidates
                coefficients = torch.sin(
                    torch.arange(
                        1, residual.numel() + 1, device=residual.device, dtype=torch.float32
                    )
                ).reshape_as(residual)
                loss = (residual.float() * coefficients).sum()
                if not bool(torch.isfinite(loss)):
                    raise ValueError("Nonfinite sidecar-only probe loss")
                del result
                captured.base_logits = captured.sidecar_logits = None
                loss.backward()
            gradients = _gradients(wrapper)
            gradients["loss"] = float(loss.detach())
            gradients["loss_definition"] = (
                "sum(candidate_sidecar.float * sin(arange(1,N+1))); base logits excluded"
            )
            groups = gradients["groups"]
            report["gradients"][name] = gradients
            report["checks"][f"{name}.ownership"] = (
                groups["base"]["all_require_grad"] and groups["base"]["present"] == 0
            )
            report["checks"][f"{name}.finite"] = all(
                group["all_present_gradients_finite"] for group in groups.values()
            )
            report["checks"][f"{name}.up_open"] = groups["up"]["nonzero_parameters"] == 1
            report["checks"][f"{name}.upstream"] = all(
                (
                    groups[group]["nonzero_parameters"] > 0
                    if opened
                    else groups[group]["nonzero_parameters"] == 0
                )
                for group in ("writer", "reader", "adapter_upstream")
            )
            report["checks"][f"{name}.inactive"] = groups["inactive"]["present"] == 0
            wrapper.zero_grad(set_to_none=True)

        with torch.no_grad(), autocast():
            native = wrapper.base_model(
                input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True
            ).logits
            if not bool(torch.isfinite(native).all()):
                raise ValueError("Nonfinite direct native logits")
            native_cpu = native.detach().cpu()
            del native
        case("true_bypass", bypass=True, native_cpu=native_cpu)
        del native_cpu
        report["checks"]["true_bypass.identity"] = (
            report["cases"]["true_bypass"]["base_object_returned"]
            and report["cases"]["true_bypass"]["full_numeric_equal_direct_native"]
        )
        with torch.no_grad():
            up.zero_()
        zero = case("zero_up")
        report["checks"]["zero_up.noop"] = (
            report["cases"]["zero_up"]["full_numeric_equal_base"]
            and report["cases"]["zero_up"]["sidecar_full"]["nonzero_elements"] == 0
        )
        gradient_case("zero_up", False)
        generator = torch.Generator(device="cpu").manual_seed(PROBE_SEED)
        opened = torch.randn(up.shape, generator=generator, dtype=torch.float32) * PROBE_STD
        with torch.no_grad():
            up.copy_(opened.to(device=up.device, dtype=up.dtype))
        report["probe"]["temporary_up_sha256"] = _hash(up)
        intact = case("opened_intact")
        report["checks"]["opened.route_visible"] = not _same(intact, zero)
        for mode in MODES[1:]:
            case(f"opened_{mode}", mode)
        observed = case("opened_observed", observe=True)
        report["checks"]["observer.passthrough"] = _same(observed, intact)
        gradient_case("opened", True)
        report["status"] = "COMPLETE" if all(report["checks"].values()) else "MISMATCH"
    except Exception as exc:
        report.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
    finally:
        with torch.no_grad():
            up.copy_(saved_up)
        wrapper.zero_grad(set_to_none=True)
        for parameter, flag in flags:
            parameter.requires_grad_(flag)
        for module, training in modes:
            module.training = training
        workspace_after = _workspace_hashes(wrapper)
        report["restoration"] = {
            "input_tensor_bytes_unchanged": input_hashes
            == {
                name: _hash(value)
                for name, value in batch.items()
                if isinstance(value, torch.Tensor)
            },
            "workspace_state_bytes_restored": workspace_after == workspace_before,
            "workspace_state_sha256_after": workspace_after,
            "base_parameter_identity_version_dtype_device_flags_unchanged": _base_identity(wrapper)
            == base_before,
            "base_weight_bytes_rehashed": False,
            "base_scope": (
                "Object/version/dtype/device/requires_grad only; "
                "caller checkpoint hashes remain separate."
            ),
            "temporary_up_version_counter_may_advance": True,
            "gradients_cleared": all(p.grad is None for p in wrapper.parameters()),
            "requires_grad_flags_restored": all(p.requires_grad == flag for p, flag in flags),
            "training_flags_restored": all(module.training == flag for module, flag in modes),
        }
        restore = report["restoration"]
        report["checks"]["restoration"] = all(
            restore[key]
            for key in (
                "input_tensor_bytes_unchanged",
                "workspace_state_bytes_restored",
                "base_parameter_identity_version_dtype_device_flags_unchanged",
                "gradients_cleared",
                "requires_grad_flags_restored",
                "training_flags_restored",
            )
        )
        if not report["checks"]["restoration"]:
            report["status"] = "FAILED"
        report["instrument_checks_passed"] = report["status"] == "COMPLETE" and all(
            report["checks"].values()
        )
    return report
