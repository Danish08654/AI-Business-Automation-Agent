import streamlit as st
import requests
import pandas as pd
import time
import json

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="MCP AP Agent",
    page_icon="🤖",
    layout="wide"
)

st.title(" MCP Production Business Agent")

# Health check
try:
    health = requests.get(f"{API_URL}/health", timeout=3).json()
    if health.get("groq_key") == "SET":
        st.success("✅ Agent ready — Groq API connected")
    else:
        st.error("⚠️ GROQ_API_KEY missing in .env")
    if health.get("slack_webhook") == "NOT_SET (optional)":
        st.info(
            "ℹ️ Slack webhook not configured — "
            "notifications will be logged to database only"
        )
except Exception:
    st.error("⚠️ API not running. Start: uvicorn api.main:app --reload")
    st.stop()

st.divider()

tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 Run Workflow",
    "📋 Invoices",
    "📊 Dashboard",
    "📜 Audit Log"
])

# ── Tab 1: Run Workflow ───────────────────────────────────────
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
            "🚀 Run AP Workflow",
            type="primary",
            use_container_width=True
        )

    with col_reset:
        if st.button("🔄 Reset Database", use_container_width=True):
            requests.post(f"{API_URL}/db/reset")
            st.success("Database reset — 5 fresh invoices added")
            st.rerun()

    if run_btn:
        try:
            resp = requests.post(
                f"{API_URL}/workflow/run",
                json={"command": command},
                timeout=10
            ).json()
            st.success(f"✅ {resp.get('message')}")
        except Exception as e:
            st.error(f"Error: {e}")

    st.divider()

    # Workflow status poller
    st.subheader("Workflow Status")

    if st.button("🔄 Check Status"):
        st.rerun()

    try:
        status_resp = requests.get(
            f"{API_URL}/workflow/status", timeout=5
        ).json()
        wf_status = status_resp.get("status", "idle")

        if wf_status == "running":
            st.warning("⏳ Workflow running — refresh in a few seconds")
            st.progress(0.5)

        elif wf_status == "completed":
            result = status_resp.get("result", {})
            st.success("✅ Workflow completed successfully")

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("✅ Approved",    result.get("approved_count", 0))
            c2.metric("❌ Rejected",    result.get("rejected_count", 0))
            c3.metric("⚠️ For Review",  result.get("review_count", 0))
            c4.metric("📨 Notified",    result.get("notifications_sent", 0))

            if result.get("final_report"):
                st.subheader("Agent Final Report")
                st.markdown(result["final_report"])

            if result.get("workflow_log"):
                with st.expander("🔍 Workflow Log"):
                    for entry in result["workflow_log"]:
                        st.text(entry)

        elif wf_status == "error":
            result = status_resp.get("result", {})
            st.error(f"❌ Workflow error: {result.get('error', 'Unknown error')}")

        else:
            st.info("Agent is idle. Click Run AP Workflow to start.")

    except Exception as e:
        st.error(f"Status check error: {e}")


# ── Tab 2: Invoices ───────────────────────────────────────────
with tab2:
    st.subheader("Invoice Management")

    status_filter = st.selectbox(
        "Filter by status",
        ["all", "pending", "approved", "rejected", "under_review"]
    )

    if st.button("🔄 Refresh Invoices"):
        st.rerun()

    try:
        url      = f"{API_URL}/invoices"
        if status_filter != "all":
            url += f"?status={status_filter}"
        invoices = requests.get(url, timeout=5).json().get("invoices", [])

        if invoices:
            df = pd.DataFrame(invoices)

            # Colour status
            status_icons = {
                "pending":      "⏳",
                "approved":     "✅",
                "rejected":     "❌",
                "under_review": "⚠️"
            }
            df["Status"] = df["status"].map(
                lambda x: f"{status_icons.get(x, '❓')} {x}"
            )

            display_cols = [
                "invoice_number", "vendor_name", "amount",
                "description", "due_date", "priority", "Status"
            ]
            st.dataframe(
                df[display_cols],
                use_container_width=True
            )
            st.info(f"Showing {len(invoices)} invoices")
        else:
            st.info(f"No {status_filter} invoices found")

    except Exception as e:
        st.error(f"Could not load invoices: {e}")


# ── Tab 3: Dashboard ──────────────────────────────────────────
with tab3:
    st.subheader("AP Analytics Dashboard")

    if st.button("🔄 Refresh Stats"):
        st.rerun()

    try:
        import plotly.graph_objects as go
        import plotly.express as px

        stats = requests.get(f"{API_URL}/stats", timeout=5).json()

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total",        stats.get("total", 0))
        c2.metric("⏳ Pending",   stats.get("pending", 0))
        c3.metric("✅ Approved",  stats.get("approved", 0))
        c4.metric("❌ Rejected",  stats.get("rejected", 0))
        c5.metric("⚠️ Review",   stats.get("under_review", 0))

        st.divider()
        col_a, col_b = st.columns(2)

        with col_a:
            # Status pie chart
            labels = ["Pending", "Approved", "Rejected", "Under Review"]
            values = [
                stats.get("pending", 0),
                stats.get("approved", 0),
                stats.get("rejected", 0),
                stats.get("under_review", 0)
            ]
            colors = ["#f39c12", "#27ae60", "#e74c3c", "#3498db"]
            fig = go.Figure(go.Pie(
                labels=labels, values=values,
                marker_colors=colors, hole=0.4
            ))
            fig.update_layout(title="Invoice Status Distribution", height=320)
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            # Amount comparison
            fig2 = go.Figure(go.Bar(
                x=["Pending Amount", "Approved Amount"],
                y=[
                    stats.get("total_pending_amount", 0),
                    stats.get("total_approved_amount", 0)
                ],
                marker_color=["#f39c12", "#27ae60"],
                text=[
                    f"${stats.get('total_pending_amount', 0):,.0f}",
                    f"${stats.get('total_approved_amount', 0):,.0f}"
                ],
                textposition="outside"
            ))
            fig2.update_layout(title="AP Amount Summary ($)", height=320)
            st.plotly_chart(fig2, use_container_width=True)

    except Exception as e:
        st.error(f"Dashboard error: {e}")


# ── Tab 4: Audit Log ──────────────────────────────────────────
with tab4:
    st.subheader("Audit Trail")
    st.caption("Complete log of every AI agent action")

    if st.button("🔄 Refresh Log"):
        st.rerun()

    try:
        logs = requests.get(f"{API_URL}/logs", timeout=5).json().get("logs", [])

        if logs:
            action_icons = {
                "APPROVED":            "✅",
                "REJECTED":            "❌",
                "FLAGGED_FOR_REVIEW":  "⚠️",
            }
            for log in logs:
                icon = action_icons.get(log.get("action", ""), "📋")
                ts   = log.get("timestamp", "")[:19]
                st.markdown(
                    f"{icon} `{ts}` **{log.get('action')}** "
                    f"— `{log.get('invoice_number')}` "
                    f"— _{log.get('reason', '')[:80]}_"
                )
            st.info(f"{len(logs)} actions logged")
        else:
            st.info(
                "No audit log entries yet. "
                "Run the workflow to generate actions."
            )

    except Exception as e:
        st.error(f"Could not load audit log: {e}")