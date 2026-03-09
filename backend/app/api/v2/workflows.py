"""API v2 — Workflow endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import check_auth
from app.database import get_db
from app.models.workflow import WorkflowJob, WorkflowStep
from app.schemas.workflow import RetryRequest, WorkflowJobOut

router = APIRouter(prefix="/api/v2/workflows", tags=["workflows-v2"], dependencies=[Depends(check_auth)])


@router.get("/{job_id}", response_model=WorkflowJobOut)
async def get_workflow(job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a workflow job with all its steps."""
    result = await db.execute(
        select(WorkflowJob)
        .options(selectinload(WorkflowJob.steps))
        .where(WorkflowJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Workflow job not found")
    return job


@router.post("/{job_id}/retry", response_model=WorkflowJobOut)
async def retry_workflow(job_id: UUID, body: RetryRequest | None = None, db: AsyncSession = Depends(get_db)):
    """Retry a failed workflow from the last failed step or a specific step."""
    result = await db.execute(
        select(WorkflowJob).where(WorkflowJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Can only retry failed/cancelled jobs, current: {job.status}")

    from app.tasks.workflow_tasks import run_workflow_job
    step_index = body.step_index if body else None

    # Reset failed steps
    steps_result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.job_id == job_id)
        .order_by(WorkflowStep.step_index)
    )
    steps = steps_result.scalars().all()
    for step in steps:
        if step_index is not None and step.step_index < step_index:
            continue
        if step.status in ("failed", "warning"):
            step.status = "pending"
            step.attempts = 0
            step.last_error = None
            step.detail = None
            step.started_at = None
            step.completed_at = None

    job.status = "queued"
    job.error_message = None
    await db.commit()

    task = run_workflow_job.delay(str(job_id))
    job.celery_task_id = task.id
    await db.commit()

    # Re-fetch with steps
    result = await db.execute(
        select(WorkflowJob)
        .options(selectinload(WorkflowJob.steps))
        .where(WorkflowJob.id == job_id)
    )
    return result.scalar_one()


@router.post("/{job_id}/cancel")
async def cancel_workflow(job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Cancel a running or queued workflow."""
    result = await db.execute(
        select(WorkflowJob).where(WorkflowJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("pending", "queued", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status: {job.status}")

    job.status = "cancelled"
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    await db.commit()
    return {"status": "cancelled", "job_id": str(job_id)}


@router.post("/{job_id}/steps/{step_index}/retry", response_model=WorkflowJobOut)
async def retry_step(job_id: UUID, step_index: int, db: AsyncSession = Depends(get_db)):
    """Retry a specific step."""
    result = await db.execute(
        select(WorkflowJob).where(WorkflowJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    step_result = await db.execute(
        select(WorkflowStep).where(
            WorkflowStep.job_id == job_id,
            WorkflowStep.step_index == step_index,
        )
    )
    step = step_result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    if step.status not in ("failed", "warning"):
        raise HTTPException(status_code=400, detail=f"Can only retry failed/warning steps, current: {step.status}")

    step.status = "pending"
    step.attempts = 0
    step.last_error = None
    step.detail = None
    step.started_at = None
    step.completed_at = None

    if job.status == "failed":
        job.status = "queued"
        job.error_message = None

    await db.commit()

    from app.tasks.workflow_tasks import run_workflow_job
    task = run_workflow_job.delay(str(job_id))
    job.celery_task_id = task.id
    await db.commit()

    result = await db.execute(
        select(WorkflowJob)
        .options(selectinload(WorkflowJob.steps))
        .where(WorkflowJob.id == job_id)
    )
    return result.scalar_one()
