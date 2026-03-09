"""Mailbox pipeline steps — 9 steps for mailbox creation."""

from app.workflow.steps.mailbox_pipeline.s01_assign_license import AssignLicenseStep
from app.workflow.steps.mailbox_pipeline.s02_enable_org_smtp import EnableOrgSmtpStep
from app.workflow.steps.mailbox_pipeline.s03_add_domain import AddDomainStep
from app.workflow.steps.mailbox_pipeline.s04_verify_domain import VerifyDomainStep
from app.workflow.steps.mailbox_pipeline.s05_setup_dkim import SetupDkimStep
from app.workflow.steps.mailbox_pipeline.s06_setup_dmarc import SetupDmarcStep
from app.workflow.steps.mailbox_pipeline.s07_create_mailboxes import CreateMailboxesStep
from app.workflow.steps.mailbox_pipeline.s08_enable_smtp import EnableSmtpStep
from app.workflow.steps.mailbox_pipeline.s09_disable_calendar import DisableCalendarStep

MAILBOX_PIPELINE_STEPS = [
    AssignLicenseStep,
    EnableOrgSmtpStep,
    AddDomainStep,
    VerifyDomainStep,
    SetupDkimStep,
    SetupDmarcStep,
    CreateMailboxesStep,
    EnableSmtpStep,
    DisableCalendarStep,
]

__all__ = ["MAILBOX_PIPELINE_STEPS"]
