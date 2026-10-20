"""Explicit allocator maintenance after synchronous native-owner boundaries.

No numerical tensors, CPU gradient buffers, optimizer state or RNG are mutated.
The caller must have returned from accumulate/restore (no live forward locals).
This is opt-in orchestration, not an optimizer or checkpoint-format change.
"""

from __future__ import annotations

import time

import torch

from .native_owner import NativeFullUpdateOwner
from .optimizer_state import require


def release_unused_cache(owner, boundary):
    require(type(owner) is NativeFullUpdateOwner and not owner.failed, "Healthy native owner")
    require(boundary in ("spill", "restore"), "Explicit completed cache boundary")
    require(all(p.grad is None for _, p in owner.named), "Unspilled native gradient")
    require(all(p.grad is None for p in owner.masters.values()), "Live optimizer gradient")
    window = owner.window
    if boundary == "spill":
        require(
            window is not None
            and window._active
            and window._merge_device == "cpu"
            and 0 < owner.cursor <= len(owner.plan)
            and window._spill_count == owner.cursor,
            "Complete synchronous CPU spill required",
        )
        require(
            set(window._buffers) == {id(p) for _, p in owner.named}
            and all(t.device.type == "cpu" for t in window._buffers.values())
            and all(t.device.type == "cpu" for t in window._staging_buffers.values()),
            "Complete host gradient ownership required",
        )
    else:
        require(window is None and not owner.plan and owner.cursor == 0, "Clean restored owner")
    device = next(owner.model.parameters()).device
    require(all(p.device == device for _, p in owner.named), "Single owner device")
    started = time.monotonic()
    if device.type == "cpu":
        return dict(boundary=boundary, device="cpu", action="CPU_NOOP", elapsed_seconds=0)
    require(device.type == "cuda", "CPU/CUDA cache policy only")

    def sample():
        free, total = torch.cuda.mem_get_info(device)
        return dict(
            allocated_bytes=torch.cuda.memory_allocated(device),
            reserved_bytes=torch.cuda.memory_reserved(device),
            free_bytes=free,
            total_bytes=total,
        )

    # Spill already synchronizes D2H copies before clearing native gradients.
    # This additional whole-device boundary also drains unrelated pending frees
    # in this exclusively owned worker before measuring/releasing unused blocks.
    with torch.cuda.device(device):
        torch.cuda.synchronize(device)
        before = sample()
        torch.cuda.empty_cache()
        torch.cuda.synchronize(device)
        after = sample()
    require(
        after["allocated_bytes"] == before["allocated_bytes"],
        "Cache maintenance changed live allocation",
    )
    return dict(
        boundary=boundary,
        device=str(device),
        action="SYNCHRONIZE_EMPTY_CACHE",
        before=before,
        after=after,
        elapsed_seconds=time.monotonic() - started,
    )
