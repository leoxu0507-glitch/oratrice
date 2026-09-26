"""Configuration-driven launch plan contracts.

The launcher package intentionally contains no process or network lifecycle
code.  It only turns a validated :class:`core.configuration.Configuration`
into immutable launch targets that an orchestration layer may execute.
"""

from .plan import LaunchPlan, LaunchPlanError, LaunchTarget
from .orchestrator import LauncherError, LauncherOrchestrator, LaunchResult, TargetOutcome

__all__ = [
    "LaunchPlan",
    "LaunchPlanError",
    "LaunchTarget",
    "LauncherOrchestrator",
    "LauncherError",
    "LaunchResult",
    "TargetOutcome",
]
