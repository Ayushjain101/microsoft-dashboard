"""Workflow engine — runs, resumes, and retries workflow jobs."""

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.exceptions import JobNotFoundError, LockError, StepError, WorkflowError
from app.core.uow import UnitOfWork
from app.core.temp_artifacts import TempArtifact
from app.models.workflow import WorkflowJob, WorkflowStep
from app.websocket import publish_event_sync
from app.workflow.locking import acquire_advisory_lock, release_advisory_lock
from app.workflow.state_machine import StateMachine
from app.workflow.step_registry import BaseStep, StepResult, get_steps
from app.workflow.retry import exponential_backoff

logger = logging.getLogger(__name__)

sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, pool_recycle=3600)


@dataclass
class StepContext:
    """Context passed to each step during execution."""
    job: WorkflowJob
    tenant_data: dict[str, Any]
    step_record: WorkflowStep
    db: Session
    uow: UnitOfWork
    temp: TempArtifact
    shared: dict[str, Any] = field(default_factory=dict)  # Steps can pass data forward

    def publish(self, event_type: str, data: dict):
        """Publish a WebSocket event."""
        publish_event_sync(event_type, data)

    def publish_progress(self, message: str, status: str = "running"):
        """Publish workflow progress update."""
        job_id = str(self.job.id)
        event_type = "mailbox_pipeline_progress" if self.job.job_type == "mailbox_pipeline" else "tenant_setup_progress"
        data = {
            "step": self.step_record.step_index,
            "total": self.job.total_steps,
            "message": message,
            "status": status,
        }
        if self.job.job_type == "mailbox_pipeline":
            data["job_id"] = job_id
        else:
            data["tenant_id"] = str(self.job.tenant_id)
        self.publish(event_type, data)


class WorkflowEngine:
    """Executes workflow jobs by running their registered steps."""

    def run(self, job_id: str):
        """Run or resume a workflow job."""
        with Session(sync_engine) as db:
            job = db.get(WorkflowJob, job_id)
            if not job:
                raise JobNotFoundError(f"Job {job_id} not found")

            # Idempotency: skip completed/cancelled jobs
            if job.status in ("complete", "cancelled"):
                logger.info(f"Job {job_id} already {job.status}, skipping")
                return {"status": job.status, "reason": "already_finished"}

            # Acquire distributed lock
            if not acquire_advisory_lock(db, str(job_id)):
                raise LockError(f"Job {job_id} is already being processed by another worker")

            try:
                return self._execute_job(db, job)
            finally:
                release_advisory_lock(db, str(job_id))

    def _execute_job(self, db: Session, job: WorkflowJob) -> dict:
        """Execute all pending steps for a job."""
        job_id = str(job.id)
        step_classes = get_steps(job.job_type)
        if not step_classes:
            raise WorkflowError(f"No steps registered for job type '{job.job_type}'")

        # Transition to running
        if job.status != "running":
            job.status = StateMachine.transition_job(job.status, "running")
            job.started_at = job.started_at or datetime.now(timezone.utc)
            db.commit()

        # Ensure step records exist
        self._ensure_step_records(db, job, step_classes)

        # Load tenant data
        from app.tasks.mailbox_pipeline import _load_tenant_data
        tenant_data = _load_tenant_data(str(job.tenant_id))

        uow = UnitOfWork(db, actor=f"celery:workflow")
        temp = TempArtifact(db=db, job_id=job.id)

        # Track PFX path from tenant_data for cleanup
        pfx_path = tenant_data.get("cert_pfx_path")
        if pfx_path:
            temp._files.append(pfx_path)

        try:
            shared: dict[str, Any] = {}

            # Load config into shared context
            if job.config:
                shared.update(job.config)
            shared["tenant_data"] = tenant_data

            steps = db.execute(
                select(WorkflowStep)
                .where(WorkflowStep.job_id == job.id)
                .order_by(WorkflowStep.step_index)
            ).scalars().all()

            for step_record in steps:
                if step_record.status == "success":
                    continue  # Already completed, skip (idempotent resume)

                step_idx = step_record.step_index
                if step_idx >= len(step_classes):
                    break

                step_cls = step_classes[step_idx]
                step_instance = step_cls()

                ctx = StepContext(
                    job=job,
                    tenant_data=tenant_data,
                    step_record=step_record,
                    db=db,
                    uow=uow,
                    temp=temp,
                    shared=shared,
                )

                # Update job progress
                job.current_step_index = step_idx
                if job.job_type == "mailbox_pipeline":
                    job_phase = f"Step {step_idx + 1}/{job.total_steps}: {step_instance.name}"
                else:
                    job_phase = f"Step {step_idx + 1}/{job.total_steps}: {step_instance.name}"
                db.commit()

                ctx.publish_progress(step_instance.name)

                # Check preconditions
                if not step_instance.preconditions(ctx):
                    step_record.status = "skipped"
                    step_record.detail = "Precondition not met"
                    step_record.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    self._publish_step_result(job, step_record, step_instance.name)
                    continue

                # Execute with retries
                result = self._execute_step_with_retry(ctx, step_instance, step_record)

                # Record result
                step_record.status = result.status
                step_record.detail = result.detail
                step_record.completed_at = datetime.now(timezone.utc)
                db.commit()

                self._publish_step_result(job, step_record, step_instance.name)

                uow.add_event(
                    f"step_{result.status}",
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    payload={"step_index": step_idx, "step_name": step_instance.name, "detail": result.detail},
                )

                # Merge step data into shared context
                if result.data:
                    shared.update(result.data)

                # Handle failure
                if result.status == "failed" and step_instance.is_blocking:
                    job.status = "failed"
                    job.error_message = f"Step {step_idx + 1} ({step_instance.name}) failed: {result.detail}"
                    uow.commit()
                    self._publish_job_progress(job, f"Failed at: {step_instance.name}", "failed")
                    return {"status": "failed", "error": job.error_message, "job_id": str(job.id)}

            # All steps done
            job.status = "complete"
            job.completed_at = datetime.now(timezone.utc)
            job.current_step_index = None
            uow.add_event("job_complete", tenant_id=job.tenant_id, job_id=job.id)
            uow.commit()

            self._publish_job_progress(job, "Pipeline complete", "complete")
            return {"status": "complete", "job_id": str(job.id)}

        except Exception as e:
            logger.error(f"Job {job_id} failed with exception: {e}", exc_info=True)
            try:
                job.status = "failed"
                job.error_message = str(e)[:2000]
                uow.add_event("job_failed", tenant_id=job.tenant_id, job_id=job.id,
                              payload={"error": str(e)[:500]})
                uow.commit()
            except Exception:
                db.rollback()
                job.status = "failed"
                job.error_message = str(e)[:2000]
                db.commit()
            self._publish_job_progress(job, f"Failed: {str(e)}", "failed")
            return {"status": "failed", "error": str(e), "job_id": str(job.id)}
        finally:
            temp.cleanup()

    def _execute_step_with_retry(self, ctx: StepContext, step: BaseStep, record: WorkflowStep) -> StepResult:
        """Execute a step with retry logic."""
        import time

        max_attempts = step.max_attempts
        last_error = None

        for attempt in range(max_attempts):
            record.attempts = attempt + 1
            record.status = "running"
            record.started_at = record.started_at or datetime.now(timezone.utc)
            ctx.db.commit()

            try:
                result = step.execute(ctx)
                return result
            except Exception as e:
                last_error = e
                record.last_error = str(e)[:2000]
                ctx.db.commit()

                if attempt < max_attempts - 1:
                    delay = exponential_backoff(attempt, step.backoff_base, step.backoff_max)
                    logger.warning(
                        f"Step {record.step_index + 1} ({step.name}) attempt {attempt + 1}/{max_attempts} "
                        f"failed: {e}. Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

        # All attempts exhausted
        if step.is_blocking:
            return StepResult(status="failed", detail=str(last_error)[:2000])
        else:
            return StepResult(status="warning", detail=str(last_error)[:2000])

    def _ensure_step_records(self, db: Session, job: WorkflowJob, step_classes: list[type[BaseStep]]):
        """Ensure WorkflowStep records exist for all steps."""
        existing = db.execute(
            select(WorkflowStep).where(WorkflowStep.job_id == job.id)
        ).scalars().all()
        existing_indices = {s.step_index for s in existing}

        for idx, step_cls in enumerate(step_classes):
            if idx not in existing_indices:
                step = step_cls()
                db.add(WorkflowStep(
                    job_id=job.id,
                    step_index=idx,
                    step_name=step.name,
                    max_attempts=step.max_attempts,
                ))
        job.total_steps = len(step_classes)
        db.commit()

    def _publish_step_result(self, job: WorkflowJob, step: WorkflowStep, step_name: str):
        """Publish step result via WebSocket."""
        event_type = "mailbox_step_result" if job.job_type == "mailbox_pipeline" else "tenant_step_result"
        data = {
            "step": step.step_index + 1,  # 1-indexed for frontend compat
            "step_status": step.status,
            "message": step_name,
            "detail": step.detail,
        }
        if job.job_type == "mailbox_pipeline":
            data["job_id"] = str(job.id)
        else:
            data["tenant_id"] = str(job.tenant_id)
        publish_event_sync(event_type, data)

    def _publish_job_progress(self, job: WorkflowJob, message: str, status: str):
        """Publish job-level progress via WebSocket."""
        event_type = "mailbox_pipeline_progress" if job.job_type == "mailbox_pipeline" else "tenant_setup_progress"
        data = {
            "step": job.current_step_index or 0,
            "total": job.total_steps or 0,
            "message": message,
            "status": status,
        }
        if job.job_type == "mailbox_pipeline":
            data["job_id"] = str(job.id)
        else:
            data["tenant_id"] = str(job.tenant_id)
        publish_event_sync(event_type, data)

    def retry_from_step(self, job_id: str, step_index: int | None = None):
        """Retry a failed job, optionally from a specific step."""
        with Session(sync_engine) as db:
            job = db.get(WorkflowJob, job_id)
            if not job:
                raise JobNotFoundError(f"Job {job_id} not found")

            if job.status not in ("failed", "cancelled"):
                raise WorkflowError(f"Can only retry failed/cancelled jobs, current status: {job.status}")

            # Reset failed/warning steps from the given index onward
            steps = db.execute(
                select(WorkflowStep)
                .where(WorkflowStep.job_id == job.id)
                .order_by(WorkflowStep.step_index)
            ).scalars().all()

            start_idx = step_index if step_index is not None else None
            for step in steps:
                if start_idx is not None and step.step_index < start_idx:
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
            db.commit()

        return self.run(job_id)
