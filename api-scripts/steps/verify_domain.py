"""Step 4: Verify domain in Microsoft 365 with retry + exponential backoff."""

import time
from log import info, ok, warn, err
from services.graph_api import GraphClient

BACKOFF_SCHEDULE = [5, 15, 30, 60]  # seconds


def run(tenant: dict, domain: str = None, **kwargs) -> dict:
    if not domain:
        err("--domain is required for verify-domain step")
        return {"status": "error", "reason": "missing_domain"}

    info(f"Step 4: Verify domain '{domain}'")

    graph = GraphClient(tenant["tenant_id"], tenant["client_id"], tenant["client_secret"])

    # Check if already verified
    try:
        resp = graph.get(f"/domains/{domain}")
        domain_data = resp.json()
        if domain_data.get("isVerified", False):
            ok(f"Domain '{domain}' is already verified")
            return {"status": "already_verified", "domain": domain}
    except RuntimeError:
        pass

    # Attempt verification with retries
    for attempt, wait in enumerate(BACKOFF_SCHEDULE, start=1):
        info(f"Verification attempt {attempt}/{len(BACKOFF_SCHEDULE)}")
        try:
            resp = graph.post(f"/domains/{domain}/verify")
            data = resp.json()
            if data.get("isVerified", False):
                ok(f"Domain '{domain}' verified successfully")
                return {"status": "verified", "domain": domain, "attempts": attempt}
        except RuntimeError as e:
            warn(f"Verification attempt {attempt} failed: {e}")

        if attempt < len(BACKOFF_SCHEDULE):
            info(f"Waiting {wait}s for DNS propagation...")
            time.sleep(wait)

    # Final attempt
    info("Final verification attempt")
    try:
        resp = graph.post(f"/domains/{domain}/verify")
        data = resp.json()
        if data.get("isVerified", False):
            ok(f"Domain '{domain}' verified successfully")
            return {"status": "verified", "domain": domain, "attempts": len(BACKOFF_SCHEDULE) + 1}
    except RuntimeError as e:
        err(f"Final verification failed: {e}")

    err(f"Domain '{domain}' could not be verified after all attempts")
    return {"status": "error", "reason": "verification_failed", "domain": domain}
