"""Backfill certificates for tenants that are missing cert_pfx/cert_password.

Generates a new cert, uploads to Azure via Graph API, saves to DB.
Run from backend dir: python3 backfill_certs.py
"""

import sys
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Tenant
from app.services.encryption import decrypt, encrypt, encrypt_bytes
from app.selenium_worker.cert_generator import generate_cert
from app.services.graph_client import MicrosoftGraphClient

sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)


def _decrypt_safe(val):
    if val is None:
        return None
    try:
        return decrypt(val)
    except Exception:
        return None


def backfill():
    with Session(sync_engine) as db:
        tenants = db.execute(
            select(Tenant).where(
                Tenant.status == "complete",
                Tenant.cert_pfx.is_(None),
            )
        ).scalars().all()

        print(f"Found {len(tenants)} tenants missing certificates")
        if not tenants:
            return

        success = 0
        failed = 0

        for t in tenants:
            tenant_id_ms = _decrypt_safe(t.tenant_id_ms)
            client_id = _decrypt_safe(t.client_id)
            client_secret = _decrypt_safe(t.client_secret)

            if not all([tenant_id_ms, client_id, client_secret]):
                print(f"  SKIP {t.name} — missing basic credentials")
                failed += 1
                continue

            try:
                # Get app object ID from Graph
                graph = MicrosoftGraphClient(tenant_id_ms, client_id, client_secret)
                resp = graph.get(f"/applications?$filter=appId eq '{client_id}'")
                apps = resp.json().get("value", [])
                if not apps:
                    print(f"  SKIP {t.name} — app registration not found")
                    failed += 1
                    continue
                app_object_id = apps[0]["id"]

                # Generate certificate
                cert_data = generate_cert(t.name)

                # Upload to Azure
                from datetime import datetime, timedelta, timezone
                now = datetime.now(timezone.utc)
                start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                end = (now + timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")

                graph.patch(f"/applications/{app_object_id}", json_data={
                    "keyCredentials": [{
                        "type": "AsymmetricX509Cert",
                        "usage": "Verify",
                        "key": cert_data["cert_pem_b64"],
                        "displayName": "automation-cert",
                        "startDateTime": start,
                        "endDateTime": end,
                    }]
                })

                # Save to DB
                t.cert_pfx = encrypt_bytes(cert_data["pfx_bytes"])
                t.cert_password = encrypt(cert_data["pfx_password"])
                db.commit()

                print(f"  OK   {t.name}")
                success += 1
                time.sleep(0.5)  # Rate limit

            except Exception as e:
                db.rollback()
                print(f"  FAIL {t.name} — {e}")
                failed += 1

        print(f"\nDone: {success} success, {failed} failed")


if __name__ == "__main__":
    backfill()
