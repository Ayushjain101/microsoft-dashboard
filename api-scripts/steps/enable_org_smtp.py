"""Step 2: Enable SMTP AUTH at the organisation level."""

from log import info, ok, warn, err
from services.graph_api import GraphClient
from services.powershell import PowerShellRunner, check_pwsh_available


def _try_graph_beta(graph: GraphClient) -> bool:
    """Try to enable SMTP via Graph beta endpoint."""
    try:
        graph.patch("/admin/exchange/transportConfig", beta=True, json_data={
            "smtpAuthEnabled": True,
        })
        return True
    except RuntimeError as e:
        warn(f"Graph beta SMTP enable failed: {e}")
        return False


def _try_powershell(tenant: dict) -> bool:
    """Fall back to PowerShell to enable SMTP."""
    if not check_pwsh_available():
        err("PowerShell (pwsh) not available — cannot enable SMTP")
        return False

    ps = PowerShellRunner(tenant)
    try:
        ps.run([
            "Set-TransportConfig -SmtpClientAuthenticationDisabled $false",
        ])
        return True
    except RuntimeError as e:
        err(f"PowerShell SMTP enable failed: {e}")
        return False


def run(tenant: dict, **kwargs) -> dict:
    info("Step 2: Enable organisation-level SMTP AUTH")

    # PowerShell first — Graph beta transportConfig is unreliable
    if check_pwsh_available():
        if _try_powershell(tenant):
            ok("SMTP AUTH enabled via PowerShell")
            return {"status": "enabled", "method": "powershell"}
        warn("PowerShell method failed, trying Graph beta")

    # Graph beta fallback
    graph = GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])
    if _try_graph_beta(graph):
        ok("SMTP AUTH enabled via Graph beta API")
        return {"status": "enabled", "method": "graph_beta"}

    err("Could not enable SMTP AUTH via any method")
    return {"status": "error", "reason": "all_methods_failed"}
