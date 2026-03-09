"""Step registry — maps step names to step classes."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.workflow.engine import StepContext

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of executing a step."""
    status: str  # success, failed, warning
    detail: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class BaseStep(ABC):
    """Base class for workflow steps."""

    name: str = ""
    max_attempts: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 120.0
    is_blocking: bool = True  # If False, failure produces warning, not error

    @abstractmethod
    def execute(self, ctx: "StepContext") -> StepResult:
        """Execute the step. Must return a StepResult."""
        ...

    def preconditions(self, ctx: "StepContext") -> bool:
        """Check if step can run. Return False to skip."""
        return True

    def rollback(self, ctx: "StepContext"):
        """Optional rollback logic."""
        pass


# Global step registries
_REGISTRIES: dict[str, list[type[BaseStep]]] = {}


def register_steps(job_type: str, steps: list[type[BaseStep]]):
    """Register an ordered list of step classes for a job type."""
    _REGISTRIES[job_type] = steps


def get_steps(job_type: str) -> list[type[BaseStep]]:
    """Get registered step classes for a job type."""
    return _REGISTRIES.get(job_type, [])
