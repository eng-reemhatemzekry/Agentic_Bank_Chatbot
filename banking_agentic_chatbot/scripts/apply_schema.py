
import os
import re
import sys

import teradatasql
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loaded = load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
if not _loaded:
    print(
        f"WARNING: no .env file found at {os.path.join(_PROJECT_ROOT, '.env')}. "
        "Copy .env.example to .env and fill in real values, or set these variables in "
        "your shell before running this script."
    )


def split_statements(sql_text: str) -> list[str]:
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)
    statements = [s.strip() for s in cleaned.split(";")]
    return [s for s in statements if s]


def main():
    schema_path = os.path.join(_PROJECT_ROOT, "db", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql_text = f.read()

    statements = split_statements(sql_text)
    print(f"Found {len(statements)} statements in {schema_path}")

    required = ["TD_HOST", "TD_ADMIN_USER", "TD_ADMIN_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Missing required .env variable(s): {', '.join(missing)}")

    conn = teradatasql.connect(
        host=os.environ["TD_HOST"],
        user=os.environ["TD_ADMIN_USER"],
        password=os.environ["TD_ADMIN_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements, start=1):
                preview = re.sub(r"\s+", " ", stmt)[:80]
                try:
                    cur.execute(stmt)
                    print(f"[{i}/{len(statements)}] OK   {preview}")
                except Exception as e:
                    print(f"[{i}/{len(statements)}] FAIL {preview}\n    -> {e}")
    finally:
        conn.close()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
