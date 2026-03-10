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
    task_soft_time_limit=900,   # 15 min global default
    task_time_limit=960,        # 16 min global hard limit
    task_annotations={
        "app.tasks.tenant_setup.run_tenant_setup": {
            "soft_time_limit": 1800, "time_limit": 1860,   # 30/31 min
        },
        "app.tasks.mailbox_pipeline.run_mailbox_pipeline": {
            "soft_time_limit": 3000, "time_limit": 3060,   # 50/51 min (larger batches)
        },
        "app.tasks.workflow_tasks.run_workflow_job": {
            "soft_time_limit": 3000, "time_limit": 3060,   # 50/51 min (matches mailbox pipeline)
        },
        "app.tasks.workflow_tasks.retry_workflow_job": {
            "soft_time_limit": 3000, "time_limit": 3060,
        },
        "app.tasks.monitor.run_mailflow_check": {
            "soft_time_limit": 180, "time_limit": 210,     # 3/3.5 min
        },
        "app.tasks.monitor.run_tenant_check": {
            "soft_time_limit": 300, "time_limit": 330,     # 5/5.5 min
        },
        "app.tasks.monitor.reap_stale_tasks": {
            "soft_time_limit": 120, "time_limit": 150,     # 2/2.5 min
        },
    },
    task_routes={
        "app.tasks.tenant_setup.*": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.enable_dkim_task": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.retry_pending_dkim": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.retry_missing_mailboxes": {"queue": "tenant_setup"},
        "app.tasks.mailbox_pipeline.run_mailbox_health_check": {"queue": "health_check"},
        "app.tasks.mailbox_pipeline.*": {"queue": "mailbox"},
        "app.tasks.workflow_tasks.*": {"queue": "mailbox"},  # v2 workflow tasks default to mailbox queue
        "app.tasks.monitor.run_mailflow_check": {"queue": "health_check"},
        "app.tasks.monitor.*": {"queue": "monitor"},
    },
    task_default_queue="default",
    worker_prefetch_multiplier=1,
    beat_schedule={
        "monitor-smtp-every-6h": {
            "task": "app.tasks.monitor.run_smtp_checks",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "monitor-dns-every-6h": {
            "task": "app.tasks.monitor.run_dns_checks",
            "schedule": crontab(minute=30, hour="*/6"),
        },
        "reap-stale-tasks-every-5m": {
            "task": "app.tasks.monitor.reap_stale_tasks",
            "schedule": crontab(minute="*/5"),
        },
        "monitor-mailflow-every-6h": {
            "task": "app.tasks.monitor.run_mailflow_checks",
            "schedule": crontab(minute=15, hour="*/6"),
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
import app.tasks.tenant_health  # noqa: F401, E402
import app.tasks.workflow_tasks  # noqa: F401, E402
