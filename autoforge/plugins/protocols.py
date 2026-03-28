"""Plugin protocol definitions and shared result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from autoforge.campaign import CampaignConfig, ProjectConfig
    from autoforge.protocol import Direction, TestRequest


class PathsConfig(TypedDict, total=False):
    """Well-known [paths] section of runner config."""

    source_dir: str
    build_dir: str


class TimeoutsConfig(TypedDict, total=False):
    """Well-known [timeouts] section of runner config."""

    build_minutes: int
    test_minutes: int


class RunnerSectionConfig(TypedDict, total=False):
    """Well-known [runner] section of runner config."""

    phase: str
    log_level: str
    log_file: str
    poll_interval: int
    runner_id: str


class RunnerConfig(TypedDict, total=False):
    """Top-level runner configuration loaded from runner.toml.

    Well-known sections are typed; plugin-specific sections
    (build, deploy, bench, testpmd, profiling, etc.) are accessed
    via the dict[str, Any] base and vary per project.
    """

    paths: PathsConfig
    timeouts: TimeoutsConfig
    runner: RunnerSectionConfig


@dataclass
class BuildResult:
    """Result of a build phase."""

    success: bool
    log: str
    duration_seconds: float
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeployResult:
    """Result of a deploy phase."""

    success: bool
    log: str = ""
    error: str | None = None
    target_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of a test phase."""

    __test__ = False

    success: bool
    metric_value: float | None
    results_json: dict[str, Any] | None
    results_summary: str | None
    error: str | None
    duration_seconds: float
    log: str = ""


@dataclass
class ProfileResult:
    """Result of a profiling phase."""

    success: bool
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0


@runtime_checkable
class Builder(Protocol):
    """Builds a project from source at a given commit."""

    name: str

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        """Store configuration for subsequent build calls."""
        ...

    def build(self, source_path: Path, commit: str, build_dir: Path, timeout: int) -> BuildResult:
        """Build the project and return the result."""
        ...


@runtime_checkable
class Deployer(Protocol):
    """Deploys build artifacts to a test target."""

    name: str

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        """Store configuration for subsequent deploy calls."""
        ...

    def deploy(self, build_result: BuildResult) -> DeployResult:
        """Deploy build artifacts and return the result."""
        ...


@runtime_checkable
class Tester(Protocol):
    """Runs performance tests against a deployed target."""

    name: str

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        """Store configuration for subsequent test calls."""
        ...

    def test(self, deploy_result: DeployResult, timeout: int) -> TestResult:
        """Run tests and return the result."""
        ...


@runtime_checkable
class Profiler(Protocol):
    """Captures performance profiles during test execution."""

    name: str

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        """Store configuration for subsequent profile calls."""
        ...

    def profile(self, pid: int, duration: int, config: dict[str, Any]) -> ProfileResult:
        """Profile a running process and return the result."""
        ...


@dataclass
class JudgeVerdict:
    """Decision returned by a judge plugin."""

    keep: bool
    reason: str


@runtime_checkable
class Judge(Protocol):
    """Decides whether to keep or revert a completed test result."""

    name: str

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        """Store configuration for subsequent judge calls."""
        ...

    def judge(
        self,
        metric: float | None,
        best_val: float | None,
        direction: Direction,
        campaign: CampaignConfig,
        request: TestRequest,
    ) -> JudgeVerdict:
        """Return a verdict for whether to keep or revert the result.

        Args:
            metric: Metric value from this test run, or None if the test failed.
            best_val: Best metric seen so far, or None if no prior baseline.
            direction: Whether higher or lower is better.
            campaign: Full campaign config for this sprint.
            request: The completed test request.
        """
        ...
