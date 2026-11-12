from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd
from database import connection, rows, is_postgres

PL_LINES = [
    "Revenue", "Cost of sales", "Gross profit", "Other income",
    "Selling and distribution expenses", "Administrative expenses",
    "Finance costs", "Share of profit/(loss) of associates", "Income tax expense",
    "Other comprehensive income", "Unmapped / review required",
]
BS_LINES = [
    "Property, plant and equipment", "Right-of-use assets", "Intangible assets",
    "Deferred tax assets", "Other non-current assets", "Inventories",
    "Trade and other receivables", "Current tax assets", "Cash and cash equivalents",
    "Other current assets", "Share capital", "Retained earnings",
    "Other reserves", "Lease liabilities", "Borrowings", "Deferred tax liabilities",
    "Trade and other payables", "Contract liabilities / deferred income",
    "Current tax liabilities", "Other liabilities", "Unmapped / review required",
]

DEFAULT_NOTE_LINES = [
    "Basis of preparation",
    "Material accounting policy information",
    "Revenue",
    "Property, plant and equipment",
    "Right-of-use assets and leases",
    "Intangible assets",
    "Investments and associates",
    "Inventories",
    "Trade and other receivables",
    "Cash and cash equivalents",
    "Share capital",
    "Retained earnings and reserves",
    "Borrowings",
    "Lease liabilities",
    "Trade and other payables",
    "Contract liabilities / deferred income",
    "Current and deferred taxation",
    "Employee benefits",
    "Finance costs",
    "Related-party transactions and balances",
    "Commitments and contingencies",
    "Financial risk management",
    "Events after the reporting period",
    "Going concern",
    "Other disclosures",
]


def init_mapping_catalogues():
    """Create editable master lists and add the notes-line field safely."""
    p = "%s" if is_postgres() else "?"
    with connection() as (conn, _):
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS fr_mapping_line_catalogue (
            catalogue_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL DEFAULT '*',
            line_type TEXT NOT NULL, statement_type TEXT NOT NULL DEFAULT '',
            line_label TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, UNIQUE(entity_code,line_type,statement_type,line_label))""")
        # SQLite and PostgreSQL both support this form. Ignore only the
        # duplicate-column error when an installation has already migrated.
        if is_postgres():
            cur.execute("ALTER TABLE fr_account_mappings ADD COLUMN IF NOT EXISTS notes_line TEXT")
            cur.execute("ALTER TABLE fr_account_mappings ADD COLUMN IF NOT EXISTS cash_flow_classification TEXT")
            cur.execute("ALTER TABLE fr_mapping_line_catalogue ADD COLUMN IF NOT EXISTS parent_ifrs_line TEXT")
            cur.execute("ALTER TABLE fr_mapping_line_catalogue ADD COLUMN IF NOT EXISTS parent_statement_type TEXT")
        else:
            for sql in (
                "ALTER TABLE fr_account_mappings ADD COLUMN notes_line TEXT",
                "ALTER TABLE fr_account_mappings ADD COLUMN cash_flow_classification TEXT",
                "ALTER TABLE fr_mapping_line_catalogue ADD COLUMN parent_ifrs_line TEXT",
                "ALTER TABLE fr_mapping_line_catalogue ADD COLUMN parent_statement_type TEXT",
            ):
                try:
                    cur.execute(sql)
                except Exception as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise
        # Notes lines are standalone catalogue records. Earlier versions stored
        # IFRS/statement parents on Notes rows; consolidate duplicate legacy rows
        # by label while retaining one active record per Notes line.
        # Include inactive rows in the scan: the catalogue's UNIQUE constraint
        # applies to inactive records too. A previous migration could therefore
        # collide with an inactive standalone Notes row when changing PL/BS rows
        # to statement_type=''. Reuse that existing blank-statement row instead.
        cur.execute(
            "SELECT catalogue_id,line_label,statement_type,is_active FROM fr_mapping_line_catalogue "
            "WHERE entity_code='*' AND line_type='NOTES' ORDER BY line_label,statement_type"
        )
        note_records = cur.fetchall()
        grouped = {}
        for record in note_records:
            try:
                rec = dict(record)
            except Exception:
                rec = dict(zip(["catalogue_id", "line_label", "statement_type", "is_active"], record))
            grouped.setdefault(str(rec["line_label"]), []).append(rec)
        for label, records in grouped.items():
            canonical = next(
                (x for x in records if not str(x.get("statement_type") or "").strip()),
                records[0],
            )
            # Deactivate the other rows first. If a blank-statement row already
            # exists (even inactive), it is the canonical row and is reactivated.
            for duplicate in records:
                if duplicate["catalogue_id"] != canonical["catalogue_id"]:
                    cur.execute(
                        "UPDATE fr_mapping_line_catalogue SET is_active=0 WHERE catalogue_id=" + p,
                        (duplicate["catalogue_id"],),
                    )
            cur.execute(
                "UPDATE fr_mapping_line_catalogue SET statement_type='',parent_ifrs_line=NULL,"
                "parent_statement_type=NULL,is_active=1 WHERE catalogue_id=" + p,
                (canonical["catalogue_id"],),
            )


def _entity(entity_code):
    value = str(entity_code or "").strip()
    if not value:
        raise ValueError("A reporting entity is required for catalogue operations.")
    return value


def get_account_type_catalogue(entity_code):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    return rows(
        f"SELECT line_label FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND is_active=1 ORDER BY line_label",
        (entity_code, "ACCOUNT_TYPE"),
    )


def add_account_type(label, entity_code):
    entity_code = _entity(entity_code)
    label = str(label or "").strip()
    if not label:
        raise ValueError("Enter an Account Type.")
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    with connection() as (conn, _):
        conn.cursor().execute(
            f"INSERT INTO fr_mapping_line_catalogue "
            f"(catalogue_id,entity_code,line_type,statement_type,line_label,parent_ifrs_line,parent_statement_type,is_active,created_at) "
            f"VALUES ({','.join([p]*9)}) "
            f"ON CONFLICT(entity_code,line_type,statement_type,line_label) DO UPDATE SET is_active=1",
            (str(__import__("uuid").uuid4()), entity_code, "ACCOUNT_TYPE", "", label, None, None, 1, now),
        )


def update_account_type_catalogue(edited_df, entity_code):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    added = updated = 0
    with connection() as (conn, _):
        cur = conn.cursor()
        for _, record in edited_df.iterrows():
            old = str(record.get("Original Account Type") or "").strip()
            new = str(record.get("Account Type") or "").strip()
            if bool(record.get("Delete")):
                continue
            if not new:
                raise ValueError("Account Type cannot be blank.")
            if old and old != new:
                cur.execute(
                    f"UPDATE fr_mapping_line_catalogue SET line_label={p} WHERE entity_code={p} AND line_type='ACCOUNT_TYPE' AND statement_type='' AND line_label={p}",
                    (new, entity_code, old),
                )
                if not cur.rowcount:
                    raise ValueError(f"Could not find Account Type '{old}' for this entity.")
                cur.execute(
                    f"UPDATE fr_chart_of_accounts SET account_type={p} WHERE entity_code={p} AND account_type={p}",
                    (new, entity_code, old),
                )
                cur.execute(
                    f"UPDATE fr_account_mappings SET account_nature={p} WHERE entity_code={p} AND account_nature={p}",
                    (new, entity_code, old),
                )
                updated += 1
            elif not old:
                add_account_type(new, entity_code)
                added += 1
    return {"added": added, "updated": updated}


def bulk_deactivate_account_types(labels, entity_code):
    entity_code = _entity(entity_code)
    labels = list(dict.fromkeys(str(x).strip() for x in (labels or []) if str(x).strip()))
    if not labels:
        return 0
    p = "%s" if is_postgres() else "?"
    with connection() as (conn, _):
        cur = conn.cursor()
        for label in labels:
            used = rows(
                f"SELECT COUNT(*) AS n FROM fr_chart_of_accounts WHERE entity_code={p} AND account_type={p}",
                (entity_code, label),
            )
            if used and int(used[0].get("n") or 0) > 0:
                raise ValueError(f"Cannot remove '{label}' because it is assigned to this entity's Chart of Accounts.")
            cur.execute(
                f"UPDATE fr_mapping_line_catalogue SET is_active=0 WHERE entity_code={p} AND line_type='ACCOUNT_TYPE' AND line_label={p}",
                (entity_code, label),
            )
    return len(labels)


def get_catalogue(line_type, statement_type=None, entity_code=None):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    if line_type == "IFRS":
        return [r["line_label"] for r in rows(
            f"SELECT line_label FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND is_active=1 ORDER BY line_label",
            (entity_code, line_type))]
    return [r["line_label"] for r in rows(
        f"SELECT line_label FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND is_active=1 ORDER BY line_label",
        (entity_code, line_type))]


def get_notes_catalogue(entity_code):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    return rows(
        f"SELECT line_label FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type='NOTES' AND is_active=1 ORDER BY line_label",
        (entity_code,),
    )


def get_note_parent(note_label, entity_code):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    found = rows(
        f"SELECT COALESCE(parent_statement_type, statement_type) AS statement_type, parent_ifrs_line FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type='NOTES' AND line_label={p} AND is_active=1",
        (entity_code, note_label),
    )
    return found[0] if found else None


def update_note_parent(note_label, statement_type, parent_ifrs_line, entity_code):
    entity_code = _entity(entity_code)
    if statement_type not in ("PL", "BS"):
        raise ValueError("Choose the statement for this Notes line.")
    if parent_ifrs_line not in get_catalogue("IFRS", statement_type, entity_code):
        raise ValueError("Choose an active IFRS presentation line for the selected statement.")
    p = "%s" if is_postgres() else "?"
    with connection() as (conn, _):
        conn.cursor().execute(
            f"UPDATE fr_mapping_line_catalogue SET parent_statement_type={p}, parent_ifrs_line={p} WHERE entity_code={p} AND line_type='NOTES' AND line_label={p}",
            (statement_type, parent_ifrs_line, entity_code, note_label),
        )


def add_catalogue_line(line_type, label, statement_type=None, parent_ifrs_line=None, entity_code=None):
    entity_code = _entity(entity_code)
    label = str(label or "").strip()
    if not label:
        raise ValueError("Enter a line description.")
    if line_type not in ("IFRS", "NOTES"):
        raise ValueError("Invalid catalogue type.")
    statement_type = "" if line_type in ("IFRS", "NOTES") else (statement_type or "")
    parent_ifrs_line = None
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    with connection() as (conn, _):
        conn.cursor().execute(
            f"INSERT INTO fr_mapping_line_catalogue (catalogue_id,entity_code,line_type,statement_type,line_label,parent_ifrs_line,parent_statement_type,is_active,created_at) VALUES ({','.join([p]*9)}) ON CONFLICT (entity_code,line_type,statement_type,line_label) DO UPDATE SET is_active=1",
            (str(__import__('uuid').uuid4()), entity_code, line_type, statement_type, label, None, None, 1, now),
        )


def deactivate_catalogue_line(line_type, label, statement_type=None, entity_code=None):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    with connection() as (conn, _):
        conn.cursor().execute(
            f"UPDATE fr_mapping_line_catalogue SET is_active=0 WHERE entity_code={p} AND line_type={p} AND line_label={p}",
            (entity_code, line_type, label),
        )


def bulk_deactivate_catalogue_lines(line_type, labels, statement_type=None, entity_code=None):
    entity_code = _entity(entity_code)
    labels = list(dict.fromkeys(str(x).strip() for x in (labels or []) if str(x).strip()))
    if not labels:
        return 0
    p = "%s" if is_postgres() else "?"
    with connection() as (conn, _):
        cur = conn.cursor()
        for label in labels:
            cur.execute(
                f"UPDATE fr_mapping_line_catalogue SET is_active=0 WHERE entity_code={p} AND line_type={p} AND line_label={p}",
                (entity_code, line_type, label),
            )
    return len(labels)


def get_all_ifrs_catalogue(entity_code):
    entity_code = _entity(entity_code)
    p = "%s" if is_postgres() else "?"
    return rows(
        f"SELECT MIN(line_label) AS line_label FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type='IFRS' AND is_active=1 GROUP BY LOWER(line_label) ORDER BY MIN(line_label)",
        (entity_code,),
    )


def _clean_catalogue_cell(value):
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return "" if value.casefold() in {"nan", "none", "<na>", "nat"} else value


def update_ifrs_catalogue_rows(edited_df, entity_code):
    entity_code = _entity(entity_code)
    existing = {str(x["line_label"]).casefold(): str(x["line_label"]) for x in get_all_ifrs_catalogue(entity_code)}
    prepared, seen = [], set()
    for _, row in edited_df.iterrows():
        old_name = _clean_catalogue_cell(row.get("Original line", ""))
        new_name = _clean_catalogue_cell(row.get("IFRS presentation line", ""))
        if not new_name:
            continue
        key = new_name.casefold()
        if key in seen:
            raise ValueError(f"Duplicate IFRS presentation line '{new_name}'.")
        seen.add(key)
        if key in existing and key != old_name.casefold():
            raise ValueError(f"IFRS presentation line '{new_name}' already exists.")
        prepared.append((old_name, new_name))
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    inserted = updated = 0
    with connection() as (conn, _):
        cur = conn.cursor()
        for old_name, new_name in prepared:
            if not old_name:
                cur.execute(
                    f"INSERT INTO fr_mapping_line_catalogue (catalogue_id,entity_code,line_type,statement_type,line_label,parent_ifrs_line,parent_statement_type,is_active,created_at) VALUES ({','.join([p]*9)}) ON CONFLICT (entity_code,line_type,statement_type,line_label) DO UPDATE SET is_active=1",
                    (str(__import__("uuid").uuid4()), entity_code, "IFRS", "", new_name, None, None, 1, now),
                )
                inserted += 1
            elif old_name != new_name:
                cur.execute(
                    f"UPDATE fr_mapping_line_catalogue SET line_label={p} WHERE entity_code={p} AND line_type='IFRS' AND line_label={p} AND is_active=1",
                    (new_name, entity_code, old_name),
                )
                if not cur.rowcount:
                    raise ValueError(f"Could not find original IFRS line '{old_name}' for this entity.")
                cur.execute(
                    f"UPDATE fr_mapping_line_catalogue SET parent_ifrs_line={p} WHERE entity_code={p} AND line_type='NOTES' AND parent_ifrs_line={p}",
                    (new_name, entity_code, old_name),
                )
                updated += 1
    return {"added": inserted, "updated": updated, "processed": len(prepared)}


def update_ifrs_catalogue(statement_type, edited_df, entity_code):
    entity_code = _entity(entity_code)
    if statement_type not in ("PL", "BS"):
        raise ValueError("Invalid statement type.")
    existing_names = {x.casefold() for x in get_catalogue("IFRS", statement_type, entity_code)}
    seen, prepared = set(), []
    for _, row in edited_df.iterrows():
        new = str(row.get("IFRS presentation line") or "").strip()
        old = str(row.get("Original line") or "").strip()
        if not new:
            continue
        if new.casefold() in seen:
            raise ValueError(f"Duplicate IFRS presentation line: {new}")
        seen.add(new.casefold())
        prepared.append((old, new))
    for old, new in prepared:
        if new.casefold() in existing_names and new.casefold() != old.casefold():
            raise ValueError(f"An IFRS presentation line named '{new}' already exists.")
    for old, new in prepared:
        if not old:
            add_catalogue_line("IFRS", new, statement_type, entity_code=entity_code)
        elif old != new:
            p = "%s" if is_postgres() else "?"
            with connection() as (conn, _):
                conn.cursor().execute(
                    f"UPDATE fr_mapping_line_catalogue SET line_label={p} WHERE entity_code={p} AND line_type='IFRS' AND statement_type={p} AND line_label={p}",
                    (new, entity_code, statement_type, old),
                )


def update_notes_catalogue(edited_df, entity_code):
    entity_code = _entity(entity_code)
    existing = {str(x["line_label"]).casefold(): str(x["line_label"]) for x in get_notes_catalogue(entity_code)}
    prepared, seen = [], set()
    for _, row in edited_df.iterrows():
        old = _clean_catalogue_cell(row.get("Original Notes Line", row.get("Original Notes line", "")))
        new = _clean_catalogue_cell(row.get("Notes Line", row.get("Notes line", "")))
        if not new:
            continue
        if new.casefold() in seen:
            raise ValueError(f"Duplicate Notes line: {new}")
        seen.add(new.casefold())
        if new.casefold() in existing and new.casefold() != old.casefold():
            raise ValueError(f"A Notes line named '{new}' already exists.")
        prepared.append((old, new))
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    added = updated = 0
    with connection() as (conn, _):
        cur = conn.cursor()
        for old, new in prepared:
            if not old:
                cur.execute(
                    f"INSERT INTO fr_mapping_line_catalogue (catalogue_id,entity_code,line_type,statement_type,line_label,parent_ifrs_line,parent_statement_type,is_active,created_at) VALUES ({','.join([p]*9)}) ON CONFLICT(entity_code,line_type,statement_type,line_label) DO UPDATE SET is_active=1",
                    (str(__import__("uuid").uuid4()), entity_code, "NOTES", "", new, None, None, 1, now),
                )
                added += 1
            elif old != new:
                cur.execute(
                    f"UPDATE fr_mapping_line_catalogue SET line_label={p} WHERE entity_code={p} AND line_type='NOTES' AND line_label={p}",
                    (new, entity_code, old),
                )
                if not cur.rowcount:
                    raise ValueError(f"Could not find Notes line '{old}' for this entity.")
                updated += 1
    return {"added": added, "updated": updated, "processed": len(prepared)}


def get_mapping(entity, code, name):
    ph = "%s" if is_postgres() else "?"
    result = rows("SELECT * FROM fr_account_mappings WHERE entity_code="+ph+" AND account_code="+ph+" AND account_name="+ph, (entity,code,name))
    return result[0] if result else None


def save_mapping(entity, code, name, statement_type, statement_line, nature, normal, classification, notes_line="", cash_flow_classification=""):
    """Persist an account mapping without deleting the existing primary-key row."""
    ph = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    with connection() as (conn, _):
        cur = conn.cursor()
        cur.execute(
            "UPDATE fr_account_mappings SET statement_type="+ph+", statement_line="+ph+", notes_line="+ph+", cash_flow_classification="+ph+", account_nature="+ph+", normal_balance="+ph+", classification="+ph+", is_mapped=1, updated_at="+ph+
            " WHERE entity_code="+ph+" AND account_code="+ph+" AND account_name="+ph,
            (statement_type, statement_line, notes_line, cash_flow_classification, nature, normal, classification, now, entity, code, name),
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO fr_account_mappings (entity_code,account_code,account_name,statement_type,statement_line,notes_line,cash_flow_classification,account_nature,normal_balance,classification,is_mapped,updated_at) VALUES ("+",".join([ph]*12)+")",
                (entity, code, name, statement_type, statement_line, notes_line, cash_flow_classification, nature, normal, classification, 1, now),
            )


def clear_mapping(entity, code, name):
    """Clear mapping attributes for an account while retaining its mapping row."""
    ph = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    with connection() as (conn, _):
        cur = conn.cursor()
        cur.execute(
            "UPDATE fr_account_mappings SET statement_type="+ph+", statement_line="+ph+
            ", notes_line="+ph+", account_nature="+ph+", normal_balance="+ph+
            ", classification="+ph+", is_mapped=0, updated_at="+ph+
            " WHERE entity_code="+ph+" AND account_code="+ph+" AND account_name="+ph,
            ("", "", "", "", "", "", now, entity, code, name),
        )


def mapped_lines(import_id, entity):
    ph = "%s" if is_postgres() else "?"
    sql = """SELECT l.*,m.statement_type,m.statement_line,m.notes_line,m.cash_flow_classification,m.account_nature,m.normal_balance,m.classification,
        COALESCE(m.is_mapped,0) AS is_mapped
        FROM fr_tb_lines l LEFT JOIN fr_account_mappings m
        ON m.entity_code=l.entity_code AND m.account_code=l.account_code AND m.account_name=l.account_name
        WHERE l.import_id=""" + ph + " ORDER BY l.account_code,l.account_name"
    return rows(sql,(import_id,))


def get_mapping_summary(entity):
    ph = "%s" if is_postgres() else "?"
    return rows("SELECT * FROM fr_account_mappings WHERE entity_code="+ph+" ORDER BY account_code",(entity,))


def statement_data(import_ids, entity):
    if not import_ids: return pd.DataFrame()
    ph = "%s" if is_postgres() else "?"
    placeholders = ",".join([ph]*len(import_ids))
    sql = f"""SELECT l.*,m.statement_type,m.statement_line,m.notes_line,m.cash_flow_classification,m.account_nature,m.normal_balance,m.classification
        FROM fr_tb_lines l LEFT JOIN fr_account_mappings m
        ON m.entity_code=l.entity_code AND m.account_code=l.account_code AND m.account_name=l.account_name
        WHERE l.import_id IN ({placeholders}) AND l.entity_code={ph}"""
    return pd.DataFrame(rows(sql, tuple(import_ids)+(entity,)))


def _catalogue_upload_columns(upload_df):
    """Build a forgiving header lookup for Excel/CSV catalogue imports."""
    def normalise(value):
        return " ".join(str(value).replace("\ufeff", "").strip().casefold().split())
    return {normalise(column): column for column in upload_df.columns}


def import_ifrs_catalogue_rows(upload_df, entity_code):
    """Import standalone IFRS presentation line labels for one entity."""
    entity_code = _entity(entity_code)
    if upload_df is None or upload_df.empty:
        raise ValueError("The uploaded file contains no data rows.")
    columns = _catalogue_upload_columns(upload_df)
    line_col = next((columns[k] for k in ("ifrs presentation line", "ifrs line", "presentation line", "line") if k in columns), None)
    if line_col is None:
        raise ValueError("IFRS upload must contain an 'IFRS Line' column.")
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    added = reactivated = unchanged = 0
    rejected, seen = [], set()
    with connection() as (conn, _):
        cur = conn.cursor()
        for excel_row, (_, record) in enumerate(upload_df.iterrows(), start=2):
            label = _clean_catalogue_cell(record.get(line_col))
            if not label:
                continue
            if label.casefold() in seen:
                rejected.append({"Row": excel_row, "Line": label, "Reason": "Duplicate line in upload; first occurrence used."})
                continue
            seen.add(label.casefold())
            cur.execute(
                f"SELECT catalogue_id,is_active FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type='IFRS' AND LOWER(line_label)=LOWER({p}) ORDER BY is_active DESC",
                (entity_code, label),
            )
            found = cur.fetchone()
            if found:
                cid = found["catalogue_id"] if hasattr(found, "keys") else found[0]
                active = found["is_active"] if hasattr(found, "keys") else found[1]
                if int(active or 0):
                    unchanged += 1
                else:
                    cur.execute(f"UPDATE fr_mapping_line_catalogue SET is_active=1,statement_type='' WHERE catalogue_id={p}", (cid,))
                    reactivated += 1
            else:
                cur.execute(
                    f"""INSERT INTO fr_mapping_line_catalogue
                    (catalogue_id,entity_code,line_type,statement_type,line_label,parent_ifrs_line,parent_statement_type,is_active,created_at)
                    VALUES ({','.join([p]*9)})""",
                    (str(__import__('uuid').uuid4()), entity_code, 'IFRS', '', label, None, None, 1, now),
                )
                added += 1
    if not seen and not rejected:
        raise ValueError("No non-empty IFRS presentation lines were found in the uploaded file.")
    return {"added": added, "reactivated": reactivated, "unchanged": unchanged, "rejected": rejected, "processed": len(seen)}


def import_notes_catalogue_rows(upload_df, entity_code):
    entity_code = _entity(entity_code)
    """Import standalone Notes lines. Only a Notes Line column is required."""
    columns = _catalogue_upload_columns(upload_df)
    note_col = next((columns[k] for k in ("notes line", "notes", "note line", "line label", "description") if k in columns), None)
    if note_col is None:
        return {"added": 0, "reactivated": 0, "unchanged": 0,
                "rejected": [{"Row": 1, "Notes line": "", "Reason": "Required column: Notes Line."}]}
    p = "%s" if is_postgres() else "?"
    now = datetime.now(timezone.utc).isoformat()
    added = reactivated = unchanged = 0
    rejected = []
    for idx, record in upload_df.iterrows():
        label = _clean_catalogue_cell(record.get(note_col))
        if not label:
            continue
        found = rows(
            f"SELECT catalogue_id,is_active FROM fr_mapping_line_catalogue WHERE entity_code={p} AND line_type={p} AND statement_type={p} AND line_label={p}",
            (entity_code, "NOTES", "", label),
        )
        if found:
            if not int(found[0].get("is_active") or 0):
                with connection() as (conn, _):
                    conn.cursor().execute(
                        f"UPDATE fr_mapping_line_catalogue SET is_active=1 WHERE catalogue_id={p}",
                        (found[0]["catalogue_id"],),
                    )
                reactivated += 1
            else:
                unchanged += 1
        else:
            with connection() as (conn, _):
                conn.cursor().execute(
                    f"""INSERT INTO fr_mapping_line_catalogue
                    (catalogue_id,entity_code,line_type,statement_type,line_label,
                     parent_ifrs_line,parent_statement_type,is_active,created_at)
                    VALUES ({','.join([p]*9)})""",
                    (str(__import__("uuid").uuid4()), entity_code, "NOTES", "", label, None, None, 1, now),
                )
            added += 1
    return {"added": added, "reactivated": reactivated, "unchanged": unchanged,
            "updated": 0, "rejected": rejected}
