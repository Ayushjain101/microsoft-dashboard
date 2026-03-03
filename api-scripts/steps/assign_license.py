"""Step 1: Assign an available license to the admin user."""

from log import info, ok, warn, err
from services.graph_api import GraphClient


def run(tenant: dict, **kwargs) -> dict:
    info("Step 1: Assign license to admin user")

    graph = GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])

    # Get subscribed SKUs
    resp = graph.get("/subscribedSkus")
    skus = resp.json().get("value", [])

    # Find a SKU with available units
    target_sku = None
    for sku in skus:
        available = sku.get("prepaidUnits", {}).get("enabled", 0) - sku.get("consumedUnits", 0)
        if available > 0:
            target_sku = sku
            info(f"Found SKU: {sku['skuPartNumber']} ({available} available)")
            break

    if not target_sku:
        err("No SKUs with available licenses found")
        return {"status": "error", "reason": "no_available_sku"}

    # Get admin user — list users and pick the first (admin) account
    resp = graph.get("/users?$select=id,displayName,userPrincipalName&$top=10")
    users = resp.json().get("value", [])
    if not users:
        err("No users found in tenant")
        return {"status": "error", "reason": "no_users"}
    admin_user = users[0]
    user_id = admin_user["id"]
    admin_email = admin_user["userPrincipalName"]
    info(f"Admin user: {admin_email} ({user_id})")

    # Check if already assigned
    resp = graph.get(f"/users/{user_id}/licenseDetails")
    existing = [ld["skuId"] for ld in resp.json().get("value", [])]
    if target_sku["skuId"] in existing:
        ok(f"License {target_sku['skuPartNumber']} already assigned")
        return {"status": "already_assigned", "sku": target_sku["skuPartNumber"]}

    # Assign the license
    graph.post(f"/users/{user_id}/assignLicense", {
        "addLicenses": [{"skuId": target_sku["skuId"], "disabledPlans": []}],
        "removeLicenses": [],
    })

    ok(f"License {target_sku['skuPartNumber']} assigned to {admin_email}")
    return {"status": "assigned", "sku": target_sku["skuPartNumber"], "user": admin_email}
