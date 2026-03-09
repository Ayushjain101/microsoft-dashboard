"""Tenant setup steps — 13 steps for Selenium-based tenant provisioning.

These steps are NOT decomposed yet since they delegate to the selenium_worker module.
The tenant_setup task continues to use the existing selenium_worker.setup_single_tenant()
function, wrapped in the workflow engine for unified tracking.
"""

from app.workflow.steps.tenant_setup.full_setup import TenantSetupStep

TENANT_SETUP_STEPS = [TenantSetupStep]

__all__ = ["TENANT_SETUP_STEPS"]
