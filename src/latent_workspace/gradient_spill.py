"""No-update native-gradient diagnostics with one backward per objective/row.

Post-accumulate hooks copy each final native leaf gradient synchronously to CPU
and release its device storage. A tied/shared leaf must fire exactly once per
backward. A second event fails closed rather than changing its accumulation
order. The diagnostic across-row sum is FP32 CPU, NOT the owner's native-dtype
window or an optimizer update. No loss scaling or parameter changes occur.
"""

from contextlib import contextmanager

import torch

from .execution import require


class GradientSpill:
    def __init__(self, named_parameters):
        self.named = list(named_parameters)
        require(self.named, "Nonempty parameter census")
        require(len({n for n, _ in self.named}) == len(self.named), "Unique names")
        require(len({id(p) for _, p in self.named}) == len(self.named), "Unique physical leaves")
        require(
            all(p.is_leaf and p.requires_grad and p.grad is None for _, p in self.named),
            "Clean trainable leaves",
        )
        self.schema = {n: (tuple(p.shape), p.dtype, p.device, p._version) for n, p in self.named}
        self.buffers = {}
        self.events = {}
        self.backward_count = 0
        self.active = False
        self.poisoned = False

    def _check(self):
        require(not self.poisoned, "Poisoned spill cannot be reused")
        require(not self.active, "No nested spill")
        for name, p in self.named:
            require(
                (tuple(p.shape), p.dtype, p.device, p._version) == self.schema[name],
                "Parameter schema/version changed",
            )
            require(p.grad is None and p.requires_grad, "Clean trainable gradients")

    @contextmanager
    def capture(self, *, require_all=True):
        """Enclose exactly one backward; clean hooks/grad fields even on failure.

        The graph and native gradient accumulation finish upstream of each leaf
        hook. Missing leaves are zero only for deliberately selected W/Q/R paths;
        a full objective must visit every leaf (including numerical zero grads).
        """
        self._check()
        hooks, seen = [], set()
        self.active = True

        def spill(name, param):
            require(name not in seen, "Repeated leaf accumulation; unsupported execution")
            seen.add(name)
            grad = param.grad
            require(grad is not None and grad.layout == torch.strided, "Dense leaf gradient")
            require(grad.dtype == param.dtype and grad.shape == param.shape, "Native gradient")
            # Blocking D2H ensures the source is safe to release. No untracked DMA.
            cpu = grad.detach().to(device="cpu", dtype=torch.float32, copy=True)
            require(bool(torch.isfinite(cpu).all()), "Finite native gradient")
            if name in self.buffers:
                self.buffers[name].add_(cpu)
            else:
                self.buffers[name] = cpu
            param.grad = None

        try:
            for name, p in self.named:
                hooks.append(
                    p.register_post_accumulate_grad_hook(
                        lambda param, name=name: spill(name, param)
                    )
                )
            yield self
            require(bool(seen), "One nonempty backward required")
            require(not require_all or seen == set(self.schema), "Incomplete full gradient")
            require(all(p.grad is None for _, p in self.named), "Device gradients released")
            for name in seen:
                self.events[name] = self.events.get(name, 0) + 1
            self.backward_count += 1
        except BaseException:
            self.poisoned = True
            raise
        finally:
            for hook in hooks:
                hook.remove()
            for _, p in self.named:
                p.grad = None
            self.active = False

    def receipt(self):
        self._check()
        return dict(
            backwards=self.backward_count,
            parameter_tensors=len(self.schema),
            visited_tensors=len(self.buffers),
            events=dict(self.events),
            cpu_buffer_bytes=sum(v.numel() * v.element_size() for v in self.buffers.values()),
            aggregation="native leaf gradients summed in row order on CPU FP32; not owner window",
            device_gradients_retained=0,
            native_weight_updates=0,
        )


def tensor_pair_stats(left, right, *, chunk_elements=1 << 20):
    """FP64 reduction in bounded chunks, including zeros for an unused path."""
    require(left is not None or right is not None, "At least one tensor")
    template = left if left is not None else right
    require(type(chunk_elements) is int and chunk_elements > 0, "Chunk size")
    for v in (left, right):
        require(v is None or (v.device.type == "cpu" and v.shape == template.shape), "CPU layout")
    a = None if left is None else left.detach().reshape(-1)
    b = None if right is None else right.detach().reshape(-1)
    dot = aa = bb = error2 = 0.0
    max_error = max_left = max_right = 0.0
    nonzero_a = nonzero_b = positive_a = positive_b = 0
    for start in range(0, template.numel(), chunk_elements):
        stop = min(start + chunk_elements, template.numel())
        x = torch.zeros(stop - start, dtype=torch.float64) if a is None else a[start:stop].double()
        y = torch.zeros(stop - start, dtype=torch.float64) if b is None else b[start:stop].double()
        require(bool(torch.isfinite(x).all() and torch.isfinite(y).all()), "Finite reduction")
        dot += float(x.dot(y))
        aa += float(x.dot(x))
        bb += float(y.dot(y))
        d = x - y
        error2 += float(d.dot(d))
        max_error = max(max_error, float(d.abs().max()))
        max_left = max(max_left, float(x.abs().max()))
        max_right = max(max_right, float(y.abs().max()))
        nonzero_a += int(x.count_nonzero())
        nonzero_b += int(y.count_nonzero())
        positive_a += int((x > 0).sum())
        positive_b += int((y > 0).sum())
    return dict(
        elements=template.numel(),
        dot=dot,
        left_sq=aa,
        right_sq=bb,
        cosine=dot / (aa * bb) ** 0.5 if aa and bb else None,
        residual_sq=error2,
        max_abs_residual=max_error,
        left_max_abs=max_left,
        right_max_abs=max_right,
        left_nonzero=nonzero_a,
        right_nonzero=nonzero_b,
        left_positive=positive_a,
        right_positive=positive_b,
    )


def upper_replay(graph, trace):
    """Detached-state native R graph, using the same cut/masks/extent/head."""
    from .composition import pack_memory

    query, memory = trace.query.detach(), trace.memory.detach()
    packed, mask = pack_memory(memory, trace.memory_mask, query, trace.query_mask)
    final = graph.host.from_cut_states(packed, mask, graph.cut)
    columns = trace.memory_mask.sum(1)[:, None] + torch.arange(query.shape[1], device=query.device)
    rows = torch.arange(query.shape[0], device=query.device)[:, None]
    return graph.host.head(final[rows, columns])
