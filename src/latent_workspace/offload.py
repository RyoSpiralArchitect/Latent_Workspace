"""Promoted CPU gradient transport; historical arithmetic is unchanged.

See configs/architecture/PROMOTIONS.json and the transport parity test.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import torch
from torch import nn

from .optimizer_state import require


@dataclass(frozen=True)
class _CPUGradientAccumulatorSpec:
    name: str
    parameter: nn.Parameter = field(repr=False, compare=False)
    shape: tuple[int, ...]
    stride: tuple[int, ...]
    dtype: torch.dtype
    device: torch.device


class _CPUGradientAccumulator:
    """Store one accumulation window's gradients on host memory.

    ``merge_device='cuda'`` is the original exact-spill path: prior host state
    returns to CUDA for every merge. ``merge_device='cpu'`` keeps the same
    microbatch order and dtype but performs only the cross-microbatch ``add_``
    on pinned host tensors. The latter needs one D2H gradient volume per
    microbatch and one final H2D restore instead of a round trip per merge.
    """

    def __init__(
        self,
        parameters: Iterable[tuple[str, nn.Parameter]],
        *,
        require_cuda: bool = False,
        merge_device: str = "cuda",
    ) -> None:
        if merge_device not in {"cuda", "cpu"}:
            raise RuntimeError(
                "CPU gradient accumulation merge_device must be cuda or cpu."
            )
        specs: list[_CPUGradientAccumulatorSpec] = []
        names: set[str] = set()
        physical_ids: set[int] = set()
        for name, parameter in parameters:
            if not isinstance(name, str) or not name:
                raise RuntimeError(
                    "CPU gradient accumulation requires non-empty parameter names."
                )
            if name in names:
                raise RuntimeError(
                    f"Duplicate CPU gradient accumulation parameter name: {name!r}."
                )
            if not isinstance(parameter, nn.Parameter):
                raise RuntimeError(
                    f"CPU gradient accumulation entry {name!r} is not a Parameter."
                )
            physical_id = id(parameter)
            if physical_id in physical_ids:
                raise RuntimeError(
                    "CPU gradient accumulation received a duplicate physical "
                    f"parameter at {name!r}."
                )
            if not parameter.requires_grad:
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not trainable."
                )
            if parameter.layout is not torch.strided:
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not strided."
                )
            if not torch.is_floating_point(parameter):
                raise RuntimeError(
                    f"CPU gradient accumulation parameter {name!r} is not floating point."
                )
            if require_cuda and parameter.device.type != "cuda":
                raise RuntimeError(
                    "CPU gradient accumulation offload requires every trainable "
                    f"parameter on CUDA; {name!r} is on {parameter.device}."
                )
            names.add(name)
            physical_ids.add(physical_id)
            specs.append(
                _CPUGradientAccumulatorSpec(
                    name=name,
                    parameter=parameter,
                    shape=tuple(parameter.shape),
                    stride=tuple(parameter.stride()),
                    dtype=parameter.dtype,
                    device=parameter.device,
                )
            )
        if not specs:
            raise RuntimeError(
                "CPU gradient accumulation offload found no trainable parameters."
            )

        # Releasing small current gradients before a large merge bounds the
        # transient device allocation to one parameter-sized tensor.
        self._specs = tuple(
            sorted(specs, key=lambda spec: (spec.parameter.numel(), spec.name))
        )
        self._specs_by_id = {id(spec.parameter): spec for spec in self._specs}
        self._merge_device = merge_device
        self._pin_memory = bool(
            merge_device == "cpu"
            and self._specs
            and all(spec.device.type == "cuda" for spec in self._specs)
        )
        self._buffers: dict[int, torch.Tensor] = {}
        self._staging_buffers: dict[int, torch.Tensor] = {}
        self._seen_parameter_ids: set[int] = set()
        self._buffer_strides: dict[int, tuple[int, ...]] = {}
        self._spill_count = 0
        self._merge_count = 0
        self._first_spill_count = 0
        self._cumulative_current_gradient_bytes = 0
        self._peak_cpu_accumulator_bytes = 0
        self._peak_cpu_staging_bytes = 0
        self._peak_cpu_total_bytes = 0
        self._active = True

    def schema_records(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "shape": list(spec.shape),
                "stride": list(spec.stride),
                "dtype": str(spec.dtype),
                "device": str(spec.device),
                "numel": int(spec.parameter.numel()),
                "logical_bytes": int(
                    spec.parameter.numel() * spec.parameter.element_size()
                ),
            }
            for spec in sorted(self._specs, key=lambda spec: spec.name)
        ]

    @staticmethod
    def _storage_bytes(tensor: torch.Tensor) -> int:
        try:
            return int(tensor.untyped_storage().nbytes())
        except (AttributeError, RuntimeError):
            return int(tensor.numel() * tensor.element_size())

    def _buffer_bytes(self) -> int:
        return sum(self._storage_bytes(buffer) for buffer in self._buffers.values())

    def _staging_bytes(self) -> int:
        return sum(
            self._storage_bytes(buffer) for buffer in self._staging_buffers.values()
        )

    def _live_cpu_buffer_count(self) -> int:
        return len(self._buffers) + len(self._staging_buffers)

    def _live_cpu_buffer_bytes(self) -> int:
        return self._buffer_bytes() + self._staging_bytes()

    def _empty_cpu_like(self, tensor: torch.Tensor) -> torch.Tensor:
        return torch.empty_strided(
            tuple(tensor.shape),
            tuple(tensor.stride()),
            dtype=tensor.dtype,
            device="cpu",
            pin_memory=self._pin_memory,
        )

    def _require_active(self) -> None:
        if not self._active:
            raise RuntimeError("CPU gradient accumulator is no longer active.")

    @staticmethod
    def _has_internal_overlap(tensor: torch.Tensor) -> bool:
        checker = getattr(torch, "_debug_has_internal_overlap", None)
        if checker is None:
            return False
        return int(checker(tensor)) != 0

    def _validate_parameter(self, spec: _CPUGradientAccumulatorSpec) -> None:
        parameter = spec.parameter
        failures: list[str] = []
        if not parameter.requires_grad:
            failures.append("requires_grad")
        if tuple(parameter.shape) != spec.shape:
            failures.append("shape")
        if parameter.layout is not torch.strided:
            failures.append("layout")
        elif tuple(parameter.stride()) != spec.stride:
            failures.append("stride")
        if parameter.dtype != spec.dtype:
            failures.append("dtype")
        if parameter.device != spec.device:
            failures.append("device")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation parameter schema changed for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _validate_gradient(
        self,
        spec: _CPUGradientAccumulatorSpec,
        gradient: torch.Tensor,
    ) -> None:
        failures: list[str] = []
        if tuple(gradient.shape) != spec.shape:
            failures.append("shape")
        if gradient.layout is not torch.strided:
            failures.append("layout")
        elif self._has_internal_overlap(gradient):
            failures.append("internal_overlap")
        if gradient.dtype != spec.dtype:
            failures.append("dtype")
        if gradient.device != spec.device:
            failures.append("device")
        if gradient.requires_grad or gradient.grad_fn is not None:
            failures.append("autograd_history")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation gradient schema mismatch for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _validate_buffer(
        self,
        spec: _CPUGradientAccumulatorSpec,
        buffer: torch.Tensor,
    ) -> None:
        failures: list[str] = []
        if tuple(buffer.shape) != spec.shape:
            failures.append("shape")
        if buffer.layout is not torch.strided:
            failures.append("layout")
        elif self._has_internal_overlap(buffer):
            failures.append("internal_overlap")
        if buffer.dtype != spec.dtype:
            failures.append("dtype")
        if buffer.device.type != "cpu":
            failures.append("device")
        if bool(buffer.is_pinned()) != self._pin_memory:
            failures.append("pin_memory")
        expected_stride = self._buffer_strides.get(id(spec.parameter))
        if expected_stride is None:
            failures.append("missing_stride_schema")
        elif tuple(buffer.stride()) != expected_stride:
            failures.append("stride")
        if failures:
            raise RuntimeError(
                "CPU gradient accumulation buffer schema mismatch for "
                f"{spec.name!r}: {sorted(failures)}."
            )

    def _synchronize_host_copies(
        self,
        specs: Iterable[_CPUGradientAccumulatorSpec],
    ) -> None:
        if not self._pin_memory:
            return
        devices = {spec.device for spec in specs}
        for device in sorted(devices, key=str):
            torch.cuda.current_stream(device).synchronize()

    @torch.no_grad()
    def spill(self) -> dict[str, int]:
        """Merge current grads in microbatch order, then clear them."""

        self._require_active()
        current_gradient_count = 0
        current_gradient_bytes = 0
        new_parameter_count = 0
        merged_parameter_count = 0
        try:
            cpu_merge_copies: list[
                tuple[
                    _CPUGradientAccumulatorSpec,
                    torch.Tensor,
                    torch.Tensor,
                    bool,
                ]
            ] = []
            for spec in self._specs:
                self._validate_parameter(spec)
                physical_id = id(spec.parameter)
                buffer = self._buffers.get(physical_id)
                if buffer is not None:
                    self._validate_buffer(spec, buffer)
                gradient = spec.parameter.grad
                if gradient is None:
                    continue
                self._validate_gradient(spec, gradient)
                gradient_bytes = self._storage_bytes(gradient)
                current_gradient_count += 1
                current_gradient_bytes += gradient_bytes

                if buffer is None:
                    buffer = self._empty_cpu_like(gradient)
                    self._buffers[physical_id] = buffer
                    self._seen_parameter_ids.add(physical_id)
                    self._buffer_strides[physical_id] = tuple(buffer.stride())
                    new_parameter_count += 1
                    if self._merge_device == "cuda":
                        buffer.copy_(gradient.detach(), non_blocking=False)
                    else:
                        buffer.copy_(
                            gradient.detach(),
                            non_blocking=self._pin_memory,
                        )
                        cpu_merge_copies.append((spec, buffer, buffer, True))
                elif self._merge_device == "cuda":
                    previous_device = torch.empty_strided(
                        tuple(buffer.shape),
                        tuple(buffer.stride()),
                        dtype=buffer.dtype,
                        device=spec.device,
                    )
                    previous_device.copy_(buffer, non_blocking=False)
                    previous_device.add_(gradient.detach())
                    buffer.copy_(previous_device, non_blocking=False)
                    del previous_device
                    merged_parameter_count += 1
                else:
                    staging = self._staging_buffers.get(physical_id)
                    if staging is None:
                        staging = self._empty_cpu_like(gradient)
                        self._staging_buffers[physical_id] = staging
                    else:
                        self._validate_buffer(spec, staging)
                    staging.copy_(
                        gradient.detach(),
                        non_blocking=self._pin_memory,
                    )
                    cpu_merge_copies.append((spec, buffer, staging, False))
                    merged_parameter_count += 1

                if self._merge_device == "cuda":
                    # Clear only after the synchronous host copy has succeeded.
                    spec.parameter.grad = None

            if self._merge_device == "cpu":
                self._synchronize_host_copies(
                    spec for spec, _buffer, _staging, _is_new in cpu_merge_copies
                )
                # Host copies are now complete, so device gradients can be
                # released before CPU accumulation begins.
                for spec, _buffer, _staging, _is_new in cpu_merge_copies:
                    spec.parameter.grad = None
                for _spec, buffer, staging, is_new in cpu_merge_copies:
                    if not is_new:
                        buffer.add_(staging)

            if not self._buffers:
                raise RuntimeError(
                    "CPU gradient accumulation spill observed no trainable gradients."
                )
            if set(self._buffers) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation buffer accounting is incomplete."
                )
            if set(self._buffer_strides) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation stride accounting is incomplete."
                )
            self._spill_count += 1
            self._merge_count += merged_parameter_count
            self._first_spill_count += new_parameter_count
            self._cumulative_current_gradient_bytes += current_gradient_bytes
            self._peak_cpu_accumulator_bytes = max(
                self._peak_cpu_accumulator_bytes,
                self._buffer_bytes(),
            )
            self._peak_cpu_staging_bytes = max(
                self._peak_cpu_staging_bytes,
                self._staging_bytes(),
            )
            self._peak_cpu_total_bytes = max(
                self._peak_cpu_total_bytes,
                self._live_cpu_buffer_bytes(),
            )
            return {
                "spill_count": self._spill_count,
                "current_gradient_count": current_gradient_count,
                "current_gradient_bytes": current_gradient_bytes,
                "new_parameter_count": new_parameter_count,
                "merged_parameter_count": merged_parameter_count,
                "accumulated_parameter_count": len(self._buffers),
                "cpu_accumulator_bytes": self._buffer_bytes(),
                "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
                "cpu_staging_buffer_count": len(self._staging_buffers),
                "cpu_staging_bytes": self._staging_bytes(),
                "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
                "live_cpu_buffer_count": self._live_cpu_buffer_count(),
                "live_cpu_buffer_bytes": self._live_cpu_buffer_bytes(),
                "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
                "cumulative_merge_count": self._merge_count,
                "cumulative_first_spill_count": self._first_spill_count,
                "cumulative_current_gradient_bytes": (
                    self._cumulative_current_gradient_bytes
                ),
            }
        except Exception:
            self.discard()
            raise

    @torch.no_grad()
    def restore(self) -> dict[str, int]:
        """Restore the complete window to original devices for optimizer use."""

        self._require_active()
        try:
            buffer_ids = set(self._buffers)
            if buffer_ids != self._seen_parameter_ids:
                missing = sorted(self._seen_parameter_ids - buffer_ids)
                unexpected = sorted(buffer_ids - self._seen_parameter_ids)
                raise RuntimeError(
                    "CPU gradient accumulation restore buffer accounting mismatch: "
                    f"missing={missing}, unexpected={unexpected}."
                )
            if not buffer_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore has no spilled gradients."
                )
            if set(self._buffer_strides) != self._seen_parameter_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore stride accounting mismatch."
                )
            if not buffer_ids <= set(self._specs_by_id):
                raise RuntimeError(
                    "CPU gradient accumulation restore found an unknown parameter buffer."
                )
            staging_ids = set(self._staging_buffers)
            if not staging_ids <= buffer_ids:
                raise RuntimeError(
                    "CPU gradient accumulation restore found an unknown staging buffer."
                )

            for spec in self._specs:
                self._validate_parameter(spec)
                if spec.parameter.grad is not None:
                    raise RuntimeError(
                        "CPU gradient accumulation restore would duplicate an existing "
                        f"gradient for {spec.name!r}."
                    )
                buffer = self._buffers.get(id(spec.parameter))
                if buffer is not None:
                    self._validate_buffer(spec, buffer)
                staging = self._staging_buffers.get(id(spec.parameter))
                if staging is not None:
                    self._validate_buffer(spec, staging)

            cpu_accumulator_bytes = self._buffer_bytes()
            cpu_staging_bytes = self._staging_bytes()
            restored_parameter_count = 0
            pending_restores: list[
                tuple[_CPUGradientAccumulatorSpec, torch.Tensor]
            ] = []
            for spec in self._specs:
                buffer = self._buffers.get(id(spec.parameter))
                if buffer is None:
                    continue
                restored = torch.empty_strided(
                    tuple(buffer.shape),
                    tuple(buffer.stride()),
                    dtype=buffer.dtype,
                    device=spec.device,
                )
                restored.copy_(buffer, non_blocking=self._pin_memory)
                pending_restores.append((spec, restored))
                restored_parameter_count += 1

            self._synchronize_host_copies(spec for spec, _restored in pending_restores)
            for spec, restored in pending_restores:
                spec.parameter.grad = restored

            self._buffers.clear()
            self._staging_buffers.clear()
            self._seen_parameter_ids.clear()
            self._buffer_strides.clear()
            self._active = False
            return {
                "spill_count": self._spill_count,
                "merge_count": self._merge_count,
                "first_spill_count": self._first_spill_count,
                "cumulative_current_gradient_bytes": (
                    self._cumulative_current_gradient_bytes
                ),
                "restored_parameter_count": restored_parameter_count,
                "cpu_accumulator_bytes_before_restore": cpu_accumulator_bytes,
                "cpu_staging_bytes_before_restore": cpu_staging_bytes,
                "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
                "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
                "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
                "live_cpu_buffer_count": 0,
                "live_cpu_buffer_bytes": 0,
            }
        except Exception:
            self.discard()
            raise

    @torch.no_grad()
    def discard(self) -> None:
        """Drop host state and all managed device gradients after failure."""

        for spec in self._specs:
            spec.parameter.grad = None
        self._buffers.clear()
        self._staging_buffers.clear()
        self._seen_parameter_ids.clear()
        self._buffer_strides.clear()
        self._active = False

    def statistics(self) -> dict[str, int]:
        return {
            "spill_count": self._spill_count,
            "merge_count": self._merge_count,
            "first_spill_count": self._first_spill_count,
            "cumulative_current_gradient_bytes": (
                self._cumulative_current_gradient_bytes
            ),
            "peak_cpu_accumulator_bytes": self._peak_cpu_accumulator_bytes,
            "peak_cpu_staging_bytes": self._peak_cpu_staging_bytes,
            "peak_cpu_total_bytes": self._peak_cpu_total_bytes,
            "live_cpu_buffer_count": self._live_cpu_buffer_count(),
            "live_cpu_buffer_bytes": self._live_cpu_buffer_bytes(),
        }


class CompleteCPUWindow(_CPUGradientAccumulator):
    """Consume completed host gradients without an unnecessary full GPU restore.

    Inherits the sealed engine's synchronized, native-dtype CPU addition. A new
    adapter owns its buffers only after complete-window validation. No old
    transport implementation or receipt is modified or re-labelled.
    """

    @torch.no_grad()
    def take(self, expected_spills):
        self._require_active()
        require(type(expected_spills) is int and expected_spills > 0, "Positive window length")
        require(self._spill_count == expected_spills, "Incomplete accumulation window")
        require(
            set(self._buffers) == set(self._specs_by_id) == self._seen_parameter_ids,
            "Missing gradient ownership",
        )
        for spec in self._specs:
            self._validate_parameter(spec)
            require(spec.parameter.grad is None, "Unspilled gradient")
            self._validate_buffer(spec, self._buffers[id(spec.parameter)])
            require(
                bool(torch.isfinite(self._buffers[id(spec.parameter)]).all()),
                "Nonfinite accumulation",
            )
        values = {spec.name: self._buffers[id(spec.parameter)] for spec in self._specs}
        receipt = self.statistics()
        receipt.update(consumed_parameter_count=len(values), consumer="CPU master plus FP32 bridge")
        self._buffers.clear()
        self._staging_buffers.clear()
        self._seen_parameter_ids.clear()
        self._buffer_strides.clear()
        self._active = False
        return values, receipt
