
import asyncio
import json
import os

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

required = ["TD_HOST", "TD_ADMIN_USER", "TD_ADMIN_PASSWORD"]
missing = [v for v in required if not os.environ.get(v)]
if missing:
    raise SystemExit(f"Missing required .env variable(s): {', '.join(missing)}")

DATABASE_URI = (
    f"teradata://{os.environ['TD_ADMIN_USER']}:{os.environ['TD_ADMIN_PASSWORD']}"
    f"@{os.environ['TD_HOST']}:1025/amana_bank"
)


async def main():
    server_params = StdioServerParameters(
        command="uvx",
        args=["teradata-mcp-server", "--profile", "all"],
        env={**os.environ, "DATABASE_URI": DATABASE_URI},
    )

    print("Launching teradata-mcp-server (admin session)...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            tdvs_tools = [t for t in tools if t.name.startswith("tdvs_")]

            if not tdvs_tools:
                print(
                    "No tdvs_* (Teradata Vector Store) tools were exposed by this server.\n"
                    "Either the 'evs'/vector-store extra isn't installed "
                    "(try: uv tool install \"teradata-mcp-server[evs]\"), or your Teradata "
                    "instance doesn't have the native VECTOR type enabled.\n"
                    "Fall back to reading amana_bank.faqs directly, or run "
                    "`python db/load_data.py --legacy-embed-faqs`."
                )
                return

            print(f"\nFound {len(tdvs_tools)} Teradata Vector Store tools:")
            for t in tdvs_tools:
                print(f"\n=== SCHEMA FOR: {t.name} ===")
                print(t.description)
                print(f"--- {t.name} input schema ---")
                print(json.dumps(t.inputSchema, indent=2))
                print(f"=== END SCHEMA FOR: {t.name} ===")

            if not any(t.name == "tdvs_create" for t in tdvs_tools):
                print("\ntdvs_create not found among the tools above -- can't proceed automatically.")
                return

            print("\nAttempting tdvs_create over amana_bank.faqs (question, answer)...")
            # This server wraps every action's parameters in a nested object named after the
            # action (confirmed from tdvs_update's schema: {"vs_name": ..., "vs_update": {...}}
            # and tdvs_similarity_search's: {"vs_name": ..., "vs_similaritysearch": {...}}) --
            # so tdvs_create follows the same pattern: {"vs_name": ..., "vs_create": {...}}.
            # object_names is a STRING (a table name), not a list, per the sibling schemas.
            try:
                result = await session.call_tool(
                    "tdvs_create",
                    arguments={
                        "vs_name": "faq_vector_store",
                        "vs_create": {
                            "description": "FAQ knowledge base for Amana Bank customer support",
                            "object_names": "amana_bank.faqs",
                        },
                    },
                )
                print("Result:")
                for block in result.content:
                    print(getattr(block, "text", block))
                print(
                    "\nIf this succeeded, the agent can now use tdvs_similarity_search / "
                    "tdvs_ask on 'faq_vector_store' automatically -- no further setup needed, "
                    "since app.py discovers all tools dynamically."
                )
            except Exception as e:
                print(f"tdvs_create failed: {e}")
                print(
                    "\nCheck the 'SCHEMA FOR: tdvs_create' block printed above (search for "
                    "that exact heading in the output) for the precise required/optional "
                    "fields your server version expects, and adjust the `arguments=` dict "
                    "in this script accordingly, then re-run. Or use one of the fallbacks "
                    "described at the top of this file."
                )


if __name__ == "__main__":
    asyncio.run(main())
