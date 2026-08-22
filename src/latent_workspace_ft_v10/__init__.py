"""Portable LatentWorkspace FT v12 package with v10 import compatibility."""

from .engine import (
    ExperimentConfig,
    FunctionalBoundaryAdapter,
    LatentWorkspaceCausalLM,
    TrainConfig,
    WorkspaceConfig,
    build_optimizer,
    configure_trainability,
    main,
    resume_signature,
)

__all__ = [
    "ExperimentConfig",
    "FunctionalBoundaryAdapter",
    "LatentWorkspaceCausalLM",
    "TrainConfig",
    "WorkspaceConfig",
    "build_optimizer",
    "configure_trainability",
    "main",
    "resume_signature",
]

__version__ = "12.0.0"
