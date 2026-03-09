"""Workflow state machine — validates status transitions."""

from app.core.exceptions import InvalidStateTransition

# Valid transitions for jobs
JOB_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "cancelled"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"complete", "failed", "cancelled"},
    "failed": {"queued", "cancelled"},  # retry -> re-queue
    "complete": set(),
    "cancelled": {"queued"},  # can re-queue a cancelled job
}

# Valid transitions for steps
STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "skipped"},
    "running": {"success", "failed", "warning"},
    "failed": {"running", "skipped"},  # retry
    "warning": {"running"},  # retry to upgrade
    "success": set(),
    "skipped": set(),
}


class StateMachine:
    """Validates and applies state transitions."""

    @staticmethod
    def can_transition_job(current: str, target: str) -> bool:
        return target in JOB_TRANSITIONS.get(current, set())

    @staticmethod
    def transition_job(current: str, target: str) -> str:
        if not StateMachine.can_transition_job(current, target):
            raise InvalidStateTransition(current, target)
        return target

    @staticmethod
    def can_transition_step(current: str, target: str) -> bool:
        return target in STEP_TRANSITIONS.get(current, set())

    @staticmethod
    def transition_step(current: str, target: str) -> str:
        if not StateMachine.can_transition_step(current, target):
            raise InvalidStateTransition(current, target)
        return target
