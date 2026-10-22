"""Release only inactive CUDA allocator reservations at generation boundaries."""

import json


class GenerationBoundaryGuard:
    def __init__(self, guard, device, journal, *, cuda=None):
        if cuda is None:
            import torch

            cuda = torch.cuda
        self.guard, self.device, self.journal, self.cuda = guard, device, journal, cuda

    def __call__(self, phase):
        if phase.startswith("generation:") and self.device.type == "cuda":
            # The prior full-prefix result was deleted and its chosen token copied
            # to CPU. No live model, token, RNG or KV tensor is replaced here.
            self.cuda.synchronize(self.device)
            before = self.cuda.memory_allocated(self.device)
            reserved_before = self.cuda.memory_reserved(self.device)
            self.cuda.empty_cache()
            after = self.cuda.memory_allocated(self.device)
            row = dict(
                phase=phase,
                allocated_before=before,
                allocated_after=after,
                reserved_before=reserved_before,
                reserved_after=self.cuda.memory_reserved(self.device),
            )
            self.journal.write(json.dumps(row, sort_keys=True) + "\n")
            self.journal.flush()
            if before != after:
                raise ValueError("Generation cache release changed live allocation")
        # The original guard and every resource floor remain in force.
        return self.guard(phase)


def generate(graph, prefix, memory, *, journal, guard, **policy):
    from latent_workspace.native_evaluation import generate as original

    boundary = GenerationBoundaryGuard(guard, next(graph.parameters()).device, journal)
    return original(graph, prefix, memory, guard=boundary, **policy)
