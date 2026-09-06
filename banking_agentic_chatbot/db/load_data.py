
import argparse
import csv
import hashlib
import os
import secrets
import string
import sys

import pandas as pd
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


def _rows_with_none(df: pd.DataFrame, cols: list) -> list:
    """Convert a DataFrame's selected columns to a list of row-lists, replacing NaN/NaT
    with real Python None everywhere -- required because DataFrame.where(notnull, None)
    silently puts NaN right back into float64/datetime columns (a well-known pandas
    gotcha: assigning None into a numeric-dtype column just re-coerces to NaN), which
    Teradata then rejects as a "numeric overflow" on INSERT rather than accepting it as
    a NULL. Converting to dtype=object first avoids that re-coercion."""
    return df[cols].astype(object).where(pd.notnull(df[cols]), None).values.tolist()


def get_connection():
    required = ["TD_HOST", "TD_ADMIN_USER", "TD_ADMIN_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise SystemExit(
            f"Missing required environment variable(s): {', '.join(missing)}.\n"
            f"Make sure .env exists at {os.path.join(_PROJECT_ROOT, '.env')} "
            "with real values (not just .env.example)."
        )
    return teradatasql.connect(
        host=os.environ["TD_HOST"],
        user=os.environ["TD_ADMIN_USER"],
        password=os.environ["TD_ADMIN_PASSWORD"],
        database=os.environ.get("TD_DATABASE", "amana_bank"),
    )


def load_customers(conn, path, login_secrets_path="db/customer_login_secrets.csv"):
    """Note on national_id: the source CSV was exported from Excel with big national-ID
    numbers auto-converted to scientific notation (e.g. "2.15235E+13"), which permanently
    discards the exact digits -- there is no way to recover the real ID from this file, so
    it cannot be used as a login secret. Instead, this generates a random 8-digit login PIN
    per customer here (demo-only mechanism -- swap for real auth/OTP/SSO in production),
    hashes it the same way for storage, and writes the plaintext PIN lookup table to
    login_secrets_path so you have something to actually log in with in app.py.
    """
    df = pd.read_csv(path)

    rng = secrets.SystemRandom()
    login_pins = [f"{rng.randint(0, 99999999):08d}" for _ in range(len(df))]
    df["auth_secret_hash"] = [hashlib.sha256(pin.encode()).hexdigest() for pin in login_pins]

    with open(login_secrets_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "login_pin"])
        w.writerows(zip(df["customer_id"], login_pins))
    print(f"Wrote login PINs for {len(df)} customers -> {login_secrets_path}")

    cols = [
        "customer_id", "full_name", "national_id", "age", "job", "marital", "education",
        "default", "balance", "housing", "loan", "contact", "day", "credit_score",
        "monthly_income", "loan_history", "risk_level", "email", "phone", "auth_secret_hash",
    ]
    rows = _rows_with_none(df, cols)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM amana_bank.customers ALL;")
        cur.executemany(
            """INSERT INTO amana_bank.customers
               (customer_id, full_name, national_id, age, job, marital, education,
                has_credit_default, balance, housing_loan, personal_loan, contact_method,
                contact_day, credit_score, monthly_income, loan_history, risk_level, email,
                phone, auth_secret_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    print(f"Loaded {len(rows)} customers")


def load_faqs(conn, path):
    df = pd.read_csv(path)
    rows = df[["Question", "Answer"]].values.tolist()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM amana_bank.faqs ALL;")
        cur.executemany("INSERT INTO amana_bank.faqs (question, answer) VALUES (?, ?)", rows)
    print(f"Loaded {len(rows)} FAQs")


def load_products(conn, path):
    df = pd.read_excel(path, engine="openpyxl")  # .csv extension, actually .xlsx content
    cols = [
        "product_id", "product_name", "category", "description", "currency",
        "interest_rate_pct", "term_months", "min_balance", "monthly_fee", "annual_fee",
        "min_income_eligibility", "min_credit_score_eligibility", "min_age_eligibility",
        "max_amount", "status", "launch_date",
    ]
    rows = _rows_with_none(df, cols)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM amana_bank.products ALL;")
        cur.executemany(
            """INSERT INTO amana_bank.products
               (product_id, product_name, category, description, currency, interest_rate_pct,
                term_months, min_balance, monthly_fee, annual_fee, min_income_eligibility,
                min_credit_score_eligibility, min_age_eligibility, max_amount, status,
                launch_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    print(f"Loaded {len(rows)} products")


def load_transactions(conn, path, batch_size=5000):
    df = pd.read_excel(path, engine="openpyxl")  # .csv extension, actually .xlsx content
    cols = [
        "transaction_id", "customer_id", "product_id", "transaction_date", "transaction_type",
        "category", "direction", "amount", "currency", "channel", "merchant_or_counterparty",
        "description", "status", "balance_after",
    ]
    rows = _rows_with_none(df, cols)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM amana_bank.transactions ALL;")
        for i in range(0, len(rows), batch_size):
            cur.executemany(
                """INSERT INTO amana_bank.transactions
                   (transaction_id, customer_id, product_id, transaction_date,
                    transaction_type, category, direction, amount, currency, channel,
                    merchant_or_counterparty, description, status, balance_after)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows[i : i + batch_size],
            )
    print(f"Loaded {len(rows)} transactions")


def provision_users(conn, out_credentials_path="db/customer_db_credentials.csv"):
    """Create one restricted Teradata login per customer and populate user_customer_map.

    Since db/schema.sql grants v_my_* and the public tables to PUBLIC once (they're safe to
    share because v_my_* self-filters on CURRENT_USER), this step only needs to CREATE USER
    and INSERT the mapping -- no per-customer GRANT statements. This is what lets the single
    official teradata-mcp-server, connected as this login, act as the customer's whole
    "identity" for the session: whatever SQL the LLM sends via base_readQuery, Teradata's own
    permission system means only this customer's rows are ever visible.

    Resumable: skips customers already present in user_customer_map. Auto-reconnects if the
    connection drops mid-run (seen on some trial instances under sustained load) instead of
    aborting the whole run -- just re-run the same command to pick up where it left off.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM amana_bank.customers")
        customer_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT customer_id FROM amana_bank.user_customer_map")
        already_done = {r[0] for r in cur.fetchall()}

    creds = []
    if os.path.exists(out_credentials_path):
        with open(out_credentials_path) as f:
            creds = [
                (row["customer_id"], row["db_username"], row["db_password"])
                for row in csv.DictReader(f)
            ]
    have_creds_locally = {c[0] for c in creds}

    todo_create = [cid for cid in customer_ids if cid not in already_done]
    # Provisioned in Teradata already, but this local folder's credentials file doesn't
    # have their password -- happens whenever the project is re-downloaded/re-extracted
    # into a new folder after a previous run already provisioned some customers elsewhere.
    # Teradata never lets you read a password back, so these get a fresh one via
    # ALTER USER rather than being silently left permanently unusable.
    todo_reset = [cid for cid in customer_ids if cid in already_done and cid not in have_creds_locally]

    print(
        f"{len(already_done)} customers already provisioned in Teradata, "
        f"{len(todo_create)} need CREATE USER, "
        f"{len(todo_reset)} need a password reset (provisioned elsewhere, password unknown here)"
    )

    active_conn = conn

    def run_with_retry(cid, db_user, pwd, statements, label, total):
        nonlocal active_conn
        for attempt in range(3):
            try:
                with active_conn.cursor() as cur:
                    for stmt in statements:
                        sql, params = stmt if isinstance(stmt, tuple) else (stmt, None)
                        try:
                            cur.execute(sql, params) if params else cur.execute(sql)
                        except Exception as stmt_err:
                            if "already exists" in str(stmt_err) or "5612" in str(stmt_err):
                                print(f"  {db_user} already exists from an earlier run -- recreating it")
                                cur.execute(f"DROP USER {db_user};")
                                cur.execute(
                                    f'CREATE USER {db_user} FROM amana_bank AS PASSWORD = "{pwd}", PERM = 0;'
                                )
                            else:
                                raise
                creds.append((cid, db_user, pwd))
                return True
            except Exception as e:
                print(f"  [{label}] {cid} attempt {attempt + 1} failed: {e}")
                try:
                    active_conn.close()
                except Exception:
                    pass
                try:
                    active_conn = get_connection()
                except Exception as reconnect_err:
                    print(f"  reconnect failed: {reconnect_err}")
        print(f"  GIVING UP on {cid} after 3 attempts -- will retry on next run")
        return False

    def new_password():
        # Alphanumeric-only + double-quoted at use: Teradata's PASSWORD clause rejects
        # standard single-quoted string literals (wants an unquoted or double-quoted/
        # "Unicode delimited identifier" token instead).
        return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))

    total = len(todo_create) + len(todo_reset)
    done = 0

    for cid in todo_create:
        db_user = f"u_{cid.lower()}"
        pwd = new_password()
        run_with_retry(
            cid, db_user, pwd,
            [
                f'CREATE USER {db_user} FROM amana_bank AS PASSWORD = "{pwd}", PERM = 0;',
                (
                    "INSERT INTO amana_bank.user_customer_map (db_username, customer_id) "
                    "VALUES (?, ?)",
                    [db_user, cid],
                ),
            ],
            "create", total,
        )
        done += 1
        if done % 50 == 0 or done == total:
            print(f"  progress: {done}/{total}")
            with open(out_credentials_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["customer_id", "db_username", "db_password"])
                w.writerows(creds)

    for cid in todo_reset:
        db_user = f"u_{cid.lower()}"
        pwd = new_password()
        run_with_retry(
            cid, db_user, pwd,
            [f'ALTER USER {db_user} AS PASSWORD = "{pwd}";'],
            "reset", total,
        )
        done += 1
        if done % 50 == 0 or done == total:
            print(f"  progress: {done}/{total}")
            with open(out_credentials_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["customer_id", "db_username", "db_password"])
                w.writerows(creds)

    with open(out_credentials_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "db_username", "db_password"])
        w.writerows(creds)
    print(f"{len(creds)} customers now have usable credentials in {out_credentials_path}")
    print("Keep this file out of version control (see .gitignore).")
    return active_conn  # may be a reconnected connection, different from the one passed in


def embed_faqs_legacy(conn):
    """LEGACY fallback only -- use scripts/setup_vector_store.py (real Teradata Vector
    Store / tdvs_* tools) instead if your instance supports it. This function embeds FAQs
    via local Ollama and stores them as JSON text, for the case where native Teradata
    vector search genuinely isn't available and you don't just want to hand the whole
    ~70-row faqs table to the agent directly (also a perfectly fine option for a set this
    small -- see the note in db/schema.sql section 2)."""
    import json

    import requests

    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    embed_model = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    with conn.cursor() as cur:
        cur.execute("SELECT faq_id, question, answer FROM amana_bank.faqs")
        faqs = cur.fetchall()

    with conn.cursor() as cur:
        cur.execute("DELETE FROM amana_bank.faq_embeddings ALL;")
        for faq_id, question, answer in faqs:
            text = f"Q: {question}\nA: {answer}"
            resp = requests.post(
                f"{ollama_url}/api/embeddings", json={"model": embed_model, "prompt": text}, timeout=60
            )
            resp.raise_for_status()
            vector = resp.json()["embedding"]
            cur.execute(
                "INSERT INTO amana_bank.faq_embeddings (faq_id, question, answer, embedding) "
                "VALUES (?, ?, ?, ?)",
                [faq_id, question, answer, json.dumps(vector)],
            )
    print(f"[legacy] Embedded {len(faqs)} FAQs into amana_bank.faq_embeddings")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default="./data")
    ap.add_argument("--provision-users", action="store_true")
    ap.add_argument(
        "--legacy-embed-faqs", action="store_true",
        help="Only needed if scripts/setup_vector_store.py's real tdvs_create fails on "
             "your instance and you don't want to just hand the LLM the raw faqs table.",
    )
    args = ap.parse_args()

    conn = get_connection()
    try:
        load_customers(conn, os.path.join(args.source_dir, "Synthetic_Bank_Customers.csv"))
        load_faqs(conn, os.path.join(args.source_dir, "Bank_FAQs.csv"))
        load_products(conn, os.path.join(args.source_dir, "Bank_Products.csv"))
        load_transactions(conn, os.path.join(args.source_dir, "Customer_Transactions.csv"))
        if args.provision_users:
            conn = provision_users(conn)  # may return a reconnected connection
        if args.legacy_embed_faqs:
            embed_faqs_legacy(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass  # connection may already be dead after a mid-run reconnect; not fatal


if __name__ == "__main__":
    sys.exit(main())
