"""Workspace algorithms under stable, version-free names.

Each name is the historical class itself, not a copy, so no arithmetic can drift:
v4.1's token-local lattice and v5's causal-broadcast lattice and
``LatentWorkspaceLoss`` (reached until now only through ``engine.py``), v9's
writer and reader and v4's low-rank logit adapter (``workspace_core``), and the
V14-V19 readers.
"""

from latent_workspace_ft_v10.engine import CausalBroadcastLatentWorkspace as CausalBroadcastLattice
from latent_workspace_ft_v10.engine import CausalLatentWorkspace as TokenLocalLattice
from latent_workspace_ft_v10.engine import LatentWorkspaceLoss
from latent_workspace_ft_v10.precision_bridge import (
    PrecisionAwareWorkspaceBridge as PrecisionBridge,
)
from latent_workspace_ft_v10.query_modulated_bridge import (
    QueryModulatedWorkspaceBridge as QueryModulatedBridge,
)
from latent_workspace_ft_v10.v19_dual_budget_reader import (
    DualBudgetWorkspaceBridge as DualBudgetBridge,
)
from latent_workspace_ft_v10.workspace_core import (
    FunctionalMemoryReader,
    FunctionalMemoryWriter,
    ReaderState,
)
from latent_workspace_ft_v10.workspace_core import (
    LowRankWorkspaceLogitAdapter as LowRankLogitAdapter,
)

__all__ = [
    "CausalBroadcastLattice",
    "DualBudgetBridge",
    "FunctionalMemoryReader",
    "FunctionalMemoryWriter",
    "LatentWorkspaceLoss",
    "LowRankLogitAdapter",
    "PrecisionBridge",
    "QueryModulatedBridge",
    "ReaderState",
    "TokenLocalLattice",
]
