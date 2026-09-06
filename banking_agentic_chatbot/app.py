
import asyncio
import getpass
import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from auth import authenticate
from graph.build_graph import build_graph

load_dotenv()


async def main():
    customer_id = input("Customer ID (e.g. CUST000001): ").strip().upper()
    login_pin = getpass.getpass("Login PIN (see db/customer_login_secrets.csv): ").strip()

    result = authenticate(customer_id, login_pin)
    if not result.ok:
        print(result.message)
        sys.exit(1)

    print(f"\n{result.message} Ask me anything (any language) -- 'exit' to quit.\n")
    graph = await build_graph(result.db_username, result.db_password)

    state = {
        "messages": [],
        "customer_id": result.customer_id,
        "db_username": result.db_username,
        "language": None,
        "input_guardrail": None,
        "output_guardrail": None,
    }

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in {"exit", "quit"}:
            break
        state["messages"].append(HumanMessage(content=user_text))
        state = await graph.ainvoke(state)
        reply = state["messages"][-1]
        print(f"Assistant: {reply.content}\n")


if __name__ == "__main__":
    asyncio.run(main())
