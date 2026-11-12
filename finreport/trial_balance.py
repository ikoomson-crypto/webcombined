from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone

import pandas as pd

from database import connection, rows


ALIASES = {
    "account_name": ["name", "account name", "account", "description", "account description"],
    "account_code": ["code", "account code", "account number", "nominal code", "source code"],
    "category": ["category", "account category", "group", "account group"],
    "source": ["source", "account type", "type"],
    "debit": ["debit", "debit balance", "dr"],
    "credit": ["credit", "credit balance", "cr"],
}


def _norm(value):
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _find_header(columns):
    lookup = {_norm(c): c for c in columns}
    found = {}
    for key, aliases in ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                found[key] = lookup[alias]
                break
    if not all(key in found for key in ("account_name", "debit", "credit")):
        return None
    return found


def _read_csv_report(raw: bytes) -> pd.DataFrame:
    """Read ordinary CSVs and report-style CSVs with title/section rows."""
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Excel may prepend a delimiter directive such as: sep=,
    delimiter = None
    if lines and lines[0].strip().lower().startswith("sep="):
        directive = lines.pop(0).strip()
        delimiter = directive[4:] or ","

    if delimiter is None:
        sample = "\\n".join(lines[:30])
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\\t|").delimiter
        except csv.Error:
            delimiter = ","

    parsed = list(csv.reader(lines, delimiter=delimiter))
    header_index = None
    found = None
    for i, row in enumerate(parsed):
        candidate = _find_header(row)
        if candidate:
            header_index, found = i, candidate
            break

    if header_index is None:
        raise ValueError(
            "Could not locate the trial balance column headings. "
            "Expected columns for account name, debit and credit."
        )

    headers = [str(x).strip() for x in parsed[header_index]]
    width = len(headers)
    records = []
    debit_idx = headers.index(found["debit"])
    credit_idx = headers.index(found["credit"])

    for row in parsed[header_index + 1:]:
        # Report section headings and report footers have fewer columns.
        if len(row) != width:
            continue
        debit_text = row[debit_idx].strip()
        credit_text = row[credit_idx].strip()
        # Keep only account rows with at least one numeric debit/credit value.
        if not (_is_amount(debit_text) or _is_amount(credit_text)):
            continue
        records.append(row)

    if not records:
        raise ValueError("The CSV contains headings but no account rows with debit/credit values.")

    return pd.DataFrame(records, columns=headers)


def _is_amount(value):
    value = str(value or "").strip().replace(",", "").replace(" ", "")
    if not value:
        return False
    value = value.replace("(", "-").replace(")", "")
    try:
        float(value)
        return True
    except ValueError:
        return False


def _read_excel_report(raw: bytes) -> pd.DataFrame:
    # Read without assuming the headings are on the first row.
    raw_df = pd.read_excel(io.BytesIO(raw), header=None)
    header_index = None
    for i in range(min(len(raw_df), 50)):
        if _find_header(raw_df.iloc[i].tolist()):
            header_index = i
            break
    if header_index is None:
        raise ValueError(
            "Could not locate the trial balance column headings in the Excel file. "
            "Expected columns for account name, debit and credit."
        )
    headers = [str(x).strip() for x in raw_df.iloc[header_index].tolist()]
    df = raw_df.iloc[header_index + 1:].copy()
    df.columns = headers
    df = df.loc[:, [h for h in headers if h and h.lower() != "nan"]]
    found = _find_header(df.columns)
    debit_col, credit_col = found["debit"], found["credit"]
    valid = df[debit_col].map(_is_amount) | df[credit_col].map(_is_amount)
    return df.loc[valid].copy()


def _number_series(series):
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def parse_trial_balance(upload):
    raw = upload.getvalue()
    name = getattr(upload, "name", "trial_balance.xlsx")
    if name.lower().endswith((".xlsx", ".xls")):
        df = _read_excel_report(raw)
    elif name.lower().endswith(".csv"):
        df = _read_csv_report(raw)
    else:
        raise ValueError("Upload an Excel (.xlsx) or CSV (.csv) trial balance.")

    df.columns = [str(c).strip() for c in df.columns]
    found = _find_header(df.columns)
    if not found:
        raise ValueError(
            "Could not identify required columns. Required: account name, debit and credit."
        )

    name_col = found["account_name"]
    # In this report layout, Category is a grouping (e.g. Sales), Source is
    # a source label (e.g. Account Balance), and the nominal code is prefixed
    # to the Name field (e.g. 1056/000 Core Banking Platform).
    candidate_code_cols = [
        found[k] for k in ("account_code", "source", "category")
        if k in found and found[k] != name_col
    ]

    def code_score(col):
        vals = df[col].dropna().astype(str).head(200)
        if vals.empty:
            return 0.0
        return sum(
            bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./_-]*", v.strip()))
            and any(ch.isdigit() for ch in v)
            for v in vals
        ) / len(vals)

    code_col = max(candidate_code_cols, key=code_score) if candidate_code_cols else None
    if code_col is not None and code_score(code_col) < 0.5:
        code_col = None

    raw_names = df[name_col].fillna("").astype(str).str.strip()
    extracted = raw_names.str.extract(r"^\s*([A-Za-z0-9][A-Za-z0-9./_-]*)\s+(.+?)\s*$")
    name_has_code = extracted[0].notna() & extracted[0].str.contains(r"\d", na=False)

    if code_col is not None:
        codes = df[code_col].fillna("").astype(str).str.strip()
    else:
        codes = pd.Series("", index=df.index, dtype="object")

    # Prefer a code embedded in the account name when the nominal-code
    # candidate columns are actually categories/source descriptions.
    codes = codes.where(codes.ne(""), extracted[0].where(name_has_code, ""))
    # Preserve the complete Name column exactly (apart from outer whitespace).
    # A leading nominal-code-like prefix may be part of the COA Account Name.
    account_names = raw_names

    out = pd.DataFrame(index=df.index)
    out["account_code"] = codes
    out["account_name"] = account_names
    out["category"] = (
        df[found["category"]].fillna("").astype(str).str.strip()
        if "category" in found else ""
    )
    out["source"] = (
        df[found["source"]].fillna("").astype(str).str.strip()
        if "source" in found else ""
    )
    out["debit"] = _number_series(df[found["debit"]])
    out["credit"] = _number_series(df[found["credit"]])

    # Report-level summary rows (for example "Net Profit/Loss After Tax")
    # are not ledger accounts. In the supplied export they have no code,
    # category or source; exclude them from the account-level TB.
    summary_labels = {
        "total", "total debit", "total credit", "grand total",
        "net profit/loss after tax", "net profit after tax",
        "profit/loss for the period",
    }
    is_summary = out["account_name"].str.strip().str.lower().isin(summary_labels)
    out = out[~is_summary].copy()
    out = out[(out.account_name != "") | (out.account_code != "")].copy()
    out["balance"] = out["debit"] - out["credit"]
    if out.empty:
        raise ValueError("The uploaded trial balance contains no account rows.")
    return out.reset_index(drop=True), name


def save_import(entity, year, month, df, filename, username=""):
    import_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    debit = float(df.debit.sum())
    credit = float(df.credit.sum())
    with connection() as (conn, ph):
        cur = conn.cursor()
        cur.execute(
            "SELECT import_id FROM fr_tb_imports WHERE entity_code=" + ph +
            " AND fiscal_year=" + ph + " AND fiscal_month=" + ph +
            " AND status <> 'SUPERSEDED'",
            (entity, int(year), int(month)),
        )
        existing = cur.fetchall()
        if existing:
            raise ValueError(
                "A trial balance already exists for this entity and month. "
                "Use the replace option only after reviewing the existing import."
            )
        cur.execute(
            "INSERT INTO fr_tb_imports "
            "(import_id,entity_code,fiscal_year,fiscal_month,file_name,imported_at,imported_by,status,debit_total,credit_total,line_count) "
            "VALUES (" + ",".join([ph] * 11) + ")",
            (import_id, entity, int(year), int(month), filename, now, username,
             "DRAFT", debit, credit, len(df)),
        )
        for r in df.to_dict("records"):
            cur.execute(
                "INSERT INTO fr_tb_lines "
                "(line_id,import_id,entity_code,account_code,account_name,category,source,debit,credit,balance) "
                "VALUES (" + ",".join([ph] * 10) + ")",
                # The TB's source code is not a COA key. The permanent COA
                # account code is attached only after an Account Name match.
                (str(uuid.uuid4()), import_id, entity, "",
                 str(r["account_name"]), str(r.get("category", "")),
                 str(r.get("source", "")), float(r["debit"]),
                 float(r["credit"]), float(r["balance"])),
            )
    return import_id


def list_imports(entity=None, year=None):
    sql = "SELECT * FROM fr_tb_imports WHERE 1=1"
    p = []
    if entity:
        sql += " AND entity_code=?"
        p.append(entity)
    if year:
        sql += " AND fiscal_year=?"
        p.append(int(year))
    sql += " ORDER BY fiscal_year DESC,fiscal_month DESC, imported_at DESC"
    from database import is_postgres
    if is_postgres():
        sql = sql.replace("?", "%s")
    return rows(sql, p)


def get_import(import_id):
    from database import is_postgres
    return rows(
        "SELECT * FROM fr_tb_imports WHERE import_id=" +
        ("%s" if is_postgres() else "?"),
        (import_id,),
    )


def get_lines(import_id):
    from database import is_postgres
    return rows(
        "SELECT * FROM fr_tb_lines WHERE import_id=" +
        ("%s" if is_postgres() else "?"),
        (import_id,),
    )
