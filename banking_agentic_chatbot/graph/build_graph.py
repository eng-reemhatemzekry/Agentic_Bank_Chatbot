
import os

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from graph.agent import build_agent_node, load_tools
from graph.guardrails import (
    input_guardrail_node,
    output_guardrail_node,
    route_after_input_guardrail,
)
from graph.state import BankingState


async def build_graph(db_username: str, db_password: str):
    """Build one compiled graph for one authenticated customer's session, connected to the
    single official teradata-mcp-server AS that customer's own Teradata login. Both the CLI
    (app.py) and the Gradio UI (web_app.py) call this per session -- each session gets its
    own independent tool set/MCP connection, so concurrent customers in the same Python
    process (as happens under Gradio) can never share or leak each other's credentials."""
    tools = await load_tools(db_username, db_password)
    agent_node = build_agent_node(tools)

    graph = StateGraph(BankingState)
    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("output_guardrail", output_guardrail_node)

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail", route_after_input_guardrail, {"agent": "agent", "__end__": END}
    )
    graph.add_conditional_edges(
        "agent", tools_condition, {"tools": "tools", "__end__": "output_guardrail"}
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("output_guardrail", END)

    return graph.compile()


async def export_mermaid(path="diagrams/agent_graph.mmd", db_username=None, db_password=None):
    """For diagram export, any working Teradata login is fine (structure doesn't depend on
    whose data it can see) -- defaults to the admin login already in .env."""
    db_username = db_username or os.environ.get("TD_ADMIN_USER")
    db_password = db_password or os.environ.get("TD_ADMIN_PASSWORD")
    compiled = await build_graph(db_username, db_password)
    mermaid_src = compiled.get_graph().draw_mermaid()
    with open(path, "w") as f:
        f.write(mermaid_src)
    print(f"Wrote {path}")
    return mermaid_src


if __name__ == "__main__":
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(export_mermaid())
