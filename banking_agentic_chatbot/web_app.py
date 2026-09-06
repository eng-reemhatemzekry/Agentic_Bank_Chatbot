
import asyncio
import os

import gradio as gr
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from auth import authenticate
from graph.build_graph import build_graph

load_dotenv()


async def handle_login(customer_id, pin):
    """Verify credentials, then build this session's own graph + conversation state.
    Returns Gradio component updates: toggle the login/chat panels, show a status message,
    and store the session's graph+state bundle in the (per-browser-session) gr.State."""
    result = authenticate(customer_id, pin)
    if not result.ok:
        return (
            gr.update(visible=True),   # login_group stays visible
            gr.update(visible=False),  # chat_group stays hidden
            f"⚠️ {result.message}",
            None,                      # session_state unchanged (still logged out)
            [],                        # chatbot history
        )

    try:
        graph = await build_graph(result.db_username, result.db_password)
    except Exception as e:
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            f"⚠️ Could not start the assistant: {e}",
            None,
            [],
        )

    session_state = {
        "graph": graph,
        "state": {
            "messages": [],
            "customer_id": result.customer_id,
            "db_username": result.db_username,
            "language": None,
            "input_guardrail": None,
            "output_guardrail": None,
        },
    }
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        "",
        session_state,
        [],
    )


async def handle_chat(message, chat_history, session_state):
    """One turn of the conversation: run the full LangGraph pipeline (input guardrail ->
    agent <-> tools -> output guardrail) for this session's own graph, exactly like app.py's
    CLI loop does -- this function is the only place web_app.py touches the agent, and it
    does nothing but pass the message through; no routing/business logic lives here."""
    if not session_state:
        chat_history = chat_history + [(message, "Please sign in first.")]
        return chat_history, session_state, ""

    graph = session_state["graph"]
    state = session_state["state"]
    state["messages"].append(HumanMessage(content=message))

    state = await graph.ainvoke(state)
    session_state["state"] = state

    reply = state["messages"][-1].content
    chat_history = chat_history + [(message, reply)]
    return chat_history, session_state, ""


def handle_logout():
    return gr.update(visible=True), gr.update(visible=False), None, [], ""


with gr.Blocks(title="Amana Bank Assistant") as demo:
    gr.Markdown("# 🏦 Amana Bank Assistant")

    session_state = gr.State(None)

    with gr.Group(visible=True) as login_group:
        gr.Markdown("### Sign in")
        customer_id_box = gr.Textbox(label="Customer ID", placeholder="CUST000001")
        pin_box = gr.Textbox(label="Login PIN", type="password")
        login_btn = gr.Button("Sign in", variant="primary")
        login_status = gr.Markdown("")

    with gr.Group(visible=False) as chat_group:
        chatbot = gr.Chatbot(label="Amana Bank Assistant", height=520)
        msg_box = gr.Textbox(
            label="Message",
            placeholder="Ask about your account, transactions, products, or general questions (any language)...",
        )
        with gr.Row():
            send_btn = gr.Button("Send", variant="primary")
            logout_btn = gr.Button("Sign out")

    login_outputs = [login_group, chat_group, login_status, session_state, chatbot]
    login_btn.click(handle_login, inputs=[customer_id_box, pin_box], outputs=login_outputs)
    pin_box.submit(handle_login, inputs=[customer_id_box, pin_box], outputs=login_outputs)

    chat_outputs = [chatbot, session_state, msg_box]
    send_btn.click(handle_chat, inputs=[msg_box, chatbot, session_state], outputs=chat_outputs)
    msg_box.submit(handle_chat, inputs=[msg_box, chatbot, session_state], outputs=chat_outputs)

    logout_btn.click(
        handle_logout,
        outputs=[login_group, chat_group, session_state, chatbot, login_status],
    )

if __name__ == "__main__":
    demo.queue()
    demo.launch()
