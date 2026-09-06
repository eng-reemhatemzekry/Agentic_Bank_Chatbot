
import csv
import hashlib
import os

import teradatasql

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


class AuthResult:
    def __init__(self, ok: bool, message: str, customer_id: str = None,
                 db_username: str = None, db_password: str = None):
        self.ok = ok
        self.message = message
        self.customer_id = customer_id
        self.db_username = db_username
        self.db_password = db_password


def authenticate(customer_id: str, login_pin: str) -> AuthResult:
    """Verify credentials and resolve session DB login. Never raises for expected failure
    cases (bad credentials, missing config) -- always returns an AuthResult so callers
    (CLI prompt loop, Gradio form handler) can present the failure however fits their UI."""
    customer_id = (customer_id or "").strip().upper()
    login_pin = (login_pin or "").strip()

    if not customer_id or not login_pin:
        return AuthResult(False, "Please enter both Customer ID and login PIN.")

    required = ["TD_HOST", "TD_ADMIN_USER", "TD_ADMIN_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        return AuthResult(
            False,
            f"Server misconfigured: missing {', '.join(missing)} in .env "
            f"(expected at {os.path.join(_PROJECT_ROOT, '.env')}).",
        )

    secret_hash = hashlib.sha256(login_pin.encode()).hexdigest()

    try:
        admin_conn = teradatasql.connect(
            host=os.environ["TD_HOST"],
            user=os.environ["TD_ADMIN_USER"],
            password=os.environ["TD_ADMIN_PASSWORD"],
            database="amana_bank",
        )
    except Exception as e:
        return AuthResult(False, f"Could not connect to Teradata: {e}")

    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT customer_id FROM amana_bank.customers "
                "WHERE customer_id = ? AND auth_secret_hash = ?",
                [customer_id, secret_hash],
            )
            if cur.fetchone() is None:
                return AuthResult(False, "Invalid Customer ID or PIN.")

            cur.execute(
                "SELECT db_username FROM amana_bank.user_customer_map WHERE customer_id = ?",
                [customer_id],
            )
            row = cur.fetchone()
            if row is None:
                return AuthResult(
                    False,
                    "No database login provisioned for this customer yet -- run "
                    "'python db/load_data.py --provision-users' first.",
                )
            db_username = row[0]
    finally:
        admin_conn.close()

    creds_path = os.path.join(_PROJECT_ROOT, "db", "customer_db_credentials.csv")
    try:
        with open(creds_path) as f:
            for row in csv.DictReader(f):
                if row["customer_id"] == customer_id:
                    return AuthResult(
                        True, f"Welcome, {customer_id}!",
                        customer_id=customer_id,
                        db_username=db_username,
                        db_password=row["db_password"],
                    )
    except FileNotFoundError:
        return AuthResult(
            False,
            f"{creds_path} not found -- run 'python db/load_data.py --provision-users' first.",
        )

    return AuthResult(False, "Could not resolve database credentials for this customer.")
