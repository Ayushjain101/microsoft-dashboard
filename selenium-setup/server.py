#!/usr/bin/env python3
"""FastAPI server wrapping the Selenium tenant setup automation + mailbox creation.

Endpoints (Selenium setup):
    POST /api/run    – Queue tenants for setup. Body: {"emails": [...]} or {} for all pending.
    GET  /api/status – Current tenant, step, queue, completed list.
    POST /api/stop   – Stop after current tenant finishes, clear queue.

Endpoints (Mailbox creation):
    POST /api/mailbox/run    – Queue tenants for mailbox creation. Body: {"tenants": [...]} or {}.
    GET  /api/mailbox/status – Current mailbox job status.
    POST /api/mailbox/stop   – Stop after current tenant finishes.

    GET  /api/health – Simple alive check (no auth).

Start:
    export API_KEY="your-chosen-key"
    xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python3 server.py
"""

import collections
import threading
import time
import traceback
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from config import SERVER_PORT, API_KEY
from sheets import (
    read_tenants_from_sheet, set_step_callback,
    read_mailbox_tenants, update_mailbox_step, update_mailbox_status,
    write_generated_mailboxes,
)
from setup_tenant import setup_single_tenant
from mailbox_creator import create_room_mailboxes

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Selenium Tenant Setup Server")

# ── Server State ─────────────────────────────────────────────────────────────
server_state = {
    "current_email": None,
    "current_step": None,
    "queue": [],          # snapshot for API consumers (real queue is _queue)
    "completed": [],
    "started_at": None,
}

_queue: collections.deque = collections.deque()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
stop_requested = threading.Event()


# ── Step callback (keeps server_state in sync) ───────────────────────────────
def _on_step_update(email, step_text):
    server_state["current_step"] = step_text


set_step_callback(_on_step_update)


# ── Auth helper ──────────────────────────────────────────────────────────────
def _check_api_key(x_api_key: str | None):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── Worker ───────────────────────────────────────────────────────────────────
def _worker():
    """Process tenants from the queue one at a time."""
    global _worker_thread

    while _queue and not stop_requested.is_set():
        tenant = _queue.popleft()
        email = tenant["email"]
        server_state["current_email"] = email
        server_state["current_step"] = "Starting..."
        server_state["queue"] = list(_queue)
        server_state["started_at"] = datetime.now(timezone.utc).isoformat()

        print(f"[worker] Processing: {email}")
        try:
            result = setup_single_tenant(
                email=email,
                password=tenant["password"],
                new_password=tenant.get("new_password") or None,
            )
            status = result.get("status", "unknown")
            if status == "complete":
                server_state["completed"].append({"email": email, "status": "complete"})
            else:
                server_state["completed"].append({"email": email, "status": "failed", "error": result.get("error", status)})
        except Exception as e:
            traceback.print_exc()
            server_state["completed"].append({"email": email, "status": "failed", "error": str(e)})

        server_state["queue"] = list(_queue)

    # Cleanup
    server_state["current_email"] = None
    server_state["current_step"] = None
    server_state["started_at"] = None
    stop_requested.clear()

    with _worker_lock:
        _worker_thread = None

    print("[worker] Queue empty — worker stopped.")


def _ensure_worker():
    """Start the worker thread if it's not already running."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker, daemon=True)
            _worker_thread.start()


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Simple alive check — no auth required."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/run")
async def run_tenants(request: Request, x_api_key: str | None = Header(None)):
    """Queue tenants for setup.

    Body: {"emails": ["admin@a.onmicrosoft.com", ...]}
    Or:   {} to queue all pending tenants from the Sheet.
    """
    _check_api_key(x_api_key)

    body = await request.json() if await request.body() else {}
    requested_emails = body.get("emails", [])

    # Read all tenants (with passwords) from the Sheet
    all_tenants = read_tenants_from_sheet()
    if not all_tenants:
        raise HTTPException(status_code=404, detail="No tenants found in Google Sheet")

    # Filter by requested emails, or take all
    if requested_emails:
        email_set = {e.strip().strip("\xa0").lower() for e in requested_emails}
        tenants_to_queue = [t for t in all_tenants if t["email"].lower() in email_set]
        if not tenants_to_queue:
            raise HTTPException(
                status_code=404,
                detail=f"None of the requested emails found in Sheet: {requested_emails}",
            )
    else:
        tenants_to_queue = all_tenants

    # Add to queue (skip duplicates already in queue or currently processing)
    already_queued = {t["email"].lower() for t in _queue}
    current = (server_state["current_email"] or "").lower()
    added = []
    for t in tenants_to_queue:
        email_lower = t["email"].lower()
        if email_lower not in already_queued and email_lower != current:
            _queue.append(t)
            added.append(t["email"])

    _ensure_worker()

    return {
        "queued": added,
        "total_in_queue": len(_queue),
        "already_processing": server_state["current_email"],
    }


@app.get("/api/status")
def status(x_api_key: str | None = Header(None)):
    """Return current processing state."""
    _check_api_key(x_api_key)

    return {
        "current_email": server_state["current_email"],
        "current_step": server_state["current_step"],
        "started_at": server_state["started_at"],
        "queue": [t["email"] for t in _queue],
        "queue_length": len(_queue),
        "completed": server_state["completed"],
    }


@app.post("/api/stop")
def stop_processing(x_api_key: str | None = Header(None)):
    """Stop after the current tenant finishes, clear the queue."""
    _check_api_key(x_api_key)

    stop_requested.set()
    cleared = list(_queue)
    _queue.clear()
    server_state["queue"] = []

    return {
        "message": "Stop requested — current tenant will finish, queue cleared.",
        "cleared_emails": [t["email"] for t in cleared],
        "current_email": server_state["current_email"],
    }


# ── Mailbox State ────────────────────────────────────────────────────────────
mailbox_state = {
    "current_tenant": None,
    "current_step": None,
    "queue": [],
    "completed": [],
    "started_at": None,
}

_mailbox_queue: collections.deque = collections.deque()
_mailbox_worker_thread: threading.Thread | None = None
_mailbox_worker_lock = threading.Lock()
_mailbox_stop_requested = threading.Event()


# ── Mailbox Worker ──────────────────────────────────────────────────────────
def _mailbox_worker():
    """Process tenants from the mailbox queue one at a time."""
    global _mailbox_worker_thread

    while _mailbox_queue and not _mailbox_stop_requested.is_set():
        tenant_info = _mailbox_queue.popleft()
        tenant_name = tenant_info["tenant_name"]
        domain = tenant_info["domain"]
        count = tenant_info.get("count", 50)
        cf_email = tenant_info.get("cf_email", "")
        cf_api_key = tenant_info.get("cf_api_key", "")

        mailbox_state["current_tenant"] = tenant_name
        mailbox_state["current_step"] = "Starting..."
        mailbox_state["queue"] = [t["tenant_name"] for t in _mailbox_queue]
        mailbox_state["started_at"] = datetime.now(timezone.utc).isoformat()

        print(f"[mailbox-worker] Processing: {tenant_name}")
        update_mailbox_status(tenant_name, "running")

        def on_progress(step_text, _tn=tenant_name):
            mailbox_state["current_step"] = step_text
            update_mailbox_step(_tn, step_text)

        try:
            result = create_room_mailboxes(
                tenant_name=tenant_name,
                domain=domain,
                count=count,
                cf_email=cf_email,
                cf_api_key=cf_api_key,
                on_progress=on_progress,
            )
            status = result.get("status", "unknown")
            if status == "complete":
                summary = result.get("summary", "complete")
                update_mailbox_status(tenant_name, "complete")
                update_mailbox_step(tenant_name, summary)
                # Write generated emails/passwords to a per-tenant tab
                identities = result.get("identities", [])
                if identities:
                    write_generated_mailboxes(tenant_name, identities)
                mailbox_state["completed"].append({
                    "tenant": tenant_name, "status": "complete", "summary": summary,
                })
            else:
                update_mailbox_status(tenant_name, "failed", error=str(result))
                mailbox_state["completed"].append({
                    "tenant": tenant_name, "status": "failed", "error": str(result),
                })
        except Exception as e:
            traceback.print_exc()
            update_mailbox_status(tenant_name, "failed", error=str(e))
            mailbox_state["completed"].append({
                "tenant": tenant_name, "status": "failed", "error": str(e),
            })

        mailbox_state["queue"] = [t["tenant_name"] for t in _mailbox_queue]

    # Cleanup
    mailbox_state["current_tenant"] = None
    mailbox_state["current_step"] = None
    mailbox_state["started_at"] = None
    _mailbox_stop_requested.clear()

    with _mailbox_worker_lock:
        _mailbox_worker_thread = None

    print("[mailbox-worker] Queue empty — worker stopped.")


def _ensure_mailbox_worker():
    """Start the mailbox worker thread if not already running."""
    global _mailbox_worker_thread
    with _mailbox_worker_lock:
        if _mailbox_worker_thread is None or not _mailbox_worker_thread.is_alive():
            _mailbox_worker_thread = threading.Thread(target=_mailbox_worker, daemon=True)
            _mailbox_worker_thread.start()


# ── Mailbox Endpoints ───────────────────────────────────────────────────────

@app.post("/api/mailbox/run")
async def run_mailbox(request: Request, x_api_key: str | None = Header(None)):
    """Queue tenants for mailbox creation.

    Body: {"tenants": ["TenantName1", ...]} or {} for all pending from Sheet.
    """
    _check_api_key(x_api_key)

    body = await request.json() if await request.body() else {}
    requested_tenants = body.get("tenants", [])

    # Read all tenants from the Mailboxes tab
    all_tenants = read_mailbox_tenants()
    if not all_tenants:
        raise HTTPException(status_code=404, detail="No tenants found in Mailboxes tab")

    if requested_tenants:
        name_set = {n.strip().lower() for n in requested_tenants}
        tenants_to_queue = [t for t in all_tenants if t["tenant_name"].lower() in name_set]
        if not tenants_to_queue:
            raise HTTPException(
                status_code=404,
                detail=f"None of the requested tenants found in Mailboxes tab: {requested_tenants}",
            )
    else:
        # Queue all pending (not complete/running)
        tenants_to_queue = [t for t in all_tenants if t["status"] not in ("complete", "running")]

    if not tenants_to_queue:
        return {"queued": [], "total_in_queue": len(_mailbox_queue), "message": "No pending tenants to queue"}

    # Add to queue (skip duplicates)
    already_queued = {t["tenant_name"].lower() for t in _mailbox_queue}
    current = (mailbox_state["current_tenant"] or "").lower()
    added = []
    for t in tenants_to_queue:
        name_lower = t["tenant_name"].lower()
        if name_lower not in already_queued and name_lower != current:
            _mailbox_queue.append(t)
            added.append(t["tenant_name"])

    _ensure_mailbox_worker()

    return {
        "queued": added,
        "total_in_queue": len(_mailbox_queue),
        "already_processing": mailbox_state["current_tenant"],
    }


@app.get("/api/mailbox/status")
def mailbox_status(x_api_key: str | None = Header(None)):
    """Return current mailbox processing state."""
    _check_api_key(x_api_key)

    return {
        "current_tenant": mailbox_state["current_tenant"],
        "current_step": mailbox_state["current_step"],
        "started_at": mailbox_state["started_at"],
        "queue": [t["tenant_name"] for t in _mailbox_queue],
        "queue_length": len(_mailbox_queue),
        "completed": mailbox_state["completed"],
    }


@app.post("/api/mailbox/stop")
def stop_mailbox(x_api_key: str | None = Header(None)):
    """Stop mailbox processing after the current tenant finishes."""
    _check_api_key(x_api_key)

    _mailbox_stop_requested.set()
    cleared = list(_mailbox_queue)
    _mailbox_queue.clear()
    mailbox_state["queue"] = []

    return {
        "message": "Stop requested — current tenant will finish, queue cleared.",
        "cleared_tenants": [t["tenant_name"] for t in cleared],
        "current_tenant": mailbox_state["current_tenant"],
    }


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[server] Starting on port {SERVER_PORT}")
    print(f"[server] API key: {'(default — change me!)' if API_KEY == 'changeme' else '(set)'}")
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)
