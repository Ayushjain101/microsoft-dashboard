"""Step 2: Enable organization-wide SMTP authentication."""

import logging

from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class EnableOrgSmtpStep(BaseStep):
    name = "Enable Org SMTP"
    max_attempts = 2
    is_blocking = False

    def execute(self, ctx) -> StepResult:
        from app.services.powershell import PowerShellRunner, check_pwsh_available

        graph = ctx.shared.get("graph")
        if not graph:
            from app.services.graph_client import MicrosoftGraphClient
            td = ctx.tenant_data
            graph = MicrosoftGraphClient(td["tenant_id"], td["client_id"], td["client_secret"])
            ctx.shared["graph"] = graph

        if check_pwsh_available():
            ps = PowerShellRunner(ctx.tenant_data)
            try:
                ps.run(["Set-TransportConfig -SmtpClientAuthenticationDisabled $false"])
                return StepResult(status="success")
            except Exception:
                try:
                    graph.patch("/admin/exchange/transportConfig", beta=True,
                                json_data={"smtpAuthEnabled": True})
                    return StepResult(status="success")
                except Exception:
                    raise
        else:
            graph.patch("/admin/exchange/transportConfig", beta=True,
                        json_data={"smtpAuthEnabled": True})
            return StepResult(status="success")
