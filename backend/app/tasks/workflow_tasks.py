"""Celery tasks that wrap the workflow engine."""

import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.workflow_tasks.run_workflow_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_workflow_job(self, job_id: str):
    """Run a workflow job through the engine.

    Queue routing is handled by the caller based on job_type:
    - tenant_setup -> queue='tenant_setup'
    - mailbox_pipeline -> queue='mailbox'
    - health_check -> queue='health_check'
    """
    from app.workflow.engine import WorkflowEngine
    from app.workflow.step_registry import register_steps, get_steps

    # Lazy-register step classes if not already registered
    if not get_steps("mailbox_pipeline"):
        from app.workflow.steps.mailbox_pipeline import MAILBOX_PIPELINE_STEPS
        register_steps("mailbox_pipeline", MAILBOX_PIPELINE_STEPS)

    if not get_steps("tenant_setup"):
        from app.workflow.steps.tenant_setup import TENANT_SETUP_STEPS
        register_steps("tenant_setup", TENANT_SETUP_STEPS)

    engine = WorkflowEngine()
    return engine.run(job_id)


@celery_app.task(
    name="app.tasks.workflow_tasks.retry_workflow_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def retry_workflow_job(self, job_id: str, step_index: int | None = None):
    """Retry a failed workflow job from a specific step."""
    from app.workflow.engine import WorkflowEngine
    from app.workflow.step_registry import register_steps, get_steps

    if not get_steps("mailbox_pipeline"):
        from app.workflow.steps.mailbox_pipeline import MAILBOX_PIPELINE_STEPS
        register_steps("mailbox_pipeline", MAILBOX_PIPELINE_STEPS)

    if not get_steps("tenant_setup"):
        from app.workflow.steps.tenant_setup import TENANT_SETUP_STEPS
        register_steps("tenant_setup", TENANT_SETUP_STEPS)

    engine = WorkflowEngine()
    return engine.retry_from_step(job_id, step_index)
