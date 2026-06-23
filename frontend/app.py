import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv

#  LOAD ENVIRONMENT VARIABLES
load_dotenv()

#  GROQ API SETUP
try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    
    if not GROQ_API_KEY:
        st.error(" GROQ_API_KEY not found! Add it to Streamlit Secrets.")
        st.stop()
    
    client = Groq(api_key=GROQ_API_KEY)
except ImportError:
    st.error(" groq module not installed. Add to requirements.txt: groq")
    st.stop()
except Exception as e:
    st.error(f" Groq initialization error: {str(e)}")
    st.stop()

#  SLACK WEBHOOK (OPTIONAL)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

#  STREAMLIT PAGE CONFIG
st.set_page_config(
    page_title="AI Business Agent",
    page_icon="🤖",
    layout="wide"
)

st.title(" AI Business Agent")

#  INITIALIZE SESSION STATE (In-memory database)
if "invoices" not in st.session_state:
    st.session_state.invoices = [
        {
            "id": 1,
            "invoice_number": "INV-001",
            "vendor_name": "Tech Solutions Inc",
            "amount": 5000,
            "description": "Software licensing",
            "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        },
        {
            "id": 2,
            "invoice_number": "INV-002",
            "vendor_name": "Office Supplies Co",
            "amount": 1200,
            "description": "Office equipment",
            "due_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
            "priority": "medium",
            "status": "pending"
        },
        {
            "id": 3,
            "invoice_number": "INV-003",
            "vendor_name": "Consulting Group",
            "amount": 8500,
            "description": "Business consulting",
            "due_date": (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        },
        {
            "id": 4,
            "invoice_number": "INV-004",
            "vendor_name": "Marketing Agency",
            "amount": 3200,
            "description": "Marketing campaigns",
            "due_date": (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d"),
            "priority": "medium",
            "status": "pending"
        },
        {
            "id": 5,
            "invoice_number": "INV-005",
            "vendor_name": "Cloud Services Ltd",
            "amount": 2800,
            "description": "Cloud infrastructure",
            "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        }
    ]

if "audit_log" not in st.session_state:
    st.session_state.audit_log = []

if "workflow_status" not in st.session_state:
    st.session_state.workflow_status = "idle"

if "workflow_result" not in st.session_state:
    st.session_state.workflow_result = {}

# ──────────────────────────────────────────────────────────────
#  GROQ AI AGENT FUNCTIONS
# ──────────────────────────────────────────────────────────────

def call_groq_agent(command: str, invoices: list) -> dict:
    """
    Call Groq AI to process invoices and make decisions
    Returns: {"decisions": [...], "summary": "...", "final_report": "..."}
    """
    invoices_summary = json.dumps(invoices, indent=2)
    
    prompt = f"""You are an expert AP (Accounts Payable) automation agent.

TASK: {command}

CURRENT INVOICES TO PROCESS:
{invoices_summary}

For each invoice, you MUST decide one of:
1. APPROVED - Invoice is valid and should be paid
2. REJECTED - Invoice has issues and should be rejected  
3. FLAGGED_FOR_REVIEW - Invoice needs human review

RESPOND ONLY with valid JSON in this exact format, no other text:
{{
    "decisions": [
        {{
            "invoice_number": "INV-001",
            "action": "APPROVED",
            "reason": "Clear business expense, proper vendor"
        }},
        {{
            "invoice_number": "INV-002",
            "action": "FLAGGED_FOR_REVIEW",
            "reason": "Unusual amount for this vendor type"
        }}
    ],
    "summary": "Processed X invoices",
    "final_report": "Executive summary of decisions"
}}"""

    try:
        message = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.choices[0].message.content
        
        # Try to parse JSON
        try:
            result = json.loads(response_text)
            return result
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return result
                except:
                    return {"decisions": [], "summary": "Parse error", "final_report": response_text}
            else:
                return {"decisions": [], "summary": "No JSON found", "final_report": response_text}
    
    except Exception as e:
        error_msg = str(e)
        st.error(f" Groq API Error: {error_msg}")
        return {"error": error_msg}

def send_slack_notification(message: str) -> bool:
    """Send notification to Slack webhook if configured"""
    if not SLACK_WEBHOOK_URL:
        return False
    
    try:
        import requests
        payload = {"text": message}
        response = requests.post(
            SLACK_WEBHOOK_URL, 
            json=payload, 
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        st.warning(f"Slack notification failed: {str(e)}")
        return False

def process_workflow(command: str):
    """Process AP workflow using Groq AI"""
    # Get pending invoices only
    pending_invoices = [
        inv for inv in st.session_state.invoices 
        if inv["status"] == "pending"
    ]
    
    if not pending_invoices:
        st.warning(" No pending invoices to process")
        st.session_state.workflow_status = "idle"
        return
    
    # Call Groq AI
    with st.spinner(" AI Agent analyzing invoices..."):
        result = call_groq_agent(command, pending_invoices)
    
    # Handle errors
    if "error" in result:
        st.error(f" Workflow error: {result['error']}")
        st.session_state.workflow_status = "error"
        st.session_state.workflow_result = result
        return
    
    # Process decisions from AI
    decisions = result.get("decisions", [])
    approved_count = 0
    rejected_count = 0
    review_count = 0
    notifications_sent = 0
    
    for decision in decisions:
        invoice_num = decision.get("invoice_number")
        action = decision.get("action", "").upper()
        reason = decision.get("reason", "No reason provided")
        
        # Update invoice status
        for invoice in st.session_state.invoices:
            if invoice["invoice_number"] == invoice_num:
                if action == "APPROVED":
                    invoice["status"] = "approved"
                    approved_count += 1
                elif action == "REJECTED":
                    invoice["status"] = "rejected"
                    rejected_count += 1
                elif action == "FLAGGED_FOR_REVIEW":
                    invoice["status"] = "under_review"
                    review_count += 1
                
                # Add to audit log
                st.session_state.audit_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "invoice_number": invoice_num,
                    "action": action,
                    "reason": reason[:100]
                })
                
                # Send Slack notification
                if SLACK_WEBHOOK_URL:
                    slack_msg = f"📋 Invoice {invoice_num}: {action}\n💬 {reason}"
                    if send_slack_notification(slack_msg):
                        notifications_sent += 1
                
                break
    
    # Set workflow completion status
    st.session_state.workflow_status = "completed"
    st.session_state.workflow_result = {
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "review_count": review_count,
        "notifications_sent": notifications_sent,
        "final_report": result.get("final_report", "Workflow completed successfully"),
        "workflow_log": [f"{d.get('invoice_number')}: {d.get('action')}" for d in decisions]
    }

def reset_database():
    """Reset database to initial state"""
    st.session_state.invoices = [
        {
            "id": 1,
            "invoice_number": "INV-001",
            "vendor_name": "Tech Solutions Inc",
            "amount": 5000,
            "description": "Software licensing",
            "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        },
        {
            "id": 2,
            "invoice_number": "INV-002",
            "vendor_name": "Office Supplies Co",
            "amount": 1200,
            "description": "Office equipment",
            "due_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
            "priority": "medium",
            "status": "pending"
        },
        {
            "id": 3,
            "invoice_number": "INV-003",
            "vendor_name": "Consulting Group",
            "amount": 8500,
            "description": "Business consulting",
            "due_date": (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        },
        {
            "id": 4,
            "invoice_number": "INV-004",
            "vendor_name": "Marketing Agency",
            "amount": 3200,
            "description": "Marketing campaigns",
            "due_date": (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d"),
            "priority": "medium",
            "status": "pending"
        },
        {
            "id": 5,
            "invoice_number": "INV-005",
            "vendor_name": "Cloud Services Ltd",
            "amount": 2800,
            "description": "Cloud infrastructure",
            "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
            "priority": "high",
            "status": "pending"
        }
    ]
    st.session_state.audit_log = []
    st.session_state.workflow_status = "idle"
    st.session_state.workflow_result = {}

# ──────────────────────────────────────────────────────────────
#  HEALTH CHECK DISPLAY
# ──────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.success("Agent ready — Groq API connected")

with col2:
    if SLACK_WEBHOOK_URL:
        st.success(" Slack webhook configured")
    else:
        st.info(" Slack webhook not configured (optional)")

st.divider()

# ──────────────────────────────────────────────────────────────
#  TABS
# ──────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    " Run Workflow",
    " Invoices",
    " Dashboard",
    " Audit Log"
])

# ── TAB 1: RUN WORKFLOW ───────────────────────────────────────
with tab1:
    st.subheader("Autonomous AP Workflow")
    
    command = st.text_area(
        "Workflow Command",
        value="Process all pending invoices completely",
        height=80
    )

    col_run, col_reset = st.columns([2, 1])

    with col_run:
        run_btn = st.button(
            " Run AP Workflow",
            type="primary",
            use_container_width=True
        )

    with col_reset:
        if st.button(" Reset Database", use_container_width=True):
            reset_database()
            st.success(" Database reset — 5 fresh invoices added")
            st.rerun()

    if run_btn:
        if command.strip():
            process_workflow(command)
            st.rerun()
        else:
            st.warning(" Please enter a workflow command")

    st.divider()

    # Workflow status display
    st.subheader("Workflow Status")

    if st.button(" Check Status", use_container_width=True):
        st.rerun()

    wf_status = st.session_state.workflow_status

    if wf_status == "running":
        st.warning(" Workflow running — please wait...")
        st.progress(0.5)

    elif wf_status == "completed":
        result = st.session_state.workflow_result
        st.success(" Workflow completed successfully")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(" Approved", result.get("approved_count", 0))
        with c2:
            st.metric(" Rejected", result.get("rejected_count", 0))
        with c3:
            st.metric(" For Review", result.get("review_count", 0))
        with c4:
            st.metric(" Notified", result.get("notifications_sent", 0))

        if result.get("final_report"):
            st.subheader("Agent Final Report")
            st.markdown(result["final_report"])

        if result.get("workflow_log"):
            with st.expander(" Workflow Log"):
                for entry in result["workflow_log"]:
                    st.text(f"• {entry}")

    elif wf_status == "error":
        result = st.session_state.workflow_result
        st.error(f" Workflow error: {result.get('error', 'Unknown error')}")

    else:
        st.info("Agent is idle. Click 'Run AP Workflow' to start processing invoices.")


# ── TAB 2: INVOICES ───────────────────────────────────────────
with tab2:
    st.subheader("Invoice Management")

    status_filter = st.selectbox(
        "Filter by status",
        ["all", "pending", "approved", "rejected", "under_review"]
    )

    if st.button(" Refresh Invoices", use_container_width=True):
        st.rerun()

    # Filter invoices based on selection
    if status_filter == "all":
        filtered_invoices = st.session_state.invoices
    else:
        filtered_invoices = [
            inv for inv in st.session_state.invoices 
            if inv["status"] == status_filter
        ]

    if filtered_invoices:
        df = pd.DataFrame(filtered_invoices)

        # Add status icons
        status_icons = {
            "pending": "⏳",
            "approved": "✅",
            "rejected": "❌",
            "under_review": "⚠️"
        }
        df["Status"] = df["status"].map(
            lambda x: f"{status_icons.get(x, '❓')} {x.title()}"
        )

        # Select columns to display
        display_cols = [
            "invoice_number", "vendor_name", "amount",
            "description", "due_date", "priority", "Status"
        ]
        
        st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True
        )
        
        st.info(f"Showing {len(filtered_invoices)} invoices")
    else:
        st.info(f"ℹ️ No {status_filter} invoices found")


# ── TAB 3: DASHBOARD ──────────────────────────────────────────
with tab3:
    st.subheader("AP Analytics Dashboard")

    if st.button("🔄 Refresh Stats", use_container_width=True):
        st.rerun()

    try:
        import plotly.graph_objects as go

        # Calculate statistics
        total = len(st.session_state.invoices)
        pending = len([i for i in st.session_state.invoices if i["status"] == "pending"])
        approved = len([i for i in st.session_state.invoices if i["status"] == "approved"])
        rejected = len([i for i in st.session_state.invoices if i["status"] == "rejected"])
        under_review = len([i for i in st.session_state.invoices if i["status"] == "under_review"])

        total_pending_amount = sum(
            [i["amount"] for i in st.session_state.invoices if i["status"] == "pending"]
        )
        total_approved_amount = sum(
            [i["amount"] for i in st.session_state.invoices if i["status"] == "approved"]
        )

        # Display metrics
        c1, c2, c3, c4, c5 = st.columns(5)
        
        with c1:
            st.metric("Total", total)
        with c2:
            st.metric("⏳ Pending", pending)
        with c3:
            st.metric("✅ Approved", approved)
        with c4:
            st.metric("❌ Rejected", rejected)
        with c5:
            st.metric("⚠️ Review", under_review)

        st.divider()
        col_a, col_b = st.columns(2)

        with col_a:
            # Status pie chart
            labels = ["Pending", "Approved", "Rejected", "Under Review"]
            values = [pending, approved, rejected, under_review]
            colors = ["#f39c12", "#27ae60", "#e74c3c", "#3498db"]
            
            fig = go.Figure(go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors),
                hole=0.4
            ))
            fig.update_layout(
                title="Invoice Status Distribution",
                height=350,
                showlegend=True
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            # Amount comparison bar chart
            fig2 = go.Figure(go.Bar(
                x=["Pending Amount", "Approved Amount"],
                y=[total_pending_amount, total_approved_amount],
                marker=dict(color=["#f39c12", "#27ae60"]),
                text=[
                    f"${total_pending_amount:,.0f}",
                    f"${total_approved_amount:,.0f}"
                ],
                textposition="outside"
            ))
            fig2.update_layout(
                title="AP Amount Summary ($)",
                height=350,
                showlegend=False
            )
            st.plotly_chart(fig2, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Dashboard error: {str(e)}")


# ── TAB 4: AUDIT LOG ──────────────────────────────────────────
with tab4:
    st.subheader("Audit Trail")
    st.caption("Complete log of every AI agent action")

    if st.button("🔄 Refresh Log", use_container_width=True):
        st.rerun()

    logs = st.session_state.audit_log

    if logs:
        action_icons = {
            "APPROVED": "✅",
            "REJECTED": "❌",
            "FLAGGED_FOR_REVIEW": "⚠️",
        }
        
        # Display logs in reverse order (newest first)
        for log in reversed(logs):
            icon = action_icons.get(log.get("action", ""), "📋")
            ts = log.get("timestamp", "")[:19]
            action = log.get("action", "UNKNOWN")
            invoice = log.get("invoice_number", "N/A")
            reason = log.get("reason", "No reason")[:80]
            
            st.markdown(
                f"{icon} `{ts}` **{action}** — `{invoice}` — _{reason}_"
            )
        
        st.info(f"📊 {len(logs)} actions logged")
    
    else:
        st.info(
            "ℹ️ No audit log entries yet. "
            "Run the workflow to generate actions."
        )
