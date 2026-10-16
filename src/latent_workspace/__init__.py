"""Latent Workspace: one stack over portable hosts (docs/ARCHITECTURE.md).

The version-free public API. It wraps the historical ``latent_workspace_ft_v10``
modules without changing them; parity tests pin every wrapper to its source.
"""

from .components import (
    CausalBroadcastLattice,
    DualBudgetBridge,
    FunctionalMemoryReader,
    FunctionalMemoryWriter,
    LatentWorkspaceLoss,
    LowRankLogitAdapter,
    PrecisionBridge,
    QueryModulatedBridge,
    ReaderState,
    TokenLocalLattice,
)
from .host import DecoderHost, Host
from .routes import AnswerResidualRoute, CutResidualRoute, LogitResidualRoute
from .scratch import ScratchDecoder

__all__ = [
    "AnswerResidualRoute",
    "CausalBroadcastLattice",
    "CutResidualRoute",
    "DecoderHost",
    "DualBudgetBridge",
    "FunctionalMemoryReader",
    "FunctionalMemoryWriter",
    "Host",
    "LatentWorkspaceLoss",
    "LogitResidualRoute",
    "LowRankLogitAdapter",
    "PrecisionBridge",
    "QueryModulatedBridge",
    "ReaderState",
    "ScratchDecoder",
    "TokenLocalLattice",
]
