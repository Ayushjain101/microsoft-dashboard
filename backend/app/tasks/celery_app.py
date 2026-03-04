"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("tenant_tool")

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    task_routes={
        "app.tasks.tenant_setup.*": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.enable_dkim_task": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.retry_pending_dkim": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.*": {"queue": "mailbox"},
        "app.tasks.monitor.*": {"queue": "monitor"},
    },
    task_default_queue="default",
    beat_schedule={
        "monitor-smtp-every-30m": {
            "task": "app.tasks.monitor.run_smtp_checks",
            "schedule": crontab(minute="*/30"),
        },
        "monitor-dns-every-6h": {
            "task": "app.tasks.monitor.run_dns_checks",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "reap-stale-tasks-every-5m": {
            "task": "app.tasks.monitor.reap_stale_tasks",
            "schedule": crontab(minute="*/5"),
        },
        "retry-pending-dkim-every-2h": {
            "task": "app.tasks.mailbox_pipeline.retry_pending_dkim",
            "schedule": crontab(minute=0, hour="*/2"),
        },
    },
)

# Explicit imports to register tasks
import app.tasks.tenant_setup  # noqa: F401, E402
import app.tasks.mailbox_pipeline  # noqa: F401, E402
import app.tasks.monitor  # noqa: F401, E402
