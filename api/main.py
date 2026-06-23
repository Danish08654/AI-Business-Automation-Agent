import os
import sys
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.db import (
    get_all_invoices, get_invoice,
    get_approval_log, init_db, seed_sample_invoices
)

load_dotenv()

app = FastAPI(
    title="MCP Business AP Agent",
    description="Autonomous invoice processing via MCP + LangGraph",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Background task state
WORKFLOW_STATE = {
    "status":   "idle",
    "result":   None,
    "started":  None,
    "completed":None,
}


class WorkflowRequest(BaseModel):
    command: str = "Process all pending invoices"


def run_workflow_background(command: str):
    """Run AP workflow in background."""
    global WORKFLOW_STATE
    WORKFLOW_STATE["status"]  = "running"
    WORKFLOW_STATE["started"] = datetime.now().isoformat()
    WORKFLOW_STATE["result"]  = None

    try:
        from agent.ap_agent import run_workflow_sync
        result = run_workflow_sync(command)
        WORKFLOW_STATE["status"]    = "completed"
        WORKFLOW_STATE["result"]    = result
        WORKFLOW_STATE["completed"] = datetime.now().isoformat()
    except Exception as e:
        WORKFLOW_STATE["status"] = "error"
        WORKFLOW_STATE["result"] = {"error": str(e)}


@app.get("/")
def root():
    return {
        "service":   "MCP Business AP Agent",
        "version":   "1.0.0",
        "workflow":  WORKFLOW_STATE["status"],
        "endpoints": [
            "/workflow/run",
            "/workflow/status",
            "/invoices",
            "/invoices/{invoice_number}",
            "/logs"
        ]
    }


@app.get("/health")
def health():
    groq_ok  = bool(os.getenv("GROQ_API_KEY"))
    slack_ok = bool(os.getenv("SLACK_WEBHOOK_URL"))
    return {
        "groq_key":    "SET" if groq_ok  else "MISSING",
        "slack_webhook":"SET" if slack_ok else "NOT_SET (optional)",
        "database":    "connected",
        "status":      "healthy" if groq_ok else "missing keys"
    }


@app.post("/workflow/run")
def run_workflow(
    request: WorkflowRequest,
    background_tasks: BackgroundTasks
):
    if WORKFLOW_STATE["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Workflow already running. Check /workflow/status"
        )

    background_tasks.add_task(
        run_workflow_background, request.command
    )

    return {
        "message": "AP workflow started",
        "command": request.command,
        "status":  "running",
        "check":   "/workflow/status"
    }


@app.get("/workflow/status")
def workflow_status():
    return {
        "status":    WORKFLOW_STATE["status"],
        "started":   WORKFLOW_STATE["started"],
        "completed": WORKFLOW_STATE["completed"],
        "result":    WORKFLOW_STATE["result"]
    }


@app.get("/invoices")
def list_invoices(status: str = None):
    invoices = get_all_invoices()
    if status:
        invoices = [i for i in invoices if i["status"] == status]
    return {"invoices": invoices, "count": len(invoices)}


@app.get("/invoices/{invoice_number}")
def get_invoice_endpoint(invoice_number: str):
    invoice = get_invoice(invoice_number)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@app.get("/logs")
def get_logs():
    return {"logs": get_approval_log()}


@app.post("/db/reset")
def reset_database():
    """Reset and reseed the database for testing."""
    init_db()
    seed_sample_invoices()
    return {"message": "Database reset and reseeded"}


@app.get("/stats")
def get_stats():
    invoices = get_all_invoices()
    stats    = {
        "total":       len(invoices),
        "pending":     len([i for i in invoices if i["status"] == "pending"]),
        "approved":    len([i for i in invoices if i["status"] == "approved"]),
        "rejected":    len([i for i in invoices if i["status"] == "rejected"]),
        "under_review":len([i for i in invoices if i["status"] == "under_review"]),
        "total_pending_amount":  sum(
            i["amount"] for i in invoices if i["status"] == "pending"
        ),
        "total_approved_amount": sum(
            i["amount"] for i in invoices if i["status"] == "approved"
        ),
    }
    return stats