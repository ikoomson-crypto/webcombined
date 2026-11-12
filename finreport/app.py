from __future__ import annotations
import re
import sys
import io
import csv
import calendar
import html as html_lib
from html.parser import HTMLParser
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path
from datetime import datetime
import uuid
import pandas as pd
import streamlit as st

# Rich-text disclosure editor. The app remains usable with a plain-text fallback
# if the optional component has not yet been installed in the environment.
try:
    from streamlit_quill import st_quill
    RICH_TEXT_EDITOR_AVAILABLE = True
except Exception:
    st_quill = None
    RICH_TEXT_EDITOR_AVAILABLE = False

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
import database as DB
import trial_balance as TB
import account_mapping as AM
import chart_of_accounts as COA
import reporting_extensions as RX
import ifrs_financial_report as IFRSReport
import automated_report_generator as ARG

st.set_page_config(page_title="Kulana | Financial Reporting", page_icon="📑", layout="wide")
try:
    DB.init_db()
    RX.init_schema()
    AM.init_mapping_catalogues()
    COA.init_coa()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

st.markdown("""<style>
.block-container{padding-top:1.4rem;padding-bottom:2rem}
.fr-header{background:linear-gradient(110deg,#14243a,#244c68);color:white;padding:1.25rem 1.5rem;border-radius:12px;margin-bottom:1rem}
.fr-header h1{margin:0;font-size:1.7rem}.fr-header p{margin:.35rem 0 0;color:#d9e5ef}
.small-note{color:#64748b;font-size:.86rem}
</style>""",unsafe_allow_html=True)
entities = DB.rows("SELECT * FROM fr_entities WHERE is_active=1 ORDER BY entity_code")
entity_options = {f"{e['entity_code']} — {e['entity_name']} ({e['functional_currency']})":e for e in entities}
if not entity_options:
    st.error("No reporting entities are configured."); st.stop()

# Button-based sidebar navigation, preserving the approved grouped layout.
NAV_GROUPS = {
    "Overview": [("Dashboard", "Dashboard")],
    "Inputs": [
        ("Mapping Catalogue", "Mapping Catalogue"),
        ("COA", "Chart of Accounts"),
        ("Trial Balance", "Trial Balance Import"),
    ],
    "Review and Edits": [
        ("Cashflow Statement", "Cash Flow Statement"),
        ("Changes in Equity", "Changes in Equity"),
        ("Corporate Information", "Corporate Information"),
        ("Notes and Disclosures", "Notes & Disclosures"),
    ],
    "Reports": [
        ("General Financial Report", "Generate Financial Report"),
        ("Automated Financial Statement", "Automated Financial Statements"),
        ("IFRS Disclosure Checks", "IFRS Disclosure Checks"),
    ],
    "Settings": [
        ("Import History", "Import History"),
        ("Entity Setup", "Entity Setup"),
        ("Database Reset", "Database Reset"),
    ],
}
NAV_ITEMS = [page_id for items in NAV_GROUPS.values() for _label, page_id in items]
if st.session_state.get("active_page") not in NAV_ITEMS:
    st.session_state["active_page"] = "Dashboard"

with st.sidebar:
    st.subheader("Reporting workspace")
    entity_label=st.selectbox("Reporting entity",list(entity_options))
    entity=entity_options[entity_label]
    st.caption("Navigation")
    for group_name, group_items in NAV_GROUPS.items():
        st.markdown(f"**{group_name}**")
        for nav_label, page_id in group_items:
            if st.button(
                nav_label,
                key="nav_" + re.sub(r"[^a-z0-9]+", "_", page_id.lower()).strip("_"),
                type="primary" if st.session_state["active_page"] == page_id else "secondary",
                use_container_width=True,
            ):
                st.session_state["active_page"] = page_id
                st.rerun()
    page = st.session_state["active_page"]
    st.divider()
    st.caption(f"Functional currency: {entity['functional_currency']}")
    st.caption(f"Database: {DB.database_target()}")
    st.caption("Imported balances are retained as source records.")

# The workspace banner follows the currently selected reporting entity.
_header_entity_name = html_lib.escape(str(entity.get("entity_name") or entity.get("entity_code") or "Reporting Entity").strip())
st.markdown(
    f'<div class="fr-header"><h1>{_header_entity_name.upper()} | FINANCIAL REPORTING</h1>'
    '<p>IFRS reporting workspace · Chart of Accounts, trial balance and financial statements</p></div>',
    unsafe_allow_html=True,
)


def _plain_text_to_quill_html(value):
    """Convert legacy plain-text disclosures to safe Quill paragraph HTML."""
    value = str(value or "")
    if re.search(r"</?(?:p|div|strong|b|em|i|u|ol|ul|li|br)\b", value, re.I):
        return value
    paragraphs = [html_lib.escape(line) for line in value.splitlines()]
    return "".join(f"<p>{line or '<br>'}</p>" for line in paragraphs) or "<p><br></p>"


def _rich_narrative_editor(label, value, key, height=280, help_text=None):
    """Display an editable rich-text notepad and return its HTML value."""
    if RICH_TEXT_EDITOR_AVAILABLE:
        return st_quill(
            value=_plain_text_to_quill_html(value),
            html=True,
            key=key,
            toolbar=[
                ["bold", "italic", "underline", "strike"],
                [{"list": "ordered"}, {"list": "bullet"}],
                [{"indent": "-1"}, {"indent": "+1"}],
                [{"align": []}],
                ["link"],
                ["clean"],
            ],
        ) or ""
    st.info("For bold, italic, underline, headings, alignment and numbered/bulleted lists, install the optional editor with: `pip install streamlit-quill`. Until then, this field remains available as plain text.")
    return st.text_area(label, value=str(value or ""), height=height,
                        placeholder="Enter the entity-specific disclosure wording...",
                        help=help_text, key=key)


class _ReportLabNarrativeParser(HTMLParser):
    """Translate the supported Quill formatting into ReportLab paragraph markup."""
    TAG_MAP = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.TAG_MAP:
            self.parts.append(f"<{self.TAG_MAP[tag]}>")
        elif tag in ("p", "div"):
            if self.parts and not self.parts[-1].endswith("<br/>"):
                self.parts.append("<br/>")
        elif tag == "br":
            self.parts.append("<br/>")
        elif tag == "li":
            self.parts.append("&#8226; ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.TAG_MAP:
            self.parts.append(f"</{self.TAG_MAP[tag]}>")
        elif tag in ("p", "div", "li"):
            self.parts.append("<br/>")

    def handle_data(self, data):
        self.parts.append(xml_escape(data))


def _narrative_to_reportlab(value):
    """Preserve basic rich-text formatting in generated PDF disclosures."""
    raw = str(value or "")
    if not re.search(r"</?(?:p|div|strong|b|em|i|u|ol|ul|li|br)\b", raw, re.I):
        return "<br/>".join(xml_escape(line) for line in raw.splitlines())
    parser = _ReportLabNarrativeParser()
    parser.feed(raw)
    return "".join(parser.parts).strip("<br/>") or " "


def audit(action, details, year=None, month=None):
    from database import connection, is_postgres
    ph="%s" if is_postgres() else "?"
    with connection() as (conn,_):
        conn.cursor().execute("INSERT INTO fr_audit_log (audit_id,event_time,username,entity_code,fiscal_year,fiscal_month,action,details) VALUES ("+",".join([ph]*8)+")",(str(uuid.uuid4()),datetime.utcnow().isoformat(),st.session_state.get("username",""),entity['entity_code'],year,month,action,details))


def import_history():
    items=TB.list_imports(entity['entity_code'])
    if not items: return pd.DataFrame()
    df=pd.DataFrame(items)
    df["period"]=df.apply(lambda r:f"{int(r['fiscal_year'])}-{int(r['fiscal_month']):02d}",axis=1)
    return df[["period","file_name","status","line_count","debit_total","credit_total","imported_at","import_id"]]


def read_catalogue_upload(upload):
    """Read catalogue uploads without delimiter sniffing.

    Catalogue templates are comma-separated. Automatic delimiter detection is
    unreliable for one-column Notes Line files because commas inside note labels
    can be mistaken for delimiters.
    """
    payload = upload.getvalue()
    filename = upload.name.lower()
    if filename.endswith(".csv"):
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("cp1252")

        # Parse Notes Lines as a one-column list. If a label contains commas
        # but was not quoted in the source CSV, preserve the complete label
        # instead of treating the extra commas as additional columns.
        if "notes" in filename or "note" in filename:
            parsed = list(csv.reader(io.StringIO(text), delimiter=","))
            if not parsed:
                return pd.DataFrame(columns=["Notes Line"])
            headers = parsed[0]
            header_text = " ".join(str(x).strip().casefold() for x in headers)
            is_notes_header = any(
                token in header_text
                for token in ("notes line", "note line", "notes", "description")
            )
            if len(headers) == 1:
                values = []
                for row in parsed[1:]:
                    if row:
                        label = ",".join(row).strip()
                        if label:
                            values.append(label)
                return pd.DataFrame({"Notes Line": values})
            if is_notes_header:
                # Keep the declared Notes Line column and tolerate surplus
                # comma-separated fragments caused by unquoted commas.
                normalized = re.sub(r"[^a-z0-9]+", "", str(headers[0]).casefold())
                if normalized in ("notesline", "noteline", "notes", "description"):
                    values = [",".join(row).strip() for row in parsed[1:] if row]
                    return pd.DataFrame({"Notes Line": values})

        return pd.read_csv(io.StringIO(text), sep=",", engine="python")
    return pd.read_excel(io.BytesIO(payload))


def read_tb_mapping_metadata(upload):
    """Read optional account mapping columns from the uploaded TB file."""
    payload = upload.getvalue()
    filename = upload.name.lower()
    if filename.endswith(".csv"):
        try:
            raw = pd.read_csv(io.BytesIO(payload), sep=None, engine="python", encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = pd.read_csv(io.BytesIO(payload), sep=None, engine="python", encoding="cp1252")
    else:
        raw = pd.read_excel(io.BytesIO(payload))

    def norm_col(value):
        return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())

    aliases = {
        "account_code": {"accountcode", "code", "accountnumber", "accountno", "glcode"},
        "account_name": {"accountname", "name", "account", "description"},
        "notes_line": {"notesline", "noteline", "ifrsnotesline", "notes"},
        "account_nature": {"accountnature", "nature"},
        "normal_balance": {"normalbalance", "normal"},
        "classification": {"classification", "accountclassification"},
    }
    columns = {}
    for column in raw.columns:
        key = norm_col(column)
        for field, names in aliases.items():
            if key in names and field not in columns:
                columns[field] = column

    if not any(field in columns for field in ("notes_line", "account_nature", "normal_balance", "classification")):
        return pd.DataFrame()

    result = pd.DataFrame()
    for field in aliases:
        result[field] = (
            raw[columns[field]].fillna("").astype(str).str.strip()
            if field in columns else ""
        )
    return result


def apply_imported_account_mappings(entity_code, preview, metadata=None):
    """Compatibility wrapper: account mappings now come from the entity COA."""
    return COA.match_trial_balance(entity_code, preview)


def show_dataframe(data, **kwargs):
    """Display tables with consistent comma-separated financial amounts."""
    frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    numeric_cols = list(frame.select_dtypes(include=["number"]).columns)
    if numeric_cols:
        try:
            styled = frame.style.format({col: (lambda value: "" if pd.isna(value) else f"{value:,.2f}") for col in numeric_cols})
            st.dataframe(styled, **kwargs)
            return
        except Exception:
            pass
    st.dataframe(frame, **kwargs)


def show_catalogue_import_result(result, label):
    a, b, c, d = st.columns(4)
    a.metric("New lines", result.get("added", 0))
    b.metric("Reactivated", result.get("reactivated", 0))
    c.metric("Already active", result.get("unchanged", 0))
    d.metric("Rejected rows", len(result.get("rejected", [])))
    if result.get("updated", 0):
        st.info(f"Updated existing links: {result['updated']}")
    if result.get("rejected"):
        st.warning(f"{len(result['rejected'])} row(s) were not imported. Review the row numbers and reasons below, correct the file, and upload again.")
        show_dataframe(pd.DataFrame(result["rejected"]), use_container_width=True, hide_index=True)
    else:
        st.success(f"All valid {label} rows were processed successfully.")



def _is_statement_type(value, wanted):
    """Accept stored system codes and common display labels for statement type."""
    def clean(x):
        return re.sub(r"[^a-z0-9]+", "", str(x or "").casefold())
    actual = clean(value)
    target = clean(wanted)
    aliases = {
        "BS": {"bs", "financialposition", "statementoffinancialposition", "balancesheet", "statementof financialposition".replace(" ", "")},
        "PL": {"pl", "profitandloss", "statementofprofitorloss", "profitloss", "incomestatement"},
    }
    return actual == target or actual in aliases.get(target, {target})


def _statement_amounts(frame, statement_type, currency):
    """Aggregate mapped balances using consistent financial-statement signs.

    Trial balance debit/credit columns are treated as positive movement columns.
    For P&L, credit less debit gives income as positive and expenses as negative.
    """
    if frame is None or frame.empty:
        return {}
    data = frame[
        frame["statement_type"].apply(lambda x: _is_statement_type(x, statement_type))
        & frame["statement_line"].notna()
    ].copy()
    if data.empty:
        return {}

    debit_col = next((c for c in ("debit", "debit_amount", "dr") if c in data.columns), None)
    credit_col = next((c for c in ("credit", "credit_amount", "cr") if c in data.columns), None)
    if debit_col and credit_col:
        debit = pd.to_numeric(data[debit_col], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(data[credit_col], errors="coerce").fillna(0.0)
    elif "balance" in data.columns:
        balance = pd.to_numeric(data["balance"], errors="coerce").fillna(0.0)
        debit = balance.clip(lower=0)
        credit = (-balance).clip(lower=0)
    else:
        raise ValueError("Mapped trial balance rows have no debit/credit or balance fields.")

    labels = data["statement_line"].astype(str).str.strip()
    if _is_statement_type(statement_type, "PL"):
        data["report_amount"] = credit - debit
        # Tax expense accounts are sometimes mapped to a broad G&A line in the COA.
        # Present them separately in the IFRS P&L without silently changing the saved COA mapping.
        account_names = data.get("account_name", pd.Series("", index=data.index)).fillna("").astype(str).str.casefold()
        tax_mask = account_names.str.contains(r"income\s*tax\s*expense|tax\s*expense", regex=True, na=False)
        if tax_mask.any():
            data.loc[tax_mask, "statement_line"] = "Income tax expense"
        labels = data["statement_line"].astype(str).str.strip()
    else:
        lower = labels.str.casefold()
        credit_normal = lower.str.contains(
            r"liabilit|payable|borrow|loan|lease obligation|deferred income|contract liabilit|equity|capital|retained earning|share|provision",
            regex=True, na=False,
        )
        data["report_amount"] = (credit - debit).where(credit_normal, debit - credit)
    data["statement_line"] = labels
    return data.groupby("statement_line", dropna=True)["report_amount"].sum().to_dict()


def _build_pl_report(amounts):
    """Build P&L subtotals from signed mapped amounts (income +, expenses -)."""
    def norm(label):
        return re.sub(r"[^a-z0-9]+", " ", str(label).casefold()).strip()

    def find_amount(candidates):
        for label, amount in amounts.items():
            if norm(label) in candidates:
                return float(amount), label
        return 0.0, None

    revenue, revenue_label = find_amount({"revenue", "sales", "turnover"})
    cost, cost_label = find_amount({"cost of sales", "cost of goods sold", "cost of operations", "direct costs", "direct expenses"})
    other_income, other_label = find_amount({"other income", "other operating income", "investment income"})
    tax, tax_label = find_amount({"income tax expense", "tax expense", "income tax"})
    finance, finance_label = find_amount({"finance costs", "finance cost", "interest expense", "finance charges"})
    associates, associates_label = find_amount({"share of profit loss of associates", "share of profit of associates", "share of loss of associates"})
    oci, oci_label = find_amount({"other comprehensive income", "other comprehensive loss"})

    excluded = {x for x in (revenue_label, cost_label, other_label, tax_label, finance_label, associates_label, oci_label) if x}
    other_rows = [(str(label), float(amount), "line") for label, amount in amounts.items() if label not in excluded]

    # All mapped lines already carry their accounting sign: income +, expenses -.
    gross = revenue + cost
    operating_result = gross + other_income + sum(row[1] for row in other_rows)
    pbt = operating_result + finance + associates
    profit = pbt + tax

    rows = []
    if revenue_label:
        rows.append(("Revenue", revenue, "line"))
    if cost_label:
        rows.append(("Cost of sales", cost, "line"))
    rows.append(("Gross profit/(loss)", gross, "subtotal"))
    if other_label:
        rows.append(("Other income", other_income, "line"))
    rows.extend(other_rows)
    if finance_label:
        rows.append(("Finance costs", finance, "line"))
    if associates_label:
        rows.append(("Share of profit/(loss) of associates", associates, "line"))
    rows.append(("Profit/(loss) before tax", pbt, "subtotal"))
    if tax_label:
        rows.append(("Income tax expense", tax, "line"))
    rows.append(("Net profit/(loss) for the period", profit, "total"))
    if oci_label:
        rows.append(("Other comprehensive income/(loss)", oci, "line"))
        rows.append(("Total comprehensive income/(loss)", profit + oci, "total"))
    return rows


def _bs_notes_lookup(frame):
    """Return the COA Notes Line(s) associated with each Balance Sheet IFRS Line."""
    if frame is None or frame.empty or "statement_line" not in frame.columns or "notes_line" not in frame.columns:
        return {}
    data = frame[frame["statement_type"].apply(lambda x: _is_statement_type(x, "BS")) & frame["statement_line"].notna()].copy()
    if data.empty:
        return {}
    data["statement_line"] = data["statement_line"].astype(str).str.strip()
    data["notes_line"] = data["notes_line"].fillna("").astype(str).str.strip()
    result = {}
    for ifrs_line, group in data.groupby("statement_line", dropna=True):
        note_lines = sorted({x for x in group["notes_line"] if x}, key=str.casefold)
        result[ifrs_line] = "; ".join(note_lines) if note_lines else "Not assigned"
    return result


def _bs_amounts_by_ifrs_and_note(frame):
    """Aggregate Balance Sheet balances by IFRS Line and Notes Line."""
    if frame is None or frame.empty:
        return {}
    data = frame[frame["statement_type"].apply(lambda x: _is_statement_type(x, "BS")) & frame["statement_line"].notna()].copy()
    if data.empty:
        return {}
    dc = next((c for c in ("debit", "debit_amount", "dr") if c in data.columns), None)
    cc = next((c for c in ("credit", "credit_amount", "cr") if c in data.columns), None)
    if dc and cc:
        debit = pd.to_numeric(data[dc], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(data[cc], errors="coerce").fillna(0.0)
    elif "balance" in data.columns:
        bal = pd.to_numeric(data["balance"], errors="coerce").fillna(0.0)
        debit, credit = bal.clip(lower=0), (-bal).clip(lower=0)
    else:
        raise ValueError("Mapped trial balance rows have no debit/credit or balance fields.")
    statement_labels = data["statement_line"].astype(str).str.strip()
    if "account_nature" in data.columns:
        nature_labels = data["account_nature"].fillna("").astype(str).str.strip()
        # Account nature carries the current/non-current classification in the
        # COA mapping (for example, a lease liability may sit under a broad
        # Statement Line called Current liabilities but be classified as
        # Non-Current Liabilities).
        labels = nature_labels.where(nature_labels.ne(""), statement_labels)
    else:
        labels = statement_labels
    low = labels.str.casefold()
    credit_normal = low.str.contains(
        r"liabilit|payable|borrow|loan from|loan payable|lease obligation|deferred income|contract liabilit|equity|capital|retained earning|share|provision|due to",
        regex=True, na=False,
    )
    data["_amount"] = (credit - debit).where(credit_normal, debit - credit)
    data["_ifrs"] = labels
    data["_note"] = data["notes_line"].fillna("").astype(str).str.strip() if "notes_line" in data.columns else ""
    data.loc[data["_note"] == "", "_note"] = "Notes line not assigned"
    grouped = data.groupby(["_ifrs", "_note"], dropna=False, sort=False)["_amount"].sum()
    return {(str(a), str(b)): float(v) for (a, b), v in grouped.items()}


def _build_bs_report_with_notes(current, prior):
    """Delegate Balance Sheet grouping and IFRS presentation to its module."""
    return IFRSReport.build_balance_sheet_rows(current, prior)


def _build_bs_report(amounts):
    def section(label):
        x = str(label).casefold()
        if any(k in x for k in ("equity", "capital", "retained earning", "share")): return "Equity"
        if any(k in x for k in ("liabilit", "payable", "borrow", "loan", "lease obligation", "deferred income", "provision")): return "Liabilities"
        return "Assets"
    buckets = {"Assets": [], "Liabilities": [], "Equity": []}
    for label, amount in amounts.items():
        buckets[section(label)].append((str(label), float(amount), "line"))
    rows = []
    for heading, total_label in (("Assets", "Total Assets"), ("Liabilities", "Total Liabilities"), ("Equity", "Total Equity")):
        rows.append((heading, 0.0, 0.0, "section"))
        items = buckets[heading]
        rows.extend((label, amount, 0.0, kind) for label, amount, kind in items)
        rows.append((total_label, sum(x[1] for x in items), 0.0, "total"))
    return rows

def _report_excel_bytes(entity, year, period_label, currency, pl_rows, bs_rows, comparative_label, bs_note_lookup=None, current_column_label=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
    from openpyxl.utils import get_column_letter
    wb=Workbook(); info=wb.active; info.title="Report Information"
    info.append(["KULANA GROUP | IFRS FINANCIAL REPORT"])
    info.append(["Reporting entity",entity['entity_name']]); info.append(["Entity code",entity['entity_code']])
    info.append(["Reporting period",period_label]); info.append(["Functional currency",currency])
    info.append(["Comparative period",comparative_label or "Not available"])
    def add_statement(title, rows, include_notes=False):
        ws=wb.create_sheet(title[:31]); ws.append(["IFRS Line", current_column_label or currency, comparative_label or "Comparative"])
        for label, current, prior, kind in rows:
            display_label = label
            if include_notes:
                display_label = label
            ws.append([display_label, current, prior])
            idx=ws.max_row
            if kind in ("subtotal","total"):
                for cell in ws[idx]: cell.font=Font(bold=True); cell.border=Border(top=Side(style="thin",color="64748B"))
                if kind=="total":
                    for cell in ws[idx]: cell.fill=PatternFill("solid",fgColor="DCE6F1")
        ws.freeze_panes="B2"; ws.column_dimensions["A"].width=52
        if include_notes:
            from openpyxl.styles import Alignment
            for row_idx in range(2, ws.max_row + 1):
                ws.cell(row_idx, 1).alignment = Alignment(wrap_text=True, vertical="top")
        for col in (2,3):
            ws.column_dimensions[get_column_letter(col)].width=20
            for cell in ws.iter_cols(min_col=col,max_col=col,min_row=2):
                for c in cell: c.number_format='#,##0.00;[Red](#,##0.00);-'
        for c in ws[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="17365D")
        return ws
    for c in info[1]: c.font=Font(bold=True,size=14,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="17365D")
    info.column_dimensions["A"].width=28; info.column_dimensions["B"].width=42
    add_statement("Statement of Profit or Loss",pl_rows)
    add_statement("Statement of Financial Position",bs_rows,include_notes=True)
    out=io.BytesIO(); wb.save(out); return out.getvalue()


def _report_pdf_bytes(entity, year, period_label, currency, pl_rows, bs_rows, comparative_label, bs_note_lookup=None, current_column_label=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from xml.sax.saxutils import escape
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm)
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="ReportTitle",parent=styles["Title"],textColor=colors.HexColor("#17365D"),fontSize=16,leading=20,spaceAfter=4))
    styles.add(ParagraphStyle(name="ReportSub",parent=styles["Normal"],alignment=TA_CENTER,textColor=colors.HexColor("#475569"),fontSize=9,leading=13))
    story=[Paragraph("KULANA GROUP",styles["ReportTitle"]),Paragraph("IFRS FINANCIAL STATEMENTS",styles["Heading2"]),
           Paragraph(f"{entity['entity_name']} · {period_label} · {currency}",styles["ReportSub"]),Spacer(1,10)]
    def table_for(title, rows, include_notes=False):
        story.append(Paragraph(title,styles["Heading2"]))
        data=[["IFRS Line", current_column_label or currency, comparative_label or "Comparative"] if include_notes else ["Description",current_column_label or currency,comparative_label or "Comparative"]]
        for label,cur,prior,kind in rows:
            if include_notes:
                if kind == "ifrs":
                    first_cell = Paragraph(f"<b>{escape(str(label))}</b>", styles["BodyText"])
                elif kind == "note":
                    first_cell = Paragraph(f"<font size='7' color='#64748B'>{escape(str(label))}</font>", styles["BodyText"])
                else:
                    first_cell = Paragraph(escape(str(label)), styles["BodyText"])
                data.append([first_cell,f"{cur:,.2f}" if cur else "–",f"{prior:,.2f}" if prior else "–"])
            else:
                data.append([label,f"{cur:,.2f}" if cur else "–",f"{prior:,.2f}" if prior else "–"])
        widths=[92*mm,38*mm,38*mm]
        t=Table(data,colWidths=widths,repeatRows=1,hAlign="LEFT")
        commands=[("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17365D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("ALIGN",(1,1),(-1,-1),"RIGHT"),("GRID",(0,0),(-1,-1),.25,colors.HexColor("#CBD5E1")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F8FAFC")]),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]
        for i,row in enumerate(rows,start=1):
            if row[3] in ("section","subtotal","total","ifrs"):
                commands += [("FONTNAME",(0,i),(-1,i),"Helvetica-Bold"),("LINEABOVE",(0,i),(-1,i),.6,colors.HexColor("#64748B"))]
            if row[3]=="section": commands.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#E8EEF5")))
            if row[3]=="total": commands.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#DCE6F1")))
        t.setStyle(TableStyle(commands)); story.extend([t,Spacer(1,10)])
    table_for("Statement of Profit or Loss",pl_rows)
    story.append(PageBreak())
    table_for("Statement of Financial Position",bs_rows,include_notes=True)
    story.append(Spacer(1,12)); story.append(Paragraph("Basis: amounts are derived from the imported and mapped trial balance. Comparative amounts are shown only where a corresponding prior-year import is available. Review mapping, classification and sign conventions before authorisation.",styles["Italic"]))
    doc.build(story); return out.getvalue()


def _aggregate_cashflow_notes(rows, amount_key, label_key="Notes Line"):
    """Aggregate statement presentation by Notes Line while retaining source schedules."""
    totals = {}
    order = []
    for item in rows:
        amount = item.get(amount_key)
        if amount is None:
            continue
        label = str(item.get(label_key) or "Notes line not assigned").strip()
        if label not in totals:
            totals[label] = 0.0
            order.append(label)
        totals[label] += float(amount or 0.0)
    return [(label, totals[label]) for label in order]


def _aggregate_cashflow_pairs(rows):
    """Aggregate (Notes Line, amount) pairs for the published cash flow statement."""
    totals = {}
    order = []
    for label, amount in rows:
        label = str(label or "Notes line not assigned").strip()
        if label not in totals:
            totals[label] = 0.0
            order.append(label)
        totals[label] += float(amount or 0.0)
    return [(label, totals[label]) for label in order]


FINANCIAL_NOTE_TEMPLATES = [
    ("N01", "General information", "", ""),
    ("N02", "Material accounting policy information", "", ""),
    ("N03", "Critical accounting estimates and judgements", "", ""),
    ("N04", "Financial risk management", "", ""),
    ("N05", "Revenue", "PL", "Revenue"),
    ("N06", "Cost of service", "PL", "Cost of sales"),
    ("N07", "Other income", "PL", "Other income"),
    ("N08", "Operating expenses", "", ""),
    ("N09", "Taxation", "PL", "Income tax expense"),
    ("N10", "Property and equipment", "BS", "Property and equipment"),
    ("N11", "Subsidiary", "BS", "Investment in subsidiary company"),
    ("N12", "Right-of-use assets and lease liability", "BS", "Right-of-use asset"),
    ("N13", "Cash and cash equivalents", "BS", "Cash and cash equivalents"),
    ("N14", "Trade and other receivables", "BS", "Trade and other receivables"),
    ("N15", "Related parties", "BS", "Amount due from related parties"),
    ("N16", "Stated capital", "BS", "Share capital"),
    ("N17", "Trade and other payables", "BS", "Trade and other payables"),
    ("N18", "Dividend", "", ""),
    ("N19", "Capital commitments and contingent liabilities", "", ""),
    ("N20", "Events after the reporting period", "", ""),
    ("N21", "Holding company and ultimate beneficial owner", "", ""),
]

REPORT_PROFILE_FIELDS = [
    ("DIRECTORS", "Board of Directors"),
    ("REGISTERED_OFFICE", "Registered office"),
    ("COMPANY_SECRETARY", "Company Secretary"),
    ("AUDITOR", "Auditor"),
    ("LEGAL_ADVISERS", "Legal Advisors"),
    ("BANKERS", "Bankers"),
    ("APPROVAL_SIGNATORIES", "Approval and signing"),
]


def _normalise_report_label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _note_tb_amount(note_code, pl_amounts, bs_amounts):
    """Return a TB-derived note anchor where a single mapped line is meaningful."""
    template = next((x for x in FINANCIAL_NOTE_TEMPLATES if x[0] == note_code), None)
    if not template or not template[2]:
        return None
    source = pl_amounts if template[2] == "PL" else bs_amounts
    target = _normalise_report_label(template[3])
    aliases = {
        "cost of sales": {"cost of sales", "cost of service", "cost of operations", "direct costs"},
        "income tax expense": {"income tax expense", "tax expense", "income tax"},
        "property and equipment": {"property and equipment", "property plant and equipment", "property equipment", "ppe"},
        "right of use asset": {"right of use asset", "right of use assets", "right of use asset net book value"},
        "investment in subsidiary company": {"investment in subsidiary company", "investment in subsidiary", "investment in subsidiary undertaking"},
        "share capital": {"share capital", "stated capital"},
    }
    accepted = aliases.get(target, {target})
    for label, amount in source.items():
        if _normalise_report_label(label) in accepted:
            return float(amount or 0.0)
    return None


def _is_not_applicable_note_row(row):
    """Return True when a generated-statement note is marked Not applicable.

    The report pipeline uses six-field note rows in some places and seven-field
    comparative rows in others, so status is the final field in either shape.
    """
    if not row:
        return False
    status = row[6] if len(row) > 6 else (row[5] if len(row) > 5 else "")
    return str(status or "").strip().casefold() == "not applicable"


def _note_sort_key(code):
    """Sort note codes hierarchically: 1, 1.1, 1.2, 2, 2.1, 10."""
    parts = re.findall(r"\d+", str(code))
    return tuple(int(part) for part in parts) if parts else (999999,)


def _display_note_code(code):
    """Display stored codes such as N02.1 as financial-statement numbering 2.1."""
    parts = re.findall(r"\d+", str(code))
    return ".".join(str(int(part)) for part in parts) if parts else str(code)


def _build_note_rows(entity, year, month, pl_frame, bs_frame):
    pl_amounts = _statement_amounts(pl_frame, "PL", entity["functional_currency"])
    bs_amounts = _statement_amounts(bs_frame, "BS", entity["functional_currency"])
    saved = {x["note_code"]: x for x in RX.get_notes(entity['entity_code'], year, month)}
    rows = []
    standard_codes = {item[0] for item in FINANCIAL_NOTE_TEMPLATES}
    for code, title, _kind, _line in FINANCIAL_NOTE_TEMPLATES:
        rec = saved.get(code, {})
        rows.append((code, rec.get("note_title", title), _note_tb_amount(code, pl_amounts, bs_amounts),
                     rec.get("manual_amount"), rec.get("narrative", ""), rec.get("status", "Pending")))
    # Include user-created main notes and numbered subsections. The note code
    # carries the hierarchy (N22, N02.1, N02.2) without changing the DB schema.
    custom_codes = sorted(
        set(saved) - standard_codes,
        key=_note_sort_key
    )
    for code in custom_codes:
        rec = saved.get(code, {})
        rows.append((code, rec.get("note_title", code), None, None,
                     rec.get("narrative", ""), rec.get("status", "Pending")))
    rows.sort(key=lambda row: _note_sort_key(row[0]))
    return rows


def _full_ifrs_schedules(entity, year, month, imports, pl_frame, bs_frame, opening_year=None, opening_month=None, activity_start_month=1):
    """Build report schedules using the same persisted inputs as the dedicated pages.

    For YTD financial statements, opening balances must be the prior financial year-end,
    not the previous month. Existing callers retain the previous-month default.
    """
    current=next((x for x in imports if int(x['fiscal_year'])==year and int(x['fiscal_month'])==month),None)
    if opening_year is not None and opening_month is not None:
        py,pm=int(opening_year),int(opening_month)
    else:
        py,pm=(year-1,12) if month==1 else (year,month-1)
    prior=next((x for x in imports if int(x['fiscal_year'])==py and int(x['fiscal_month'])==pm and str(x.get('status') or '').upper()!='SUPERSEDED'),None)
    cur_bs=RX.balance_by_line(bs_frame)
    prev_frame=RX.period_frame(prior,entity['entity_code']) if prior else pd.DataFrame()
    prev_bs=RX.balance_by_line(prev_frame)
    cur_equity=RX.equity_balance_by_note(bs_frame)
    prev_equity=RX.equity_balance_by_note(prev_frame)
    cf_schedule=RX.cash_flow_classification_schedule(bs_frame, prev_frame)
    pl_cf_schedule=RX.cash_flow_classification_schedule(pl_frame)
    pl_rows_current = _build_pl_report(_statement_amounts(pl_frame, "PL", entity['functional_currency']))
    pl = {row[0]: float(row[1]) for row in pl_rows_current}
    if opening_year is not None:
        cf_inputs=[]
        for input_month in range(int(activity_start_month), month+1):
            cf_inputs.extend(RX.get_inputs(entity['entity_code'], year, input_month, 'CASH_FLOW'))
    else:
        cf_inputs=RX.get_inputs(entity['entity_code'],year,month,'CASH_FLOW')
    cf={}
    for item in cf_inputs:
        code=item['input_code']
        cf[code]=cf.get(code,0.0)+float(item.get('amount') or 0)
    op_codes=['DEPR','IMPAIR','DISPOSAL','FINANCE_ADD','OTHER_NONCASH','INTEREST_PAID','TAX_PAID']
    cfi_codes=['PPE_PURCHASE','PPE_PROCEEDS','INTANGIBLE_PURCHASE','INTANGIBLE_PROCEEDS','INVESTMENT_PURCHASE','INVESTMENT_PROCEEDS','OTHER_INVESTING']
    cff_codes=['BORROWINGS_PROCEEDS','BORROWINGS_REPAY','LEASE_PAYMENTS','SHARES_ISSUED','DIVIDENDS_PAID','OTHER_FINANCING']
    wc=_aggregate_cashflow_notes(cf_schedule['working_capital'], 'Cash Flow')
    auto_noncash=sum(float(x['Cash Flow'] or 0) for x in pl_cf_schedule['noncash'])
    auto_investing=sum(float(x['Cash Flow'] or 0) for x in cf_schedule['investing'])
    auto_financing=sum(float(x['Cash Flow'] or 0) for x in cf_schedule['financing'])
    pbt_value = pl.get('Profit/(loss) before tax', pl.get('Profit before tax', 0.0))
    net_profit_value = pl.get('Net profit/(loss) for the period', pl.get('Profit for the period', 0.0))
    cfo=pbt_value+auto_noncash+sum(cf.get(k,0) for k in op_codes)+sum(v for _,v in wc)
    cfi=auto_investing+sum(cf.get(k,0) for k in cfi_codes); cff=auto_financing+sum(cf.get(k,0) for k in cff_codes)
    cash_open=cf_schedule['cash_open']; cash_close=cf_schedule['cash_close']
    cash_rows=[('OPERATING ACTIVITIES',None),('Profit/(loss) before tax',float(pbt_value))]
    cash_rows += [(f"{label}", amount) for label, amount in _aggregate_cashflow_notes(pl_cf_schedule['noncash'], 'Cash Flow')]
    cash_rows += [('Total automatically classified non-cash P&L adjustments',auto_noncash),('Additional non-cash and other operating adjustments',sum(cf.get(k,0) for k in op_codes))]+wc+[
        ('Net cash generated from/(used in) operating activities',cfo),('INVESTING ACTIVITIES',None)]
    cash_rows += _aggregate_cashflow_notes(cf_schedule['investing'], 'Cash Flow')
    cash_rows += [(label,cf.get(code,0)) for code,label in [
        ('PPE_PURCHASE','Purchase of property, plant and equipment'),('PPE_PROCEEDS','Proceeds from disposal of property, plant and equipment'),
        ('INTANGIBLE_PURCHASE','Purchase of intangible assets'),('INTANGIBLE_PROCEEDS','Proceeds from disposal of intangible assets'),
        ('INVESTMENT_PURCHASE','Purchase of investments'),('INVESTMENT_PROCEEDS','Proceeds from disposal of investments'),('OTHER_INVESTING','Other investing cash flows')]]
    cash_rows += [('Net cash generated from/(used in) investing activities',cfi),('FINANCING ACTIVITIES',None)]
    cash_rows += _aggregate_cashflow_notes(cf_schedule['financing'], 'Cash Flow')
    cash_rows += [(label,cf.get(code,0)) for code,label in [
        ('BORROWINGS_PROCEEDS','Proceeds from borrowings'),('BORROWINGS_REPAY','Repayment of borrowings'),
        ('LEASE_PAYMENTS','Lease principal payments'),('SHARES_ISSUED','Proceeds from issue of shares'),
        ('DIVIDENDS_PAID','Dividends paid'),('OTHER_FINANCING','Other financing cash flows')]]
    cash_rows += [('Net cash generated from/(used in) financing activities',cff),('Net increase/(decrease) in cash and cash equivalents',cfo+cfi+cff),('Opening cash and cash equivalents',cash_open),('Closing cash and cash equivalents',cash_close)]
    # Equity statement follows the dedicated Changes in Equity page logic.
    if opening_year is not None:
        eq_inputs=[]
        for input_month in range(int(activity_start_month), month+1):
            eq_inputs.extend(RX.get_inputs(entity['entity_code'], year, input_month, 'EQUITY'))
    else:
        eq_inputs=RX.get_inputs(entity['entity_code'],year,month,'EQUITY')
    eq={}
    for item in eq_inputs:
        code=item['input_code']
        eq[code]=eq.get(code,0.0)+float(item.get('amount') or 0)
    movement_defs=[('SHARE_ISSUE','Share capital'),('CAPITAL_RETURN','Share capital'),('DIVIDEND','Retained earnings'),('TRANSFER','Other reserves'),('RESERVE_MOVEMENT','Other reserves'),('RETAINED_OTHER','Retained earnings')]
    equity=[]
    oci=0.0
    if not pl_frame.empty and 'statement_type' in pl_frame:
        oci=-float(pl_frame[(pl_frame.statement_type=='PL') & (pl_frame.statement_line=='Other comprehensive income')].balance.sum())
    for line in ['Share capital','Retained earnings','Other reserves']:
        # Equity components are mapped through the COA Notes Line; the higher-level
        # Statement Line may be a single aggregate "Equity" line.
        opening=float(prev_equity.get(line.casefold(),0)); movement=sum(eq.get(code,0) for code,component in movement_defs if component==line)
        # Show current-period net profit/(loss) as its own equity movement line.
        profit=0.0
        other_oci=oci if line=='Other reserves' else 0.0
        equity.append((line,opening,profit,other_oci,movement,opening+profit+other_oci+movement,float(cur_equity.get(line.casefold(),0))))
    equity.append(('Net profit/(loss)',0.0,net_profit_value,0.0,0.0,net_profit_value,None))
    note_rows=_build_note_rows(entity,year,month,pl_frame,bs_frame)
    return cash_rows,equity,note_rows


def _full_excel_bytes(entity, period_label, currency, pl_rows, bs_rows, cash_rows, equity_rows, note_rows,
                      current_column_label=None, comparative_column_label=None, report_profile=None):
    # Not-applicable notes remain in the Notes & Disclosures register but are not
    # part of the issued financial statements workbook.
    note_rows = [row for row in (note_rows or []) if not _is_not_applicable_note_row(row)]
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
    from openpyxl.utils import get_column_letter
    wb=Workbook(); info=wb.active; info.title='Report Information'
    profile = report_profile or {}
    info_rows = [
        ['MANAGEMENT REPORT AND FINANCIAL STATEMENTS'],
        ['Reporting entity', entity['entity_name']], ['Entity code', entity['entity_code']],
        ['Country', entity.get('country') or 'Not configured'], ['Reporting period', period_label],
        ['Functional currency', currency], ['Comparative period', comparative_column_label or 'Unavailable'],
        [], ['CORPORATE INFORMATION'],
    ]
    profile_labels = profile.get("__LABELS__", {})
    for code, label in (profile_labels.items() if profile_labels else REPORT_PROFILE_FIELDS):
        info_rows.append([label, profile.get(code) or ""])
    for row in info_rows: info.append(row)

    navy='17365D'; pale='DCE6F1'; line=Side(style='thin',color='CBD5E1')
    for c in info[1]: c.font=Font(bold=True,size=15,color='FFFFFF'); c.fill=PatternFill('solid',fgColor=navy)
    for row in (9,):
        for c in info[row]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor=navy)
    info.column_dimensions['A'].width=38; info.column_dimensions['B'].width=90
    for row in info.iter_rows():
        for c in row:
            c.alignment=Alignment(vertical='top',wrap_text=True)

    def add_sheet(name, headers, rows, first_col_width=52):
        ws=wb.create_sheet(name[:31]); ws.append(headers)
        for row in rows: ws.append(list(row))
        ws.freeze_panes='B2'; ws.auto_filter.ref=ws.dimensions
        ws.column_dimensions['A'].width=first_col_width
        for i in range(2,len(headers)+1): ws.column_dimensions[get_column_letter(i)].width=22
        for c in ws[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor=navy); c.alignment=Alignment(wrap_text=True,vertical='center')
        ws.row_dimensions[1].height=30
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical='top',wrap_text=True)
                if isinstance(cell.value,(int,float)): cell.number_format='#,##0.00;[Red](#,##0.00);-'
                cell.border=Border(bottom=line)
        return ws

    add_sheet('Contents',['Section','Description'],[
        ('Corporate information','Directors, registered office, company secretary, auditor, legal advisers and bankers'),
        ('Statement of profit or loss and OCI','Current and comparative reporting-period results'),
        ('Statement of financial position','Current and comparative reporting-date balances'),
        ('Statement of changes in equity','Opening balances, movements and closing balances'),
        ('Statement of cash flows','Operating, investing and financing cash flows'),
        ('Notes to the financial statements','Applicable notes and supporting disclosures'),
    ])
    add_sheet('Profit or Loss',['Description',current_column_label or currency,comparative_column_label or 'Comparative','Presentation'],pl_rows)
    add_sheet('Financial Position',['Description',current_column_label or currency,comparative_column_label or 'Comparative','Row type'],bs_rows)
    add_sheet('Changes in Equity',[
        'Equity component','Current opening','Current profit','Current OCI','Current other movements','Current calculated closing','Current TB closing',
        'Prior opening','Prior profit','Prior OCI','Prior other movements','Prior calculated closing','Prior TB closing'],equity_rows)
    add_sheet('Cash Flows',['Description',current_column_label or currency,comparative_column_label or 'Comparative'],cash_rows)
    add_sheet('Notes to Financial Statements',[
        'Note','Title','Current TB amount','Prior-year TB amount','Manual amount','Narrative / disclosure','Status'],note_rows)
    out=io.BytesIO(); wb.save(out); return out.getvalue()


def _full_pdf_bytes(entity, period_label, currency, pl_rows, bs_rows, cash_rows, equity_rows, note_rows,
                   current_column_label=None, comparative_column_label=None, report_profile=None):
    """Create IFRS financial statements using the restrained Word-style layout of the reference FS."""
    # Not-applicable notes are retained in the source register, not the issued PDF.
    note_rows = [row for row in (note_rows or []) if not _is_not_applicable_note_row(row)]
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, LongTable,
                                    TableStyle, PageBreak, KeepTogether)
    from xml.sax.saxutils import escape
    import re as _re

    profile = report_profile or {}
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=22*mm, bottomMargin=20*mm,
                            title=f"{entity['entity_name']} - Financial statements", author=entity['entity_name'])
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='FSMainTitle', parent=styles['Title'], fontName='Helvetica-Bold',
                              fontSize=17, leading=21, textColor=colors.black, alignment=TA_CENTER, spaceAfter=20))
    styles.add(ParagraphStyle(name='FSSubTitle', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=11, leading=16, textColor=colors.black, alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name='FSSection', parent=styles['Heading1'], fontName='Helvetica-Bold',
                              fontSize=10.5, leading=13, textColor=colors.black, spaceBefore=1, spaceAfter=2, keepWithNext=True))
    styles.add(ParagraphStyle(name='FSCompany', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=9.5, leading=12, textColor=colors.black, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle(name='FSNote', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=9.2, leading=12, textColor=colors.black, spaceBefore=8, spaceAfter=4, keepWithNext=True))
    styles.add(ParagraphStyle(name='FSSmall', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8.5, leading=11, textColor=colors.black, spaceAfter=4))
    styles.add(ParagraphStyle(name='FSCell', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8.2, leading=10, textColor=colors.black))
    styles.add(ParagraphStyle(name='FSCellBold', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8.2, leading=10, textColor=colors.black))
    styles.add(ParagraphStyle(name='FSCellRight', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8.2, leading=10, textColor=colors.black, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='FSCellRightBold', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=8.2, leading=10, textColor=colors.black, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='FSCoverDate', parent=styles['Normal'], fontName='Helvetica-Bold',
                              fontSize=11, leading=16, textColor=colors.black, alignment=TA_CENTER))

    black = colors.black
    story = []
    def safe(v):
        return escape(str(v if v not in (None, '') else '—'))
    def date_caption(prefix='For the'):
        value = str(period_label or '').strip()
        low = value.casefold()
        if low.startswith('year ended '):
            return f"{prefix} {value[0].lower() + value[1:]}"
        if low.startswith('period ended '):
            return f"{prefix} {value[0].lower() + value[1:]}"
        return f"{prefix} {value}".strip()
    def money(v):
        if v is None or v == '': return '—'
        if isinstance(v, (int, float)):
            if abs(v) < 0.005: return '-'
            return f"({abs(v):,.2f})" if v < 0 else f"{v:,.2f}"
        return safe(v)
    def pcell(value, bold=False, right=False):
        if value == '':
            return Paragraph('', styles['FSCell'])
        if isinstance(value, (int, float)) or value is None:
            return Paragraph(money(value), styles['FSCellRightBold' if bold else 'FSCellRight'])
        return Paragraph(safe(value).replace('\n', '<br/>'), styles['FSCellBold' if bold else 'FSCell'])
    def page_title(title, subtitle=None):
        story.append(Paragraph(safe(title), styles['FSSection']))
        if subtitle:
            story.append(Paragraph(safe(subtitle), styles['FSSection']))
        rule = Table([['']], colWidths=[174*mm], rowHeights=[1])
        rule.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,-1),0.65,black)]))
        story.extend([rule, Spacer(1, 12)])
    def table(headers, rows, widths=None, kinds=None, header=True, font=8.2, row_space=5):
        data = []
        if header:
            data.append([Paragraph('<b>' + safe(h if h else '') + '</b>', styles['FSCell']) for h in headers])
        for ridx, row in enumerate(rows):
            kind = (kinds[ridx] if kinds and ridx < len(kinds) else '')
            bold = kind in ('section', 'subtotal', 'total')
            cells = []
            for idx, value in enumerate(row):
                # First/description columns are left aligned; all numeric columns are right aligned.
                cells.append(pcell(value, bold=bold, right=idx > 0))
            data.append(cells)
        if widths is None:
            widths = [80*mm] + [94*mm/max(1, len(headers)-1)]*(len(headers)-1)
        t = LongTable(data, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),2), ('RIGHTPADDING',(0,0),(-1,-1),2),
            ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ]
        if header:
            commands += [('LINEBELOW',(0,0),(-1,0),0.65,black), ('BOTTOMPADDING',(0,0),(-1,0),5)]
        offset = 1 if header else 0
        for idx, kind in enumerate(kinds or [], start=offset):
            if kind in ('section','subtotal'):
                commands += [('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold'),
                             ('LINEABOVE',(1,idx),(-1,idx),0.45,black)]
            elif kind == 'total':
                commands += [('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold'),
                             ('LINEABOVE',(1,idx),(-1,idx),0.65,black),
                             ('LINEBELOW',(1,idx),(-1,idx),1.0,black)]
        t.setStyle(TableStyle(commands))
        story.extend([t, Spacer(1, row_space)])
        return t
    def page_decor(canvas, doc_):
        canvas.saveState()
        w, h = A4
        if doc_.page > 1:
            canvas.setFont('Helvetica-Bold', 9)
            canvas.setFillColor(black)
            canvas.drawString(18*mm, h-14*mm, entity['entity_name'])
            canvas.setFont('Helvetica', 8)
            canvas.drawRightString(w-18*mm, 9*mm, str(doc_.page-1))
            if doc_.page >= 4:
                canvas.setFont('Helvetica', 8)
                canvas.drawString(18*mm, 9*mm, 'The notes on the following pages form an integral part of these financial statements')
        canvas.restoreState()

    # Cover: plain white page, centred black bold text, as in the reference document.
    story += [Spacer(1, 68*mm), Paragraph(safe(entity['entity_name']).upper(), styles['FSMainTitle']),
              Spacer(1, 5*mm), Paragraph('Management report and financial statements', styles['FSCoverDate']),
              Spacer(1, 5*mm), Paragraph('for the year ended' if str(period_label).casefold().startswith('year ended') else 'for the period ended', styles['FSCoverDate']),
              Spacer(1, 3*mm), Paragraph(safe(str(period_label).split(' ', 2)[-1] if str(period_label).casefold().startswith('year ended ') else period_label), styles['FSCoverDate']), PageBreak()]

    # Contents
    page_title(date_caption())
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph('<b>Contents</b>', styles['FSSection']))
    contents = [
        ('Corporate information', '3'), ('Financial statements:', ''),
        ('-   Statement of profit or loss and other comprehensive income', '4'),
        ('-   Statement of financial position', '5'), ('-   Statement of changes in equity', '6'),
        ('-   Statement of cash flows', '7'), ('-   Notes to the financial statements', '8 onwards')]
    cdata = [[Paragraph(safe(a), styles['FSCell']), Paragraph(safe(b), styles['FSCellRight'])] for a,b in contents]
    ct = Table(cdata, colWidths=[145*mm, 25*mm], hAlign='LEFT')
    ct.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),2),
                            ('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),8),
                            ('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.extend([ct, PageBreak()])

    # Corporate information: two-column text layout, no coloured table/grid.
    page_title('Corporate Information', date_caption())
    profile_labels = profile.get("__LABELS__", {})
    corp = [(label, profile.get(code) or '') for code, label in profile_labels.items()]
    if not corp:
        corp = [(label, profile.get(code) or '') for code, label in REPORT_PROFILE_FIELDS]
    corp += [('Registered country', entity.get('country') or 'Not configured'),
             ('Functional / presentation currency', currency)]
    corp_data = [[Paragraph(f'<b>{safe(label)}:</b>', styles['FSCell']),
                  Paragraph(safe(value).replace('\n','<br/>'), styles['FSCell'])] for label,value in corp]
    corp_table = Table(corp_data, colWidths=[58*mm, 112*mm], hAlign='LEFT')
    corp_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),2),
                                    ('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),6),
                                    ('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    story.extend([corp_table, Spacer(1,5)])
    story.append(Paragraph('Corporate information fields not held in the reporting system must be completed and confirmed by management before authorisation.', styles['FSSmall']))
    story.append(PageBreak())

    # Statement of profit or loss and OCI
    page_title('Statement of profit or loss and other comprehensive income', date_caption())
    pl_note_refs={'revenue':'5','cost of sales':'6','cost of service':'6','other income':'7',
                  'operating expenses':'8','administrative expenses':'8','finance costs':'12',
                  'finance cost':'12','income tax expense':'9','tax expense':'9'}
    pl_data=[]
    for row in pl_rows:
        label,current,prior,kind=row
        key=_re.sub(r'[^a-z0-9]+',' ',str(label).casefold()).strip()
        pl_data.append((label,pl_note_refs.get(key,''),current,prior))
    table(['', 'Notes', current_column_label or currency, comparative_column_label or 'Comparative'],
          pl_data, widths=[82*mm, 15*mm, 37*mm, 36*mm], kinds=[r[3] for r in pl_rows], row_space=2)
    story.append(Paragraph('The notes on pages 8 onwards form an integral part of these financial statements.', styles['FSSmall']))
    story.append(PageBreak())

    # Statement of financial position
    page_title('Statement of financial position', 'As at ' + (str(period_label)[11:] if str(period_label).casefold().startswith('year ended ') else str(period_label)))
    def sfp_note_ref(label):
        key=_re.sub(r'[^a-z0-9]+',' ',str(label or '').casefold()).strip()
        if any(x in key for x in ('property','computer equipment','office furniture','office fittings')): return '10'
        if 'subsidiary' in key: return '11'
        if 'deferred tax' in key or 'tax recoverable' in key or 'current tax' in key: return '9'
        if 'right of use' in key or 'lease liability' in key: return '12'
        if 'cash' in key or 'bank overdraft' in key or 'bank balance' in key: return '13'
        if any(x in key for x in ('receivable','prepayment','vat recoverable')): return '14'
        if 'related part' in key or 'amount due from' in key: return '15'
        if 'share capital' in key or 'stated capital' in key: return '16'
        if any(x in key for x in ('payable','accrued expense','paye')): return '17'
        return ''
    bs_data=[(str(r[0] or ''), sfp_note_ref(r[0]), r[1], r[2]) for r in bs_rows]
    table(['', 'Notes', current_column_label or currency, comparative_column_label or 'Comparative'],
          bs_data, widths=[82*mm, 15*mm, 37*mm, 36*mm], kinds=[r[3] for r in bs_rows], row_space=2)
    story.append(Paragraph('The financial statements were approved by the Board and authorised for issue on the date recorded in the approval minutes.', styles['FSSmall']))
    story.append(PageBreak())

    # Statement of changes in equity
    page_title('Statement of changes in equity', date_caption())
    eq_headers=['Equity component','Current opening','Current profit','Current OCI','Current other movements','Current closing','Current TB closing',
                'Comparative opening','Comparative profit','Comparative OCI','Comparative other movements','Comparative closing','Comparative TB closing']
    table(eq_headers, equity_rows, widths=[38*mm]+[10.2*mm]*12, font=6.4, row_space=2)
    story.append(Paragraph('Other movements must be supported by approved share transactions, dividends, transfers and other reserve movements. Differences between calculated closing balances and the trial balance require investigation.', styles['FSSmall']))
    story.append(PageBreak())

    # Statement of cash flows
    page_title('Statement of cash flows', date_caption())
    table(['', current_column_label or currency, comparative_column_label or 'Comparative'], cash_rows,
          widths=[98*mm, 36*mm, 36*mm], row_space=2)
    story.append(Paragraph('Cash flow classifications and working-capital movements are based on the saved cash flow schedule. Review non-cash transactions, tax and interest paid, investing and financing transactions and the cash reconciliation before approval.', styles['FSSmall']))
    story.append(PageBreak())

    # Notes, with plain numbered headings and unshaded disclosure tables.
    page_title('Notes to the financial statements', date_caption())
    story.append(Paragraph('The following notes form part of these financial statements. Amounts derived from the trial balance are indicative anchors and should be supported by detailed schedules and entity-specific disclosures.', styles['FSSmall']))
    for row in note_rows:
        code,title,current_amount,prior_amount,manual_amount,narrative,status = (list(row)+[None]*7)[:7]
        note_no = str(code).replace('N','').lstrip('0') or '0'
        story.append(Paragraph(f"{safe(note_no)}. {safe(title)}", styles['FSNote']))
        if current_amount is not None or prior_amount is not None or manual_amount is not None:
            amount_rows=[('Amount', current_amount, prior_amount, manual_amount)]
            table(['', current_column_label or currency, comparative_column_label or 'Comparative', 'Manual / supplementary'],
                  amount_rows, widths=[65*mm, 34*mm, 34*mm, 37*mm], row_space=1)
        else:
            story.append(Paragraph('Refer to the supporting schedules and narrative disclosure for this note.', styles['FSSmall']))
        narrative_text=str(narrative or '').strip()
        if narrative_text:
            story.append(Paragraph(_narrative_to_reportlab(narrative_text), styles['FSSmall']))
        else:
            story.append(Paragraph('<b>Management disclosure required.</b> Add the entity-specific narrative, accounting policy, breakdown or supporting analysis applicable to this note.', styles['FSSmall']))
        story.append(Paragraph(f"Disclosure status: {safe(status or 'Pending')}", styles['FSSmall']))

    story.extend([Spacer(1,8), Paragraph('Preparation and authorisation', styles['FSNote']),
                  Paragraph('This report is generated from the selected entity’s imported trial balances, Chart of Accounts mappings and saved supporting inputs. It is a draft reporting package and does not constitute an audit opinion or confirmation of IFRS compliance. Management must complete outstanding disclosures, validate comparative figures, reconcile the statements and obtain appropriate approval before issue.', styles['FSSmall'])])
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return out.getvalue()


if page=="Dashboard":
    st.subheader("Reporting dashboard")
    imports=TB.list_imports(entity['entity_code'])
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Trial balances imported",len(imports))
    c2.metric("Draft periods",sum(1 for x in imports if x['status']=='DRAFT'))
    c3.metric("Approved periods",sum(1 for x in imports if x['status']=='APPROVED'))
    c4.metric("Functional currency",entity['functional_currency'])
    st.markdown("#### Recent reporting periods")
    hist=import_history()
    if hist.empty: st.info("No trial balances have been imported for this entity yet. Start with Trial Balance Import.")
    else: show_dataframe(hist.drop(columns=['import_id']),use_container_width=True,hide_index=True)
    st.markdown("#### Reporting workflow")
    st.write("1. Import the monthly trial balance.  2. Validate debit and credit totals.  3. Maintain the Chart of Accounts and its Mapping Catalogue selections.  4. Review the statements and supporting schedules.  5. Approve the period before publishing figures to Strategic Planning.")
    st.info("Supplementary reporting modules are available for cash flows, changes in equity, financial statement notes and IFRS reporting checks. These remain subject to supporting schedules and management review.")

elif page=="Trial Balance Import":
    st.subheader("Monthly trial balance import")
    st.caption("Upload a Trial Balance containing account names and debit/credit balances. The system matches account names to the selected entity's Chart of Accounts and retrieves its permanent account code and IFRS mapping.")
    st.download_button(
        "Download trial balance template",
        data="Name,Category,Source,Debit,Credit\n",
        file_name="Trial_Balance_Template.csv",
        mime="text/csv",
        key="download_tb_template",
    )
    c1,c2=st.columns(2)
    year=c1.number_input("Financial year",min_value=2000,max_value=2100,value=datetime.now().year,step=1)
    month=c2.selectbox("Reporting month",list(range(1,13)),index=datetime.now().month-1,format_func=lambda m:datetime(2000,m,1).strftime("%B"))
    upload=st.file_uploader("Upload trial balance",type=["xlsx","xls","csv"])
    if upload:
        try:
            preview,filename=TB.parse_trial_balance(upload)
            # Preview and save use the same name-only matching routine.
            # COA Account Name is compared with the parsed TB Name column;
            # TB account codes are deliberately ignored.
            match_preview = COA.match_preview_to_coa(entity['entity_code'], preview)
            match_count = match_preview["matched"]
            unmatched_names = match_preview["unmatched"]
            ambiguous_names = match_preview["ambiguous"]
            st.markdown("#### Import preview")
            a,b,c,d=st.columns(4)
            a.metric("Account rows",len(preview))
            b.metric("COA matches",match_count)
            c.metric("New / unmatched",len(unmatched_names))
            d.metric("Debit total",f"{entity['functional_currency']} {preview.debit.sum():,.2f}")
            diff=float(preview.debit.sum()-preview.credit.sum())
            if abs(diff)<0.01: st.success("Debit and credit totals agree.")
            else: st.error(f"Trial balance is out of balance by {entity['functional_currency']} {diff:,.2f}. It may be imported for investigation, but cannot be approved until resolved.")
            show_dataframe(preview.head(100),use_container_width=True,hide_index=True)
            if unmatched_names:
                st.warning("The following TB account names do not match an Account Name in this entity's Chart of Accounts. You can import the TB as a draft, but these accounts must be added to the COA and matched before approval.")
                show_dataframe(pd.DataFrame({"Unmatched TB name": sorted(set(unmatched_names))}), use_container_width=True, hide_index=True)
            if ambiguous_names:
                st.error("Some TB names match more than one COA Account Name. Resolve the duplicate names in the Chart of Accounts before approval.")
                ambiguous_display = [{"TB Name": x["tb_name"], "Matching COA account codes": ", ".join(x["account_codes"])} for x in ambiguous_names]
                show_dataframe(pd.DataFrame(ambiguous_display), use_container_width=True, hide_index=True)
            confirm=st.checkbox("I have checked the entity, reporting month and source file.")
            if st.button("Save trial balance",type="primary",disabled=not confirm):
                import_id=TB.save_import(entity['entity_code'],year,month,preview,filename,st.session_state.get("username",""))
                mapping_result = COA.match_trial_balance(entity['entity_code'], preview, import_id=import_id)
                audit(
                    "TRIAL_BALANCE_IMPORTED",
                    f"{filename}; {len(preview)} rows; import_id={import_id}; "
                    f"coa_matches={mapping_result['matched']}; unmatched={len(mapping_result['unmatched'])}; ambiguous={len(mapping_result['ambiguous'])}",
                    year, month
                )
                st.success(
                    f"Trial balance imported as DRAFT. "
                    f"{mapping_result['matched']} account(s) matched to the Chart of Accounts; "
                    f"{len(mapping_result['unmatched'])} account(s) require COA setup and "
                    f"{len(mapping_result['ambiguous'])} account(s) have ambiguous COA names."
                )
                st.rerun()
        except Exception as exc:
            st.error(str(exc))

elif page=="Mapping Catalogue":
    st.subheader(f"IFRS Mapping Catalogue — {entity['entity_name']}")
    st.caption("Maintain the master lists of IFRS presentation lines, Statements, and Notes lines independently. The Chart of Accounts selects each classification separately.")

    tab_statements, tab_ifrs, tab_notes, tab_account_types = st.tabs(
        ["Statements", "IFRS Lines", "Notes Lines", "Account Types"]
    )

    with tab_statements:
        st.markdown("#### Financial statement categories")
        st.caption("Statements are maintained separately from IFRS presentation lines and Notes lines. Select the applicable statement when maintaining an IFRS line or an account in the Chart of Accounts.")
        statement_df = pd.DataFrame([
            {"Statement": label, "Code": code, "Description": description}
            for label, code, description in [
                ("Profit or Loss", "PL", "Income and expenses for the reporting period"),
                ("Financial Position", "BS", "Assets, liabilities and equity at the reporting date"),
            ]
        ])
        show_dataframe(statement_df, use_container_width=True, hide_index=True)
        st.info("The statement codes are system-controlled (PL and BS) to protect existing account mappings and reporting logic. The statement list is intentionally separate from the IFRS and Notes catalogues.")

    with tab_ifrs:
        st.markdown("#### IFRS presentation lines")
        st.caption("Maintain the IFRS presentation line descriptions here. Statement classification is maintained separately and selected independently in the Chart of Accounts.")
        with st.expander("Upload IFRS lines from Excel or CSV", expanded=False):
            st.download_button(
                "Download IFRS Lines template",
                data="IFRS Line,Statement\\n",
                file_name="IFRS_Lines_Template.csv",
                mime="text/csv",
                key=f"coa_ifrs_template_{entity['entity_code']}",
            )
            ifrs_upload = st.file_uploader("Choose IFRS Lines file", type=["xlsx", "xls", "csv"], key=f"coa_ifrs_upload_{entity['entity_code']}")
            if ifrs_upload is not None:
                try:
                    ifrs_upload_df = read_catalogue_upload(ifrs_upload)
                    show_dataframe(ifrs_upload_df.head(20), use_container_width=True, hide_index=True)
                    if st.button("Import IFRS Lines", type="primary", key=f"coa_import_ifrs_{entity['entity_code']}"):
                        result = AM.import_ifrs_catalogue_rows(ifrs_upload_df, entity['entity_code'])
                        st.success(f"IFRS catalogue import: {result['added']} added, {result['reactivated']} reactivated, {result['unchanged']} already active.")
                        if result.get("rejected"):
                            show_dataframe(pd.DataFrame(result["rejected"]), use_container_width=True, hide_index=True)
                        st.rerun()
                except Exception as exc:
                    st.error(f"Could not import IFRS Lines: {exc}")
        with st.form(f"coa_add_ifrs_catalogue_{entity['entity_code']}", clear_on_submit=True):
            c1, c2 = st.columns([4, 1])
            new_ifrs = c1.text_input("IFRS Line")
            add_ifrs = c2.form_submit_button("Add line")
        if add_ifrs:
            try:
                AM.add_catalogue_line("IFRS", new_ifrs.strip(), entity_code=entity['entity_code'])
                st.success("IFRS line added.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        ifrs_rows = [{
            "Delete": False,
            "Original line": x["line_label"],
            "IFRS Line": x["line_label"],
        } for x in AM.get_all_ifrs_catalogue(entity['entity_code'])]
        ifrs_df = pd.DataFrame(ifrs_rows, columns=["Delete", "Original line", "IFRS Line"])
        edited_ifrs = st.data_editor(
            ifrs_df, use_container_width=True, hide_index=True, num_rows="fixed",
            key=f"coa_ifrs_catalogue_editor_{entity['entity_code']}",
            column_config={
                "Delete": st.column_config.CheckboxColumn("Delete"),
                "Original line": None,
                "IFRS Line": st.column_config.TextColumn("IFRS Line", required=True),
            },
            disabled=["Original line"],
        )
        csave, cdel = st.columns(2)
        if csave.button("Save IFRS catalogue", type="primary", key=f"coa_save_ifrs_{entity['entity_code']}"):
            try:
                result = AM.update_ifrs_catalogue_rows(edited_ifrs.rename(columns={"Delete": "Select for deletion", "IFRS Line": "IFRS presentation line"}), entity['entity_code'])
                st.success(f"Saved IFRS catalogue: {result['added']} added, {result['updated']} updated.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        delete_rows = edited_ifrs[edited_ifrs["Delete"] == True]
        if cdel.button("Deactivate selected IFRS lines", key=f"coa_delete_ifrs_{entity['entity_code']}", disabled=delete_rows.empty):
            AM.bulk_deactivate_catalogue_lines("IFRS", delete_rows["IFRS Line"].tolist(), entity_code=entity['entity_code'])
            st.success(f"Deactivated {len(delete_rows)} IFRS line(s).")
            st.rerun()

    with tab_notes:
        st.markdown("#### Notes lines")
        st.caption("Notes lines are maintained independently. They do not contain IFRS Line or Statement columns; those are selected separately from their own catalogue in the Chart of Accounts.")
        with st.expander("Upload Notes lines from Excel or CSV", expanded=False):
            st.download_button("Download Notes Lines template", data="Notes Line\\n", file_name="Notes_Lines_Template.csv", mime="text/csv", key=f"coa_notes_template_{entity['entity_code']}")
            notes_upload = st.file_uploader("Choose Notes Lines file", type=["xlsx", "xls", "csv"], key=f"coa_notes_upload_{entity['entity_code']}")
            if notes_upload is not None:
                try:
                    notes_upload_df = read_catalogue_upload(notes_upload)
                    show_dataframe(notes_upload_df.head(20), use_container_width=True, hide_index=True)
                    if st.button("Import Notes Lines", type="primary", key=f"coa_import_notes_{entity['entity_code']}"):
                        result = AM.import_notes_catalogue_rows(notes_upload_df, entity['entity_code'])
                        st.success(f"Notes catalogue import: {result['added']} added, {result['reactivated']} reactivated, {result['unchanged']} already active.")
                        if result.get("rejected"):
                            show_dataframe(pd.DataFrame(result["rejected"]), use_container_width=True, hide_index=True)
                        st.rerun()
                except Exception as exc:
                    st.error(f"Could not import Notes Lines: {exc}")
        with st.form(f"coa_add_notes_catalogue_{entity['entity_code']}", clear_on_submit=True):
            n1, n2 = st.columns([4, 1])
            new_note = n1.text_input("Notes Line")
            add_note = n2.form_submit_button("Add Notes line")
        if add_note:
            try:
                AM.add_catalogue_line("NOTES", new_note.strip(), entity_code=entity['entity_code'])
                st.success("Notes line added.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        notes_rows = [{"Delete": False, "Original Notes Line": x["line_label"], "Notes Line": x["line_label"]} for x in AM.get_notes_catalogue(entity['entity_code'])]
        notes_df = pd.DataFrame(notes_rows, columns=["Delete", "Original Notes Line", "Notes Line"])
        edited_notes = st.data_editor(
            notes_df, use_container_width=True, hide_index=True, num_rows="fixed",
            key=f"coa_notes_catalogue_editor_{entity['entity_code']}",
            column_config={
                "Delete": st.column_config.CheckboxColumn("Delete"),
                "Original Notes Line": None,
                "Notes Line": st.column_config.TextColumn("Notes Line", required=True),
            },
            disabled=["Original Notes Line"],
        )
        csave, cdel = st.columns(2)
        if csave.button("Save Notes catalogue", type="primary", key=f"coa_save_notes_{entity['entity_code']}"):
            try:
                result = AM.update_notes_catalogue(edited_notes, entity['entity_code'])
                st.success(f"Saved Notes catalogue: {result['added']} added, {result['updated']} updated.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        delete_rows = edited_notes[edited_notes["Delete"] == True]
        if cdel.button("Deactivate selected Notes lines", key=f"coa_delete_notes_{entity['entity_code']}", disabled=delete_rows.empty):
            AM.bulk_deactivate_catalogue_lines("NOTES", delete_rows["Notes Line"].tolist(), entity_code=entity['entity_code'])
            st.success(f"Deactivated {len(delete_rows)} Notes line(s).")
            st.rerun()

    with tab_account_types:
        st.markdown("#### Account Types")
        st.caption("This is the master list used by the Chart of Accounts. Add or maintain account classifications here; the COA form and register draw their options directly from this catalogue.")

        st.markdown("**Upload Account Types**")
        st.caption("Upload a CSV or Excel file containing one column named Account Type. Uploaded values are added to this catalogue only; they are not automatically translated or converted.")
        account_type_template = pd.DataFrame({"Account Type": [""]})
        at_template_csv = account_type_template.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Download CSV Template",
            data=at_template_csv,
            file_name="account_type_template.csv",
            mime="text/csv",
            key="download_account_type_template",
        )

        # Excel upload template: one column, matching the Account Type import field.
        at_template_xlsx = io.BytesIO()
        with pd.ExcelWriter(at_template_xlsx, engine="openpyxl") as writer:
            account_type_template.to_excel(
                writer,
                index=False,
                sheet_name="Account Types",
            )
        st.download_button(
            "Download Excel Template",
            data=at_template_xlsx.getvalue(),
            file_name="account_type_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_account_type_template_xlsx",
        )
        account_type_upload = st.file_uploader(
            "Choose Account Type CSV or Excel file",
            type=["csv", "xlsx", "xls"],
            key=f"account_type_catalogue_upload_{entity['entity_code']}",
        )
        if account_type_upload is not None:
            try:
                uploaded_types_df = read_catalogue_upload(account_type_upload)
                # Account Type catalogue uploads must resolve to one explicit column.
                type_col = next(
                    (c for c in uploaded_types_df.columns
                     if re.sub(r"[^a-z0-9]+", "", str(c).casefold()) in
                     ("accounttype", "accounttypes", "type")),
                    None,
                )
                if type_col is None:
                    st.error("Missing required column: Account Type. Download the template and use its column heading.")
                else:
                    cleaned_types = []
                    seen_types = set()
                    for raw_type in uploaded_types_df[type_col].dropna().tolist():
                        label = " ".join(str(raw_type).strip().split())
                        if label and label.casefold() not in seen_types:
                            cleaned_types.append(label)
                            seen_types.add(label.casefold())
                    st.write(f"Detected {len(cleaned_types)} unique Account Type value(s).")
                    st.dataframe(
                        pd.DataFrame({"Account Type": cleaned_types}),
                        use_container_width=True,
                        hide_index=True,
                    )
                    if st.button(
                        "Import Account Types",
                        type="primary",
                        key=f"import_account_type_catalogue_upload_{entity['entity_code']}",
                        disabled=not cleaned_types,
                    ):
                        existing = {
                            str(x["line_label"]).strip().casefold()
                            for x in AM.get_account_type_catalogue(entity['entity_code'])
                        }
                        added = 0
                        for label in cleaned_types:
                            if label.casefold() not in existing:
                                AM.add_account_type(label, entity['entity_code'])
                                existing.add(label.casefold())
                                added += 1
                        st.success(
                            f"Account Type upload completed: {added} new value(s) added. "
                            f"{len(cleaned_types) - added} duplicate/existing value(s) skipped."
                        )
                        st.rerun()
            except Exception as exc:
                st.error(f"Could not import Account Types: {type(exc).__name__}: {exc}")
                with st.expander("Technical error details", expanded=True):
                    st.exception(exc)
        with st.form("coa_add_account_type_catalogue", clear_on_submit=True):
            at1, at2 = st.columns([4, 1])
            new_account_type = at1.text_input("Account Type")
            add_account_type = at2.form_submit_button("Add Account Type")
        if add_account_type:
            try:
                AM.add_account_type(new_account_type, entity['entity_code'])
                st.success("Account Type added to the catalogue.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        account_type_rows = [
            {"Delete": False, "Original Account Type": x["line_label"], "Account Type": x["line_label"]}
            for x in AM.get_account_type_catalogue(entity['entity_code'])
        ]
        account_type_df = pd.DataFrame(
            account_type_rows, columns=["Delete", "Original Account Type", "Account Type"]
        )
        edited_account_types = st.data_editor(
            account_type_df, use_container_width=True, hide_index=True, num_rows="fixed",
            key=f"coa_account_type_catalogue_editor_{entity['entity_code']}",
            column_config={
                "Delete": st.column_config.CheckboxColumn("Delete"),
                "Original Account Type": None,
                "Account Type": st.column_config.TextColumn("Account Type", required=True),
            },
            disabled=["Original Account Type"],
        )
        at_save, at_delete = st.columns(2)
        if at_save.button("Save Account Types", type="primary", key=f"coa_save_account_types_{entity['entity_code']}"):
            try:
                result = AM.update_account_type_catalogue(
                    edited_account_types.rename(columns={"Delete": "Delete"}), entity['entity_code']
                )
                st.success(f"Saved Account Types: {result['added']} added, {result['updated']} renamed.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        selected_types = edited_account_types[edited_account_types["Delete"] == True]
        if at_delete.button(
            f"Remove selected Account Types ({len(selected_types)})",
            key=f"coa_delete_account_types_{entity['entity_code']}",
            disabled=selected_types.empty,
        ):
            try:
                removed = AM.bulk_deactivate_account_types(selected_types["Account Type"].tolist(), entity['entity_code'])
                st.success(f"Removed {removed} Account Type(s) from the active catalogue.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

elif page=="Chart of Accounts":
    st.subheader("Chart of Accounts")
    st.caption("The COA is the master account register for this entity. Account codes are permanent. IFRS, Notes and Cash Flow classifications are maintained independently.")

    account_type_options = COA.get_account_types(entity['entity_code'])
    if not account_type_options:
        st.warning("Add at least one Account Type in Mapping Catalogue before creating or editing COA accounts.")
    notes_options = [""] + [x["line_label"] for x in AM.get_notes_catalogue(entity['entity_code'])]
    ifrs_catalogue = AM.get_all_ifrs_catalogue(entity['entity_code'])
    ifrs_options = [""] + sorted({x["line_label"] for x in ifrs_catalogue})
    statement_options = [""] + COA.STATEMENTS
    cash_flow_options = COA.CASH_FLOW_CLASSIFICATIONS

    with st.expander("Upload Chart of Accounts", expanded=False):
        st.caption("Required columns: Account Name, Account Type, Notes Line, IFRS Line and Statement. Account Code is generated automatically and must not be included.")
        st.download_button(
            "Download COA upload template",
            data="Account Name,Account Type,Notes Line,IFRS Line,Statement\\n",
            file_name="Chart_of_Accounts_Template.csv",
            mime="text/csv",
            key="download_coa_template",
        )
        coa_upload = st.file_uploader("Choose COA Excel or CSV file", type=["xlsx", "xls", "csv"], key=f"coa_upload_{entity['entity_code']}")
        if coa_upload is not None:
            try:
                upload_df = read_catalogue_upload(coa_upload)
                st.markdown("**COA upload preview**")
                show_dataframe(upload_df.head(50), use_container_width=True, hide_index=True)
                if st.button("Import Chart of Accounts", type="primary", key=f"import_coa_{entity['entity_code']}"):
                    def col_lookup(df):
                        # Normalize ordinary whitespace, line breaks, BOMs and literal
                        # escaped newline sequences sometimes present in CSV headers.
                        lookup = {}
                        for column in df.columns:
                            normalized = str(column).replace("\\ufeff", "").strip().casefold()
                            normalized = normalized.replace("\\\\n", "").replace("\\\\r", "")
                            normalized = normalized.replace("\\n", "").replace("\\r", "")
                            key = re.sub(r"[^a-z0-9]+", "", normalized)
                            lookup[key] = column
                        return lookup
                    cols = col_lookup(upload_df)
                    aliases = {
                        "Account Name": ("accountname", "name", "account", "description"),
                        "Account Type": ("accounttype", "type"),
                        "Notes Line": ("notesline", "noteline", "notes"),
                        "IFRS Line": ("ifrsline", "ifrspresentationline", "presentationline"),
                        "Statement": ("statement", "statementtype"),
                        "Cash Flow Classification": ("cashflowclassification", "cashflowcategory", "cashflow"),
                    }
                    selected_cols = {}
                    for label, keys in aliases.items():
                        selected_cols[label] = next((cols[k] for k in keys if k in cols), None)
                    missing = [label for label, col in selected_cols.items() if col is None and label != "Cash Flow Classification"]
                    if missing:
                        raise ValueError("Missing required COA columns: " + ", ".join(missing))
                    # Account Type values must already exist in Mapping Catalogue.
                    # COA imports never create, normalize into, or auto-populate types.
                    added, failed = 0, []
                    for idx, record in upload_df.iterrows():
                        try:
                            code = COA.save_account(
                                entity['entity_code'],
                                COA.normalize_account_name(record[selected_cols["Account Name"]]),
                                record[selected_cols["Account Type"]],
                                record[selected_cols["Notes Line"]],
                                record[selected_cols["IFRS Line"]],
                                record[selected_cols["Statement"]],
                                cash_flow_classification=(record[selected_cols["Cash Flow Classification"]] if selected_cols.get("Cash Flow Classification") else ""),
                            )
                            added += 1
                        except Exception as exc:
                            failed.append({"Row": int(idx) + 2, "Account Name": str(record.get(selected_cols["Account Name"], "")), "Reason": str(exc)})
                    audit("COA_UPLOADED", f"{added} accounts imported; {len(failed)} rows rejected")
                    # Display the result in this run. Calling st.rerun() here clears
                    # transient success/warning messages before the user can read them.
                    if added:
                        st.success(f"COA import completed: {added} account(s) saved.")
                    if failed:
                        st.warning(f"{len(failed)} row(s) could not be imported. Review the details below.")
                        show_dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)
                    if not added and not failed:
                        st.info("The file contains no account rows to import.")
            except Exception as exc:
                st.error(f"Could not import Chart of Accounts: {type(exc).__name__}: {exc}")
                with st.expander("Technical error details", expanded=True):
                    st.exception(exc)

    with st.expander("Add account", expanded=False):
        with st.form("coa_add_account_form", clear_on_submit=True):
            a1, a2 = st.columns(2)
            account_name = a1.text_input("Account Name")
            account_type = a2.selectbox("Account Type", account_type_options, disabled=not account_type_options)
            a3, a4, a5 = st.columns(3)
            notes_line = a3.selectbox("Notes Line", notes_options)
            ifrs_line = a4.selectbox("IFRS Line", ifrs_options)
            statement_label = a5.selectbox("Statement", statement_options)
            cash_flow_classification = st.selectbox("Cash Flow Classification", cash_flow_options, key=f"coa_add_cf_{entity['entity_code']}")
            add_account = st.form_submit_button("Add to Chart of Accounts", type="primary")
        if add_account:
            try:
                if not notes_line or not ifrs_line or not statement_label:
                    raise ValueError("Select a Notes Line, IFRS Line and Statement from the Mapping Catalogue.")
                code = COA.save_account(entity['entity_code'], account_name, account_type, notes_line, ifrs_line, statement_label, cash_flow_classification=cash_flow_classification)
                audit("COA_ACCOUNT_ADDED", f"{code} — {account_name}")
                st.success(f"Account added with generated code {code}.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    accounts = COA.list_accounts(entity['entity_code'])
    st.markdown("#### Account register")
    st.caption(f"{len(accounts)} active account(s) for {entity['entity_code']}. Edit the account details and save changes below.")
    display_rows = [{
        "Delete": False,
        "Account Code": x["account_code"],
        "Account Name": x["account_name"],
        "Account Type": x["account_type"],
        "Notes Line": x.get("notes_line") or "",
        "Cash Flow Classification": x.get("cash_flow_classification") or "",
        "IFRS Line": x.get("ifrs_line") or "",
        "Statement": "Profit or Loss" if x.get("statement_type") == "PL" else ("Financial Position" if x.get("statement_type") == "BS" else ""),
    } for x in accounts]
    coa_df = pd.DataFrame(display_rows, columns=["Delete", "Account Code", "Account Name", "Account Type", "Notes Line", "Cash Flow Classification", "IFRS Line", "Statement"])
    edited_coa = st.data_editor(
        coa_df, use_container_width=True, hide_index=True, num_rows="fixed",
        key=f"coa_editor_{entity['entity_code']}",
        column_config={
            "Delete": st.column_config.CheckboxColumn("Delete", help="Select multiple accounts for permanent deletion"),
            "Account Code": st.column_config.TextColumn("Account Code", disabled=True),
            "Account Name": st.column_config.TextColumn("Account Name", required=True),
            "Account Type": st.column_config.SelectboxColumn("Account Type", options=[""] + account_type_options, required=True),
            "Notes Line": st.column_config.SelectboxColumn("Notes Line", options=notes_options),
            "Cash Flow Classification": st.column_config.SelectboxColumn("Cash Flow Classification", options=cash_flow_options),
            "IFRS Line": st.column_config.SelectboxColumn("IFRS Line", options=ifrs_options),
            "Statement": st.column_config.SelectboxColumn("Statement", options=statement_options),
        },
        disabled=["Account Code"],
    )
    selected_delete = edited_coa[edited_coa["Delete"] == True]
    save_col, delete_col = st.columns([1, 1])
    if delete_col.button(
        f"Delete selected accounts permanently ({len(selected_delete)})",
        key=f"delete_coa_{entity['entity_code']}",
        disabled=selected_delete.empty,
    ):
        try:
            selected_codes = selected_delete["Account Code"].astype(str).tolist()
            deleted = COA.bulk_delete_accounts(entity['entity_code'], selected_codes)
            audit("COA_ACCOUNTS_DELETED", f"Permanently deleted {deleted} account(s): {', '.join(selected_codes)}")
            st.success(f"{deleted} account(s) permanently deleted. Imported trial-balance rows were retained and detached from the deleted account codes.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if save_col.button("Save Chart of Accounts changes", type="primary", key=f"save_coa_{entity['entity_code']}", disabled=not accounts):
        try:
            saved = 0
            for _, row in edited_coa.iterrows():
                code = str(row.get("Account Code") or "").strip()
                if not code:
                    continue
                COA.save_account(
                    entity['entity_code'], row.get("Account Name"), row.get("Account Type"),
                    row.get("Notes Line"), row.get("IFRS Line"), row.get("Statement"), account_code=code,
                    cash_flow_classification=row.get("Cash Flow Classification")
                )
                saved += 1
            audit("COA_UPDATED", f"Updated {saved} Chart of Accounts row(s)")
            st.success(f"Saved {saved} account(s). Their COA mappings are now available to Trial Balance uploads and financial reports.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.markdown("#### Mapping completeness")
    if accounts:
        mapped = sum(1 for x in accounts if x.get("account_type") in account_type_options and x.get("notes_line") and x.get("ifrs_line") and x.get("statement_type") and x.get("cash_flow_classification"))
        m1, m2 = st.columns(2)
        m1.metric("Fully mapped accounts", mapped)
        m2.metric("Require mapping", len(accounts) - mapped)
        if mapped < len(accounts):
            st.warning("Complete the Notes Line, IFRS Line, Statement and Cash Flow Classification selections for all accounts before approving Trial Balances that contain them.")


elif page=="Generate Financial Report":
    st.subheader("IFRS Financial Statements")
    st.caption("Financial statement lines are classified directly from the IFRS Line assigned to each account in the Chart of Accounts. No account-name or account-type classification is applied here.")
    imports=TB.list_imports(entity['entity_code'])
    if not imports:
        st.info("Import a trial balance before generating the financial statements.")
    else:
        years=sorted({int(x["fiscal_year"]) for x in imports},reverse=True)
        year=st.selectbox("Financial year",years,key=f"ifrs_report_year_{entity['entity_code']}")
        year_imports=[x for x in imports if int(x["fiscal_year"])==year]
        period_type=st.radio("Reporting period",["Monthly","Quarterly","Half-year","Annual"],horizontal=True,key=f"ifrs_report_period_type_{entity['entity_code']}")
        available_months={int(x["fiscal_month"]):x for x in year_imports}
        if period_type=="Monthly":
            selected=st.selectbox("Month",sorted(available_months),format_func=lambda m:datetime(2000,m,1).strftime("%B"),key=f"ifrs_report_month_{entity['entity_code']}")
            pl_months=[selected]; closing_month=selected
        elif period_type=="Quarterly":
            quarter=st.selectbox("Quarter",["Q1","Q2","Q3","Q4"],key=f"ifrs_report_quarter_{entity['entity_code']}")
            q=int(quarter[1]); pl_months=list(range((q-1)*3+1,q*3+1)); closing_month=q*3
        elif period_type=="Half-year":
            half=st.selectbox("Half-year",["H1","H2"],key=f"ifrs_report_half_{entity['entity_code']}")
            pl_months=list(range(1,7)) if half=="H1" else list(range(7,13)); closing_month=6 if half=="H1" else 12
        else:
            pl_months=list(range(1,13)); closing_month=12

        missing=[m for m in pl_months if m not in available_months]
        selected_pl_imports=[available_months[m] for m in pl_months if m in available_months]
        closing_import=available_months.get(closing_month)
        prior_year_imports=[x for x in imports if int(x["fiscal_year"])==year-1 and int(x["fiscal_month"]) in pl_months]
        prior_closing=next((x for x in imports if int(x["fiscal_year"])==year-1 and int(x["fiscal_month"])==closing_month),None)
        pl_frame=AM.statement_data([x["import_id"] for x in selected_pl_imports],entity['entity_code']) if selected_pl_imports else pd.DataFrame()
        prior_pl_frame=AM.statement_data([x["import_id"] for x in prior_year_imports],entity['entity_code']) if prior_year_imports else pd.DataFrame()
        # Use the same mapping-aware statement dataset as the P&L report.
        # RX.period_frame is retained separately for cash-flow/equity schedules;
        # it may not carry the COA Statement/IFRS Line/Notes Line fields.
        bs_schedule_frame=RX.period_frame(closing_import,entity['entity_code']) if closing_import else pd.DataFrame()
        prior_bs_schedule_frame=RX.period_frame(prior_closing,entity['entity_code']) if prior_closing else pd.DataFrame()
        bs_frame=AM.statement_data([closing_import["import_id"]],entity['entity_code']) if closing_import else pd.DataFrame()
        prior_bs_frame=AM.statement_data([prior_closing["import_id"]],entity['entity_code']) if prior_closing else pd.DataFrame()
        currency=entity["functional_currency"]
        pl_amounts=_statement_amounts(pl_frame,"PL",currency)
        prior_pl_amounts=_statement_amounts(prior_pl_frame,"PL",currency)
        bs_amounts=_statement_amounts(bs_frame,"BS",currency)
        prior_bs_amounts=_statement_amounts(prior_bs_frame,"BS",currency)
        bs_note_lookup=_bs_notes_lookup(bs_frame)
        current_note_amounts=_bs_amounts_by_ifrs_and_note(bs_frame)
        prior_note_amounts=_bs_amounts_by_ifrs_and_note(prior_bs_frame)
        current_pl=_build_pl_report(pl_amounts)
        prior_pl={r[0]:r[1] for r in _build_pl_report(prior_pl_amounts)}
        pl_rows=[(label,float(amount),float(prior_pl.get(label,0.0)),kind) for label,amount,kind in current_pl]

        # Present the current-period result as a separate equity component on the
        # Statement of Financial Position. The comparative result is sourced from
        # the corresponding prior-year P&L period. This also brings the equity
        # total into agreement with assets less liabilities when retained earnings
        # excludes the current-period result.
        net_profit_label="Net profit/(loss) for the period"
        current_net_profit=float(next((r[1] for r in current_pl if r[0]==net_profit_label),0.0))
        prior_net_profit=float(prior_pl.get(net_profit_label,0.0))
        current_note_amounts[("Net profit/(loss)", "Net profit/(loss)")]=current_net_profit
        if prior_bs_frame is not None and not prior_bs_frame.empty:
            prior_note_amounts[("Net profit/(loss)", "Net profit/(loss)")]=prior_net_profit
        bs_rows=_build_bs_report_with_notes(current_note_amounts, prior_note_amounts)
        period_label=(datetime(year,pl_months[0],1).strftime("%B %Y") if len(pl_months)==1 else f"{period_type} ended {datetime(year,closing_month,1).strftime('%B %Y')}")
        comparative_label=(datetime(year-1,pl_months[0],1).strftime("%B %Y") if len(pl_months)==1 and (prior_year_imports or prior_closing)
                           else f"{period_type} ended {datetime(year-1,closing_month,1).strftime('%B %Y')}" if (prior_year_imports or prior_closing)
                           else "Comparative unavailable")
        current_column_label = datetime(year, closing_month, 1).strftime("%b %y")
        comparative_column_label = datetime(year-1, closing_month, 1).strftime("%b %y") if (prior_year_imports or prior_closing) else "Comparative"

        if missing:
            st.warning("Missing monthly trial balance(s): "+", ".join(datetime(2000,m,1).strftime("%b") for m in missing)+". Profit or loss includes only available months.")
        if not closing_import:
            st.error(f"A closing trial balance for {datetime(year,closing_month,1).strftime('%B %Y')} is required for the Statement of Financial Position and cannot be prepared yet.")
        else:
            st.markdown(f"### {entity['entity_name']}\n**{period_label}** · Functional currency: **{currency}**")
            status=str(closing_import.get("status") or "DRAFT")
            k1,k2,k3=st.columns(3)
            k1.metric("Reporting period",period_label)
            k2.metric("Closing TB status",status)
            k3.metric("IFRS lines populated",len(set(bs_amounts.keys())|set(pl_amounts.keys())))
            if status!="APPROVED":
                st.warning("The closing trial balance is not approved. Treat this report as a draft for review.")
            if not prior_year_imports and not prior_closing:
                st.info("No corresponding prior-year trial balance was found. Comparative amounts are shown as nil.")

            cash_rows,equity_rows,note_rows=_full_ifrs_schedules(entity,year,closing_month,imports,pl_frame,bs_schedule_frame)
            prior_cash_rows=[]; prior_equity_rows=[]; prior_note_rows=[]
            if not prior_pl_frame.empty or not prior_bs_schedule_frame.empty:
                prior_cash_rows,prior_equity_rows,prior_note_rows=_full_ifrs_schedules(
                    entity,year-1,closing_month,imports,prior_pl_frame,prior_bs_schedule_frame
                )
            prior_cash_map={r[0]:r[1] for r in prior_cash_rows}
            cash_comparatives=[(r[0],r[1],prior_cash_map.get(r[0]) if prior_cash_rows else None) for r in cash_rows]
            prior_equity_map={r[0]:r for r in prior_equity_rows}
            equity_comparatives=[(r[0],*r[1:],*(prior_equity_map.get(r[0],(None,None,None,None,None,None,None))[1:])) for r in equity_rows]
            prior_note_map={r[0]:r for r in prior_note_rows}
            notes_comparatives=[(r[0],r[1],r[2],prior_note_map.get(r[0],(None,None,None,None,None,None))[2] if prior_note_rows else None,r[3],r[4],r[5]) for r in note_rows]
            tabs=st.tabs(["Statement of Profit or Loss","Statement of Financial Position","Statement of Cash Flows","Statement of Changes in Equity","Notes & Disclosures","Basis and checks"])
            with tabs[0]:
                st.markdown("#### Statement of Profit or Loss and Other Comprehensive Income")
                st.caption(f"For the {period_label} · {currency}")
                show_dataframe(pd.DataFrame([{"IFRS Line":r[0],current_column_label:r[1],comparative_column_label:r[2],"Presentation":r[3]} for r in pl_rows]),use_container_width=True,hide_index=True)
                if not pl_amounts: st.info("No Profit or Loss accounts have an IFRS Line classified to Profit or Loss in the Chart of Accounts.")
            with tabs[1]:
                st.markdown("#### Statement of Financial Position")
                st.caption(f"As at {datetime(year,closing_month,1).strftime('%B %Y')} · {currency}")
                show_dataframe(pd.DataFrame([{"IFRS Line": r[0],current_column_label:r[1],comparative_column_label:r[2]} for r in bs_rows]),use_container_width=True,hide_index=True)
                if not bs_amounts:
                    st.error("The report did not receive usable mapped Balance Sheet balances for this closing import.")
                    if bs_frame is not None and not bs_frame.empty:
                        diag_cols = [c for c in ("account_name", "account_code", "statement_type", "statement_line", "notes_line", "debit", "credit", "balance") if c in bs_frame.columns]
                        st.caption(f"Mapping dataset contains {len(bs_frame)} rows. Statement classifications received: {sorted(bs_frame['statement_type'].dropna().astype(str).unique().tolist()) if 'statement_type' in bs_frame.columns else 'statement_type column missing'}.")
                        if diag_cols:
                            show_dataframe(bs_frame[diag_cols].head(100), use_container_width=True, hide_index=True)
                    else:
                        st.warning("The mapping-aware statement dataset is empty for the selected import. Check the import ID and account mapping links.")
            with tabs[2]:
                st.markdown("#### Statement of Cash Flows — IAS 7 (indirect method)")
                show_dataframe(pd.DataFrame(cash_comparatives,columns=["Description",current_column_label,comparative_column_label]),use_container_width=True,hide_index=True)
                st.caption("Comparatives use the corresponding prior-year period and its saved schedules where available. Missing prior-year inputs remain blank, not zero.")
            with tabs[3]:
                st.markdown("#### Statement of Changes in Equity")
                show_dataframe(pd.DataFrame(equity_comparatives,columns=["Equity component","Opening balance","Profit for period","Other comprehensive income","Other movements","Calculated closing balance","TB closing balance","Prior opening balance","Prior profit","Prior OCI","Prior other movements","Prior calculated closing","Prior TB closing"]),use_container_width=True,hide_index=True)
            with tabs[4]:
                st.markdown("#### Notes and Disclosures")
                show_dataframe(pd.DataFrame(notes_comparatives,columns=["Note","Title","Current TB amount","Prior-year TB amount","Manual amount","Narrative","Status"]),use_container_width=True,hide_index=True)
                st.metric("Notes requiring completion",sum(1 for r in note_rows if r[5] not in ("Complete","Not applicable")))
            with tabs[5]:
                st.write("Account classification is taken from the IFRS Line and Statement selections in the Chart of Accounts, which are linked to the Mapping Catalogue.")
                st.write("Profit or Loss includes the selected reporting months. Financial Position uses the closing month-end trial balance.")
                st.write("Comparative Profit or Loss uses the corresponding prior-year months; comparative Financial Position uses the prior-year closing month.")
                liability_equity_tokens=("liabilit","payable","borrow","loan","lease obligation","deferred income","contract liabilit","equity","capital","retained earning","share","provision")
                total_assets=sum(v for k,v in bs_amounts.items() if not any(t in str(k).casefold() for t in liability_equity_tokens))
                total_liabilities_equity=sum(v for k,v in bs_amounts.items() if any(t in str(k).casefold() for t in liability_equity_tokens))
                difference=total_assets-total_liabilities_equity
                st.metric("Statement of Financial Position difference",f"{difference:,.2f} {currency}")
                if abs(difference)>0.01:
                    st.error("The Statement of Financial Position does not balance. Review unmapped or incorrectly classified IFRS Lines and the underlying trial balance.")
                else:
                    st.success("Total Assets agree to Total Liabilities and Equity.")
                # Reconcile the generated P&L result to all mapped P&L account balances.
                oci_labels={"other comprehensive income", "other comprehensive loss", "other comprehensive income loss"}
                mapped_pl_total=sum(
                    float(value or 0.0) for label,value in pl_amounts.items()
                    if re.sub(r"[^a-z0-9]+", " ", str(label).casefold()).strip() not in oci_labels
                )
                reported_net_profit=float(next((r[1] for r in current_pl if r[0]=="Net profit/(loss) for the period"),0.0))
                pl_reconciliation_difference=mapped_pl_total-reported_net_profit
                st.metric("P&L reconciliation difference",f"{pl_reconciliation_difference:,.2f} {currency}")
                if abs(pl_reconciliation_difference)>0.01:
                    st.error("The mapped P&L account balances do not reconcile to the reported net profit/(loss). Review P&L mappings and statement-line classifications before authorisation.")
                else:
                    st.success("Mapped P&L account balances reconcile to net profit/(loss).")
                unmapped=int(pl_frame["statement_line"].isna().sum()) if not pl_frame.empty and "statement_line" in pl_frame else 0
                st.metric("Unmapped Profit or Loss rows",unmapped)
                st.warning("Review all mappings, cash flow supporting schedules, equity movements, note disclosures, accounting policies and disclosure evidence before authorisation.")

            st.markdown("#### Corporate information for the report")
            st.caption("These details are not held in the trial balance. Enter or update them here; they are saved with the selected reporting period and inserted into the report.")
            profile_saved=RX.get_inputs(entity['entity_code'],year,closing_month,'REPORT_PROFILE') or RX.get_latest_inputs(entity['entity_code'],year,closing_month,'REPORT_PROFILE')
            if profile_saved:
                profile_editor=pd.DataFrame([
                    {"Code":x["input_code"],"Corporate information":x.get("description") or x["input_code"],
                     "Information":x.get("narrative") or "", "Status":x.get("status") or "Draft"}
                    for x in profile_saved
                ])
            else:
                profile_editor=pd.DataFrame([
                    {"Code":code,"Corporate information":label,"Information":"", "Status":"Draft"}
                    for code,label in REPORT_PROFILE_FIELDS
                ])
            edited_profile=st.data_editor(
                profile_editor,use_container_width=True,hide_index=True,num_rows="dynamic",
                key=f"report_profile_{entity['entity_code']}_{year}_{closing_month}",
                column_config={
                    "Code":st.column_config.TextColumn("Field code"),
                    "Corporate information":st.column_config.TextColumn("Information heading",required=True),
                    "Information":st.column_config.TextColumn("Company information",width="large"),
                    "Status":st.column_config.SelectboxColumn("Status", options=["Draft", "In progress", "Complete", "Not applicable"], required=True)
                })
            if st.button("Save corporate information",key=f"save_report_profile_{entity['entity_code']}_{year}_{closing_month}"):
                records=[]; used_codes=set()
                for idx,r in enumerate(edited_profile.to_dict('records'),start=1):
                    label=str(r.get("Corporate information") or "").strip()
                    info=str(r.get("Information") or "").strip()
                    status=str(r.get("Status") or "Draft").strip() or "Draft"
                    code=re.sub(r"[^A-Z0-9]+","_",str(r.get("Code") or "").strip().upper()).strip("_")
                    if not label and not info and not code: continue
                    if not label: st.error(f"Row {idx}: enter an information heading."); st.stop()
                    if not code: code=re.sub(r"[^A-Z0-9]+","_",label.upper()).strip("_")
                    if code in used_codes: st.error(f"Duplicate field code '{code}'."); st.stop()
                    used_codes.add(code)
                    records.append({"Code":code,"Description":label,"Amount":0,"Commentary":info,"Status":status})
                RX.save_inputs(entity['entity_code'],year,closing_month,'REPORT_PROFILE',records)
                audit("REPORT_PROFILE_SAVED",f"Corporate report information saved for {year}-{closing_month:02d}",year,closing_month)
                st.success("Corporate information saved.")
                st.rerun()
            report_profile_rows=RX.get_inputs(entity['entity_code'],year,closing_month,'REPORT_PROFILE') or RX.get_latest_inputs(entity['entity_code'],year,closing_month,'REPORT_PROFILE')
            report_profile={x['input_code']:x.get('narrative') or '' for x in report_profile_rows}
            report_profile["__LABELS__"]={x['input_code']:x.get('description') or x['input_code'] for x in report_profile_rows}

            st.markdown("#### Export complete financial statements package")
            d1,d2=st.columns(2)
            try:
                excel_bytes=_full_excel_bytes(entity,period_label,currency,pl_rows,bs_rows,cash_comparatives,equity_comparatives,notes_comparatives,current_column_label,comparative_column_label,report_profile)
                d1.download_button("Download complete IFRS Excel report",data=excel_bytes,file_name=f"IFRS_Financial_Report_{entity['entity_code']}_{year}_{closing_month:02d}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key=f"ifrs_excel_{entity['entity_code']}_{year}_{closing_month}",use_container_width=True)
            except Exception as exc:
                d1.error(f"Could not prepare Excel report: {exc}")
            try:
                pdf_bytes=_full_pdf_bytes(entity,period_label,currency,pl_rows,bs_rows,cash_comparatives,equity_comparatives,notes_comparatives,current_column_label,comparative_column_label,report_profile)
                d2.download_button("Download complete IFRS PDF report",data=pdf_bytes,file_name=f"IFRS_Financial_Report_{entity['entity_code']}_{year}_{closing_month:02d}.pdf",mime="application/pdf",key=f"ifrs_pdf_{entity['entity_code']}_{year}_{closing_month}",use_container_width=True)
            except Exception as exc:
                d2.error(f"Could not prepare PDF report: {exc}")

elif page=="Cash Flow Statement":
    st.subheader("Statement of Cash Flows — IAS 7 (indirect method)")
    imports=TB.list_imports(entity['entity_code'])
    if not imports:
        st.info("Import a trial balance before preparing the cash flow statement.")
    else:
        years=sorted({int(x['fiscal_year']) for x in imports},reverse=True)
        y=st.selectbox("Financial year",years,key="cf_year")
        year_imports=[x for x in imports if int(x['fiscal_year'])==y]
        month_choices=sorted({int(x['fiscal_month']) for x in year_imports})
        m=st.selectbox("Reporting month",month_choices,format_func=lambda x:datetime(2000,x,1).strftime("%B"),key="cf_month")
        current=next((x for x in year_imports if int(x['fiscal_month'])==m),None)
        current_frame=RX.period_frame(current,entity['entity_code']) if current else pd.DataFrame()
        prior_y,prior_m=(y-1,12) if m==1 else (y,m-1)
        prior=next((x for x in imports if int(x['fiscal_year'])==prior_y and int(x['fiscal_month'])==prior_m),None)
        prior_frame=RX.period_frame(prior,entity['entity_code']) if prior else pd.DataFrame()
        if current is None:
            st.error("No trial balance exists for the selected reporting month.")
        else:
            current_bs=RX.balance_by_line(current_frame)
            prior_bs=RX.balance_by_line(prior_frame)
            cf_schedule=RX.cash_flow_classification_schedule(current_frame, prior_frame)
            pl=RX.profit_and_loss(current_frame)
            st.caption("Operating working-capital movements are calculated from the selected and preceding month-end trial balances. Investing and financing transactions are maintained in separate supporting schedules.")
            cash_open=cf_schedule["cash_open"]
            cash_close=cf_schedule["cash_close"]
            if cash_close is None:
                st.warning("Map the relevant bank and cash accounts to 'Cash and cash equivalents' to enable the cash reconciliation.")

            existing=RX.get_inputs(entity['entity_code'],y,m,"CASH_FLOW")
            by_code={x['input_code']:x for x in existing}

            # Prepare the three activity schedules before rendering the tabs.
            op_defaults=[
                ("DEPR","Depreciation and amortisation",0.0),
                ("IMPAIR","Impairment and expected credit losses",0.0),
                ("DISPOSAL","Loss/(gain) on disposal of assets",0.0),
                ("FINANCE_ADD","Finance costs added back",float(pl.get("Finance costs",0))),
                ("OTHER_NONCASH","Other non-cash adjustments",0.0),
                ("INTEREST_PAID","Interest paid (cash outflow)",0.0),
                ("TAX_PAID","Income taxes paid (cash outflow)",0.0),
            ]
            operating_rows=[]
            for code,label,default in op_defaults:
                rec=by_code.get(code,{})
                amount=rec.get('amount',default) if rec else default
                operating_rows.append({"Code":code,"Description":label,"Amount":float(amount or 0),"Commentary":rec.get('narrative','')})

            # Automatically classified operating adjustments and working capital.
            auto_noncash_rows=cf_schedule["noncash"]
            auto_noncash=sum(float(x["Cash Flow"] or 0) for x in auto_noncash_rows)
            auto_investing=sum(float(x["Cash Flow"] or 0) for x in cf_schedule["investing"])
            auto_financing=sum(float(x["Cash Flow"] or 0) for x in cf_schedule["financing"])
            wc_rows=[]
            if prior is not None:
                for item in cf_schedule["working_capital"]:
                    wc_rows.append({
                        "Account Code":item["Account Code"], "Account Name":item.get("Account Name") or "Account name not assigned",
                        "Classification":item["Cash Flow Classification"], "Opening balance":item["Opening Balance"],
                        "Closing balance":item["Closing Balance"], "Change in balance":item["Movement"],
                        "Cash flow":item["Cash Flow"]
                    })

            investing_defaults=[
                ("PPE_PURCHASE","Purchase of property, plant and equipment",0.0),
                ("PPE_PROCEEDS","Proceeds from disposal of property, plant and equipment",0.0),
                ("INTANGIBLE_PURCHASE","Purchase of intangible assets",0.0),
                ("INTANGIBLE_PROCEEDS","Proceeds from disposal of intangible assets",0.0),
                ("INVESTMENT_PURCHASE","Purchase of investments",0.0),
                ("INVESTMENT_PROCEEDS","Proceeds from disposal of investments",0.0),
                ("OTHER_INVESTING","Other investing cash flows",0.0),
            ]
            investing_rows=[]
            for code,label,default in investing_defaults:
                rec=by_code.get(code,{})
                investing_rows.append({"Code":code,"Description":label,"Amount":float(rec.get('amount',default) or 0),"Commentary":rec.get('narrative','')})

            financing_defaults=[
                ("BORROWINGS_PROCEEDS","Proceeds from borrowings",0.0),
                ("BORROWINGS_REPAY","Repayment of borrowings",0.0),
                ("LEASE_PAYMENTS","Lease principal payments",0.0),
                ("SHARES_ISSUED","Proceeds from issue of shares",0.0),
                ("DIVIDENDS_PAID","Dividends paid",0.0),
                ("OTHER_FINANCING","Other financing cash flows",0.0),
            ]
            financing_rows=[]
            for code,label,default in financing_defaults:
                rec=by_code.get(code,{})
                financing_rows.append({"Code":code,"Description":label,"Amount":float(rec.get('amount',default) or 0),"Commentary":rec.get('narrative','')})

            activity_tabs=st.tabs(["Financing Activities","Operating Activities","Investing Activities"])
            with activity_tabs[0]:
                st.caption("Record borrowings, lease principal, share capital and dividends. Proceeds are positive; repayments and distributions are negative.")
                financing_edit=st.data_editor(pd.DataFrame(financing_rows),use_container_width=True,hide_index=True,key=f"cf_financing_{entity['entity_code']}_{y}_{m}",disabled=["Code","Description"],column_config={"Amount":st.column_config.NumberColumn("Amount (cash-flow sign)",help="Proceeds positive; repayments and dividends negative.",format="%,.2f")})
                if cf_schedule["financing"]:
                    st.markdown("**Automatically classified financing account movements**")
                    show_dataframe(pd.DataFrame([{
                        "Account Code":x["Account Code"], "Account Name":x.get("Account Name") or "Account name not assigned",
                        "Opening balance":x["Opening Balance"], "Closing balance":x["Closing Balance"],
                        "Movement":x["Movement"], "Cash flow":x["Cash Flow"]
                    } for x in cf_schedule["financing"]]),use_container_width=True,hide_index=True)
                else:
                    st.info("No accounts are currently classified as Financing Activity.")

            with activity_tabs[1]:
                st.caption("The engine adds P&L accounts classified as Operating – Non-cash Adjustment automatically. Use supporting inputs only for additional/reconciling items and actual cash interest/tax payments; do not duplicate automatically classified accounts.")
                operating_edit=st.data_editor(pd.DataFrame(operating_rows),use_container_width=True,hide_index=True,key=f"cf_operating_{entity['entity_code']}_{y}_{m}",disabled=["Code","Description"],column_config={"Amount":st.column_config.NumberColumn("Amount (cash-flow sign)",help="Enter cash inflows/add-backs as positive and cash outflows as negative.",format="%,.2f")})
                if prior is not None and wc_rows:
                    st.markdown("**Working-capital movements — calculated from COA classifications**")
                    show_dataframe(pd.DataFrame(wc_rows),use_container_width=True,hide_index=True)
                elif prior is None:
                    st.warning(f"The preceding month-end trial balance ({prior_y}-{prior_m:02d}) is not available. Balance movements are not calculated using zero opening balances.")
                else:
                    st.info("No accounts are classified as Operating – Working Capital Asset or Operating – Working Capital Liability. Assign these classifications in the Chart of Accounts.")
                if auto_noncash_rows:
                    st.markdown("**Automatically classified non-cash P&L adjustments**")
                    show_dataframe(pd.DataFrame([{
                        "Account Code":x["Account Code"], "Account Name":x.get("Account Name") or "Account name not assigned",
                        "Cash Flow Classification":x["Cash Flow Classification"], "Cash flow":x["Cash Flow"]
                    } for x in auto_noncash_rows]),use_container_width=True,hide_index=True)
                else:
                    st.info("No Profit or Loss accounts are classified as Operating – Non-cash Adjustment.")
                if cf_schedule["unmapped"]:
                    with st.expander(f"Accounts without a Cash Flow Classification ({len(cf_schedule['unmapped'])})"):
                        show_dataframe(pd.DataFrame(cf_schedule["unmapped"]),use_container_width=True,hide_index=True)

            with activity_tabs[2]:
                st.caption("Record cash paid/received for long-term assets and investments. Purchases are negative; proceeds are positive.")
                investing_edit=st.data_editor(pd.DataFrame(investing_rows),use_container_width=True,hide_index=True,key=f"cf_investing_{entity['entity_code']}_{y}_{m}",disabled=["Code","Description"],column_config={"Amount":st.column_config.NumberColumn("Amount (cash-flow sign)",help="Purchases/payments negative; proceeds/receipts positive.",format="%,.2f")})
                if cf_schedule["investing"]:
                    st.markdown("**Automatically classified investing account movements**")
                    show_dataframe(pd.DataFrame([{
                        "Account Code":x["Account Code"], "Account Name":x.get("Account Name") or "Account name not assigned",
                        "Opening balance":x["Opening Balance"], "Closing balance":x["Closing Balance"],
                        "Movement":x["Movement"], "Cash flow":x["Cash Flow"]
                    } for x in cf_schedule["investing"]]),use_container_width=True,hide_index=True)
                else:
                    st.info("No accounts are currently classified as Investing Activity.")

            if st.button("Save cash flow schedules",type="primary",key=f"save_cf_{entity['entity_code']}_{y}_{m}"):
                all_inputs=pd.concat([operating_edit,investing_edit,financing_edit],ignore_index=True)
                RX.save_inputs(entity['entity_code'],y,m,"CASH_FLOW",all_inputs.to_dict('records'))
                audit("CASH_FLOW_SCHEDULE_SAVED",f"Cash flow schedules saved for {y}-{m:02d}",y,m)
                st.success("Operating, investing and financing schedules saved separately.")
                st.rerun()

            saved=RX.get_inputs(entity['entity_code'],y,m,"CASH_FLOW")
            saved_amount={x['input_code']:float(x['amount'] or 0) for x in saved}
            # Use displayed defaults until the user saves the schedule for the first time.
            for code,_,default in op_defaults + investing_defaults + financing_defaults:
                saved_amount.setdefault(code,float(default or 0))
            op_codes=[x[0] for x in op_defaults]
            investing_codes=[x[0] for x in investing_defaults]
            financing_codes=[x[0] for x in financing_defaults]
            op_adjustments=sum(saved_amount.get(code,0) for code in op_codes)
            wc_total=sum(x['Cash flow'] for x in wc_rows)
            cfo=float(pl.get("Profit before tax",0))+auto_noncash+op_adjustments+wc_total
            cfi=auto_investing+sum(saved_amount.get(code,0) for code in investing_codes)
            cff=auto_financing+sum(saved_amount.get(code,0) for code in financing_codes)
            net_change=cfo+cfi+cff

            st.markdown("### Statement of cash flows")
            statement_rows=[
                {"Description":"OPERATING ACTIVITIES","Amount":None},
                {"Description":"Profit before tax","Amount":float(pl.get("Profit before tax",0))},
            ]
            statement_rows.extend({"Description":f"  {label}","Amount":amount} for label,amount in _aggregate_cashflow_notes(auto_noncash_rows, 'Cash Flow'))
            statement_rows.append({"Description":"Additional non-cash and other operating adjustments","Amount":op_adjustments})
            statement_rows.extend({"Description":f"  {label}","Amount":amount} for label,amount in _aggregate_cashflow_notes(wc_rows, 'Cash flow'))
            statement_rows.extend([
                {"Description":"Net cash generated from/(used in) operating activities","Amount":cfo},
                {"Description":"INVESTING ACTIVITIES","Amount":None},
            ])
            statement_rows.extend({"Description":f"  {label}","Amount":amount} for label,amount in _aggregate_cashflow_notes(cf_schedule['investing'], 'Cash Flow'))
            statement_rows.extend({"Description":label,"Amount":saved_amount.get(code,0)} for code,label,_ in investing_defaults)
            statement_rows.extend([
                {"Description":"Net cash generated from/(used in) investing activities","Amount":cfi},
                {"Description":"FINANCING ACTIVITIES","Amount":None},
            ])
            statement_rows.extend({"Description":f"  {label}","Amount":amount} for label,amount in _aggregate_cashflow_notes(cf_schedule['financing'], 'Cash Flow'))
            statement_rows.extend({"Description":label,"Amount":saved_amount.get(code,0)} for code,label,_ in financing_defaults)
            statement_rows.extend([
                {"Description":"Net cash generated from/(used in) financing activities","Amount":cff},
                {"Description":"Net increase/(decrease) in cash and cash equivalents","Amount":net_change},
                {"Description":"Opening cash and cash equivalents","Amount":cash_open},
                {"Description":"Closing cash and cash equivalents per statement of financial position","Amount":cash_close},
            ])
            show_dataframe(pd.DataFrame(statement_rows),use_container_width=True,hide_index=True)
            if cash_open is not None and cash_close is not None:
                difference=(cash_close-cash_open)-net_change
                st.metric("Cash flow reconciliation difference",f"{entity['functional_currency']} {difference:,.2f}")
                if abs(difference)<0.01:
                    st.success("Cash flow movement agrees to the change in cash and cash equivalents.")
                else:
                    st.warning("Cash flow does not yet reconcile. Review non-cash movements, foreign exchange effects, acquisitions/disposals and missing cash flow inputs.")
            else:
                st.warning("Opening or closing cash balance is unavailable. Complete the cash mapping and import the preceding month-end trial balance.")
            st.caption("Draft indirect-method working statement. Confirm the entity's IAS 7 policy for interest and dividends, and separately identify non-cash transactions and foreign-exchange effects before approval.")

elif page=="Changes in Equity":
    st.subheader("Statement of Changes in Equity")
    imports=TB.list_imports(entity['entity_code'])
    if not imports: st.info("Import a trial balance first.")
    else:
        years=sorted({int(x['fiscal_year']) for x in imports},reverse=True)
        y=st.selectbox("Financial year",years,key="eq_year")
        year_imports=[x for x in imports if int(x['fiscal_year'])==y]
        months=sorted({int(x['fiscal_month']) for x in year_imports})
        m=st.selectbox("Reporting month",months,format_func=lambda x:datetime(2000,x,1).strftime("%B"),key="eq_month")
        current=next((x for x in year_imports if int(x['fiscal_month'])==m),None)
        prior_y,prior_m=(y-1,12) if m==1 else (y,m-1)
        prior=next((x for x in imports if int(x['fiscal_year'])==prior_y and int(x['fiscal_month'])==prior_m),None)
        cur_frame=RX.period_frame(current,entity['entity_code']) if current else pd.DataFrame()
        prev_frame=RX.period_frame(prior,entity['entity_code']) if prior else pd.DataFrame()
        opening=RX.balance_by_line(prev_frame)
        closing=RX.balance_by_line(cur_frame)
        mapped_pl_frame=AM.statement_data([current['import_id']],entity['entity_code']) if current else pd.DataFrame()
        pl_rows_current=_build_pl_report(_statement_amounts(mapped_pl_frame,'PL',entity['functional_currency']))
        pl={row[0]:float(row[1]) for row in pl_rows_current}
        net_profit_value=pl.get('Net profit/(loss) for the period',pl.get('Profit for the period',0.0))
        equity_lines=[("Share capital","Share capital"),("Retained earnings","Retained earnings"),("Other reserves","Other reserves")]
        st.caption("Opening balances are taken from the preceding month-end trial balance. Profit for the period is added to retained earnings. Other movements must be supported by the relevant equity records.")
        if not prior: st.warning("No preceding month-end trial balance was found. Opening equity balances cannot be populated automatically.")
        movement_defaults=[("SHARE_ISSUE","Share capital","Issue of shares",0.0),("CAPITAL_RETURN","Share capital","Return/reduction of capital",0.0),("DIVIDEND","Retained earnings","Dividends declared/paid",0.0),("TRANSFER","Other reserves","Transfers between reserves",0.0),("RESERVE_MOVEMENT","Other reserves","Other reserve movements",0.0),("RETAINED_OTHER","Retained earnings","Other retained earnings movements",0.0)]
        saved=RX.get_inputs(entity['entity_code'],y,m,"EQUITY")
        saved_by={x['input_code']:x for x in saved}
        edit_rows=[]
        for code,component,label,default in movement_defaults:
            rec=saved_by.get(code,{})
            edit_rows.append({"Code":code,"Equity component":component,"Description":label,"Amount":float(rec.get('amount',default) or 0),"Commentary":rec.get('narrative','')})
        edited=st.data_editor(pd.DataFrame(edit_rows),use_container_width=True,hide_index=True,key=f"equity_inputs_{entity['entity_code']}_{y}_{m}",disabled=["Code","Equity component","Description"])
        if st.button("Save equity movements",type="primary",key=f"save_equity_{entity['entity_code']}_{y}_{m}"):
            RX.save_inputs(entity['entity_code'],y,m,"EQUITY",edited.rename(columns={"Equity component":"Component"}).to_dict('records'))
            audit("EQUITY_MOVEMENTS_SAVED",f"Equity movements saved for {y}-{m:02d}",y,m)
            st.success("Equity movements saved."); st.rerun()
        saved=RX.get_inputs(entity['entity_code'],y,m,"EQUITY")
        mov={x['input_code']:float(x['amount'] or 0) for x in saved}
        rows_eq=[]
        for line,label in equity_lines:
            opening_amt=float(opening.get(line,0))
            movement=sum(mov.get(code,0) for code,component,_,_ in movement_defaults if component==line)
            profit=0.0
            oci=-float(cur_frame[(cur_frame.statement_type=='PL') & (cur_frame.statement_line=='Other comprehensive income')].balance.sum()) if line=="Other reserves" and not cur_frame.empty and "statement_type" in cur_frame else 0.0
            closing_calc=opening_amt+movement+profit+oci
            rows_eq.append({"Equity component":line,"Opening balance":opening_amt,"Profit for period":profit,"Other comprehensive income":oci,"Other movements":movement,"Calculated closing balance":closing_calc,"TB closing balance":float(closing.get(line,0))})
        rows_eq.append({"Equity component":"Net profit/(loss)","Opening balance":0.0,"Profit for period":net_profit_value,"Other comprehensive income":0.0,"Other movements":0.0,"Calculated closing balance":net_profit_value,"TB closing balance":None})
        st.markdown("#### Statement of changes in equity")
        show_dataframe(pd.DataFrame(rows_eq),use_container_width=True,hide_index=True)
        st.caption("The calculated closing balance is compared with the mapped closing trial balance. Investigate differences such as prior-period adjustments, dividends, transfers, share transactions and unrecorded reserve movements.")

elif page=="Corporate Information":
    st.subheader("Corporate Information")
    st.caption("Maintain the official entity details used in the front matter of your financial statements. Information is saved by reporting period and carried forward until you update it.")

    imports = TB.list_imports(entity['entity_code'])
    saved_periods = DB.rows(
        "SELECT DISTINCT fiscal_year, fiscal_month FROM fr_reporting_inputs "
        "WHERE entity_code=? AND input_type=? ORDER BY fiscal_year DESC, fiscal_month DESC",
        (entity['entity_code'], "REPORT_PROFILE"),
    ) if not DB.is_postgres() else DB.rows(
        "SELECT DISTINCT fiscal_year, fiscal_month FROM fr_reporting_inputs "
        "WHERE entity_code=%s AND input_type=%s ORDER BY fiscal_year DESC, fiscal_month DESC",
        (entity['entity_code'], "REPORT_PROFILE"),
    )
    available_periods = {(int(x["fiscal_year"]), int(x["fiscal_month"])) for x in imports}
    available_periods.update((int(x["fiscal_year"]), int(x["fiscal_month"])) for x in saved_periods)
    if not available_periods:
        now = datetime.utcnow()
        available_periods = {(now.year, now.month)}
    years = sorted({y for y, _ in available_periods}, reverse=True)
    default_period = max(available_periods)
    c1, c2 = st.columns(2)
    profile_year = c1.selectbox("Financial year", years, index=years.index(default_period[0]), key="corp_profile_year")
    available_months = sorted(m for y, m in available_periods if y == profile_year)
    default_month = default_period[1] if default_period[0] == profile_year else max(available_months)
    profile_month = c2.selectbox("Effective reporting period", available_months,
                                 index=available_months.index(default_month),
                                 format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
                                 key="corp_profile_month")
    period_label = datetime(profile_year, profile_month, 1).strftime("%B %Y")

    exact_profile = RX.get_inputs(entity['entity_code'], profile_year, profile_month, "REPORT_PROFILE")
    inherited_profile = RX.get_latest_inputs(entity['entity_code'], profile_year, profile_month, "REPORT_PROFILE")
    profile_saved = exact_profile or inherited_profile
    if profile_saved:
        profile_editor = pd.DataFrame([
            {"Code": x["input_code"], "Corporate information": x.get("description") or x["input_code"],
             "Information": x.get("narrative") or "", "Status": x.get("status") or "Draft"}
            for x in profile_saved
        ])
        source_period = (profile_saved[0].get("fiscal_year"), profile_saved[0].get("fiscal_month"))
        if not exact_profile:
            st.info(f"Showing the latest saved corporate information from {int(source_period[0])}-{int(source_period[1]):02d}. Saving will create a separate version for {period_label} and will not overwrite the earlier period.")
        else:
            st.caption(f"Corporate information saved for {period_label}.")
    else:
        profile_editor = pd.DataFrame([
            {"Code": code, "Corporate information": label, "Information": "", "Status": "Draft"}
            for code, label in REPORT_PROFILE_FIELDS
        ])
        st.info("No previous corporate information was found. Complete the fields below.")

    # Corporate information is maintained through a focused narrative editor rather
    # than a grid at the top of the page. This avoids duplicate editing surfaces.
    corporate_rows = profile_editor.to_dict("records")
    corporate_options = {
        f"{str(row.get('Code') or '').strip()} — {str(row.get('Corporate information') or '').strip()}": index
        for index, row in enumerate(corporate_rows)
        if str(row.get("Code") or "").strip() or str(row.get("Corporate information") or "").strip()
    }

    st.markdown("#### View and edit saved corporate information")
    if corporate_options:
        selected_corporate_label = st.selectbox(
            "Select information to view or edit",
            list(corporate_options.keys()),
            key=f"corporate_profile_view_select_{entity['entity_code']}_{profile_year}_{profile_month}",
        )
        selected_corporate_index = corporate_options[selected_corporate_label]
        selected_corporate_row = corporate_rows[selected_corporate_index]
        selected_corporate_code = str(selected_corporate_row.get("Code") or "CUSTOM").strip()
        narrative_key = f"corporate_profile_narrative_{entity['entity_code']}_{profile_year}_{profile_month}_{selected_corporate_code}"
        selected_corporate_text = st.text_area(
            "Saved information / narrative",
            value=str(selected_corporate_row.get("Information") or ""),
            height=220,
            key=narrative_key,
            help="View and edit the complete saved text. Multiple paragraphs and line breaks are supported.",
        )
        selected_heading = st.text_input(
            "Information heading",
            value=str(selected_corporate_row.get("Corporate information") or ""),
            key=f"corporate_profile_heading_{entity['entity_code']}_{profile_year}_{profile_month}_{selected_corporate_code}",
        )
        corporate_status_options = ["Draft", "In progress", "Complete", "Not applicable"]
        selected_corporate_status = st.selectbox(
            "Status",
            corporate_status_options,
            index=(corporate_status_options.index(str(selected_corporate_row.get("Status") or "Draft"))
                   if str(selected_corporate_row.get("Status") or "Draft") in corporate_status_options else 0),
            key=f"corporate_profile_status_{entity['entity_code']}_{profile_year}_{profile_month}_{selected_corporate_code}",
        )

        action_cols = st.columns([1, 1, 2])
        save_selected = action_cols[0].button(
            "Save selected information", type="primary",
            key=f"save_selected_corporate_profile_{entity['entity_code']}_{profile_year}_{profile_month}_{selected_corporate_code}",
        )
        delete_selected = action_cols[1].button(
            "Remove selected field",
            key=f"remove_selected_corporate_profile_{entity['entity_code']}_{profile_year}_{profile_month}_{selected_corporate_code}",
        )
        if save_selected:
            corporate_rows[selected_corporate_index]["Information"] = selected_corporate_text
            corporate_rows[selected_corporate_index]["Corporate information"] = selected_heading.strip()
            corporate_rows[selected_corporate_index]["Status"] = selected_corporate_status
            if not selected_heading.strip():
                st.error("Enter an information heading before saving.")
                st.stop()
            records = []
            used_codes = set()
            for index, row in enumerate(corporate_rows, start=1):
                label = str(row.get("Corporate information") or "").strip()
                info = str(row.get("Information") or "").strip()
                code = re.sub(r"[^A-Z0-9]+", "_", str(row.get("Code") or "").strip().upper()).strip("_")
                if not label and not info and not code:
                    continue
                if not label:
                    st.error(f"Field {index}: enter an information heading before saving.")
                    st.stop()
                if not code:
                    code = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
                if code in used_codes:
                    st.error(f"Duplicate field code '{code}'. Each field must have a unique code.")
                    st.stop()
                used_codes.add(code)
                records.append({"Code": code, "Description": label, "Amount": 0, "Commentary": info,
                                "Status": str(row.get("Status") or "Draft")})
            RX.save_inputs(entity['entity_code'], profile_year, profile_month, "REPORT_PROFILE", records)
            st.session_state.pop("automated_fs_result", None)
            audit("CORPORATE_INFORMATION_SAVED",
                  f"Corporate information field {selected_corporate_code} saved for {profile_year}-{profile_month:02d}",
                  profile_year, profile_month)
            st.success(f"{selected_heading.strip()} saved for {period_label}.")
            st.rerun()

        if delete_selected:
            corporate_rows.pop(selected_corporate_index)
            records = []
            for row in corporate_rows:
                label = str(row.get("Corporate information") or "").strip()
                code = re.sub(r"[^A-Z0-9]+", "_", str(row.get("Code") or "").strip().upper()).strip("_")
                if label and code:
                    records.append({"Code": code, "Description": label, "Amount": 0,
                                    "Commentary": str(row.get("Information") or "").strip(),
                                    "Status": str(row.get("Status") or "Draft")})
            RX.save_inputs(entity['entity_code'], profile_year, profile_month, "REPORT_PROFILE", records)
            st.session_state.pop("automated_fs_result", None)
            audit("CORPORATE_INFORMATION_FIELD_REMOVED",
                  f"Corporate information field {selected_corporate_code} removed for {profile_year}-{profile_month:02d}",
                  profile_year, profile_month)
            st.success("Selected corporate information field removed for this reporting period.")
            st.rerun()
    else:
        st.info("No corporate information fields are available. Add a field below to get started.")

    with st.expander("Add additional company information"):
        new_corporate_heading = st.text_input(
            "New information heading",
            key=f"new_corporate_heading_{entity['entity_code']}_{profile_year}_{profile_month}",
            placeholder="e.g. Principal activities, Tax identification number",
        )
        new_corporate_text = st.text_area(
            "Information / narrative",
            key=f"new_corporate_text_{entity['entity_code']}_{profile_year}_{profile_month}",
            height=120,
        )
        new_corporate_status = st.selectbox(
            "Initial status", ["Draft", "In progress", "Complete", "Not applicable"],
            key=f"new_corporate_status_{entity['entity_code']}_{profile_year}_{profile_month}",
        )
        if st.button("Add company information", key=f"add_corporate_field_{entity['entity_code']}_{profile_year}_{profile_month}"):
            heading = new_corporate_heading.strip()
            if not heading:
                st.error("Enter an information heading.")
                st.stop()
            new_code = re.sub(r"[^A-Z0-9]+", "_", heading.upper()).strip("_")
            existing_codes = {str(row.get("Code") or "").upper() for row in corporate_rows}
            if new_code in existing_codes:
                st.error("A field with this heading already exists. Please use a different heading.")
                st.stop()
            corporate_rows.append({"Code": new_code, "Corporate information": heading,
                                   "Information": new_corporate_text.strip(), "Status": new_corporate_status})
            records = [{"Code": re.sub(r"[^A-Z0-9]+", "_", str(row.get("Code") or "").strip().upper()).strip("_"),
                        "Description": str(row.get("Corporate information") or "").strip(),
                        "Amount": 0, "Commentary": str(row.get("Information") or "").strip(),
                        "Status": str(row.get("Status") or "Draft")}
                       for row in corporate_rows
                       if str(row.get("Corporate information") or "").strip()]
            RX.save_inputs(entity['entity_code'], profile_year, profile_month, "REPORT_PROFILE", records)
            st.session_state.pop("automated_fs_result", None)
            audit("CORPORATE_INFORMATION_FIELD_ADDED",
                  f"Corporate information field {new_code} added for {profile_year}-{profile_month:02d}",
                  profile_year, profile_month)
            st.success(f"{heading} added for {period_label}.")
            st.rerun()

    # Use the current editor data for the completeness check below.
    edited_profile = pd.DataFrame(corporate_rows)
    st.divider()
    st.markdown("#### Corporate information completeness")
    check_rows = []
    current_rows = {str(r.get("Code") or "").upper(): r for r in edited_profile.to_dict("records")}
    for code, label in REPORT_PROFILE_FIELDS:
        row = current_rows.get(code, {})
        value = str(row.get("Information") or "").strip()
        status = str(row.get("Status") or "Draft")
        check_rows.append({"Required information": label,
                           "Completion": "Provided" if value else "Missing",
                           "Status": status})
    missing = sum(1 for r in check_rows if r["Completion"] == "Missing")
    st.dataframe(pd.DataFrame(check_rows), use_container_width=True, hide_index=True)
    if missing:
        st.warning(f"{missing} standard corporate information field(s) still need completion. The report will flag these fields until information is provided.")
    else:
        st.success("All standard corporate information fields have been populated. Please verify their accuracy before issuing the financial statements.")



elif page=="Notes & Disclosures":
    st.subheader("Notes & disclosures")
    st.caption("Prepare and maintain the narrative disclosures accompanying the financial statements. Notes are saved by entity and reporting period; earlier narratives can be carried forward for review.")

    imports = TB.list_imports(entity['entity_code'])
    periods = sorted({(int(x["fiscal_year"]), int(x["fiscal_month"])) for x in imports}, reverse=True)
    if periods:
        years = sorted({p[0] for p in periods}, reverse=True)
        default_year = periods[0][0]
        year_idx = years.index(default_year)
        period_year_col, period_month_col = st.columns(2)
        selected_year = period_year_col.selectbox(
            "Financial year", years, index=year_idx, key="notes_disclosures_year"
        )
        months = sorted({m for y, m in periods if y == selected_year})
        selected_month = period_month_col.selectbox(
            "Reporting month", months,
            format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
            key="notes_disclosures_month"
        )
    else:
        st.info("No trial balance has been imported yet. You can still prepare disclosures by selecting a reporting period.")
        today = datetime.utcnow()
        c1, c2 = st.columns(2)
        selected_year = c1.number_input("Financial year", min_value=2000, max_value=2100, value=today.year, step=1, key="notes_disclosures_year_manual")
        selected_month = c2.selectbox("Reporting month", list(range(1, 13)), index=today.month-1,
            format_func=lambda m: datetime(2000, m, 1).strftime("%B"), key="notes_disclosures_month_manual")

    selected_year, selected_month = int(selected_year), int(selected_month)
    period_text = datetime(selected_year, selected_month, 1).strftime("%B %Y")
    exact_saved = {x["note_code"]: x for x in RX.get_notes(entity['entity_code'], selected_year, selected_month)}
    carried_saved = {x["note_code"]: x for x in RX.get_latest_notes(entity['entity_code'], selected_year, selected_month)}

    # Standard notes plus user-created notes. Custom notes are stored in the
    # same disclosure table and carry forward by note code like standard notes.
    standard_note_titles = {x[0]: x[1] for x in FINANCIAL_NOTE_TEMPLATES}
    custom_codes = sorted(
        (set(exact_saved) | set(carried_saved)) - set(standard_note_titles),
        key=_note_sort_key
    )
    # Keep standard and custom notes in one hierarchical sequence, so each
    # subsection appears immediately after its parent note.
    all_note_codes = sorted(set(standard_note_titles) | set(custom_codes), key=_note_sort_key)
    note_rows = []
    for code in all_note_codes:
        current = exact_saved.get(code)
        carried = carried_saved.get(code)
        fallback_title = standard_note_titles.get(code, (current or carried or {}).get("note_title", code))
        source = "Current period" if current else (
            f"Carried forward from {datetime(int(carried['fiscal_year']), int(carried['fiscal_month']), 1).strftime('%b %Y')}" if carried else "Not yet supplied"
        )
        note_rows.append({
            "Note code": _display_note_code(code),
            "Note title": (current or carried or {}).get("note_title", fallback_title),
            "Status": (current or carried or {}).get("status", "Draft"),
            "Source": source,
        })
    overview = pd.DataFrame(note_rows)
    status_counts = overview["Status"].value_counts().to_dict()

    tab_summary, tab_subsection, tab_edit_disclosure, tab_custom_note = st.tabs([
        "Summary table", "Add subsection", "Edit disclosure", "Add new custom note"
    ])

    with tab_summary:
        a, b, c, d = st.columns(4)
        a.metric("Notes", len(overview))
        b.metric("Complete", int(status_counts.get("Complete", 0)))
        c.metric("In progress", int(status_counts.get("In progress", 0)))
        d.metric("Draft / pending", int(sum(status_counts.get(x, 0) for x in ("Draft", "Pending"))))
        st.dataframe(overview, use_container_width=True, hide_index=True)

    with tab_subsection:
        # Subsections are stored as child note codes (for example N02.1, N02.2).
        # This keeps them attached to their parent note without changing the existing
        # disclosure table or disturbing historical records.
        parent_note_codes = [code for code in all_note_codes if not re.search(r"\.\d+$", str(code))]
        parent_title_lookup = {**standard_note_titles}
        for code in custom_codes:
            parent_title_lookup[code] = (exact_saved.get(code) or carried_saved.get(code) or {}).get("note_title", code)
        parent_code = st.selectbox(
            "Parent note", parent_note_codes,
            format_func=lambda code: f"{_display_note_code(code)} — {parent_title_lookup.get(code, code)}",
            key=f"subsection_parent_{entity['entity_code']}_{selected_year}_{selected_month}"
        )
        subsection_reset_key = f"subsection_form_reset_{entity['entity_code']}_{selected_year}_{selected_month}"
        subsection_reset_version = st.session_state.get(subsection_reset_key, 0)
        subsection_title_key = f"subsection_title_{entity['entity_code']}_{selected_year}_{selected_month}_{subsection_reset_version}"
        subsection_narrative_key = f"subsection_narrative_{entity['entity_code']}_{selected_year}_{selected_month}_{subsection_reset_version}"
        subsection_status_key = f"subsection_status_{entity['entity_code']}_{selected_year}_{selected_month}_{subsection_reset_version}"
        subsection_title = st.text_input("Subsection title", placeholder="e.g. Basis of measurement", key=subsection_title_key)
        st.markdown("**Subsection disclosure notepad**")
        st.caption("Use the toolbar to format the subsection narrative with emphasis, lists, alignment and links.")
        subsection_narrative = _rich_narrative_editor(
            "Subsection disclosure", "",
            key=subsection_narrative_key,
            height=220,
            help_text="This narrative will appear under the selected parent note in the generated financial statements.",
        )
        subsection_status = st.selectbox("Subsection status", ["Draft", "In progress", "Complete", "Not applicable"], key=subsection_status_key)
        add_subsection_submit = st.button("Add subsection", type="primary", key=f"submit_subsection_{entity['entity_code']}_{selected_year}_{selected_month}_{subsection_reset_version}")
        if add_subsection_submit:
            if not subsection_title.strip():
                st.error("Enter a subsection title.")
            else:
                child_numbers = []
                for existing_code in set(exact_saved) | set(carried_saved):
                    match = re.fullmatch(re.escape(parent_code) + r"\.(\d+)", str(existing_code), re.I)
                    if match:
                        child_numbers.append(int(match.group(1)))
                child_code = f"{parent_code}.{max(child_numbers or [0]) + 1}"
                merged = dict(carried_saved)
                merged.update(exact_saved)
                merged[child_code] = {
                    "note_code": child_code, "note_title": subsection_title.strip(),
                    "narrative": subsection_narrative, "manual_amount": None,
                    "status": subsection_status,
                }
                ordered = [x[0] for x in FINANCIAL_NOTE_TEMPLATES]
                ordered.extend(sorted(set(merged) - set(ordered), key=_note_sort_key))
                records = []
                for code in ordered:
                    rec = merged.get(code)
                    if rec:
                        records.append({
                            "Note code": code, "Note title": rec.get("note_title") or code,
                            "Narrative": rec.get("narrative") or "",
                            "Manual amount": rec.get("manual_amount"),
                            "Status": rec.get("status") or "Draft",
                        })
                RX.save_notes(entity['entity_code'], selected_year, selected_month, records)
                st.session_state.pop("automated_fs_result", None)
                audit("NOTE_SUBSECTION_ADDED", f"{child_code} — {subsection_title.strip()} added under {parent_code}", selected_year, selected_month)
                st.success(f"Subsection {_display_note_code(child_code)} added under {_display_note_code(parent_code)}.")
                # Advance the form key version; Streamlit creates fresh, blank
                # entry widgets on rerun while retaining the selected parent.
                st.session_state[subsection_reset_key] = subsection_reset_version + 1
                st.rerun()

    with tab_edit_disclosure:
        note_codes = all_note_codes
        title_lookup = {**standard_note_titles}
        for code in custom_codes:
            title_lookup[code] = (exact_saved.get(code) or carried_saved.get(code) or {}).get("note_title", code)
        selected_code = st.selectbox(
            "Select note", note_codes,
            format_func=lambda code: f"{_display_note_code(code)} — {title_lookup.get(code, code)}",
            key=f"notes_disclosures_selected_{entity['entity_code']}_{selected_year}_{selected_month}"
        )
        default_record = exact_saved.get(selected_code) or carried_saved.get(selected_code) or {}
        default_narrative = str(default_record.get("narrative") or "")
        default_status = str(default_record.get("status") or "Draft")
        default_amount = default_record.get("manual_amount")
        if selected_code in exact_saved:
            st.caption("This disclosure is saved for the selected reporting period.")
        elif selected_code in carried_saved:
            carried_period = datetime(int(default_record["fiscal_year"]), int(default_record["fiscal_month"]), 1).strftime("%B %Y")
            st.info(f"A previous disclosure from {carried_period} is shown below. Saving it will create a copy for {period_text}; it will not change the earlier period.")
        else:
            st.caption("No previous narrative was found for this note. Enter the disclosure below.")

        note_title_default = default_record.get("note_title") or title_lookup.get(selected_code, selected_code)
        title_value = st.text_input("Note title", value=note_title_default, key=f"notes_title_{entity['entity_code']}_{selected_year}_{selected_month}_{selected_code}")
        st.markdown("**Narrative disclosure notepad**")
        st.caption("Format the disclosure using the toolbar. You can apply emphasis, create numbered or bulleted lists, adjust alignment and insert links.")
        narrative_value = _rich_narrative_editor(
            "Disclosure narrative", default_narrative,
            key=f"notes_narrative_{entity['entity_code']}_{selected_year}_{selected_month}_{selected_code}",
            height=280,
            help_text="This narrative is inserted into the corresponding note in the generated financial statements.",
        )
        amount_col, status_col = st.columns([1, 1])
        amount_value = amount_col.number_input(
            "Manual amount (optional)", value=float(default_amount or 0.0), format="%.2f",
            help="Use only where a manual note amount is required. Leave at zero if no manual amount applies.",
            key=f"notes_amount_{entity['entity_code']}_{selected_year}_{selected_month}_{selected_code}"
        )
        status_options = ["Draft", "In progress", "Complete", "Not applicable"]
        status_value = status_col.selectbox("Disclosure status", status_options,
            index=status_options.index(default_status) if default_status in status_options else 0,
            key=f"notes_status_{entity['entity_code']}_{selected_year}_{selected_month}_{selected_code}")

        if st.button("Save disclosure", type="primary", key=f"save_note_{entity['entity_code']}_{selected_year}_{selected_month}_{selected_code}"):
            # RX.save_notes replaces the selected period's set, so preserve all other notes.
            merged = dict(exact_saved)
            merged[selected_code] = {
                "note_code": selected_code, "note_title": title_value.strip(),
                "narrative": narrative_value, "manual_amount": amount_value,
                "status": status_value,
            }
            records = []
            save_order = [x[0] for x in FINANCIAL_NOTE_TEMPLATES]
            save_order.extend(sorted(
                set(merged) - set(save_order),
                key=_note_sort_key
            ))
            for code in save_order:
                rec = merged.get(code)
                if not rec:
                    continue
                records.append({
                    "Note code": code,
                    "Note title": str(rec.get("note_title") or title_lookup.get(code, code)),
                    "Narrative": str(rec.get("narrative") or ""),
                    "Manual amount": rec.get("manual_amount"),
                    "Status": str(rec.get("status") or "Draft"),
                })
            RX.save_notes(entity['entity_code'], selected_year, selected_month, records)
            st.session_state.pop("automated_fs_result", None)
            audit("NOTE_DISCLOSURE_SAVED", f"{selected_code} disclosure saved for {selected_year}-{selected_month:02d}", selected_year, selected_month)
            st.success(f"{selected_code} saved for {period_text}.")
            st.rerun()


    with tab_custom_note:
        st.caption("Create a new main note. Subsections can then be added beneath it using the subsection editor below.")
        custom_reset_key = f"custom_note_form_reset_{entity['entity_code']}_{selected_year}_{selected_month}"
        custom_reset_version = st.session_state.get(custom_reset_key, 0)
        custom_title_key = f"custom_note_title_{entity['entity_code']}_{selected_year}_{selected_month}_{custom_reset_version}"
        custom_narrative_key = f"custom_note_narrative_{entity['entity_code']}_{selected_year}_{selected_month}_{custom_reset_version}"
        custom_status_key = f"custom_note_status_{entity['entity_code']}_{selected_year}_{selected_month}_{custom_reset_version}"
        custom_title = st.text_input("New note title", placeholder="e.g. Capital commitments", key=custom_title_key)
        st.markdown("**Note narrative notepad**")
        st.caption("Format the new note narrative using the same toolbar available when editing an existing disclosure.")
        custom_narrative = _rich_narrative_editor(
            "Note narrative", "",
            key=custom_narrative_key,
            height=220,
            help_text="This narrative will be saved with the new custom note and included in the generated financial statements.",
        )
        custom_status = st.selectbox("Initial status", ["Draft", "In progress", "Complete", "Not applicable"], key=custom_status_key)
        add_note_submit = st.button("Add note", type="primary", key=f"submit_custom_note_{entity['entity_code']}_{selected_year}_{selected_month}_{custom_reset_version}")
        if add_note_submit:
            if not custom_title.strip():
                st.error("Enter a title for the new note.")
            else:
                used_codes = set(exact_saved) | set(carried_saved) | set(standard_note_titles)
                numeric_codes = [
                    int(m.group(1)) for code in used_codes
                    if (m := re.fullmatch(r"N(\d+)", str(code).upper()))
                ]
                next_code = f"N{max(numeric_codes or [0]) + 1:02d}"
                merged_new = dict(exact_saved)
                merged_new[next_code] = {
                    "note_code": next_code,
                    "note_title": custom_title.strip(),
                    "narrative": custom_narrative,
                    "manual_amount": None,
                    "status": custom_status,
                }
                new_records = []
                ordered_codes = [x[0] for x in FINANCIAL_NOTE_TEMPLATES] + sorted(
                    set(merged_new) - set(standard_note_titles),
                    key=_note_sort_key
                )
                for code in ordered_codes:
                    rec = merged_new.get(code)
                    if rec:
                        new_records.append({
                            "Note code": code,
                            "Note title": rec.get("note_title") or code,
                            "Narrative": rec.get("narrative") or "",
                            "Manual amount": rec.get("manual_amount"),
                            "Status": rec.get("status") or "Draft",
                        })
                RX.save_notes(entity['entity_code'], selected_year, selected_month, new_records)
                audit("CUSTOM_NOTE_ADDED", f"{next_code} — {custom_title.strip()} added for {selected_year}-{selected_month:02d}", selected_year, selected_month)
                st.success(f"{_display_note_code(next_code)} — {custom_title.strip()} added.")
                # Advance the form key version so the next form is completely blank.
                st.session_state[custom_reset_key] = custom_reset_version + 1
                st.session_state.pop("automated_fs_result", None)
                st.rerun()

    # Bulk delete: select one or more saved notes, including standard and custom notes.
    st.markdown("#### Delete multiple notes")
    if exact_saved:
        delete_options = sorted(
            exact_saved.keys(),
            key=_note_sort_key
        )
        delete_labels = {
            code: f"{_display_note_code(code)} — {exact_saved[code].get('note_title') or title_lookup.get(code, code)}"
            for code in delete_options
        }
        selected_delete_codes = st.multiselect(
            "Select note(s) to delete",
            options=delete_options,
            format_func=lambda code: delete_labels.get(code, code),
            key=f"bulk_delete_notes_{entity['entity_code']}_{selected_year}_{selected_month}",
            help="Select multiple standard IFRS notes, custom notes and sub-notes."
        )
        if selected_delete_codes:
            st.warning(
                f"You have selected {len(selected_delete_codes)} note(s) for deletion from {period_text}. "
                "Earlier reporting periods will not be changed."
            )
        confirm_bulk_delete = st.checkbox(
            "I confirm that I want to delete all selected notes.",
            key=f"confirm_bulk_delete_{entity['entity_code']}_{selected_year}_{selected_month}"
        )
        if st.button(
            "🗑️ Delete selected notes",
            type="secondary",
            disabled=(not selected_delete_codes or not confirm_bulk_delete),
            key=f"delete_selected_notes_{entity['entity_code']}_{selected_year}_{selected_month}"
        ):
            deleting = set(selected_delete_codes)
            remaining = {code: rec for code, rec in exact_saved.items() if code not in deleting}
            save_order = [x[0] for x in FINANCIAL_NOTE_TEMPLATES]
            save_order.extend(sorted(
                set(remaining) - set(save_order),
                key=_note_sort_key
            ))
            records = []
            for code in save_order:
                rec = remaining.get(code)
                if rec:
                    records.append({
                        "Note code": code,
                        "Note title": str(rec.get("note_title") or title_lookup.get(code, code)),
                        "Narrative": str(rec.get("narrative") or ""),
                        "Manual amount": rec.get("manual_amount"),
                        "Status": str(rec.get("status") or "Draft"),
                    })
            RX.save_notes(entity['entity_code'], selected_year, selected_month, records)
            st.session_state.pop("automated_fs_result", None)
            audit("NOTES_BULK_DELETED", f"Deleted notes {', '.join(selected_delete_codes)} for {selected_year}-{selected_month:02d}", selected_year, selected_month)
            st.success(f"Deleted {len(selected_delete_codes)} note(s) from {period_text}.")
            st.rerun()
    else:
        st.info("There are no notes saved in this reporting period to delete. Save carried-forward notes in this period first if you also want to delete them here.")

    st.divider()
    st.caption("The narrative is saved in the disclosure register and can be edited and formatted here at any time. Standard and custom notes are carried forward by entity and reporting period. Mark a note Complete only after management has reviewed and approved its wording and supporting information.")

elif page=="IFRS Disclosure Checks":
    st.subheader("IFRS reporting and disclosure checks")
    imports=TB.list_imports(entity['entity_code'])
    if not imports: st.info("Import a trial balance first.")
    else:
        years=sorted({int(x['fiscal_year']) for x in imports},reverse=True)
        y=st.selectbox("Financial year",years,key="ifrs_year")
        year_imports=[x for x in imports if int(x['fiscal_year'])==y]
        months=sorted({int(x['fiscal_month']) for x in year_imports})
        m=st.selectbox("Reporting month",months,format_func=lambda x:datetime(2000,x,1).strftime("%B"),key="ifrs_month")
        current=next((x for x in year_imports if int(x['fiscal_month'])==m),None)
        if current:
            lines=AM.mapped_lines(current['import_id'],entity['entity_code'])
            unmapped=[x for x in lines if not x.get('is_mapped')]
            balanced=abs(float(current['debit_total'])-float(current['credit_total']))<0.01
            frame=RX.period_frame(current,entity['entity_code'])
            bs=RX.balance_by_line(frame)
            # Balance-sheet classification check from mapped TB balances.
            assets=liabs=equity_total=0.0
            if not frame.empty:
                bsf=frame[(frame.statement_type=='BS')].copy()
                if not bsf.empty:
                    bsf['presented']=bsf.apply(lambda r:-float(r.balance or 0) if r.get('normal_balance')=='Credit' else float(r.balance or 0),axis=1)
                    assets=float(bsf[bsf.account_nature=='Asset'].presented.sum())
                    liabs=float(bsf[bsf.account_nature=='Liability'].presented.sum())
                    equity_total=float(bsf[bsf.account_nature=='Equity'].presented.sum())
            sfp_diff=assets-liabs-equity_total
            notes=RX.get_notes(entity['entity_code'],y,m)
            complete_notes=sum(1 for x in notes if x.get('status') in ('Complete','Not applicable'))
            standard_note_codes = {x[0] for x in FINANCIAL_NOTE_TEMPLATES}
            custom_note_count = len({str(x.get("note_code") or "") for x in notes} - standard_note_codes)
            total_notes = len(FINANCIAL_NOTE_TEMPLATES) + custom_note_count
            checks=[
                {"Check":"Trial balance debits equal credits","Result":"PASS" if balanced else "FAIL","Details":f"Difference: {entity['functional_currency']} {float(current['debit_total'])-float(current['credit_total']):,.2f}"},
                {"Check":"All TB accounts mapped","Result":"PASS" if not unmapped else "FAIL","Details":f"{len(unmapped)} account(s) awaiting mapping"},
                {"Check":"Statement of financial position balances","Result":"PASS" if abs(sfp_diff)<0.01 and (assets or liabs or equity_total) else "REVIEW","Details":f"Assets {assets:,.2f}; liabilities {liabs:,.2f}; equity {equity_total:,.2f}; difference {sfp_diff:,.2f}"},
                {"Check":"Financial statement notes prepared","Result":"REVIEW" if complete_notes<total_notes else "PASS","Details":f"{complete_notes} of {total_notes} note areas marked Complete/Not applicable"},
                {"Check":"Cash flow statement reconciled","Result":"MANUAL EVIDENCE REQUIRED","Details":"Review the Cash Flow Statement page and investigate any reconciliation difference."},
                {"Check":"Changes in equity reconciled","Result":"MANUAL EVIDENCE REQUIRED","Details":"Review opening balances, profit, OCI, movements and closing balances on the Changes in Equity page."},
                {"Check":"Accounting policies, estimates and judgements","Result":"MANUAL EVIDENCE REQUIRED","Details":"Confirm the entity-specific accounting policy disclosures and significant judgements."},
                {"Check":"Related parties, commitments and contingencies","Result":"MANUAL EVIDENCE REQUIRED","Details":"Obtain management confirmations and legal/contractual support; TB balances alone are insufficient."},
            ]
            show_dataframe(pd.DataFrame(checks),use_container_width=True,hide_index=True)
            fail_count=sum(1 for x in checks if x['Result']=='FAIL')
            review_count=sum(1 for x in checks if x['Result'] in ('REVIEW','MANUAL EVIDENCE REQUIRED'))
            a,b,c=st.columns(3); a.metric("Failed checks",fail_count); b.metric("Items requiring review",review_count); c.metric("Notes completed",f"{complete_notes}/{total_notes}")
            if fail_count: st.error("Do not approve this reporting period until failed checks are resolved.")
            elif review_count: st.warning("Automated checks have not identified a hard failure, but manual disclosure evidence and review remain outstanding.")
            else: st.success("All configured checks are complete. This is not an external audit opinion or IFRS compliance certification.")
            st.caption("The checklist is a control aid, not a determination of full IFRS compliance. Disclosure requirements depend on the entity's facts, materiality, applicable IFRS Accounting Standards and local regulatory requirements.")
        else:
            st.error("No trial balance exists for the selected month.")

elif page=="Import History":
    st.subheader("Trial balance import history")
    hist=import_history()
    if hist.empty: st.info("No imports found.")
    else:
        show_dataframe(hist,use_container_width=True,hide_index=True)
        selected_id=st.selectbox("Select import for review",hist.import_id.tolist())
        record=TB.get_import(selected_id)
        lines=TB.get_lines(selected_id)
        if record:
            r=record[0]; a,b,c=st.columns(3); a.metric("Debit total",f"{entity['functional_currency']} {r['debit_total']:,.2f}"); b.metric("Credit total",f"{entity['functional_currency']} {r['credit_total']:,.2f}"); c.metric("Difference",f"{entity['functional_currency']} {r['debit_total']-r['credit_total']:,.2f}")
            st.divider()
            st.markdown("#### Delete uploaded trial balance")
            st.warning(
                "This permanently deletes the selected TB import and its account rows. "
                "Chart of Accounts records, other TB imports, saved notes/disclosures, "
                "supporting schedules and audit history will be retained."
            )
            delete_confirm = st.checkbox(
                f"I confirm that I want to permanently delete {r.get('file_name') or selected_id} "
                f"for {int(r['fiscal_year'])}-{int(r['fiscal_month']):02d}.",
                key=f"confirm_delete_tb_{selected_id}",
            )
            if st.button(
                "Permanently delete this trial balance",
                key=f"delete_tb_{selected_id}",
                type="secondary",
                disabled=not delete_confirm,
            ):
                try:
                    from database import connection, is_postgres
                    ph = "%s" if is_postgres() else "?"
                    # Delete only the selected import's source rows and header.
                    # Chart of Accounts records are entity-level and intentionally retained for reuse.
                    with connection() as (conn, _):
                        cur = conn.cursor()
                        cur.execute("DELETE FROM fr_tb_lines WHERE import_id=" + ph, (selected_id,))
                        deleted_lines = cur.rowcount
                        cur.execute("DELETE FROM fr_tb_imports WHERE import_id=" + ph, (selected_id,))
                        deleted_imports = cur.rowcount
                        if deleted_imports != 1:
                            raise RuntimeError("The selected trial balance was not found; nothing was deleted.")
                    audit(
                        "TRIAL_BALANCE_DELETED",
                        f"{r.get('file_name') or selected_id}; import_id={selected_id}; "
                        f"{deleted_lines} account rows deleted; status={r.get('status')}",
                        int(r["fiscal_year"]), int(r["fiscal_month"]),
                    )
                    st.success("The selected trial balance and its account rows have been deleted. Other records were retained.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not delete the selected trial balance: {exc}")
            st.divider()
            if r['status']=="DRAFT":
                mapped_check=AM.mapped_lines(selected_id,entity['entity_code'])
                unmapped_count=sum(1 for x in mapped_check if not x['is_mapped'])
                balanced=abs(float(r['debit_total'])-float(r['credit_total'])) < 0.01
                if not balanced:
                    st.error("Approval blocked: the imported trial balance is not balanced. Resolve the difference before approval.")
                if unmapped_count:
                    st.error(f"Approval blocked: {unmapped_count} account row(s) still require IFRS mapping.")
                if balanced and not unmapped_count:
                    if st.button("Mark period approved",type="primary",help="Use only after reconciliations and independent review are complete."):
                        from database import connection, is_postgres
                        ph="%s" if is_postgres() else "?"
                        with connection() as (conn,_): conn.cursor().execute("UPDATE fr_tb_imports SET status='APPROVED' WHERE import_id="+ph,(selected_id,))
                        audit("PERIOD_APPROVED",f"Import {selected_id}",r['fiscal_year'],r['fiscal_month']); st.success("Period marked approved."); st.rerun()
            show_dataframe(pd.DataFrame(lines),use_container_width=True,hide_index=True)


elif page=="Database Reset":
    st.subheader("Full IFRS Database Reset")
    st.error(
        "DANGER: This permanently deletes IFRS reporting data for ALL entities. "
        "This action cannot be undone from the application."
    )
    st.markdown(
        """
        **The reset will permanently delete:**
        - All imported trial balance batches and transaction lines
        - All Chart of Accounts records
        - All account mappings
        - All Mapping Catalogue records (Statements/IFRS Lines/Notes Lines/Account Types)
        - All cash flow and changes-in-equity supporting inputs
        - All notes and disclosure records

        **The reset will retain:**
        - Entity Setup (entity codes, names and functional currencies)
        - Audit Log, including a record of this reset
        - Application code and database configuration
        """
    )
    st.warning(
        "This reset applies across every reporting entity, not only the entity currently selected. "
        "Take a database backup before proceeding."
    )
    with st.form("full_ifrs_database_reset_form"):
        typed_confirmation = st.text_input(
            'Type "RESET IFRS DATA" to confirm permanent deletion',
            key="full_ifrs_reset_confirmation",
        )
        acknowledge = st.checkbox(
            "I understand that all IFRS reporting data across all entities will be permanently deleted."
        )
        submitted = st.form_submit_button(
            "Permanently reset IFRS database",
            type="primary",
            disabled=not (acknowledge and typed_confirmation.strip() == "RESET IFRS DATA"),
        )
    if submitted:
        try:
            deleted_counts = DB.reset_ifrs_data(
                username=st.session_state.get("username", "system")
            )
            st.session_state["full_ifrs_reset_result"] = deleted_counts
            st.success(
                "Full IFRS data reset completed. Entity Setup and the audit trail were retained."
            )
            st.dataframe(
                pd.DataFrame(
                    [{"Table": table, "Rows deleted": count}
                     for table, count in deleted_counts.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.info(
                "The standard Account Types (Income, Expense, Asset, Equity and Liability) "
                "will be initialized as the starting catalogue when the application next initializes."
            )
        except Exception as exc:
            st.error(f"Database reset failed: {type(exc).__name__}: {exc}")
            with st.expander("Technical error details", expanded=True):
                st.exception(exc)


elif page=="Automated Financial Statements":
    st.subheader("Automated Financial Statements")
    st.caption(
        "Generate financial statements in the Kulana presentation style directly from saved reporting data. No Word template upload is required. "
        "Select a month or a range of months. Activity statements show only movements within the selected period; the Statement of Financial Position shows closing balances at period end."
    )
    imports = [x for x in TB.list_imports(entity['entity_code']) if str(x.get("status") or "").upper() != "SUPERSEDED"]
    if not imports:
        st.info("Import a trial balance and complete the Chart of Accounts IFRS mappings before generating a report.")
    else:
        years = sorted({int(x["fiscal_year"]) for x in imports}, reverse=True)
        # Keep the reporting controls compact and aligned on one horizontal row.
        # The wider period selector accommodates labels without taking excess space.
        period_cols = st.columns([0.85, 1.25, 0.9, 0.9, 0.72], gap="small")
        with period_cols[0]:
            report_year = st.selectbox("Financial year", years, key=f"auto_report_year_{entity['entity_code']}")
        year_imports = [x for x in imports if int(x["fiscal_year"]) == report_year]
        available = {}
        for item in year_imports:
            month_no = int(item["fiscal_month"])
            # list_imports is ordered newest first; retain the newest non-superseded import.
            available.setdefault(month_no, item)
        month_options = sorted(available)
        with period_cols[1]:
            period_mode = st.selectbox("Reporting period type", ["Monthly", "Custom period", "Quarterly", "Half-year", "Year to date", "Full year"], key=f"auto_report_period_type_{entity['entity_code']}_{report_year}")
        month_name = lambda m: datetime(2000, int(m), 1).strftime("%B")
        if period_mode == "Monthly":
            with period_cols[2]:
                report_start_month = report_end_month = st.selectbox("Reporting month", month_options, index=len(month_options)-1, format_func=month_name, key=f"auto_report_month_{entity['entity_code']}_{report_year}")
        elif period_mode == "Custom period":
            with period_cols[2]:
                report_start_month = st.selectbox("From month", month_options, index=0, format_func=month_name, key=f"auto_report_start_month_{entity['entity_code']}_{report_year}")
            valid_ends = [m for m in month_options if m >= report_start_month]
            with period_cols[3]:
                report_end_month = st.selectbox("To month", valid_ends, index=len(valid_ends)-1, format_func=month_name, key=f"auto_report_end_month_{entity['entity_code']}_{report_year}")
        else:
            ranges = {
                "Quarterly": [(1,3,"Q1 — January to March"),(4,6,"Q2 — April to June"),(7,9,"Q3 — July to September"),(10,12,"Q4 — October to December")],
                "Half-year": [(1,6,"First half — January to June"),(7,12,"Second half — July to December")],
                "Year to date": [(1,m,f"January to {month_name(m)}") for m in month_options],
                "Full year": [(1,12,"January to December")],
            }
            valid_ranges = [(a,b,label) for a,b,label in ranges[period_mode] if b in available]
            if not valid_ranges:
                st.warning("The selected reporting period does not have all required month-end trial balance imports.")
                st.stop()
            with period_cols[2]:
                selected_range = st.selectbox("Period", valid_ranges, format_func=lambda x: x[2], key=f"auto_report_range_{entity['entity_code']}_{report_year}_{period_mode}")
            report_start_month, report_end_month = selected_range[0], selected_range[1]
        # Keep the generate action alongside the reporting-period selectors.
        with period_cols[4]:
            st.markdown("<div style='height: 27px'></div>", unsafe_allow_html=True)
            generate_clicked = st.button(
                "Generate", type="primary", use_container_width=True,
                key=f"generate_auto_fs_{entity['entity_code']}_{report_year}_{report_start_month}_{report_end_month}"
            )
        report_month = int(report_end_month)
        current_import = available[report_month]
        prior_import = next((x for x in imports if int(x["fiscal_year"]) == report_year-1 and int(x["fiscal_month"]) == report_month and str(x.get("status") or "").upper() != "SUPERSEDED"), None)
        opening_year = report_year if report_start_month > 1 else report_year-1
        opening_month = report_start_month-1 if report_start_month > 1 else 12
        opening_import = next((x for x in imports if int(x["fiscal_year"]) == opening_year and int(x["fiscal_month"]) == opening_month and str(x.get("status") or "").upper() != "SUPERSEDED"), None)
        prior_opening_year = report_year-1 if report_start_month > 1 else report_year-2
        prior_opening_import = next((x for x in imports if int(x["fiscal_year"]) == prior_opening_year and int(x["fiscal_month"]) == opening_month and str(x.get("status") or "").upper() != "SUPERSEDED"), None)
        period_end = datetime(report_year, report_month, calendar.monthrange(report_year, report_month)[1])
        prior_period_end = datetime(report_year-1, report_month, calendar.monthrange(report_year-1, report_month)[1])
        period_label = period_end.strftime("%d %B %Y")
        prior_period_label = prior_period_end.strftime("%d %B %Y")
        period_range_label = f"{month_name(report_start_month)}–{month_name(report_month)} {report_year}"

        # Financial statements are assembled directly by the system's native
        # Python report generator from saved reporting data. No DOCX template
        # or preformatted Word document is loaded.
        native_report_enabled = True
        report_engine_name = "Native system report generator"
        st.caption("Word financial statements are generated directly from the system's saved Corporate Information, Notes & Disclosures, IFRS mappings and reporting data. No Word template is used.")

        st.info(
            f"Reporting period: {period_range_label}. Activity statements include only movements from {month_name(report_start_month)} to {month_name(report_month)}. The Statement of Financial Position is presented at {period_label}."
        )
        if not opening_import:
            st.error(f"No opening trial balance was found for {month_name(opening_month)} {opening_year}. A period-only report cannot be calculated reliably without the trial balance immediately before the selected period.")
            st.stop()
        if not prior_import:
            st.warning(
                f"No {datetime(2000, report_month, 1).strftime('%B')} {report_year-1} comparative trial balance was found. Comparative figures will be left blank where unavailable."
            )
        elif not prior_opening_import:
            st.warning(
                f"No comparative opening trial balance was found for {month_name(opening_month)} {prior_opening_year}. Prior-year activity figures cannot be calculated reliably and will be left blank."
            )
        if str(current_import.get("status") or "DRAFT").upper() != "APPROVED":
            st.warning("The selected closing trial balance is not approved. Treat the generated report as a draft for review.")

        if native_report_enabled:
            currency = entity["functional_currency"]
            # Trial balance imports are cumulative snapshots. Difference the opening
            # snapshot from the closing snapshot for P&L activity; keep BS at closing balances.
            current_snapshot = AM.statement_data([current_import["import_id"]], entity['entity_code'])
            opening_snapshot = AM.statement_data([opening_import["import_id"]], entity['entity_code'])
            prior_snapshot = AM.statement_data([prior_import["import_id"]], entity['entity_code']) if prior_import else pd.DataFrame()
            prior_opening_snapshot = AM.statement_data([prior_opening_import["import_id"]], entity['entity_code']) if prior_import and prior_opening_import else pd.DataFrame()

            def _period_activity_frame(closing, opening):
                result = closing.copy()
                if result.empty:
                    return result
                keys = [c for c in ("account_code", "account_id", "account_name") if c in result.columns and c in opening.columns]
                if not keys:
                    raise ValueError("Cannot calculate period activity: trial balance data has no common account identifier.")
                numeric_cols = [c for c in ("debit", "credit", "debit_amount", "credit_amount", "dr", "cr", "balance") if c in opening.columns]
                opening_data = opening[keys + numeric_cols].groupby(keys, dropna=False).sum(numeric_only=True).reset_index()
                result = result.merge(opening_data, on=keys, how="left", suffixes=("", "_opening"))
                pl_mask = result["statement_type"].apply(lambda x: _is_statement_type(x, "PL"))
                for col in numeric_cols:
                    opening_col = f"{col}_opening"
                    if col in result.columns and opening_col in result.columns:
                        result.loc[pl_mask, col] = pd.to_numeric(result.loc[pl_mask, col], errors="coerce").fillna(0) - pd.to_numeric(result.loc[pl_mask, opening_col], errors="coerce").fillna(0)
                        result.drop(columns=[opening_col], inplace=True)
                return result

            pl_frame = _period_activity_frame(current_snapshot, opening_snapshot)
            prior_pl_frame = _period_activity_frame(prior_snapshot, prior_opening_snapshot) if prior_import and not prior_opening_snapshot.empty else pd.DataFrame()
            bs_frame = current_snapshot.copy()
            prior_bs_frame = prior_snapshot.copy()
            bs_schedule = RX.period_frame(current_import, entity['entity_code'])
            prior_bs_schedule = RX.period_frame(prior_import, entity['entity_code']) if prior_import else pd.DataFrame()

            current_pl_rows = _build_pl_report(_statement_amounts(pl_frame, "PL", currency))
            prior_pl_rows = _build_pl_report(_statement_amounts(prior_pl_frame, "PL", currency)) if not prior_pl_frame.empty else []

            def _make_pl_values(rows):
                if not rows:
                    return {}
                values = {str(r[0]): float(r[1] or 0) for r in rows}
                excluded = {
                    _normalise_report_label(x) for x in (
                        "revenue", "cost of sales", "gross profit/(loss)", "other income", "finance costs",
                        "share of profit/(loss) of associates", "profit/(loss) before tax", "income tax expense",
                        "net profit/(loss) for the period", "other comprehensive income/(loss)",
                        "total comprehensive income/(loss)",
                    )
                }
                operating_expenses = sum(
                    float(r[1] or 0) for r in rows
                    if len(r) > 2 and r[2] == "line" and _normalise_report_label(r[0]) not in excluded
                )
                gross = values.get("Gross profit/(loss)", 0.0)
                other_income = values.get("Other income", 0.0)
                values["Operating expenses"] = operating_expenses
                values["Profit before finance cost and tax"] = gross + other_income + operating_expenses
                values["Finance cost"] = values.get("Finance costs", 0.0)
                values["Profit before tax"] = values.get("Profit/(loss) before tax", 0.0)
                values["Profit for the year"] = values.get("Net profit/(loss) for the period", 0.0)
                values["Other comprehensive income"] = values.get("Other comprehensive income/(loss)", 0.0)
                values["Total comprehensive income"] = values.get(
                    "Total comprehensive income/(loss)",
                    values.get("Net profit/(loss) for the period", 0.0) + values.get("Other comprehensive income/(loss)", 0.0)
                )
                return values

            pl_current = _make_pl_values(current_pl_rows)
            pl_prior = _make_pl_values(prior_pl_rows)
            # Keep a separate YTD result solely for the closing SFP reconciliation;
            # the issued P&L and activity notes remain limited to the selected period.
            pl_ytd_rows = _build_pl_report(_statement_amounts(current_snapshot, "PL", currency))
            prior_pl_ytd_rows = _build_pl_report(_statement_amounts(prior_snapshot, "PL", currency)) if not prior_snapshot.empty else []
            pl_ytd_values = _make_pl_values(pl_ytd_rows)
            prior_pl_ytd_values = _make_pl_values(prior_pl_ytd_rows)
            current_note_amounts = _bs_amounts_by_ifrs_and_note(bs_frame)
            prior_note_amounts = _bs_amounts_by_ifrs_and_note(prior_bs_frame)
            bs_current = _statement_amounts(bs_frame, "BS", currency)
            bs_prior = _statement_amounts(prior_bs_frame, "BS", currency)
            bs_rows = _build_bs_report_with_notes(current_note_amounts, prior_note_amounts)
            bs_totals_current = {r[0]: float(r[1] or 0) for r in bs_rows if len(r) > 3 and r[3] in {"subtotal", "total"}}
            bs_totals_prior = {r[0]: float(r[2] or 0) for r in bs_rows if len(r) > 3 and r[3] in {"subtotal", "total"}}
            # The Word SFP generator requires the composite IFRS Line + Notes Line
            # key so it can classify and display every mapped account detail.
            bs_notes_current = {
                (str(ifrs_line), str(note)): float(amount or 0)
                for (ifrs_line, note), amount in current_note_amounts.items()
            }
            bs_notes_prior = {
                (str(ifrs_line), str(note)): float(amount or 0)
                for (ifrs_line, note), amount in prior_note_amounts.items()
            }

            # Some imported TBs carry the current-period P&L result outside the
            # equity accounts because the year-end closing journal has not yet
            # transferred it to retained earnings. Add it as a separate equity
            # line only when it exactly explains the SFP reconciliation gap.
            sfp_adjustments = []
            def _include_unclosed_period_result(note_balances, pl_values, period_name):
                if not note_balances:
                    return
                period_result = (
                    float(pl_values.get("Profit for the year", 0) or 0)
                    + float(pl_values.get("Other comprehensive income", 0) or 0)
                )
                if abs(period_result) < 0.005:
                    return
                asset_total = liability_total = equity_total = 0.0
                for (ifrs_line, _note), amount in note_balances.items():
                    nature = str(ifrs_line).casefold()
                    if "liabilit" in nature:
                        liability_total += float(amount or 0)
                    elif "equity" in nature or "capital" in nature or "retained earning" in nature:
                        equity_total += float(amount or 0)
                    else:
                        asset_total += float(amount or 0)
                reconciliation_gap = asset_total - liability_total - equity_total
                if abs(reconciliation_gap - period_result) <= 0.02:
                    note_balances[("Owners Equity", "Current period profit/(loss)")] = period_result
                    sfp_adjustments.append(
                        f"{period_name}: current-period result of {period_result:,.2f} included in equity to reconcile the unclosed trial balance."
                    )

            _include_unclosed_period_result(bs_notes_current, pl_ytd_values, "Current period closing balance")
            if prior_import:
                _include_unclosed_period_result(bs_notes_prior, prior_pl_ytd_values, "Comparative period closing balance")

            cash_current_rows, equity_current_rows, _ = _full_ifrs_schedules(
                entity, report_year, report_month, imports, pl_frame, bs_schedule,
                opening_year=opening_year, opening_month=opening_month, activity_start_month=report_start_month,
            )
            if prior_import and prior_opening_import:
                cash_prior_rows, equity_prior_rows, _ = _full_ifrs_schedules(
                    entity, report_year-1, report_month, imports, prior_pl_frame, prior_bs_schedule,
                    opening_year=prior_opening_year, opening_month=opening_month, activity_start_month=report_start_month,
                )
            else:
                cash_prior_rows, equity_prior_rows = [], []

            def _period_inputs(input_year, through_month, input_type, from_month=report_start_month):
                collected = []
                for input_month in range(int(from_month), int(through_month) + 1):
                    collected.extend(RX.get_inputs(entity['entity_code'], input_year, input_month, input_type))
                return collected

            def _make_cash_values(rows, input_year, through_month):
                values = {str(label): float(amount) for label, amount in rows if label and amount is not None}
                input_rows = _period_inputs(input_year, through_month, "CASH_FLOW")
                code_totals = {}
                for item in input_rows:
                    code = str(item.get("input_code") or "").upper()
                    code_totals[code] = code_totals.get(code, 0.0) + float(item.get("amount") or 0.0)
                # These are direct supplementary cash-flow inputs, not inferred TB movements.
                explicit_labels = {
                    "DISPOSAL": "Loss on of asset disposal",
                    "TAX_PAID": "Income tax paid",
                    "PPE_PURCHASE": "Purchases of property & equipment",
                }
                for code, label in explicit_labels.items():
                    if code in code_totals:
                        values[label] = code_totals[code]
                pbt = next((v for k, v in values.items() if _normalise_report_label(k) in {"profit loss before tax", "profit before tax"}), 0.0)
                values["Pre-working capital subtotal"] = (
                    pbt + values.get("Total automatically classified non-cash P&L adjustments", 0.0)
                    + values.get("Additional non-cash and other operating adjustments", 0.0)
                )
                return values

            cash_current = _make_cash_values(cash_current_rows, report_year, report_month)
            cash_prior = _make_cash_values(cash_prior_rows, report_year-1, report_month) if prior_import else {}

            def _equity_input(input_year, input_month, code):
                rows = _period_inputs(input_year, input_month, "EQUITY")
                recs = [x for x in rows if str(x.get("input_code") or "").upper() == code]
                return sum(float(x.get("amount") or 0) for x in recs) if recs else None

            current_dividend = _equity_input(report_year, report_month, "DIVIDEND")
            prior_dividend = _equity_input(report_year-1, report_month, "DIVIDEND") if prior_import else None
            current_comprehensive = pl_current.get("Profit for the year", 0.0) + pl_current.get("Other comprehensive income", 0.0)
            prior_comprehensive = pl_prior.get("Profit for the year", 0.0) + pl_prior.get("Other comprehensive income", 0.0) if prior_import else None
            profile = RX.get_latest_inputs(entity['entity_code'], report_year, report_month, "REPORT_PROFILE")

            def _build_detailed_pl_notes(frame):
                """Build account-level note detail from mapped YTD P&L TB rows."""
                result = {"N05": [], "N06": [], "N07": [], "N08": []}
                if frame is None or frame.empty:
                    return result
                data = frame[
                    frame["statement_type"].apply(lambda x: _is_statement_type(x, "PL"))
                    & frame["statement_line"].notna()
                ].copy()
                if data.empty:
                    return result
                dc = next((c for c in ("debit", "debit_amount", "dr") if c in data.columns), None)
                cc = next((c for c in ("credit", "credit_amount", "cr") if c in data.columns), None)
                if dc and cc:
                    debit = pd.to_numeric(data[dc], errors="coerce").fillna(0.0)
                    credit = pd.to_numeric(data[cc], errors="coerce").fillna(0.0)
                    data["_signed"] = credit - debit
                elif "balance" in data.columns:
                    data["_signed"] = pd.to_numeric(data["balance"], errors="coerce").fillna(0.0)
                else:
                    return result
                data["_line"] = data["statement_line"].fillna("").astype(str).str.strip()
                data["_note"] = data.get("notes_line", pd.Series(index=data.index, dtype=object)).fillna("").astype(str).str.strip()
                data["_account"] = data.get("account_name", pd.Series(index=data.index, dtype=object)).fillna("").astype(str).str.strip()
                def line_key(value):
                    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
                for _, row in data.iterrows():
                    line = line_key(row["_line"])
                    if line in {"revenue", "sales", "turnover"}:
                        code, amount = "N05", float(row["_signed"])
                    elif "cost of" in line or line in {"cost of operations", "cost of sales", "direct costs"}:
                        code, amount = "N06", -float(row["_signed"])
                    elif line in {"other income", "other operating income", "investment income"}:
                        code, amount = "N07", float(row["_signed"])
                    elif any(term in line for term in ("finance cost", "finance charge", "interest expense", "income tax", "tax expense", "other comprehensive", "associate")):
                        continue
                    else:
                        code, amount = "N08", -float(row["_signed"])
                    label = row["_note"] or row["_account"] or row["_line"]
                    if not label or abs(amount) < 0.005:
                        continue
                    result[code].append((label, amount))
                # Consolidate accounts sharing the same mapped Notes Line.
                for code, rows in result.items():
                    grouped = {}
                    for label, amount in rows:
                        grouped[label] = grouped.get(label, 0.0) + amount
                    result[code] = [(label, amount) for label, amount in sorted(grouped.items(), key=lambda x: x[0].casefold())]
                return result

            notes_detail_current = _build_detailed_pl_notes(pl_frame)
            notes_detail_prior = _build_detailed_pl_notes(prior_pl_frame)

            def _build_all_note_details(frame):
                """Build note-level TB details without inventing supporting schedules."""
                result = {f"N{i:02d}": [] for i in range(5, 18)}
                if frame is None or frame.empty:
                    return result
                data = frame.copy()
                for col in ("debit", "credit", "balance"):
                    if col in data.columns:
                        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0.0)
                def txt(row, col):
                    return str(row.get(col) or "").strip()
                def norm(value):
                    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
                for _, row in data.iterrows():
                    stype = str(row.get("statement_type") or "").upper()
                    line = txt(row, "statement_line")
                    note = txt(row, "notes_line") or txt(row, "account_name") or "Unassigned account"
                    account = txt(row, "account_name")
                    nature = txt(row, "account_nature")
                    hay = " ".join(norm(x) for x in (line, note, account, nature))
                    debit = float(row.get("debit") or 0.0)
                    credit = float(row.get("credit") or 0.0)
                    balance = float(row.get("balance") or 0.0)
                    if stype == "PL":
                        amount = credit - debit
                        line_n = norm(line)
                        account_n = norm(account)
                        if "income tax expense" in account_n or account_n.endswith("tax expense"):
                            code = "N09"
                        elif "revenue" in line_n or norm(nature) in {"sales", "revenue"}:
                            code = "N05"
                        elif any(x in line_n for x in ("cost of", "cost of operation", "direct cost")) or "cost of sales" in norm(nature):
                            code = "N06"
                        elif "other income" in line_n or "other income" in norm(nature):
                            code = "N07"
                        elif "tax" in line_n or "income tax" in norm(nature):
                            code = "N09"
                        elif "finance cost" in line_n or "interest expense" in line_n:
                            code = None
                        elif any(x in line_n for x in ("expense", "administrative", "operating")) or "expense" in norm(nature):
                            code = "N08"
                        else:
                            code = None
                    elif stype == "BS":
                        # Use mapped balance convention: liabilities/equity are credit-normal.
                        line_n = norm(line)
                        credit_normal = any(x in line_n for x in ("liabilit", "payable", "borrow", "loan", "lease obligation", "deferred income", "equity", "capital", "retained earning", "share", "provision"))
                        amount = (credit - debit) if credit_normal else (debit - credit)
                        if any(x in hay for x in ("property and equipment", "property plant", "fixed asset", "ppe", "computer equipment")):
                            code = "N10"
                        elif "investment in subsidiar" in hay or "subsidiary investment" in hay:
                            code = "N11"
                        elif "right of use" in hay or "lease liabilit" in hay:
                            code = "N12"
                        elif any(x in hay for x in ("cash at bank", "cash on hand", "cash and cash equivalent", "bank balance", "bank overdraft")):
                            code = "N13"
                        elif any(x in hay for x in ("payable", "accrued expense", "paye", "withholding tax payable", "trade creditor")):
                            code = "N17"
                        elif any(x in hay for x in ("related part", "holding compan", "fellow subsidiar", "director loan", "amount due from", "amount due to")):
                            code = "N15"
                        elif any(x in hay for x in ("share capital", "stated capital", "ordinary share")):
                            code = "N16"
                        elif any(x in hay for x in ("receivable", "prepayment", "vat recoverable", "tax recoverable", "withholding tax")):
                            code = "N14"
                        else:
                            code = None
                    else:
                        continue
                    if code:
                        result[code].append((note, amount))
                # Aggregate duplicate Notes Lines and keep stable alphabetical order.
                for code, rows in result.items():
                    totals = {}
                    for label, amount in rows:
                        totals[label] = totals.get(label, 0.0) + float(amount or 0.0)
                    result[code] = sorted(totals.items(), key=lambda x: x[0].casefold())
                return result

            notes_detail_current = _build_all_note_details(pl_frame)
            notes_detail_prior = _build_all_note_details(prior_pl_frame)
            # Supplementary disclosure narratives and schedules are saved separately
            # from the TB. Pass them through for the note-generation diagnostics.
            note_disclosures = RX.get_latest_notes(entity['entity_code'], report_year, report_month)
            reporting_inputs = {
                kind: [record for input_month in range(report_start_month, report_month + 1)
                       for record in RX.get_inputs(entity['entity_code'], report_year, input_month, kind)]
                for kind in ("EQUITY", "CASH_FLOW", "LEASE", "PPE", "TAX", "RELATED_PARTY", "COMMITMENTS", "EVENTS")
            }

            def _word_profit_or_loss_rows(values):
                values = values or {}
                rows = []
                def add(label, amount, kind="line"):
                    if amount is not None:
                        rows.append((label, float(amount or 0.0), kind))
                add("Revenue", values.get("Revenue"))
                add("Cost of service", values.get("Cost of sales", values.get("Cost of service")))
                add("Gross profit", values.get("Gross profit/(loss)"), "subtotal")
                add("Other income", values.get("Other income"))
                add("Operating expenses", values.get("Operating expenses"))
                add("Profit before finance cost and tax", values.get("Profit before finance cost and tax"), "subtotal")
                add("Finance cost", values.get("Finance cost", values.get("Finance costs")))
                associates = values.get("Share of profit/(loss) of associates")
                if associates is not None:
                    add("Share of profit/(loss) of associates", associates)
                add("(Loss)/profit before tax", values.get("Profit before tax", values.get("Profit/(loss) before tax")), "subtotal")
                if "Income tax expense" in values:
                    add("Income tax expense", values.get("Income tax expense"))
                add("(Loss)/profit for the year/period", values.get("Profit for the year", values.get("Net profit/(loss) for the period")), "total")
                add("Other comprehensive income", values.get("Other comprehensive income"))
                add("Total comprehensive income/(loss) for the year/period", values.get("Total comprehensive income"), "total")
                return rows

            context = {
                "entity_name": entity['entity_name'], "year": report_year, "month": report_month, "start_month": report_start_month, "currency": currency,
                "pl_current": pl_current, "pl_prior": pl_prior,
                "pl_statement_rows": _word_profit_or_loss_rows(pl_current),
                "pl_statement_prior_rows": _word_profit_or_loss_rows(pl_prior),
                "bs_current": bs_current, "bs_prior": bs_prior,
                "bs_totals_current": bs_totals_current, "bs_totals_prior": bs_totals_prior,
                "bs_notes_current": bs_notes_current, "bs_notes_prior": bs_notes_prior,
                "bs_statement_rows": bs_rows,
                "cash_current": cash_current, "cash_prior": cash_prior,
                "equity_current_rows": equity_current_rows, "equity_prior_rows": equity_prior_rows,
                "current_dividend": current_dividend, "prior_dividend": prior_dividend,
                "current_comprehensive": current_comprehensive, "prior_comprehensive": prior_comprehensive,
                "profile": profile,
                "notes_detail_current": notes_detail_current,
                "notes_detail_prior": notes_detail_prior,
                "note_disclosures": note_disclosures,
                "reporting_inputs": reporting_inputs,
            }
            saved_note_count = sum(1 for item in note_disclosures if str(item.get("narrative") or "").strip())
            st.info("Period activity is calculated by subtracting the opening cumulative trial balance from the closing cumulative trial balance. Comparatives use the corresponding prior-year period. Saved corporate profile information and the latest note narratives on or before the reporting date are reused. Detailed schedules that cannot be derived from the trial balance remain subject to management support and review.")
            st.caption(f"Data retrieved for this report: {len(profile)} corporate information field(s) and {saved_note_count} saved note narrative(s). Saving either section clears the previously generated Word file; generate the statements again to include your latest changes.")
            if not profile:
                st.warning("No saved Corporate Information records were found for this entity on or before the selected reporting period. Open Corporate Information, save the company details for this entity, then generate the report again.")
            for adjustment in sfp_adjustments:
                st.caption(adjustment)
            with st.expander("Review retrieved report data", expanded=False):
                st.markdown(f"**Profit or Loss ({period_range_label})**")
                show_dataframe(
                    pd.DataFrame([
                        {"Description": k, "Current period": v, "Comparative period": pl_prior.get(k)}
                        for k, v in pl_current.items()
                    ]),
                    use_container_width=True, hide_index=True,
                )
                st.markdown("**Statement of Financial Position — section totals**")
                show_dataframe(
                    pd.DataFrame([
                        {"Description": row[0], "Current period": row[1], "Comparative period": row[2], "Row type": row[3]}
                        for row in bs_rows
                    ]),
                    use_container_width=True, hide_index=True,
                )

            if generate_clicked:
                try:
                    # Re-read saved disclosures at the point of generation. This prevents
                    # a stale in-memory context from producing an older Word report.
                    generation_context = dict(context)
                    generation_context["profile"] = RX.get_latest_inputs(
                        entity['entity_code'], report_year, report_month, "REPORT_PROFILE"
                    )
                    generation_context["note_disclosures"] = RX.get_latest_notes(
                        entity['entity_code'], report_year, report_month
                    )
                    report_bytes, diagnostics = ARG.generate_native_word_report(generation_context)
                    st.session_state["automated_fs_result"] = {
                        "bytes": report_bytes, "diagnostics": diagnostics,
                        "entity": entity['entity_name'], "year": report_year, "month": report_month, "start_month": report_start_month, "template": "Native system report generator",
                    }
                    audit("AUTOMATED_FINANCIAL_STATEMENTS_GENERATED", f"Generated Word report using {report_engine_name}", report_year, report_month)
                except Exception as exc:
                    st.error(f"Could not generate the Word report: {exc}")

            result = st.session_state.get("automated_fs_result")
            if result and result.get("entity") == entity['entity_name'] and result.get("year") == report_year and result.get("month") == report_month and result.get("start_month", report_month) == report_start_month:
                st.success(f"Word financial statements generated for {period_range_label}.")
                st.download_button(
                    "Download completed Word financial statements", data=result["bytes"],
                    file_name=f"{entity['entity_name']} - Financial Statements - {report_year}-{report_start_month:02d}_to_{report_month:02d}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary", key=f"download_auto_fs_{entity['entity_code']}_{report_year}_{report_start_month}_{report_month}",
                )
                with st.expander("Generation checks and items requiring review", expanded=True):
                    for item in result.get("diagnostics", []):
                        st.warning(item)
                    st.caption("Review all generated figures, comparative values, supporting notes and disclosures before approval or external issue.")

elif page=="Entity Setup":
    st.subheader("Reporting entities")
    show_dataframe(pd.DataFrame(entities),use_container_width=True,hide_index=True)
    st.info("Initial entities are KSL (USD), KL (GHS) and Group Consolidated (USD). Confirm legal entity names and functional currencies before loading live balances. Group consolidation and foreign currency translation will be added in a later stage.")

st.divider()

