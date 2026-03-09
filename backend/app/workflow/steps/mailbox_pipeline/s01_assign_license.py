"""Step 1: Assign Exchange license to first user."""

import logging

from app.workflow.step_registry import BaseStep, StepResult

logger = logging.getLogger(__name__)


class AssignLicenseStep(BaseStep):
    name = "Assign License"
    max_attempts = 2
    is_blocking = False  # Warning on failure

    def execute(self, ctx) -> StepResult:
        graph = ctx.shared.get("graph")
        if not graph:
            from app.services.graph_client import MicrosoftGraphClient
            td = ctx.tenant_data
            graph = MicrosoftGraphClient(td["tenant_id"], td["client_id"], td["client_secret"])
            ctx.shared["graph"] = graph

        resp = graph.get("/subscribedSkus", timeout=60)
        skus = resp.json().get("value", [])
        target_sku = None
        for sku in skus:
            available = sku.get("prepaidUnits", {}).get("enabled", 0) - sku.get("consumedUnits", 0)
            if available > 0:
                target_sku = sku
                break

        if target_sku:
            resp = graph.get("/users?$select=id,userPrincipalName&$top=1")
            users = resp.json().get("value", [])
            if users:
                user_id = users[0]["id"]
                resp = graph.get(f"/users/{user_id}/licenseDetails")
                existing = [ld["skuId"] for ld in resp.json().get("value", [])]
                if target_sku["skuId"] not in existing:
                    graph.post(f"/users/{user_id}/assignLicense", {
                        "addLicenses": [{"skuId": target_sku["skuId"], "disabledPlans": []}],
                        "removeLicenses": [],
                    })

        return StepResult(status="success")
