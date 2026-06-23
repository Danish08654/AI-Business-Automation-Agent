import os
import sys
import json
import asyncio
from typing import TypedDict, List
from datetime import datetime
from dotenv import load_dotenv

# =========================================================
# PATH FIX
# =========================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# =========================================================
# IMPORTS
# =========================================================
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AIMessage,
)
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

# =========================================================
# STATE
# =========================================================
class APAgentState(TypedDict):
    messages: List
    approved_count: int
    rejected_count: int
    review_count: int
    notifications_sent: int
    workflow_log: List[str]


# =========================================================
# SYSTEM PROMPT
# =========================================================
SYSTEM_PROMPT = """
You are an autonomous AP (Accounts Payable) Agent.

TASK:
Process all pending invoices using available tools.

RULES:
- <= 500 → APPROVE
- 501-1000 → REVIEW
- > 1000 → REJECT

WORKFLOW:
1. Fetch invoices using tools
2. Decide action per invoice
3. Trigger correct tool (approve/reject/review)
4. Send notifications
5. Generate final summary

IMPORTANT:
- Be concise
- Do not loop infinitely
- Finish after processing all invoices
"""


# =========================================================
# MAIN WORKFLOW
# =========================================================
async def run_ap_workflow(command: str = "Process all pending invoices"):

    print("\n" + "=" * 60)
    print("🚀 AP AGENT STARTING")
    print("=" * 60)

    mcp_server_path = os.path.join(
        BASE_DIR,
        "mcp_server",
        "business_tools.py"
    )

    # =====================================================
    # MCP CLIENT
    # =====================================================
    client = MultiServerMCPClient(
        {
            "business_ap": {
                "command": "python",
                "args": [mcp_server_path],
                "transport": "stdio",
            }
        }
    )

    try:

        # =================================================
        # LOAD TOOLS
        # =================================================
        tools = await asyncio.wait_for(
            client.get_tools(),
            timeout=20
        )

        if not tools:
            return {
                "status": "error",
                "error": "No MCP tools loaded"
            }

        print(f"✅ MCP Tools Loaded: {[t.name for t in tools]}")

        # =================================================
        # LLM WITH TOOLS
        # =================================================
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            api_key=os.getenv("GROQ_API_KEY")
        ).bind_tools(tools)

        # =================================================
        # AGENT NODE
        # =================================================
        async def call_agent(state: APAgentState):

            try:
                response = await llm.ainvoke(state["messages"])

                log = state["workflow_log"].copy()

                # log tool calls (if any)
                if hasattr(response, "tool_calls") and response.tool_calls:
                    for tc in response.tool_calls:
                        log.append(
                            f"{datetime.now().strftime('%H:%M:%S')} "
                            f"→ Calling tool: {tc['name']}"
                        )

                return {
                    **state,
                    "messages": state["messages"] + [response],
                    "workflow_log": log,
                }

            except Exception as e:
                return {
                    **state,
                    "workflow_log": state["workflow_log"] + [
                        f"Agent Error: {str(e)}"
                    ]
                }

        # =================================================
        # ROUTING LOGIC
        # =================================================
        def should_continue(state: APAgentState):

            try:
                last_message = state["messages"][-1]

                if (
                    isinstance(last_message, AIMessage)
                    and getattr(last_message, "tool_calls", None)
                ):
                    return "agent"   # loop back for tool execution

                return END

            except Exception:
                return END

        # =================================================
        # BUILD GRAPH
        # =================================================
        graph = StateGraph(APAgentState)

        graph.add_node("agent", call_agent)

        graph.set_entry_point("agent")

        graph.add_conditional_edges(
            "agent",
            should_continue
        )

        compiled = graph.compile()

        # =================================================
        # INITIAL STATE
        # =================================================
        initial_state = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=command)
            ],
            "approved_count": 0,
            "rejected_count": 0,
            "review_count": 0,
            "notifications_sent": 0,
            "workflow_log": [],
        }

        # =================================================
        # RUN WORKFLOW
        # =================================================
        final_state = await asyncio.wait_for(
            compiled.ainvoke(
                initial_state,
                config={"recursion_limit": 25}
            ),
            timeout=60
        )

        # =================================================
        # EXTRACT FINAL REPORT
        # =================================================
        final_report = "Workflow completed."

        for msg in reversed(final_state["messages"]):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                final_report = msg.content
                break

        result = {
            "status": "completed",
            "final_report": final_report,
            "approved": final_state["approved_count"],
            "rejected": final_state["rejected_count"],
            "review": final_state["review_count"],
            "notifications": final_state["notifications_sent"],
            "workflow_log": final_state["workflow_log"],
            "total": (
                final_state["approved_count"]
                + final_state["rejected_count"]
                + final_state["review_count"]
            )
        }

        print("\n✅ WORKFLOW FINISHED")
        print(json.dumps(result, indent=2))

        return result

    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": "Workflow timeout"
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass


# =========================================================
# SYNC WRAPPER
# =========================================================
def run_workflow_sync(command: str = "Process all pending invoices"):
    return asyncio.run(run_ap_workflow(command))


# =========================================================
# TEST
# =========================================================
if __name__ == "__main__":
    result = asyncio.run(run_ap_workflow())
    print("\n📊 FINAL RESULT:")
    print(json.dumps(result, indent=2))