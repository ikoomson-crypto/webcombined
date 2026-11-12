from __future__ import annotations
from datetime import datetime, timezone
import uuid
import re
import pandas as pd
from database import connection, rows, is_postgres

ACCOUNT_TYPES = ["Income", "Expense", "Asset", "Equity", "Liability"]

def get_account_types(entity_code):
    """Read Account Type values from the selected entity's Mapping Catalogue."""
    from account_mapping import get_account_type_catalogue
    return [str(x["line_label"]) for x in get_account_type_catalogue(entity_code)]


def normalize_account_type(value, entity_code):
    """Resolve an entered value only against the active Mapping Catalogue.

    No built-in classification aliases are applied. The catalogue label is
    returned exactly as maintained by the user.
    """
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""
    for catalogue_label in get_account_types(entity_code):
        if raw.casefold() == catalogue_label.strip().casefold():
            return catalogue_label
    return raw


def normalize_account_name(value):
    """Normalize whitespace only; preserve code prefixes that are part of the account name."""
    return " ".join(str(value or "").strip().split())


STATEMENTS = ["Profit or Loss", "Financial Position"]
CASH_FLOW_CLASSIFICATIONS = [
    "", "Operating – Working Capital Asset", "Operating – Working Capital Liability",
    "Operating – Non-cash Adjustment", "Investing Activity", "Financing Activity",
    "Cash and Cash Equivalents", "Excluded / Non-cash",
]
STATEMENT_CODES = {"Profit or Loss": "PL", "Financial Position": "BS"}
CODE_PREFIXES = {"KSL": "KSL", "KL": "KGL", "KGL": "KGL", "KHL": "KHL", "GROUP": "GRP"}


def _ph():
    return "%s" if is_postgres() else "?"


def init_coa():
    p = _ph()
    with connection() as (conn, _):
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS fr_chart_of_accounts (
            coa_id TEXT PRIMARY KEY,
            entity_code TEXT NOT NULL,
            account_code TEXT NOT NULL,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            notes_line TEXT,
            cash_flow_classification TEXT,
            ifrs_line TEXT,
            statement_type TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(entity_code, account_code)
        )""")
        # Safe additive migration for installations created by an earlier COA prototype.
        if is_postgres():
            for sql in [
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS notes_line TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS cash_flow_classification TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS ifrs_line TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS statement_type TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS account_type TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1",
            ]:
                cur.execute(sql)
        else:
            for sql in [
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN notes_line TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN cash_flow_classification TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN ifrs_line TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN statement_type TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN account_type TEXT",
                "ALTER TABLE fr_chart_of_accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            ]:
                try:
                    cur.execute(sql)
                except Exception as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise
    migrate_existing_mappings()


def _prefix(entity_code):
    return CODE_PREFIXES.get(str(entity_code).upper(), re.sub(r"[^A-Z0-9]", "", str(entity_code).upper())[:4] or "COA")


def _next_code(entity_code):
    p = _ph()
    existing = rows(
        f"SELECT account_code FROM fr_chart_of_accounts WHERE entity_code={p}",
        (entity_code,),
    )
    prefix = _prefix(entity_code) + "-"
    highest = 0
    for item in existing:
        match = re.search(r"(\d+)$", str(item.get("account_code") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:06d}"


def list_accounts(entity_code, active_only=True):
    p = _ph()
    sql = f"SELECT account_code, account_name, account_type, notes_line, cash_flow_classification, ifrs_line, statement_type, is_active FROM fr_chart_of_accounts WHERE entity_code={p}"
    if active_only:
        sql += " AND is_active=1"
    sql += " ORDER BY account_code"
    return rows(sql, (entity_code,))


def get_account(entity_code, account_code=None, account_name=None):
    p = _ph()
    if account_code:
        found = rows(
            f"SELECT * FROM fr_chart_of_accounts WHERE entity_code={p} AND account_code={p} AND is_active=1",
            (entity_code, account_code),
        )
    else:
        found = rows(
            f"SELECT * FROM fr_chart_of_accounts WHERE entity_code={p} AND LOWER(TRIM(account_name))=LOWER(TRIM({p})) AND is_active=1",
            (entity_code, account_name),
        )
    return found[0] if found else None


def save_account(entity_code, account_name, account_type, notes_line="", ifrs_line="", statement_label="", account_code=None, cash_flow_classification=""):
    account_name = " ".join(str(account_name or "").strip().split())
    account_type = normalize_account_type(account_type, entity_code)
    notes_line = str(notes_line or "").strip()
    ifrs_line = str(ifrs_line or "").strip()
    statement_label = str(statement_label or "").strip()
    cash_flow_classification = str(cash_flow_classification or "").strip()
    if cash_flow_classification not in CASH_FLOW_CLASSIFICATIONS:
        raise ValueError("Select a valid Cash Flow Classification.")
    if not account_name:
        raise ValueError("Account Name is required.")
    valid_account_types = get_account_types(entity_code)
    if account_type not in valid_account_types:
        raise ValueError("Select an active Account Type from the Mapping Catalogue.")
    if notes_line and not catalogue_value_exists("NOTES", notes_line, entity_code=entity_code):
        raise ValueError(f"Notes line '{notes_line}' is not active in the Mapping Catalogue.")
    if ifrs_line and not catalogue_value_exists("IFRS", ifrs_line, statement_label, entity_code):
        raise ValueError(f"IFRS line '{ifrs_line}' is not active in the Mapping Catalogue for the selected statement.")
    if statement_label and statement_label not in STATEMENTS:
        raise ValueError("Select a valid Statement.")
    if bool(ifrs_line) != bool(statement_label):
        raise ValueError("Select both IFRS Line and Statement, or leave both blank.")
    p = _ph()
    duplicate = rows(
        f"SELECT account_code FROM fr_chart_of_accounts WHERE entity_code={p} AND LOWER(TRIM(account_name))=LOWER(TRIM({p})) AND is_active=1",
        (entity_code, account_name),
    )
    if duplicate and (
        (account_code and any(x["account_code"] != account_code for x in duplicate))
        or (not account_code and len(duplicate) > 1)
    ):
        raise ValueError(f"An account named '{account_name}' already exists more than once in this entity's Chart of Accounts.")
    existing = get_account(entity_code, account_code=account_code) if account_code else get_account(entity_code, account_name=account_name)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        code = existing["account_code"]
        with connection() as (conn, _):
            conn.cursor().execute(
                f"""UPDATE fr_chart_of_accounts SET account_name={p}, account_type={p},
                    notes_line={p}, cash_flow_classification={p}, ifrs_line={p}, statement_type={p}, updated_at={p}
                    WHERE entity_code={p} AND account_code={p}""",
                (account_name, account_type, notes_line or None, cash_flow_classification or None, ifrs_line or None,
                 STATEMENT_CODES.get(statement_label), now, entity_code, code),
            )
    else:
        code = account_code or _next_code(entity_code)
        with connection() as (conn, _):
            conn.cursor().execute(
                f"""INSERT INTO fr_chart_of_accounts
                    (coa_id,entity_code,account_code,account_name,account_type,notes_line,
                     cash_flow_classification,ifrs_line,statement_type,created_at,updated_at,is_active)
                    VALUES ({','.join([p]*12)})""",
                (str(uuid.uuid4()), entity_code, code, account_name, account_type,
                 notes_line or None, cash_flow_classification or None, ifrs_line or None, STATEMENT_CODES.get(statement_label),
                 now, now, 1),
            )
    # If the account was created after a TB import, attach its generated COA code
    # to existing same-name TB lines for this entity so the draft can be resolved
    # without uploading the TB again.
    with connection() as (conn, _):
        conn.cursor().execute(
            f"UPDATE fr_tb_lines SET account_code={p} WHERE entity_code={p} AND LOWER(TRIM(account_name))=LOWER(TRIM({p}))",
            (code, entity_code, account_name),
        )
    sync_legacy_mapping(entity_code, code)
    return code


def catalogue_value_exists(line_type, label, statement_label=None, entity_code=None):
    if not label or not entity_code:
        return False
    p = _ph()
    if line_type == "IFRS":
        found = rows(
            f"SELECT 1 AS ok FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND line_label={p} AND is_active=1",
            (entity_code, "IFRS", label),
        )
    else:
        found = rows(
            f"SELECT 1 AS ok FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND line_label={p} AND is_active=1",
            (entity_code, line_type, label),
        )
    return bool(found)


def sync_legacy_mapping(entity_code, account_code=None):
    p = _ph()
    if account_code:
        accounts = rows(
            f"SELECT * FROM fr_chart_of_accounts WHERE entity_code={p} AND account_code={p} AND is_active=1",
            (entity_code, account_code),
        )
    else:
        accounts = rows(
            f"SELECT * FROM fr_chart_of_accounts WHERE entity_code={p} AND is_active=1",
            (entity_code,),
        )
    now = datetime.now(timezone.utc).isoformat()
    for a in accounts:
        statement = a.get("statement_type") or ""
        line = a.get("ifrs_line") or ""
        note = a.get("notes_line") or ""
        cash_flow_classification = a.get("cash_flow_classification") or ""
        mapped = 1 if statement in ("PL", "BS") and line else 0
        nature = a.get("account_type") or ""
        normal = "Credit" if nature in ("Income", "Liability", "Equity") else "Debit"
        with connection() as (conn, _):
            conn.cursor().execute(
                f"""INSERT INTO fr_account_mappings
                (entity_code,account_code,account_name,statement_type,statement_line,
                 account_nature,normal_balance,classification,is_mapped,updated_at,notes_line,cash_flow_classification)
                VALUES ({','.join([p]*12)})
                ON CONFLICT(entity_code,account_code,account_name) DO UPDATE SET
                statement_type=excluded.statement_type, statement_line=excluded.statement_line,
                account_nature=excluded.account_nature, normal_balance=excluded.normal_balance,
                is_mapped=excluded.is_mapped, updated_at=excluded.updated_at,
                notes_line=excluded.notes_line,
                cash_flow_classification=excluded.cash_flow_classification""",
                (entity_code, a["account_code"], a["account_name"], statement, line,
                 nature, normal, "", mapped, now, note, cash_flow_classification),
            )


def migrate_existing_mappings():
    """Migrate legacy account mappings into COA using newly generated permanent codes."""
    p = _ph()
    existing = rows(
        f"""SELECT m.* FROM fr_account_mappings m
        LEFT JOIN fr_chart_of_accounts c
          ON c.entity_code=m.entity_code AND c.account_code=m.account_code
        WHERE c.account_code IS NULL
        ORDER BY m.entity_code,m.account_code,m.account_name"""
    )
    for m in existing:
        old_code = str(m.get("account_code") or "")
        entity = str(m.get("entity_code") or "")
        name = str(m.get("account_name") or "").strip()
        if not entity or not name:
            continue
        # Do not guess the Account Type when the old mapping did not contain it.
        nature = str(m.get("account_nature") or "").strip()
        account_type = nature if nature in get_account_types(entity) else ""
        new_code = _next_code(entity)
        now = datetime.now(timezone.utc).isoformat()
        with connection() as (conn, _):
            cur = conn.cursor()
            cur.execute(
                f"""INSERT INTO fr_chart_of_accounts
                (coa_id,entity_code,account_code,account_name,account_type,notes_line,
                 ifrs_line,statement_type,created_at,updated_at,is_active)
                VALUES ({','.join([p]*11)})
                ON CONFLICT(entity_code,account_code) DO NOTHING""",
                (str(uuid.uuid4()), entity, new_code, name, account_type,
                 m.get("notes_line"), m.get("statement_line"),
                 m.get("statement_type"), now, now, 1),
            )
            # Re-key existing source TB rows and legacy reporting mappings to the
            # generated COA code so historical reports continue to resolve.
            cur.execute(
                f"UPDATE fr_tb_lines SET account_code={p} WHERE entity_code={p} AND account_code={p} AND account_name={p}",
                (new_code, entity, old_code, name),
            )
            cur.execute(
                f"UPDATE fr_account_mappings SET account_code={p} WHERE entity_code={p} AND account_code={p} AND account_name={p}",
                (new_code, entity, old_code, name),
            )


def match_preview_to_coa(entity_code, preview):
    """Return name-only COA matches for TB preview rows.

    Matching is based exclusively on the complete COA Account Name versus
    the complete TB Name. Code prefixes that form part of either name are
    preserved. Account codes in separate TB columns are never match keys.
    Names are compared case-insensitively with whitespace normalised only.
    Duplicate COA names are treated as ambiguous, never selected arbitrarily.
    """
    accounts = list_accounts(entity_code)
    by_name = {}
    for account in accounts:
        key = " ".join(normalize_account_name(account.get("account_name", "")).casefold().split())
        if key:
            by_name.setdefault(key, []).append(account)

    matched_rows, unmatched, ambiguous = [], [], []
    for row_index, row in preview.iterrows():
        tb_name = str(row.get("account_name") or "").strip()
        key = " ".join(normalize_account_name(tb_name).casefold().split())
        candidates = by_name.get(key, [])
        if len(candidates) == 1:
            account = candidates[0]
            matched_rows.append({
                "row_index": row_index,
                "tb_name": tb_name,
                "coa_account_name": str(account["account_name"]),
                "account_code": str(account["account_code"]),
            })
        elif len(candidates) > 1:
            ambiguous.append({"tb_name": tb_name, "coa_names": [str(x["account_name"]) for x in candidates],
                              "account_codes": [str(x["account_code"]) for x in candidates]})
        else:
            unmatched.append(tb_name)

    return {
        "matched": len(matched_rows),
        "matched_rows": matched_rows,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
    }


def match_trial_balance(entity_code, preview, import_id=None):
    """Attach COA codes using the same name-only matcher used by the preview.

    When import_id is supplied, only rows belonging to that import are updated.
    """
    result = match_preview_to_coa(entity_code, preview)
    p = _ph()
    for match in result["matched_rows"]:
        with connection() as (conn, _):
            if import_id:
                conn.cursor().execute(
                    f"UPDATE fr_tb_lines SET account_code={p} WHERE import_id={p} AND entity_code={p} AND account_name={p}",
                    (match["account_code"], import_id, entity_code, match["tb_name"]),
                )
            else:
                # Legacy compatibility for callers without an import identifier.
                conn.cursor().execute(
                    f"UPDATE fr_tb_lines SET account_code={p} WHERE entity_code={p} AND account_name={p}",
                    (match["account_code"], entity_code, match["tb_name"]),
                )
        sync_legacy_mapping(entity_code, match["account_code"])
    return {key: value for key, value in result.items() if key != "matched_rows"}


def bulk_delete_accounts(entity_code, account_codes):
    """Permanently delete selected COA accounts and their legacy mapping rows.

    Imported trial-balance rows are retained for audit/history, but detached from
    the deleted COA code so they remain available for review and remapping.
    """
    codes = list(dict.fromkeys(str(code).strip() for code in (account_codes or []) if str(code).strip()))
    if not codes:
        return 0
    p = _ph()
    deleted = 0
    with connection() as (conn, _):
        cur = conn.cursor()
        for code in codes:
            # Preserve imported TB history while removing its link to this COA account.
            cur.execute(
                f"UPDATE fr_tb_lines SET account_code=NULL WHERE entity_code={p} AND account_code={p}",
                (entity_code, code),
            )
            # Remove the reporting compatibility mapping for the deleted account.
            cur.execute(
                f"DELETE FROM fr_account_mappings WHERE entity_code={p} AND account_code={p}",
                (entity_code, code),
            )
            cur.execute(
                f"DELETE FROM fr_chart_of_accounts WHERE entity_code={p} AND account_code={p}",
                (entity_code, code),
            )
            deleted += max(int(getattr(cur, "rowcount", 0) or 0), 0)
    return deleted
