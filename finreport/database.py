"""Database layer for the Kulana Financial Reporting module.

Uses FINREPORT_DATABASE_URL when configured; otherwise DATABASE_URL.  The
module uses fr_ prefixed tables so it does not collide with existing apps.
For a physically separate database, set FINREPORT_DATABASE_URL to its URL.
"""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone


def _database_url():
    # Render provides DATABASE_URL for attached PostgreSQL databases. Local
    # development remains on SQLite unless a database URL is explicitly set.
    return (os.environ.get("FINREPORT_DATABASE_URL") or
            os.environ.get("DATABASE_URL") or "").strip()


def is_postgres():
    return _database_url().startswith(("postgres://", "postgresql://"))


def database_target():
    if is_postgres():
        return "PostgreSQL"
    path = Path(os.environ.get(
        "FINREPORT_SQLITE_PATH",
        os.path.join(os.path.dirname(__file__), "finreport.db"),
    )).expanduser()
    return f"SQLite · {path}"


def _connect():
    url = _database_url()
    if url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError("PostgreSQL driver missing. Add psycopg2-binary to requirements.txt") from exc
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        connect_options = {}
        connect_options["sslmode"] = os.environ.get("PGSSLMODE", "require")
        return psycopg2.connect(url, **connect_options), "%s"
    if os.environ.get("RENDER", "").lower() == "true":
        raise RuntimeError(
            "Render is running without a PostgreSQL URL. Attach a Render PostgreSQL "
            "database and set DATABASE_URL (or FINREPORT_DATABASE_URL) on this service. "
            "The app stopped to avoid saving data to temporary SQLite storage."
        )
    path = Path(os.environ.get(
        "FINREPORT_SQLITE_PATH",
        os.path.join(os.path.dirname(__file__), "finreport.db"),
    )).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn, "?"


@contextmanager
def connection():
    conn, ph = _connect()
    try:
        yield conn, ph
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    pg = is_postgres()
    id_type = "TEXT"
    statements = [
        """CREATE TABLE IF NOT EXISTS fr_entities (
            entity_code TEXT PRIMARY KEY, entity_name TEXT NOT NULL,
            functional_currency TEXT NOT NULL, country TEXT, is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS fr_tb_imports (
            import_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            fiscal_month INTEGER NOT NULL, file_name TEXT, imported_at TEXT NOT NULL,
            imported_by TEXT, status TEXT NOT NULL DEFAULT 'DRAFT',
            debit_total DOUBLE PRECISION NOT NULL DEFAULT 0,
            credit_total DOUBLE PRECISION NOT NULL DEFAULT 0,
            line_count INTEGER NOT NULL DEFAULT 0, notes TEXT)""",
        """CREATE TABLE IF NOT EXISTS fr_tb_lines (
            line_id TEXT PRIMARY KEY, import_id TEXT NOT NULL, entity_code TEXT NOT NULL,
            account_code TEXT NOT NULL, account_name TEXT NOT NULL, category TEXT,
            source TEXT, debit DOUBLE PRECISION NOT NULL DEFAULT 0,
            credit DOUBLE PRECISION NOT NULL DEFAULT 0,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS fr_account_mappings (
            entity_code TEXT NOT NULL, account_code TEXT NOT NULL, account_name TEXT NOT NULL,
            statement_type TEXT, statement_line TEXT, account_nature TEXT,
            normal_balance TEXT, classification TEXT, is_mapped INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, PRIMARY KEY(entity_code, account_code, account_name))""",
        """CREATE TABLE IF NOT EXISTS fr_audit_log (
            audit_id TEXT PRIMARY KEY, event_time TEXT NOT NULL, username TEXT,
            entity_code TEXT, fiscal_year INTEGER, fiscal_month INTEGER,
            action TEXT NOT NULL, details TEXT)""",
    ]
    with connection() as (conn, ph):
        cur = conn.cursor()
        for sql in statements:
            cur.execute(sql)
        cur.execute("SELECT COUNT(*) FROM fr_entities")
        count = cur.fetchone()[0]
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            defaults = [
                ("KSL", "Kulana Services Ltd", "USD", "Mauritius", 1, now),
                ("KL", "Kulana Ghana Ltd", "GHS", "Ghana", 1, now),
                ("GROUP", "Kulana Group Consolidated", "USD", "Group", 1, now),
            ]
            cur.executemany("INSERT INTO fr_entities (entity_code,entity_name,functional_currency,country,is_active,created_at) VALUES (" + ",".join([ph]*6) + ")", defaults)



# Data tables cleared by the full IFRS reporting reset. Entity setup and the
# audit log are intentionally retained so the workspace remains usable and
# the destructive reset itself remains traceable.
IFRS_RESET_TABLES = (
    "fr_tb_lines",
    "fr_tb_imports",
    "fr_account_mappings",
    "fr_chart_of_accounts",
    "fr_mapping_line_catalogue",
    "fr_reporting_inputs",
    "fr_note_disclosures",
)


def reset_ifrs_data(username=None):
    """Permanently clear all IFRS reporting data across every entity.

    Keeps fr_entities (company setup) and fr_audit_log (audit history).
    Runs in one database transaction and returns deleted row counts.
    """
    counts = {}
    with connection() as (conn, ph):
        cur = conn.cursor()
        # Child/transactional records are removed before their parent records.
        for table in IFRS_RESET_TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cur.fetchone()[0])
                cur.execute(f"DELETE FROM {table}")
            except Exception:
                # Missing optional reporting tables are treated as empty. The
                # connection context will still roll back if a real DB error
                # aborts the transaction.
                if is_postgres():
                    raise
                counts[table] = 0

        now = datetime.now(timezone.utc).isoformat()
        details = "Full IFRS data reset; deleted rows: " + ", ".join(
            f"{table}={count}" for table, count in counts.items()
        )
        cur.execute(
            "INSERT INTO fr_audit_log "
            "(audit_id,event_time,username,entity_code,fiscal_year,fiscal_month,action,details) "
            "VALUES (" + ",".join([ph] * 8) + ")",
            (
                __import__("uuid").uuid4().hex, now, username or "system",
                None, None, None, "FULL_IFRS_DATA_RESET", details
            ),
        )
    return counts

def rows(sql, params=()):
    with connection() as (conn, ph):
        cur = conn.cursor(); cur.execute(sql, params)
        return [dict(r) if isinstance(r, sqlite3.Row) else dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def execute(sql, params=()):
    with connection() as (conn, ph):
        cur = conn.cursor(); cur.execute(sql, params)
        return cur.rowcount
