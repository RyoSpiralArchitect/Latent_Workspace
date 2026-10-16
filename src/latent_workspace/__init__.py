"""Latent Workspace engine: one stack over portable hosts (docs/ARCHITECTURE.md).

The living home of every general concept. It owns its code and never imports the
frozen historical package ``latent_workspace_ft_v10``; historical algorithms
enter only by promotion (copied once, pinned by a parity test, recorded in
``configs/architecture/PROMOTIONS.json``).
"""

from .cuts import BoundaryDescriptor, FunctionalBoundaryAdapter
from .host import DecoderHost, Host
from .lattice import (
    CausalBroadcastAttention,
    CausalBroadcastLatentWorkspace,
    CausalBroadcastLattice,
    CausalLatentWorkspace,
    TokenLocalLattice,
)
from .losses import LatentWorkspaceLoss
from .operators import NormalizationSpec
from .readout import NativeReadoutResult, NativeWorkspaceReadout, ResidualInjection, inject_last
from .routes import (
    AnswerResidualRoute,
    CutResidualRoute,
    LogitResidualRoute,
    LowRankLogitAdapter,
    LowRankWorkspaceLogitAdapter,
)
from .scratch import ScratchDecoder

__all__ = [
    "AnswerResidualRoute",
    "BoundaryDescriptor",
    "CausalBroadcastAttention",
    "CausalBroadcastLatentWorkspace",
    "CausalBroadcastLattice",
    "CausalLatentWorkspace",
    "CutResidualRoute",
    "DecoderHost",
    "FunctionalBoundaryAdapter",
    "Host",
    "LatentWorkspaceLoss",
    "LogitResidualRoute",
    "LowRankLogitAdapter",
    "LowRankWorkspaceLogitAdapter",
    "NativeReadoutResult",
    "NativeWorkspaceReadout",
    "NormalizationSpec",
    "ResidualInjection",
    "ScratchDecoder",
    "TokenLocalLattice",
    "inject_last",
]
