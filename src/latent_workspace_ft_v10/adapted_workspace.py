"""Model-independent token-to-readout path shared by CE, evaluation and decoding.

The adapter, not this learner component, owns native model arithmetic. The
writer, reader and query policy stay unchanged. This opt-in path does not alter
the sealed V15 optimizer/resume runner, implement KV carry or introduce losses.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from .reader_query import QuestionSpan
from .readout_transport import ReadoutAdapter, TransportReadout
from .v15_5_learner import NativeAnswerTerms
from .v15_full_update import validate_token_tuple
from .v15_pipeline import NativeWorkspacePipeline
from .v15_readout import NativeReadoutResult


@dataclass
class AdaptedWorkspaceOutput:
    readout: NativeReadoutResult
    delta: torch.Tensor
    reader_query: torch.Tensor
    transport: TransportReadout


class AdaptedWorkspacePipeline:
    """No family checks, model attribute paths, head rows or answer inputs."""

    def __init__(self, bridge, adapter: ReadoutAdapter, mode: str = "final"):
        self.bridge, self.adapter = bridge, adapter
        # Reuse the exact bound-prefix/query/reader policy, without its old head.
        self._reader = NativeWorkspacePipeline(bridge, None, mode)

    def __call__(self, prefix_ids, memory, memory_mask, *, span: QuestionSpan):
        captured = {}

        def residual(normalized):
            delta, query = self._reader.delta(
                normalized, memory, memory_mask, prefix_ids=prefix_ids, span=span
            )
            captured.update(delta=delta, query=query)
            return delta

        transport = self.adapter.read(prefix_ids, residual)
        return AdaptedWorkspaceOutput(
            transport.readout, captured["delta"], captured["query"], transport
        )


def adapted_answer_terms(
    pipeline: AdaptedWorkspacePipeline,
    memory: torch.Tensor,
    memory_mask: torch.Tensor,
    *,
    prefix_ids: tuple[int, ...],
    completion_prefix_ids: tuple[int, ...],
    span: QuestionSpan,
    answer_token_id: int,
    eos_token_id: int,
) -> NativeAnswerTerms:
    """Same answer/EOS supervision; labels enter CE, not the answer forward.

    Completion is explicitly teacher-forced; it is not generation evidence.
    Frozen/full parameter ownership is external, and neither route detaches
    features or replaces model-native logits with selected-row approximations.
    """
    vocabulary = pipeline.adapter.vocabulary
    for ids in (prefix_ids, completion_prefix_ids, (answer_token_id, eos_token_id)):
        validate_token_tuple(ids, vocabulary)
    if answer_token_id == eos_token_id:
        raise ValueError("Answer token and EOS must differ")
    if prefix_ids != span.prefix_ids:
        raise ValueError("Answer must start at the exact bound inference prefix")
    if completion_prefix_ids != prefix_ids + (answer_token_id,):
        raise ValueError("Completion must extend prefix by its verified answer")
    answer = pipeline(prefix_ids, memory, memory_mask, span=span)
    completion = pipeline(completion_prefix_ids, memory, memory_mask, span=span)
    device = answer.readout.logits.device
    return NativeAnswerTerms(
        answer,
        completion,
        answer.readout.cross_entropy(torch.tensor([answer_token_id], device=device)),
        completion.readout.cross_entropy(torch.tensor([eos_token_id], device=device)),
    )
