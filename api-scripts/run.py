#!/usr/bin/env python3
"""CLI entry point for Microsoft 365 Tenant Pipeline (Script 2)."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure api-scripts/ is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import API_OUTPUT, MAILBOX_COUNT
from log import info, ok, warn, err
from tenant_loader import load_tenant
from sheets import read_tenants_from_sheet, update_pipeline_status
from steps import (
    assign_license,
    enable_org_smtp,
    add_domain,
    verify_domain,
    setup_dkim,
    setup_dmarc,
    create_mailboxes,
    enable_smtp,
    disable_calendar_processing,
)


# Ordered pipeline steps
STEPS = [
    ("assign-license",    assign_license),
    ("enable-org-smtp",   enable_org_smtp),
    ("add-domain",        add_domain),
    ("verify-domain",     verify_domain),
    ("setup-dkim",        setup_dkim),
    ("setup-dmarc",       setup_dmarc),
    ("create-mailboxes",  create_mailboxes),
    ("enable-smtp",       enable_smtp),
    ("disable-calendar-processing", disable_calendar_processing),
]

STEP_NAMES = [name for name, _ in STEPS]


def _load_progress(tenant_name: str) -> dict:
    path = API_OUTPUT / f"{tenant_name}_pipeline.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"tenant": tenant_name, "steps": {}}


def _save_progress(tenant_name: str, progress: dict):
    API_OUTPUT.mkdir(parents=True, exist_ok=True)
    path = API_OUTPUT / f"{tenant_name}_pipeline.json"
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)


def run_step(step_name: str, step_module, tenant: dict, args) -> dict:
    """Run a single pipeline step."""
    kwargs = {}
    if hasattr(args, "domain") and args.domain:
        kwargs["domain"] = args.domain
    if hasattr(args, "count") and args.count:
        kwargs["count"] = args.count
    return step_module.run(tenant, **kwargs)


def cmd_single_step(args, step_name: str, step_module):
    """Handler for individual step subcommands."""
    tenant = load_tenant(args.tenant)
    info(f"Tenant: {tenant['tenant_name']} ({tenant['org_domain']})")

    result = run_step(step_name, step_module, tenant, args)

    # Save to pipeline progress
    progress = _load_progress(tenant["tenant_name"])
    progress["steps"][step_name] = {
        "status": result.get("status", "unknown"),
        "completed_at": datetime.now().isoformat(),
        "result": result,
    }
    _save_progress(tenant["tenant_name"], progress)

    return result


def cmd_full_pipeline(args):
    """Run the full pipeline (all steps in order)."""
    if args.sheet:
        cmd_full_pipeline_sheet(args)
        return

    if not args.tenant:
        err("--tenant is required unless --sheet is used")
        sys.exit(1)

    tenant = load_tenant(args.tenant)
    _run_pipeline_for_tenant(tenant, args)


def _run_pipeline_for_tenant(tenant, args, use_sheet=False):
    """Core pipeline logic for a single tenant."""
    tenant_name = tenant["tenant_name"]
    info(f"=== Full Pipeline for {tenant_name} ===")
    info(f"Org: {tenant['org_domain']}")
    if args.domain:
        info(f"Domain: {args.domain}")

    if use_sheet:
        try:
            update_pipeline_status(tenant_name, "running")
        except Exception:
            pass

    progress = _load_progress(tenant_name)

    # Determine start index
    start_idx = 0
    if args.start_from:
        if args.start_from not in STEP_NAMES:
            err(f"Unknown step: {args.start_from}")
            err(f"Valid steps: {', '.join(STEP_NAMES)}")
            sys.exit(1)
        start_idx = STEP_NAMES.index(args.start_from)
        info(f"Starting from step: {args.start_from}")

    # Run each step
    for i, (step_name, step_module) in enumerate(STEPS):
        if i < start_idx:
            info(f"Skipping {step_name}")
            continue

        print()
        info(f"{'='*50}")
        info(f"Running: {step_name} ({i+1}/{len(STEPS)})")
        info(f"{'='*50}")

        if use_sheet:
            try:
                update_pipeline_status(tenant_name, "running", current_step=step_name)
            except Exception:
                pass

        try:
            result = run_step(step_name, step_module, tenant, args)
        except Exception as e:
            err(f"Step '{step_name}' failed with exception: {e}")
            result = {"status": "error", "reason": str(e)}

        # Save progress
        progress["steps"][step_name] = {
            "status": result.get("status", "unknown"),
            "completed_at": datetime.now().isoformat(),
            "result": result,
        }
        _save_progress(tenant_name, progress)

        if result.get("status") == "error":
            err(f"Step '{step_name}' failed — stopping pipeline")
            if use_sheet:
                try:
                    update_pipeline_status(tenant_name, "failed", current_step=step_name,
                                           error=result.get("reason", "unknown error"))
                except Exception:
                    pass
            err(f"Resume with: python run.py full-pipeline --tenant {args.tenant} --domain {args.domain} --start-from {step_name}")
            sys.exit(1)

    print()
    ok("=== Full pipeline completed successfully ===")

    if use_sheet:
        try:
            update_pipeline_status(tenant_name, "done")
        except Exception:
            pass


def cmd_full_pipeline_sheet(args):
    """Run the full pipeline for all pending tenants from the Google Sheet."""
    tenants = read_tenants_from_sheet()
    if not tenants:
        err("No pending tenants found in Pipeline sheet")
        sys.exit(1)

    info(f"Found {len(tenants)} pending tenant(s) in Pipeline sheet")
    results = []

    for entry in tenants:
        tenant_name = entry["tenant_name"]
        domain = entry.get("domain", "")
        mailbox_count = entry.get("mailbox_count", MAILBOX_COUNT)

        info(f"\n{'='*60}")
        info(f"  Pipeline for: {tenant_name}")
        info(f"  Domain: {domain}")
        info(f"  Mailboxes: {mailbox_count}")
        info(f"{'='*60}")

        try:
            tenant = load_tenant(tenant_name)
        except Exception as e:
            err(f"Could not load tenant '{tenant_name}': {e}")
            try:
                update_pipeline_status(tenant_name, "failed", error=f"Load failed: {e}")
            except Exception:
                pass
            results.append({"tenant": tenant_name, "status": "failed"})
            continue

        # Override domain and count from sheet if provided
        if domain:
            args.domain = domain
        if mailbox_count:
            args.count = mailbox_count

        try:
            _run_pipeline_for_tenant(tenant, args, use_sheet=True)
            results.append({"tenant": tenant_name, "status": "done"})
        except SystemExit:
            results.append({"tenant": tenant_name, "status": "failed"})
        except Exception as e:
            err(f"Pipeline failed for {tenant_name}: {e}")
            try:
                update_pipeline_status(tenant_name, "failed", error=str(e))
            except Exception:
                pass
            results.append({"tenant": tenant_name, "status": "failed"})

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "done")
    fail_count = len(results) - ok_count
    print(f"\n[batch] Done: {ok_count} succeeded, {fail_count} failed out of {len(results)}")


def main():
    parser = argparse.ArgumentParser(
        description="Microsoft 365 Tenant Pipeline — Script 2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Pipeline step to run")

    # Common arguments for each subcommand
    def add_common_args(p):
        p.add_argument("--tenant", required=True, help="Tenant name or admin email")

    def add_domain_arg(p):
        p.add_argument("--domain", help="Custom domain to configure")

    # Individual step subcommands
    for step_name, step_module in STEPS:
        p = subparsers.add_parser(step_name, help=step_module.__doc__)
        add_common_args(p)
        add_domain_arg(p)
        if step_name == "create-mailboxes":
            p.add_argument("--count", type=int, help="Number of mailboxes (default: 50)")
        p.set_defaults(func=lambda args, sn=step_name, sm=step_module: cmd_single_step(args, sn, sm))

    # Full pipeline
    p = subparsers.add_parser("full-pipeline", help="Run all steps in order")
    p.add_argument("--tenant", help="Tenant name or admin email (required unless --sheet)")
    add_domain_arg(p)
    p.add_argument("--count", type=int, help="Number of mailboxes (default: 50)")
    p.add_argument("--start-from", choices=STEP_NAMES,
                   help="Resume pipeline from this step")
    p.add_argument("--sheet", action="store_true",
                   help="Read pending tenants from Google Sheet Pipeline tab")
    p.set_defaults(func=cmd_full_pipeline)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
