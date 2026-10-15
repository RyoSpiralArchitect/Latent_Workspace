"""Portable LatentWorkspace FT v14 with the historical v10 import path."""

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

__version__ = "14.0.0"
