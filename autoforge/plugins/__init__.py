"""Plugin system for autoforge — protocols, result types, and discovery."""

from __future__ import annotations

from autoforge.plugins.loader import (
    PipelineComponents,
    list_components,
    load_component,
    load_judge,
    load_pipeline,
)
from autoforge.plugins.protocols import (
    Builder,
    BuildResult,
    Deployer,
    DeployResult,
    Judge,
    JudgeVerdict,
    PathsConfig,
    Profiler,
    ProfileResult,
    RunnerConfig,
    RunnerSectionConfig,
    Tester,
    TestResult,
    TimeoutsConfig,
)

__all__ = [
    "BuildResult",
    "Builder",
    "DeployResult",
    "Deployer",
    "Judge",
    "JudgeVerdict",
    "PathsConfig",
    "PipelineComponents",
    "ProfileResult",
    "Profiler",
    "RunnerConfig",
    "RunnerSectionConfig",
    "TestResult",
    "Tester",
    "TimeoutsConfig",
    "list_components",
    "load_component",
    "load_judge",
    "load_pipeline",
]
