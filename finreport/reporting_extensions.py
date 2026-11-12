"""Supplementary schedules for the Kulana Financial Reporting application.

Stores user-entered supporting information separately from imported TB source data.
"""
from __future__ import annotations
from datetime import datetime, timezone
import uuid
import pandas as pd
import database as DB


def init_schema():
    statements = [
        """CREATE TABLE IF NOT EXISTS fr_reporting_inputs (
            input_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            fiscal_month INTEGER NOT NULL, input_type TEXT NOT NULL, input_code TEXT NOT NULL,
            description TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            narrative TEXT, status TEXT NOT NULL DEFAULT 'Draft', updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS fr_note_disclosures (
            note_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            fiscal_month INTEGER NOT NULL, note_code TEXT NOT NULL, note_title TEXT NOT NULL,
            narrative TEXT, manual_amount DOUBLE PRECISION, status TEXT NOT NULL DEFAULT 'Draft',
            updated_at TEXT NOT NULL)""",
    ]
    with DB.connection() as (conn, _):
        cur = conn.cursor()
        for sql in statements:
            cur.execute(sql)
        # Backwards-compatible migration for existing SQLite and PostgreSQL databases.
        if DB.is_postgres():
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_name='fr_reporting_inputs' AND column_name='status'""")
            has_status = cur.fetchone() is not None
        else:
            cur.execute("PRAGMA table_info(fr_reporting_inputs)")
            has_status = any(str(row[1]).lower() == "status" for row in cur.fetchall())
        if not has_status:
            cur.execute("ALTER TABLE fr_reporting_inputs ADD COLUMN status TEXT NOT NULL DEFAULT 'Draft'")


def _ph():
    return "%s" if DB.is_postgres() else "?"


def get_inputs(entity, year, month, input_type):
    p = _ph()
    return DB.rows(
        f"SELECT * FROM fr_reporting_inputs WHERE entity_code={p} AND fiscal_year={p} AND fiscal_month={p} AND input_type={p} ORDER BY description",
        (entity, int(year), int(month), input_type),
    )



def get_latest_inputs(entity, year, month, input_type):
    """Return the latest saved input set on or before the requested reporting period."""
    p = _ph()
    rows = DB.rows(
        f"SELECT * FROM fr_reporting_inputs WHERE entity_code={p} AND input_type={p} "
        f"AND (fiscal_year < {p} OR (fiscal_year = {p} AND fiscal_month <= {p})) "
        "ORDER BY fiscal_year DESC, fiscal_month DESC, description",
        (entity, input_type, int(year), int(year), int(month)),
    )
    if not rows:
        return []
    latest_year = int(rows[0]["fiscal_year"])
    latest_month = int(rows[0]["fiscal_month"])
    return [x for x in rows if int(x["fiscal_year"]) == latest_year and int(x["fiscal_month"]) == latest_month]


def get_latest_notes(entity, year, month):
    """Return the latest saved note disclosures on or before the reporting period."""
    p = _ph()
    rows = DB.rows(
        f"SELECT * FROM fr_note_disclosures WHERE entity_code={p} "
        f"AND (fiscal_year < {p} OR (fiscal_year = {p} AND fiscal_month <= {p})) "
        "ORDER BY fiscal_year DESC, fiscal_month DESC, note_code",
        (entity, int(year), int(year), int(month)),
    )
    if not rows:
        return []
    # Select the latest record per note code, allowing notes updated at different times.
    latest = {}
    for item in rows:
        code = str(item.get("note_code") or "").upper()
        if code and code not in latest:
            latest[code] = item
    return [latest[k] for k in sorted(latest)]

def save_inputs(entity, year, month, input_type, records):
    p = _ph()
    now = datetime.now(timezone.utc).isoformat()
    with DB.connection() as (conn, _):
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM fr_reporting_inputs WHERE entity_code={p} AND fiscal_year={p} AND fiscal_month={p} AND input_type={p}",
            (entity, int(year), int(month), input_type),
        )
        for row in records:
            code = str(row.get("Code") or "").strip()
            description = str(row.get("Description") or "").strip()
            if not code or not description:
                continue
            amount = float(row.get("Amount") or 0)
            narrative = str(row.get("Commentary") or "")
            status = str(row.get("Status") or "Draft").strip() or "Draft"
            cur.execute(
                "INSERT INTO fr_reporting_inputs (input_id,entity_code,fiscal_year,fiscal_month,input_type,input_code,description,amount,narrative,status,updated_at) VALUES (" + ",".join([p]*11) + ")",
                (str(uuid.uuid4()), entity, int(year), int(month), input_type, code, description, amount, narrative, status, now),
            )


def get_notes(entity, year, month):
    p = _ph()
    return DB.rows(
        f"SELECT * FROM fr_note_disclosures WHERE entity_code={p} AND fiscal_year={p} AND fiscal_month={p} ORDER BY note_code",
        (entity, int(year), int(month)),
    )


def save_notes(entity, year, month, records):
    p = _ph()
    now = datetime.now(timezone.utc).isoformat()
    with DB.connection() as (conn, _):
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM fr_note_disclosures WHERE entity_code={p} AND fiscal_year={p} AND fiscal_month={p}",
            (entity, int(year), int(month)),
        )
        for row in records:
            code = str(row.get("Note code") or "").strip()
            title = str(row.get("Note title") or "").strip()
            if not code or not title:
                continue
            raw_amount = row.get("Manual amount")
            amount = None if pd.isna(raw_amount) or str(raw_amount).strip() == "" else float(raw_amount)
            cur.execute(
                "INSERT INTO fr_note_disclosures (note_id,entity_code,fiscal_year,fiscal_month,note_code,note_title,narrative,manual_amount,status,updated_at) VALUES (" + ",".join([p]*10) + ")",
                (str(uuid.uuid4()), entity, int(year), int(month), code, title,
                 str(row.get("Narrative") or ""), amount, str(row.get("Status") or "Draft"), now),
            )


def period_frame(import_record, entity):
    if not import_record:
        return pd.DataFrame()
    import account_mapping as AM
    return AM.statement_data([import_record["import_id"]], entity)


def balance_by_line(frame):
    if frame is None or frame.empty:
        return {}
    data = frame[(frame.statement_type == "BS") & frame.statement_line.notna()].copy()
    if data.empty:
        return {}
    data["amount"] = data.apply(
        lambda r: -float(r.balance or 0) if r.get("normal_balance") == "Credit" else float(r.balance or 0),
        axis=1,
    )
    return data.groupby("statement_line").amount.sum().to_dict()



def equity_balance_by_note(frame):
    """Return equity balances grouped by the COA Notes Line.

    Equity is identified by the account mapping's classification field;
    Notes Line identifies the individual equity components used in the SOCE.
    """
    if frame is None or frame.empty:
        return {}
    required = {"statement_type", "classification", "notes_line", "balance"}
    if not required.issubset(frame.columns):
        return {}

    statement = frame["statement_type"].fillna("").astype(str).str.strip().str.casefold()
    classification = frame["classification"].fillna("").astype(str).str.strip().str.casefold()
    notes = frame["notes_line"].fillna("").astype(str).str.strip()
    data = frame[(statement == "bs") & (classification == "equity") & (notes != "")].copy()
    if data.empty:
        return {}

    data["notes_line"] = data["notes_line"].fillna("").astype(str).str.strip()
    data["notes_line_key"] = data["notes_line"].str.casefold()
    data["amount"] = data.apply(
        lambda r: -float(r.get("balance") or 0)
        if str(r.get("normal_balance") or "").strip().casefold() == "credit"
        else float(r.get("balance") or 0),
        axis=1,
    )
    # Case-insensitive keys make COA note labels resilient to capitalization differences.
    return data.groupby("notes_line_key")["amount"].sum().to_dict()


def cash_flow_classification_schedule(current_frame, prior_frame=None):
    """Build account-level cash-flow schedules from COA cash-flow classifications.

    Balance-sheet movements are net movements, not proof of gross cash transactions.
    They must be reviewed for depreciation, disposals, non-cash additions, FX and reclasses.
    """
    categories = {
        "Operating – Working Capital Asset",
        "Operating – Working Capital Liability",
        "Operating – Non-cash Adjustment",
        "Investing Activity",
        "Financing Activity",
        "Cash and Cash Equivalents",
        "Excluded / Non-cash",
    }
    if current_frame is None or current_frame.empty:
        return {"rows": [], "working_capital": [], "noncash": [], "investing": [], "financing": [],
                "cash_open": None, "cash_close": None, "prior_available": False, "unmapped": []}

    def normalized(frame):
        if frame is None or frame.empty:
            return {}
        df = frame.copy()
        for col in ("cash_flow_classification", "statement_type", "normal_balance", "account_nature", "account_code", "account_name", "notes_line", "balance"):
            if col not in df.columns:
                df[col] = None
        df["cash_flow_classification"] = df["cash_flow_classification"].fillna("").astype(str).str.strip()
        df["statement_type"] = df["statement_type"].fillna("").astype(str).str.upper().str.strip()
        df["normal_balance"] = df["normal_balance"].fillna("").astype(str).str.casefold().str.strip()
        df["account_nature"] = df["account_nature"].fillna("").astype(str).str.casefold().str.strip()
        df["notes_line"] = df["notes_line"].fillna("").astype(str).str.strip()
        df.loc[df["notes_line"] == "", "notes_line"] = "Notes line not assigned"
        df["balance"] = pd.to_numeric(df["balance"], errors="coerce").fillna(0.0)
        df["signed_balance"] = df.apply(lambda r: -float(r["balance"]) if r["normal_balance"] == "credit" else float(r["balance"]), axis=1)
        return df

    cur = normalized(current_frame)
    prev = normalized(prior_frame)
    prior_available = prior_frame is not None and not prior_frame.empty
    keys = ["account_code", "account_name", "notes_line", "cash_flow_classification", "statement_type", "account_nature"]
    current_groups = cur.groupby(keys, dropna=False)["signed_balance"].sum().to_dict()
    prior_groups = prev.groupby(keys, dropna=False)["signed_balance"].sum().to_dict() if prior_available else {}
    account_keys = sorted(set(current_groups) | set(prior_groups), key=lambda x: tuple(str(v) for v in x))
    rows_out, wc, noncash, investing, financing = [], [], [], [], []
    for key in account_keys:
        code, name, notes_line, category, statement, nature = key
        category = str(category or "").strip()
        nature = str(nature or "").casefold().strip()
        opening = float(prior_groups.get(key, 0.0)) if prior_available else None
        closing = float(current_groups.get(key, 0.0))
        movement = closing - opening if prior_available else None
        cashflow = None
        section = ""
        if category == "Operating – Working Capital Asset" and statement == "BS":
            section = "Operating working capital"
            cashflow = -movement if movement is not None else None
        elif category == "Operating – Working Capital Liability" and statement == "BS":
            section = "Operating working capital"
            # Credit-normal liabilities are converted to positive balances above;
            # an increase in the liability is therefore a cash inflow.
            cashflow = movement if movement is not None else None
        elif category == "Operating – Non-cash Adjustment" and statement == "PL":
            section = "Operating non-cash adjustments"
            cashflow = closing
        elif category == "Investing Activity" and statement == "BS":
            section = "Investing activities"
            cashflow = -movement if movement is not None else None
        elif category == "Financing Activity" and statement == "BS":
            section = "Financing activities"
            cashflow = (movement if nature in ("liability", "equity") else -movement) if movement is not None else None
        elif category == "Cash and Cash Equivalents" and statement == "BS":
            section = "Cash and cash equivalents"
        elif category == "Excluded / Non-cash":
            section = "Excluded / non-cash"
        else:
            section = "Unclassified"
        rec = {"Section": section, "Account Code": str(code or ""), "Account Name": str(name or ""),
               "Notes Line": str(notes_line or "Notes line not assigned"), "Account Nature": str(nature or ""), "Cash Flow Classification": category, "Opening Balance": opening,
               "Closing Balance": closing, "Movement": movement, "Cash Flow": cashflow}
        rows_out.append(rec)
        if section == "Operating working capital" and cashflow is not None:
            wc.append(rec)
        elif section == "Operating non-cash adjustments":
            noncash.append(rec)
        elif section == "Investing activities" and cashflow is not None:
            investing.append(rec)
        elif section == "Financing activities" and cashflow is not None:
            financing.append(rec)

    cash_rows = cur[(cur["cash_flow_classification"] == "Cash and Cash Equivalents") & (cur["statement_type"] == "BS")]
    cash_close = float(cash_rows["signed_balance"].sum()) if not cash_rows.empty else None
    if prior_available:
        prior_cash_rows = prev[(prev["cash_flow_classification"] == "Cash and Cash Equivalents") & (prev["statement_type"] == "BS")]
        cash_open = float(prior_cash_rows["signed_balance"].sum()) if not prior_cash_rows.empty else None
    else:
        cash_open = None
    unmapped = cur[cur["cash_flow_classification"].isin([""])][["account_code", "account_name", "statement_type"]].drop_duplicates().to_dict("records")
    return {"rows": rows_out, "working_capital": wc, "noncash": noncash, "investing": investing,
            "financing": financing, "cash_open": cash_open, "cash_close": cash_close,
            "prior_available": prior_available, "unmapped": unmapped}


def profit_and_loss(frame):
    if frame is None or frame.empty:
        return {}
    data = frame[(frame.statement_type == "PL") & frame.statement_line.notna()].copy()
    if data.empty:
        return {}
    raw = data.groupby("statement_line").balance.sum().to_dict()
    revenue = -float(raw.get("Revenue", 0))
    cost = float(raw.get("Cost of sales", 0))
    other_income = -float(raw.get("Other income", 0))
    selling = float(raw.get("Selling and distribution expenses", 0))
    admin = float(raw.get("Administrative expenses", 0))
    finance = float(raw.get("Finance costs", 0))
    associate = -float(raw.get("Share of profit/(loss) of associates", 0))
    tax = float(raw.get("Income tax expense", 0))
    gross = revenue - cost
    pbt = gross + other_income - selling - admin - finance + associate
    profit = pbt - tax
    return {"Revenue": revenue, "Cost of sales": cost, "Gross profit": gross,
            "Other income": other_income, "Selling and distribution expenses": selling,
            "Administrative expenses": admin, "Finance costs": finance,
            "Share of profit/(loss) of associates": associate,
            "Income tax expense": tax, "Profit before tax": pbt,
            "Profit for the period": profit}
