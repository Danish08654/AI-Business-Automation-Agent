import os
import sys
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# =========================================================
# PATH SETUP
# =========================================================
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import (
    get_all_invoices,
    get_invoice,
    update_invoice_status,
    log_approval_action,
    log_notification
)

from mcp.server.fastmcp import FastMCP

load_dotenv()

# =========================================================
# MCP SERVER
# =========================================================
mcp = FastMCP("Business AP Agent")

# =========================================================
# CONFIG
# =========================================================
APPROVAL_THRESHOLD = float(os.getenv("APPROVAL_THRESHOLD", "1000"))
AUTO_APPROVE_THRESHOLD = float(os.getenv("AUTO_APPROVE_THRESHOLD", "500"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


# =========================================================
# HELPERS
# =========================================================
def success(data: dict):
    return json.dumps({
        "status": "success",
        **data
    })

def error(message: str):
    return json.dumps({
        "status": "error",
        "message": message
    })


# =========================================================
# TOOL 1: LIST INVOICES
# =========================================================
@mcp.tool()
def list_pending_invoices() -> str:
    invoices = get_all_invoices()
    pending = [i for i in invoices if i.get("status") == "pending"]

    return success({
        "count": len(pending),
        "invoices": [
            {
                "invoice_number": i["invoice_number"],
                "vendor_name": i["vendor_name"],
                "amount": i["amount"],
                "currency": i.get("currency", "USD"),
                "description": i.get("description", ""),
                "due_date": i.get("due_date", ""),
                "priority": i.get("priority", "normal"),
                "status": i.get("status", "pending"),
            }
            for i in pending
        ]
    })


# =========================================================
# TOOL 2: GET INVOICE
# =========================================================
@mcp.tool()
def get_invoice_details(invoice_number: str) -> str:
    invoice = get_invoice(invoice_number)

    if not invoice:
        return error(f"Invoice {invoice_number} not found")

    return success({"invoice": invoice})


# =========================================================
# TOOL 3: VALIDATE
# =========================================================
@mcp.tool()
def validate_invoice(invoice_number: str) -> str:
    invoice = get_invoice(invoice_number)

    if not invoice:
        return error(f"Invoice {invoice_number} not found")

    issues = []
    warnings = []

    amount = float(invoice.get("amount", 0))

    if not invoice.get("vendor_name"):
        issues.append("Missing vendor name")

    if amount <= 0:
        issues.append("Invalid amount")

    if amount > 10000:
        warnings.append("High value invoice → CFO approval required")

    if amount > APPROVAL_THRESHOLD:
        warnings.append("Exceeds approval threshold")

    recommendation = (
        "APPROVE" if len(issues) == 0 and amount <= AUTO_APPROVE_THRESHOLD
        else "REVIEW_REQUIRED" if len(issues) == 0 and amount <= 10000
        else "REJECT" if len(issues) > 0
        else "ESCALATE"
    )

    return success({
        "invoice_number": invoice_number,
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "amount": amount,
        "recommendation": recommendation
    })


# =========================================================
# TOOL 4: APPROVE
# =========================================================
@mcp.tool()
def approve_invoice(invoice_number: str, reason: str = "") -> str:
    invoice = get_invoice(invoice_number)

    if not invoice:
        return error(f"Invoice {invoice_number} not found")

    if invoice.get("status") == "approved":
        return success({
            "message": "Already approved",
            "invoice_number": invoice_number
        })

    reason = reason or f"Auto-approved under policy for ${invoice['amount']}"

    update_invoice_status(
        invoice_number,
        status="approved",
        approved_by="AI_AP_AGENT",
        notes=reason
    )

    log_approval_action(
        invoice_number,
        action="APPROVED",
        reason=reason,
        performed_by="AI_AP_AGENT"
    )

    return success({
        "action": "APPROVED",
        "invoice_number": invoice_number,
        "vendor": invoice["vendor_name"],
        "amount": invoice["amount"],
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })


# =========================================================
# TOOL 5: REJECT
# =========================================================
@mcp.tool()
def reject_invoice(invoice_number: str, reason: str) -> str:
    invoice = get_invoice(invoice_number)

    if not invoice:
        return error(f"Invoice {invoice_number} not found")

    update_invoice_status(
        invoice_number,
        status="rejected",
        approved_by="AI_AP_AGENT",
        notes=reason
    )

    log_approval_action(
        invoice_number,
        action="REJECTED",
        reason=reason,
        performed_by="AI_AP_AGENT"
    )

    return success({
        "action": "REJECTED",
        "invoice_number": invoice_number,
        "vendor": invoice["vendor_name"],
        "amount": invoice["amount"],
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })


# =========================================================
# TOOL 6: FLAG REVIEW
# =========================================================
@mcp.tool()
def flag_for_review(invoice_number: str, reason: str) -> str:
    invoice = get_invoice(invoice_number)

    if not invoice:
        return error(f"Invoice {invoice_number} not found")

    update_invoice_status(
        invoice_number,
        status="under_review",
        notes=reason
    )

    log_approval_action(
        invoice_number,
        action="FLAGGED_FOR_REVIEW",
        reason=reason,
        performed_by="AI_AP_AGENT"
    )

    return success({
        "action": "FLAGGED_FOR_REVIEW",
        "invoice_number": invoice_number,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })


# =========================================================
# TOOL 7: SLACK NOTIFICATION
# =========================================================
@mcp.tool()
def send_slack_notification(message: str, invoice_number: str = "") -> str:

    payload = {
        "text": f"AP Agent: {message} | Invoice: {invoice_number}"
    }

    status = "not_sent"

    if SLACK_WEBHOOK_URL:
        try:
            r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            status = "sent" if r.status_code == 200 else "failed"
        except Exception as e:
            status = f"error: {str(e)}"
    else:
        status = "no_webhook_configured"

    log_notification(
        invoice_number or "GLOBAL",
        channel="slack",
        message=message,
        status=status
    )

    return success({
        "status": status,
        "message": message,
        "invoice_number": invoice_number,
        "timestamp": datetime.now().isoformat()
    })


# =========================================================
# TOOL 8: SUMMARY
# =========================================================
@mcp.tool()
def generate_ap_summary() -> str:
    invoices = get_all_invoices()

    summary = {
        "total": len(invoices),
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "under_review": 0,
        "total_pending_amount": 0,
        "total_approved_amount": 0,
    }

    for i in invoices:
        status = i.get("status", "unknown")

        if status in summary:
            summary[status] += 1

        if status == "pending":
            summary["total_pending_amount"] += float(i.get("amount", 0))

        if status == "approved":
            summary["total_approved_amount"] += float(i.get("amount", 0))

    summary["total_pending_amount"] = round(summary["total_pending_amount"], 2)
    summary["total_approved_amount"] = round(summary["total_approved_amount"], 2)
    summary["generated_at"] = datetime.now().isoformat()

    return success({"summary": summary})


# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    print("🚀 MCP Business AP Server Starting...")

    print("\nAvailable tools:")
    for t in [
        "list_pending_invoices",
        "get_invoice_details",
        "validate_invoice",
        "approve_invoice",
        "reject_invoice",
        "flag_for_review",
        "send_slack_notification",
        "generate_ap_summary",
    ]:
        print(" -", t)

    mcp.run(transport="stdio")