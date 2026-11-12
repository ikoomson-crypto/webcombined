"""Native generation of Kulana financial statements from saved application data."""
from __future__ import annotations

from pathlib import Path
from datetime import date
import calendar
import re
import io
from html import unescape
from html.parser import HTMLParser
from docx import Document



class _NarrativeHTMLParser(HTMLParser):
    """Convert saved rich-text HTML into readable paragraph text."""
    BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")
        if tag.lower() == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCK_TAGS and (not self.parts or not self.parts[-1].endswith("\n")):
            self.parts.append("\n")

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self):
        value = unescape("".join(self.parts))
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line)


def _narrative_to_plain_text(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "<" not in raw or ">" not in raw:
        return raw
    parser = _NarrativeHTMLParser()
    try:
        parser.feed(raw)
        parser.close()
        return parser.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", unescape(raw)).strip()

def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _fmt(value):
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) < 0.0000001:
        return "-"
    rounded = int(round(number))
    return f"({abs(rounded):,})" if rounded < 0 else f"{rounded:,}"


def _set_cell(cell, value):
    """Replace cell text while retaining the first paragraph/run formatting."""
    text = "" if value is None else str(value)
    if cell.paragraphs:
        p = cell.paragraphs[0]
        if p.runs:
            p.runs[0].text = text
            for run in p.runs[1:]:
                run.text = ""
        else:
            p.add_run(text)
        for extra in cell.paragraphs[1:]:
            for run in extra.runs:
                run.text = ""
    else:
        cell.text = text


def _set_paragraph(paragraph, value):
    text = "" if value is None else str(value)
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _lookup(mapping, aliases, default=None):
    """Exact normalized label matching first, then unique containment."""
    normalized = {_norm(k): v for k, v in (mapping or {}).items()}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized:
            return normalized[key]
    for alias in aliases:
        key = _norm(alias)
        if not key:
            continue
        hits = [(k, v) for k, v in normalized.items() if key in k or k in key]
        if len(hits) == 1:
            return hits[0][1]
    return default


PL_ALIASES = {
    "revenue": ["Revenue", "Turnover", "Sales"],
    "cost of service": ["Cost of service", "Cost of sales", "Cost of services", "Cost of operations"],
    "gross profit": ["Gross profit", "Gross profit/(loss)", "Gross profit/(loss)"],
    "other income": ["Other income"],
    "operating expenses": ["Operating expenses"],
    "profit before finance cost and tax": ["Profit before finance cost and tax", "Operating profit", "Operating result"],
    "finance cost": ["Finance cost", "Finance costs"],
    "profit before tax": ["Profit/(loss) before tax", "Profit before tax", "Loss/profit before tax"],
    "income tax expense": ["Income tax expense", "Tax expense"],
    "profit for the year": ["Net profit/(loss) for the period", "Profit for the year", "Profit for the period", "Loss/profit for the year", "(Loss)/profit for the year/period"],
    "other comprehensive income": ["Other comprehensive income", "Other comprehensive income/(loss)"],
    "total comprehensive income": ["Total comprehensive income/(loss)", "Total comprehensive (loss)/income for the year/period", "Total comprehensive income"],
}

BS_ALIASES = {
    "property & equipment": ["Property & equipment", "Property and equipment", "Property, plant and equipment", "PPE"],
    "investment in subsidiary company": ["Investment in subsidiary company", "Investment in subsidiary", "Investment in subsidiary undertaking"],
    "deferred tax assets": ["Deferred tax assets", "Deferred tax asset"],
    "right-of-use asset": ["Right-of-use asset", "Right of use asset", "Right-of-use assets"],
    "cash and cash equivalents": ["Cash and cash equivalents", "Cash and bank balances", "Cash at bank"],
    "trade and other receivables": ["Trade and other receivables", "Trade receivables and other receivables", "Receivables"],
    "amount due from related parties": ["Amount due from related parties", "Amounts due from related parties", "Related party receivables"],
    "tax recoverable": ["Tax recoverable", "Current tax asset", "Income tax recoverable"],
    "total non-current assets": ["Total non-current assets", "Total non current assets"],
    "total current assets": ["Total current assets"],
    "total assets": ["Total assets"],
    "stated capital": ["Stated capital", "Share capital"],
    "retained earnings": ["Retained earnings"],
    "lease liability": ["Lease liability"],
    "total equity": ["Total equity", "Equity"],
    "total non-current liability": ["Total non-current liabilities", "Total non-current liability", "Total non current liabilities"],
    "trade and other payables": ["Trade and other payables", "Trade payables and other payables"],
    "bank overdraft": ["Bank overdraft", "Bank overdrafts"],
    "deferred income": ["Deferred income", "Contract liabilities"],
    "total current liability": ["Total current liabilities", "Total current liability"],
    "total liability": ["Total liabilities", "Total liability"],
    "total equity and liabilities": ["Total equity and liabilities"],
}

CF_ALIASES = {
    "pbt": ["Profit/(loss) before tax", "(Loss)/profit before income tax", "Profit before income tax", "Profit before tax"],
    "depreciation of property & equipment": ["Depreciation of property & equipment", "Depreciation of property and equipment", "Depreciation of property, plant and equipment"],
    "depreciation of right-of-use asset": ["Depreciation of right-of-use asset", "Depreciation of right of use asset"],
    "loss on of asset disposal": ["Loss on of asset disposal", "Loss on disposal of assets", "Loss on disposal of asset"],
    "withholding tax credits": ["Withholding tax credits", "Unused withholding tax"],
    "interest on right-of-use asset": ["Interest on right-of-use asset", "Interest on lease liability"],
    "foreign exchange on right-of-use asset": ["Foreign exchange on right-of-use asset", "Foreign exchange on lease liability"],
    "decrease in trade and other receivables": ["Decrease in trade and other receivables", "Decrease/(increase) in receivables"],
    "increase in amounts due from related parties": ["Increase in amounts due from related parties", "Increase in amounts due from related party"],
    "decrease increase in trade and other payables": ["(Decrease)/increase in trade and other payables", "Increase/(decrease) in trade and other payables"],
    "decrease increase in deferred income": ["(Decrease)/Increase in deferred income", "Increase/(decrease) in deferred income"],
    "decrease in current tax asset": ["Decrease in current tax asset", "Decrease in tax recoverable"],
    "income tax paid": ["Income tax paid", "Tax paid"],
    "lease payments": ["Lease payments", "Lease principal payments"],
    "purchases of property & equipment": ["Purchases of property & equipment", "Purchase of property, plant and equipment", "Purchase of property and equipment"],
    "fixed deposit investment": ["Fixed deposit investment", "Fixed deposit investments", "Investment in fixed deposits"],
    "investment in subsidiary": ["Investment in subsidiary", "Investment in subsidiary company"],
    "net cash generated from operating activities": ["Net cash generated from operating activities", "Net cash generated from/(used in) operating activities"],
    "net cash generated from investing activities": ["Net cash generated from/(used in) investing activities", "Net cash generated from investing activities"],
    "net cash used in financing activities": ["Net cash used in financing activities", "Net cash generated from/(used in) financing activities"],
    "net increase in cash and cash equivalents": ["Net increase in cash and cash equivalents", "Net increase/(decrease) in cash and cash equivalents"],
    "cash and cash equivalents at start of year": ["Cash and cash equivalents at start of year/period", "Opening cash and cash equivalents"],
    "cash and cash equivalents at end of year": ["Cash and cash equivalents at end of year/period", "Closing cash and cash equivalents"],
}


def _populate_year_headers(doc, year, comparative_year, currency, month=12):
    end_date = date(year, month, calendar.monthrange(year, month)[1])
    comparative_end_date = date(comparative_year, month, calendar.monthrange(comparative_year, month)[1])
    date_label = end_date.strftime("%d %B")
    comparative_date_label = comparative_end_date.strftime("%d %B")
    # Main statements: year and currency columns follow the uploaded master layout.
    for table_index, year_row, currency_row, current_col, prior_col in (
        (2, 2, 3, 2, 4),  # Profit or loss
        (3, 0, 1, 2, 4),  # Financial position
        (5, 2, 3, 2, 4),  # Cash flow
    ):
        if table_index >= len(doc.tables):
            continue
        table = doc.tables[table_index]
        if year_row < len(table.rows):
            for col, label in ((current_col, str(year)), (prior_col, str(comparative_year))):
                if col < len(table.rows[year_row].cells):
                    _set_cell(table.rows[year_row].cells[col], label)
        if currency_row < len(table.rows):
            for col in (current_col, prior_col):
                if col < len(table.rows[currency_row].cells):
                    _set_cell(table.rows[currency_row].cells[col], currency)
        if table_index in (2, 5) and table.rows:
            if month != 12:
                for col in (2, 4):
                    if col < len(table.rows[0].cells):
                        _set_cell(table.rows[0].cells[col], "Period ended")
            if 1 < len(table.rows):
                for col in (2, 4):
                    if col < len(table.rows[1].cells):
                        _set_cell(table.rows[1].cells[col], date_label if col == 2 else comparative_date_label)

    # Comparative notes with two reporting-year columns.
    for table_index in (12, 13, 14, 15, 16, 17, 18):
        if table_index < len(doc.tables) and len(doc.tables[table_index].rows) > 3:
            t = doc.tables[table_index]
            for col, label in ((3, str(year)), (5, str(comparative_year))):
                if col < len(t.rows[2].cells): _set_cell(t.rows[2].cells[col], label)
                if col < len(t.rows[3].cells): _set_cell(t.rows[3].cells[col], currency)
                if month != 12:
                    if col < len(t.rows[0].cells): _set_cell(t.rows[0].cells[col], "Period ended")
                    if col < len(t.rows[1].cells):
                        _set_cell(t.rows[1].cells[col], date_label if col == 3 else comparative_date_label)

    # Deferred tax position, cash, receivables and related-party note tables.
    for table_index in (20, 26, 27, 28, 30, 36):
        if table_index < len(doc.tables) and len(doc.tables[table_index].rows) > 1:
            t = doc.tables[table_index]
            for col, label in ((3, str(year)), (5, str(comparative_year))):
                if col < len(t.rows[0].cells): _set_cell(t.rows[0].cells[col], label)
                if col < len(t.rows[1].cells): _set_cell(t.rows[1].cells[col], currency)

    # Single-period lease maturity note.
    if len(doc.tables) > 25 and len(doc.tables[25].rows) > 1:
        _set_cell(doc.tables[25].rows[0].cells[1], str(year))
        _set_cell(doc.tables[25].rows[1].cells[1], currency)

    # Note 10 PPE roll-forward has comparative columns and year labels in its rows.
    if len(doc.tables) > 21 and len(doc.tables[21].rows) > 1:
        t = doc.tables[21]
        for col in (1, 3, 5, 7, 9):
            if col < len(t.rows[1].cells): _set_cell(t.rows[1].cells[col], currency)
        current_rows = {
            3: f"At 1 January {year}", 7: f"At {end_date.strftime('%d %B %Y')}",
            10: f"At 1 January {year}", 14: f"At {end_date.strftime('%d %B %Y')}",
            16: end_date.strftime("%d %B %Y"),
        }
        prior_rows = {
            21: f"At 1 January {comparative_year}", 24: f"At {comparative_end_date.strftime('%d %B %Y')}",
            27: f"At 1 January {comparative_year}", 30: f"At {comparative_end_date.strftime('%d %B %Y')}",
            32: comparative_end_date.strftime("%d %B %Y"),
        }
        for idx, label in {**current_rows, **prior_rows}.items():
            if idx < len(t.rows):
                _set_cell(t.rows[idx].cells[0], label)

    # Other supporting notes with one or two currency columns.
    for table_index in (19,):
        if table_index < len(doc.tables) and len(doc.tables[table_index].rows) > 1:
            t = doc.tables[table_index]
            for col in (1, 3, 5, 7):
                if col < len(t.rows[1].cells): _set_cell(t.rows[1].cells[col], currency)
            for row_idx, label in ((3, f"At 1 January {comparative_year}"),
                                   (6, f"At {comparative_end_date.strftime('%d %B %Y')}"),
                                   (10, f"At {end_date.strftime('%d %B %Y')}")):
                if row_idx < len(t.rows): _set_cell(t.rows[row_idx].cells[0], label)

    for table_index in (22, 23):
        if table_index < len(doc.tables) and len(doc.tables[table_index].rows) > 1:
            _set_cell(doc.tables[table_index].rows[1].cells[1], currency)
            if len(doc.tables[table_index].rows) > 6:
                _set_cell(doc.tables[table_index].rows[6].cells[0], f"At {end_date.strftime('%d %B %Y')}")
    if len(doc.tables) > 24 and doc.tables[24].rows:
        _set_cell(doc.tables[24].rows[0].cells[1], currency)

    # Related-party and other disclosure tables use a different column grid.
    for table_index in (29, 33, 34):
        if table_index < len(doc.tables) and len(doc.tables[table_index].rows) > 3:
            t = doc.tables[table_index]
            for col, label in ((2, str(year)), (4, str(comparative_year))):
                if col < len(t.rows[2].cells): _set_cell(t.rows[2].cells[col], label)
                if col < len(t.rows[3].cells): _set_cell(t.rows[3].cells[col], currency)

    # Statement of Changes in Equity has three amount columns.
    if len(doc.tables) > 4:
        t = doc.tables[4]
        if len(t.rows) > 1:
            for col in (2, 4, 6):
                if col < len(t.rows[1].cells): _set_cell(t.rows[1].cells[col], currency)
        start_month = int(context.get("start_month") or 1)
        for row_idx, label in ((3, f"At {start_month} {date(year, start_month, 1).strftime('%B')} {comparative_year}"),
                               (7, f"At {comparative_end_date.strftime('%d %B %Y')}"),
                               (12, f"At {end_date.strftime('%d %B %Y')}")):
            if row_idx < len(t.rows): _set_cell(t.rows[row_idx].cells[0], label)


def _populate_cover_and_dates(doc, entity_name, year, month=12):
    """Populate entity and reporting dates consistently throughout the document."""
    end_date = date(year, month, calendar.monthrange(year, month)[1])
    date_text = end_date.strftime("%d %B %Y")
    period_word = "year" if month == 12 else "period"

    def update_text(text):
        value = str(text or "")
        # Replace date captions whether they were blank placeholders or stale static dates.
        value = re.sub(
            r"(?i)for the (?:year|period) ended\s*(?:_{3,}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            f"For the {period_word} ended {date_text}", value,
        )
        # Some templates place the date on the next paragraph; update only the
        # wording here and let the following date placeholder receive the date.
        value = re.sub(r"(?i)for the year ended", f"For the {period_word} ended", value)
        value = re.sub(
            r"(?i)as at\s*(?:_{3,}|\d{1,2}\s+[A-Za-z]+\s+\d{4})?",
            f"As at {date_text}", value,
        )
        return value

    previous_nonempty = ""
    for paragraph in doc.paragraphs:
        old = paragraph.text
        if re.fullmatch(r"\s*_+\s*", old):
            previous = _norm(previous_nonempty)
            replacement = date_text if ("year ended" in previous or "period ended" in previous or "as at" in previous) else entity_name
            _set_paragraph(paragraph, replacement)
        else:
            new_text = update_text(old)
            if new_text != old:
                _set_paragraph(paragraph, new_text)
        if old.strip():
            previous_nonempty = old

    # The same date placeholders can occur in tables and in headers/footers.
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                old = cell.text
                new_text = update_text(old)
                if new_text != old:
                    _set_cell(cell, new_text)
                elif re.fullmatch(r"\s*_+\s*", old):
                    # Leave generic blank cells untouched; date labels are handled
                    # when the caption and placeholder occur in the same cell.
                    pass

    for section in doc.sections:
        for part in (section.header, section.footer):
            for paragraph in part.paragraphs:
                old = paragraph.text
                new_text = update_text(old)
                if new_text != old:
                    _set_paragraph(paragraph, new_text)
                elif re.fullmatch(r"\s*_+\s*", old):
                    # Avoid replacing signature lines in headers/footers.
                    pass
            for table in part.tables:
                for row in table.rows:
                    for cell in row.cells:
                        old = cell.text
                        new_text = update_text(old)
                        if new_text != old:
                            _set_cell(cell, new_text)


def _is_not_applicable_profile_field(item):
    """Return True when a corporate information field is marked Not applicable."""
    status = (item or {}).get("status", (item or {}).get("Status", ""))
    return str(status or "").strip().casefold() == "not applicable"


def _populate_corporate_information(doc, profile):
    """Populate the corporate information table from the latest saved profile.

    Match by saved code and visible row label rather than relying only on fixed
    row numbers. This supports standard and user-added profile fields.
    """
    if len(doc.tables) <= 1:
        return ["Corporate Information table was not found."]
    table = doc.tables[1]
    profile = profile or []
    by_code, by_label = {}, {}
    for item in profile:
        if _is_not_applicable_profile_field(item):
            continue
        code = str(item.get("input_code") or item.get("Code") or "").strip()
        label = str(item.get("description") or item.get("Corporate information") or code).strip()
        value = str(item.get("narrative") or item.get("Information") or item.get("Commentary") or "").strip()
        if code:
            code_key = re.sub(r"[^A-Z0-9]+", "_", code.upper()).strip("_")
            by_code[code_key] = value
        if label:
            by_label[_norm(label)] = value

    # Accept standard codes and common legacy/user-created variants.
    code_aliases = {
        "DIRECTORS": ("DIRECTORS", "BOARD_OF_DIRECTORS", "BOARD_DIRECTORS"),
        "REGISTERED_OFFICE": ("REGISTERED_OFFICE", "REGISTERED_OFFICE_ADDRESS"),
        "COMPANY_SECRETARY": ("COMPANY_SECRETARY", "SECRETARY"),
        "AUDITOR": ("AUDITOR", "EXTERNAL_AUDITOR"),
        "LEGAL_ADVISERS": ("LEGAL_ADVISERS", "LEGAL_ADVISORS", "LEGAL_ADVISER", "LEGAL_ADVISOR"),
        "BANKERS": ("BANKERS", "BANK", "BANKING_PARTNERS"),
        "APPROVAL_SIGNATORIES": ("APPROVAL_SIGNATORIES", "APPROVAL_AND_SIGNING", "SIGNATORIES", "AUTHORISED_SIGNATORIES", "AUTHORIZED_SIGNATORIES"),
    }

    field_aliases = [
        ("DIRECTORS", ("board of directors", "directors")),
        ("REGISTERED_OFFICE", ("registered office",)),
        ("COMPANY_SECRETARY", ("company secretary",)),
        ("AUDITOR", ("auditor", "external auditor")),
        ("LEGAL_ADVISERS", ("legal advisors", "legal advisers")),
        ("BANKERS", ("bankers", "bank")),
        ("APPROVAL_SIGNATORIES", ("approval and signing", "approval signatories", "authorised signatories", "authorized signatories")),
    ]
    missing = []
    used_rows = set()
    for code, aliases in field_aliases:
        value = next((by_code.get(alias_code) for alias_code in code_aliases.get(code, (code,))
                      if by_code.get(alias_code)), None)
        if value is None:
            value = next((by_label.get(_norm(alias)) for alias in aliases if by_label.get(_norm(alias))), None)
        if not value:
            missing.append(aliases[0].title())
            continue
        # Prefer a row whose left-hand label matches the field.
        target_row = None
        for idx, row in enumerate(table.rows):
            if idx in used_rows or len(row.cells) < 2:
                continue
            heading = _norm(row.cells[0].text)
            if any(_norm(alias) in heading or heading in _norm(alias) for alias in aliases if heading):
                target_row = row
                used_rows.add(idx)
                break
        # Fallback to the established Kulana template row positions.
        fallback = {"DIRECTORS": 0, "REGISTERED_OFFICE": 3, "COMPANY_SECRETARY": 7,
                    "AUDITOR": 14, "LEGAL_ADVISERS": 16, "BANKERS": 18}
        if target_row is None and code in fallback and fallback[code] < len(table.rows):
            target_row = table.rows[fallback[code]]
        if target_row is not None:
            _set_cell(target_row.cells[1], value)

    # Populate any extra saved profile fields if a matching heading exists in the template.
    existing_headings = set()
    for row in table.rows:
        if len(row.cells) < 2:
            continue
        heading = _norm(row.cells[0].text)
        if heading:
            existing_headings.add(heading)
            if heading in by_label and by_label[heading]:
                _set_cell(row.cells[1], by_label[heading])

    # Include user-added corporate information fields in the Word report too.
    standard_codes = {code for code, _ in field_aliases}
    standard_labels = {_norm(alias) for _, aliases in field_aliases for alias in aliases}
    for item in profile:
        code = str(item.get("input_code") or item.get("Code") or "").strip()
        label = str(item.get("description") or item.get("Corporate information") or code).strip()
        value = str(item.get("narrative") or item.get("Information") or item.get("Commentary") or "").strip()
        label_key = _norm(label)
        code_key = re.sub(r"[^A-Z0-9]+", "_", code.upper()).strip("_")
        if not label or not value or code_key in standard_codes or label_key in standard_labels or label_key in existing_headings:
            continue
        new_row = table.add_row()
        _set_cell(new_row.cells[0], f"{label}:")
        _set_cell(new_row.cells[1], value)
        existing_headings.add(label_key)

    signatories = next((by_code.get(alias_code) for alias_code in code_aliases["APPROVAL_SIGNATORIES"]
                        if by_code.get(alias_code)), None) or by_label.get(_norm("Approval and signing")) or ""
    if signatories:
        # Find the approval paragraph by its wording instead of a brittle paragraph index.
        approval_idx = next((i for i, para in enumerate(doc.paragraphs)
                             if "approved" in _norm(para.text) and "signed by" in _norm(para.text)), None)
        if approval_idx is not None:
            target = next((para for para in doc.paragraphs[approval_idx + 1:approval_idx + 4]
                           if "_" in para.text or not para.text.strip()), None)
            if target is not None:
                parts = [x.strip() for x in re.split(r"\n|\||;", signatories) if x.strip()]
                _set_paragraph(target, "\t\t\t".join(parts))
    return [f"Corporate Information not supplied: {name}." for name in missing]


def _populate_pl(doc, current, prior):
    if len(doc.tables) <= 2:
        return ["Profit or Loss table was not found."]
    table = doc.tables[2]
    diagnostics = []
    for row in table.rows:
        if not row.cells:
            continue
        label = " ".join(row.cells[0].text.split())
        key = _norm(label)
        if not key:
            continue
        aliases = None
        for alias_key, alias_values in PL_ALIASES.items():
            candidates = [_norm(alias_key)] + [_norm(x) for x in alias_values]
            if key in candidates:
                aliases = alias_values
                break
        if not aliases:
            continue
        cur = _lookup(current, aliases)
        prev = _lookup(prior, aliases)
        if cur is None:
            diagnostics.append(f"Profit or Loss: no source found for '{label}'.")
        _set_cell(row.cells[2], _fmt(cur))
        _set_cell(row.cells[4], _fmt(prev))
    return diagnostics


def _populate_bs(doc, current, prior, totals_current=None, totals_prior=None, notes_current=None, notes_prior=None):
    """Populate a detailed, expandable Statement of Financial Position.

    The original Word template contains only a small fixed set of headings.
    Rebuild its body from the mapped IFRS Line + Notes Line balances so every
    mapped detail is visible, while retaining the template's table styling.
    """
    if len(doc.tables) <= 3:
        return ["Statement of Financial Position table was not found."]
    table = doc.tables[3]
    notes_current = notes_current or {}
    notes_prior = notes_prior or {}

    def section_for(line):
        value = str(line or "").casefold()
        if any(k in value for k in ("due from", "loan to", "loan receivable", "receivable")):
            return "Assets"
        if any(k in value for k in (
            "equity", "capital", "retained earning", "share", "reserve",
            "net profit", "net loss", "profit/(loss)"
        )):
            return "Equity"
        if any(k in value for k in (
            "liabilit", "payable", "borrow", "loan from", "loan payable",
            "lease obligation", "deferred income", "contract liabilit",
            "provision", "tax payable", "due to"
        )):
            return "Liabilities"
        return "Assets"

    def asset_group(line):
        value = str(line or "").casefold().replace("–", "-")
        noncurrent = (
            "property", "plant", "equipment", "ppe", "intangible", "goodwill",
            "right-of-use", "right of use", "investment property", "non-current",
            "non current", "deferred tax asset", "long-term investment", "long term investment"
        )
        return "Non-current assets" if any(k in value for k in noncurrent) else "Current assets"

    def liability_group(line):
        value = str(line or "").casefold().replace("–", "-")
        noncurrent = ("non-current", "non current", "long-term", "long term", "deferred tax liability")
        return "Non-current liabilities" if any(k in value for k in noncurrent) else "Current liabilities"

    # Consolidate all mapped IFRS lines and Notes Lines from both periods.
    keys = list(dict.fromkeys(list(notes_current.keys()) + list(notes_prior.keys())))
    groups = {
        "Non-current assets": [], "Current assets": [],
        "Non-current liabilities": [], "Current liabilities": [], "Equity": []
    }
    line_totals_current, line_totals_prior = {}, {}
    for key in keys:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        line, note = str(key[0]).strip(), str(key[1]).strip() or "Notes line not assigned"
        section = section_for(line)
        group = asset_group(line) if section == "Assets" else (
            liability_group(line) if section == "Liabilities" else "Equity"
        )
        groups[group].append((line, note))
        line_totals_current[line] = line_totals_current.get(line, 0.0) + float(notes_current.get(key, 0.0) or 0.0)
        line_totals_prior[line] = line_totals_prior.get(line, 0.0) + float(notes_prior.get(key, 0.0) or 0.0)

    def sum_group(group, period):
        if period == "prior" and not notes_prior:
            return None
        line_totals = line_totals_current if period == "current" else line_totals_prior
        return sum(line_totals.get(line, 0.0) for line in {line for line, _note in groups[group]})

    # Keep the template's two column-header rows. Locate formatting prototypes
    # by their labels so both the full 47-row master template and compact 16-row
    # generated/revised templates are supported.
    from copy import deepcopy
    if len(table.rows) < 8:
        return ["Statement of Financial Position template does not contain enough rows to preserve its formatting."]

    def row_label(row):
        return " ".join(row.cells[0].text.split()).casefold() if row.cells else ""

    def find_row(predicate, fallback):
        for candidate in table.rows:
            if predicate(row_label(candidate)):
                return candidate
        return table.rows[fallback]

    major_section_row = find_row(lambda x: x == "assets", 2)
    group_row = find_row(lambda x: x == "non-current assets", 3)
    detail_row = find_row(
        lambda x: bool(x) and x not in {
            "assets", "equity and liabilities", "non-current assets", "current assets",
            "non-current liabilities", "current liabilities", "equity",
        } and not x.startswith("total "),
        3,
    )
    subtotal_row = find_row(lambda x: x.startswith("total non-current asset"), 4)
    total_row = find_row(lambda x: x == "total assets", 7)

    major_section_proto = deepcopy(major_section_row._tr)
    group_proto = deepcopy(group_row._tr)
    detail_proto = deepcopy(detail_row._tr)
    subtotal_proto = deepcopy(subtotal_row._tr)
    total_proto = deepcopy(total_row._tr)

    # Remove all old body rows after the two column-header rows.
    for row in list(table.rows)[2:]:
        table._tbl.remove(row._tr)

    def add_row(proto, label, current_value=None, prior_value=None, indent=False, detail=False):
        tr = deepcopy(proto)
        table._tbl.append(tr)
        row = table.rows[-1]
        if row.cells:
            _set_cell(row.cells[0], label)
        if len(row.cells) > 2:
            _set_cell(row.cells[2], _fmt(current_value))
        if len(row.cells) > 4:
            _set_cell(row.cells[4], _fmt(prior_value))
        # Remove stale note numbers or other text from cloned template cells.
        if len(row.cells) > 1:
            _set_cell(row.cells[1], "")
        if len(row.cells) > 3:
            _set_cell(row.cells[3], "")
        if row.cells and row.cells[0].paragraphs:
            for paragraph in row.cells[0].paragraphs:
                for run in paragraph.runs:
                    if detail:
                        run.bold = False
                        run.italic = True
                    elif indent:
                        run.bold = True
        return row

    def add_group_detail_then_summary(group):
        """Show mapped Notes Line descriptions directly, without repeating IFRS parent labels.

        Preserve the order supplied by the COA/reporting source. For example,
        current liabilities should read Trade payable, Due to related party,
        Deferred income when that is the source order. Group totals remain below
        the detail rows; redundant per-IFRS-line summary rows are omitted.
        """
        seen = set()
        for line, note in groups[group]:
            identity = (line.casefold(), note.casefold())
            if identity in seen:
                continue
            seen.add(identity)
            cur = float(notes_current.get((line, note), 0.0) or 0.0)
            prev = float(notes_prior.get((line, note), 0.0) or 0.0) if notes_prior else None
            label = note.strip()
            if not label or label.casefold() == "notes line not assigned":
                label = line.strip()
            add_row(detail_proto, label, cur, prev, indent=False, detail=True)

    add_row(major_section_proto, "ASSETS")
    for group in ("Non-current assets", "Current assets"):
        add_row(group_proto, group)
        add_group_detail_then_summary(group)
        title = "Total Non-current Assets" if group == "Non-current assets" else "Total Current Assets"
        add_row(subtotal_proto, title, sum_group(group, "current"), sum_group(group, "prior"))
    assets_current = sum(sum_group(g, "current") for g in ("Non-current assets", "Current assets"))
    assets_prior = sum(sum_group(g, "prior") or 0.0 for g in ("Non-current assets", "Current assets")) if notes_prior else None
    add_row(total_proto, "Total Assets", assets_current, assets_prior)

    add_row(major_section_proto, "EQUITY AND LIABILITIES")
    for group in ("Non-current liabilities", "Current liabilities", "Equity"):
        add_row(group_proto, group)
        add_group_detail_then_summary(group)
        title = {
            "Non-current liabilities": "Total Non-current Liabilities",
            "Current liabilities": "Total Current Liabilities",
            "Equity": "Total Equity",
        }[group]
        add_row(subtotal_proto, title, sum_group(group, "current"), sum_group(group, "prior"))

    liabilities_current = sum(sum_group(g, "current") for g in ("Non-current liabilities", "Current liabilities"))
    liabilities_prior = sum(sum_group(g, "prior") or 0.0 for g in ("Non-current liabilities", "Current liabilities")) if notes_prior else None
    equity_current = sum_group("Equity", "current")
    equity_prior = sum_group("Equity", "prior")
    add_row(
        total_proto, "Total Equity and Liabilities",
        liabilities_current + equity_current,
        (liabilities_prior or 0.0) + (equity_prior or 0.0) if notes_prior else None,
    )

    diagnostics = []
    if not keys:
        diagnostics.append("Statement of Financial Position: no IFRS Line / Notes Line detail was supplied; check the COA mapping and imported trial balance.")
    if not groups["Non-current assets"] and not groups["Current assets"]:
        diagnostics.append("Statement of Financial Position: no asset detail was mapped.")
    if not groups["Non-current liabilities"] and not groups["Current liabilities"] and not groups["Equity"]:
        diagnostics.append("Statement of Financial Position: no liability or equity detail was mapped.")
    return diagnostics


def _populate_cashflow(doc, current, prior):
    if len(doc.tables) <= 5:
        return ["Statement of Cash Flows table was not found."]
    table = doc.tables[5]
    diagnostics = []
    for row_idx, row in enumerate(table.rows):
        if not row.cells:
            continue
        label = " ".join(row.cells[0].text.split())
        key = _norm(label)
        if not key:
            # In the source statement this specific blank description row is the subtotal
            # after profit before tax and non-cash adjustments, before working capital.
            if row_idx == 16 and len(row.cells) > 4 and row.cells[2].text == "":
                cur = current.get("Pre-working capital subtotal")
                prev = prior.get("Pre-working capital subtotal")
                if cur is not None:
                    _set_cell(row.cells[2], _fmt(cur))
                if prev is not None:
                    _set_cell(row.cells[4], _fmt(prev))
            continue
        aliases = None
        for alias_key, alias_values in CF_ALIASES.items():
            candidates = [_norm(alias_key)] + [_norm(x) for x in alias_values]
            if key in candidates:
                aliases = alias_values
                break
        if aliases:
            cur = _lookup(current, aliases)
            prev = _lookup(prior, aliases)
            if cur is None:
                diagnostics.append(f"Cash Flow: no source found for '{label}'.")
            _set_cell(row.cells[2], _fmt(cur))
            _set_cell(row.cells[4], _fmt(prev))
        elif key == "cash generated from operating activities":
            # The pre-tax subtotal is derived from the report's net operating
            # cash flow less the separately displayed tax and lease payments.
            net_cur = _lookup(current, CF_ALIASES["net cash generated from operating activities"])
            tax_cur = _lookup(current, CF_ALIASES["income tax paid"], 0.0)
            lease_cur = _lookup(current, CF_ALIASES["lease payments"], 0.0)
            net_prev = _lookup(prior, CF_ALIASES["net cash generated from operating activities"])
            tax_prev = _lookup(prior, CF_ALIASES["income tax paid"], 0.0)
            lease_prev = _lookup(prior, CF_ALIASES["lease payments"], 0.0)
            cur = (net_cur - tax_cur - lease_cur) if net_cur is not None else None
            prev = (net_prev - tax_prev - lease_prev) if net_prev is not None else None
            _set_cell(row.cells[2], _fmt(cur))
            _set_cell(row.cells[4], _fmt(prev))
    # Populate the unlabeled pre-working-capital adjustment subtotal from the
    # PBT plus all adjustments already present in the schedule.
    # It is intentionally not guessed if the schedule does not expose its components.
    return diagnostics


def _populate_soce(doc, current_rows, prior_rows, current_dividend=None, prior_dividend=None,
                   current_comprehensive=None, prior_comprehensive=None):
    if len(doc.tables) <= 4:
        return ["Statement of Changes in Equity table was not found."]
    table = doc.tables[4]
    diagnostics = []
    def component(rows, name, col):
        for row in rows or []:
            if _norm(row[0]) == _norm(name):
                vals = list(row[1:])
                return vals[col] if col < len(vals) else None
        return None

    # The uploaded template contains comparative-year and current-year movements.
    # Its three amount columns are Share capital, Retained earnings and Total.
    for row_idx, year_rows, dividend, comprehensive, closing in (
        (3, prior_rows, None, None, False),
        (4, None, prior_dividend, None, False),
        (5, None, None, prior_comprehensive, False),
        (7, prior_rows, None, None, True),
        (9, None, current_dividend, None, False),
        (10, None, None, current_comprehensive, False),
        (12, current_rows, None, None, True),
    ):
        if row_idx >= len(table.rows):
            continue
        row = table.rows[row_idx]
        vals = [None, None, None]
        if year_rows is not None:
            if closing:
                vals[0] = component(year_rows, "Share capital", 5)
                vals[1] = component(year_rows, "Retained earnings", 5)
                vals[2] = (vals[0] or 0) + (vals[1] or 0)
                if vals[0] is None and vals[1] is None:
                    vals = [component(year_rows, "Share capital", 6),
                            component(year_rows, "Retained earnings", 6), None]
                    if vals[2] is None and vals[0] is not None and vals[1] is not None:
                        vals[2] = vals[0] + vals[1]
            else:
                vals[0] = component(year_rows, "Share capital", 0)
                vals[1] = component(year_rows, "Retained earnings", 0)
                vals[2] = (vals[0] or 0) + (vals[1] or 0) if vals[0] is not None or vals[1] is not None else None
        elif dividend is not None:
            vals = [0.0, float(dividend), float(dividend)]
        elif comprehensive is not None:
            vals = [0.0, float(comprehensive), float(comprehensive)]
        for col, value in zip((2, 4, 6), vals):
            if col < len(row.cells):
                _set_cell(row.cells[col], _fmt(value))
        if all(v is None for v in vals):
            diagnostics.append(f"Changes in Equity: row '{row.cells[0].text.strip()}' has no supporting source.")
    return diagnostics


def _populate_detailed_pl_notes(doc, current, prior, note_disclosures=None):
    """Populate the existing detailed P&L note tables (Notes 5–8)."""
    table_by_note = {"N05": 12, "N06": 13, "N07": 14, "N08": 15}
    note_names = {"N05": "Revenue", "N06": "Cost of service", "N07": "Other income", "N08": "Operating expenses"}
    diagnostics = []
    saved_status = {str(x.get("note_code") or "").upper(): x for x in (note_disclosures or [])}
    for code, table_index in table_by_note.items():
        if _is_not_applicable_disclosure(saved_status.get(code)):
            continue
        if table_index >= len(doc.tables):
            diagnostics.append(f"Note {code}: {note_names[code]} table was not found in the Word template.")
            continue
        table = doc.tables[table_index]
        cur_rows = list((current or {}).get(code, []) or [])
        prior_rows = list((prior or {}).get(code, []) or [])
        cur_map = {str(label).strip(): float(amount or 0) for label, amount in cur_rows if str(label).strip()}
        prior_map = {str(label).strip(): float(amount or 0) for label, amount in prior_rows if str(label).strip()}
        labels = sorted(set(cur_map) | set(prior_map), key=str.casefold)
        start_row = 5
        required = start_row + len(labels)
        while len(table.rows) < required:
            table.add_row()
        for offset, label in enumerate(labels):
            row = table.rows[start_row + offset]
            if len(row.cells) >= 6:
                _set_cell(row.cells[0], label)
                _set_cell(row.cells[3], _fmt(cur_map.get(label)))
                _set_cell(row.cells[5], _fmt(prior_map.get(label)))
        # Clear unused template rows so stale example labels/amounts are not shown.
        for row_idx in range(start_row + len(labels), len(table.rows)):
            row = table.rows[row_idx]
            if len(row.cells) >= 6:
                for col in (0, 3, 5):
                    _set_cell(row.cells[col], "")
        if not labels:
            diagnostics.append(f"Note {code} — {note_names[code]}: no mapped account-level detail was available for this period; management review is required.")
        else:
            diagnostics.append(f"Note {code} — {note_names[code]}: populated from {len(labels)} mapped Notes Line group(s). Verify classification and completeness before issue.")
    return diagnostics




def _populate_detailed_balance_notes(doc, current, prior, note_disclosures=None):
    """Populate balance-sheet note tables where TB mapping supports account detail."""
    specs = {
        "N13": (26, 3, 6, 3, 5, "Cash and cash equivalents"),
        "N14": (27, 3, 7, 3, 5, "Trade and other receivables"),
        "N15": (28, 2, 7, 3, 5, "Related-party balances"),
        "N16": (30, 2, 7, 3, 5, "Stated capital"),
        "N17": (36, 3, 6, 2, 4, "Trade and other payables"),
    }
    diagnostics = []
    saved_status = {str(x.get("note_code") or "").upper(): x for x in (note_disclosures or [])}
    for code, (table_idx, start, end, cur_col, prior_col, title) in specs.items():
        if _is_not_applicable_disclosure(saved_status.get(code)):
            continue
        if table_idx >= len(doc.tables):
            diagnostics.append(f"{code}: {title} table was not found in the Word template.")
            continue
        table = doc.tables[table_idx]
        cur_rows = list((current or {}).get(code, []) or [])
        prior_rows = list((prior or {}).get(code, []) or [])
        cur_map = {str(label).strip(): float(amount or 0) for label, amount in cur_rows if str(label).strip()}
        prior_map = {str(label).strip(): float(amount or 0) for label, amount in prior_rows if str(label).strip()}
        labels = sorted(set(cur_map) | set(prior_map), key=str.casefold)
        capacity = max(0, end - start)
        if len(labels) > capacity:
            diagnostics.append(f"{code}: {len(labels)} mapped lines exceed the {capacity}-row template space; remaining lines are not displayed. Expand the note table before issue.")
        for offset, label in enumerate(labels[:capacity]):
            row_idx = start + offset
            if row_idx >= len(table.rows):
                break
            row = table.rows[row_idx]
            _set_cell(row.cells[0], label)
            if cur_col < len(row.cells): _set_cell(row.cells[cur_col], _fmt(cur_map.get(label)))
            if prior_col < len(row.cells): _set_cell(row.cells[prior_col], _fmt(prior_map.get(label)))
        # Clear stale example text/amounts from remaining disclosure rows.
        for row_idx in range(start + min(len(labels), capacity), min(end, len(table.rows))):
            row = table.rows[row_idx]
            _set_cell(row.cells[0], "")
            if cur_col < len(row.cells): _set_cell(row.cells[cur_col], "")
            if prior_col < len(row.cells): _set_cell(row.cells[prior_col], "")
        if not labels:
            diagnostics.append(f"{code} — {title}: no mapped account-level detail was available; management input is required.")
        else:
            diagnostics.append(f"{code} — {title}: populated from {len(labels)} mapped Notes Line group(s). Confirm classifications and completeness.")
    return diagnostics


def _is_not_applicable_disclosure(item):
    """Recognise Not applicable consistently, regardless of stored casing."""
    return str((item or {}).get("status") or "").strip().casefold() == "not applicable"


def _remove_not_applicable_note_sections(doc, note_disclosures):
    """Remove complete note sections marked Not applicable from the Word output.

    The heading and all intervening paragraphs/tables are removed up to the next
    numbered note heading. The saved disclosure record itself is not modified.
    """
    from docx.text.paragraph import Paragraph

    note_specs = {
        "N01": (1, ("general information",)),
        "N02": (2, ("material accounting policy information", "accounting policies")),
        "N03": (3, ("critical accounting estimates and judgements", "critical accounting estimates and judgments")),
        "N04": (4, ("financial risk management",)),
        "N05": (5, ("revenue",)),
        "N06": (6, ("cost of service", "cost of sales")),
        "N07": (7, ("other income",)),
        "N08": (8, ("operating expenses",)),
        "N09": (9, ("taxation",)),
        "N10": (10, ("property and equipment",)),
        "N11": (11, ("subsidiary",)),
        "N12": (12, ("right of use assets and lease liability", "right of use assets")),
        "N13": (13, ("cash and cash equivalents",)),
        "N14": (14, ("trade and other receivables",)),
        "N15": (15, ("related parties",)),
        "N16": (16, ("stated capital",)),
        "N17": (17, ("trade and other payables",)),
        "N18": (18, ("dividend",)),
        "N19": (19, ("capital commitment and contingent liabilities", "capital commitments")),
        "N20": (20, ("events after the reporting period",)),
        "N21": (21, ("holding company and ultimate beneficial owner", "holding company")),
    }
    saved = {str(x.get("note_code") or "").upper(): x for x in (note_disclosures or [])}
    body = doc._element.body
    removed = []

    def heading_match(paragraph, number, aliases):
        match = re.match(r"^\s*(\d{1,2})\s*[.\t]\s*(.*)$", paragraph.text or "")
        if not match or int(match.group(1)) != number:
            return False
        title = _norm(match.group(2))
        return any(title.startswith(_norm(alias)) for alias in aliases)

    for code, (number, aliases) in note_specs.items():
        if not _is_not_applicable_disclosure(saved.get(code)):
            continue
        heading = next((p for p in doc.paragraphs if heading_match(p, number, aliases)), None)
        if heading is None or heading._p.getparent() is not body:
            continue
        children = list(body.iterchildren())
        start = children.index(heading._p)
        next_heading = None
        for later_code, (later_number, later_aliases) in note_specs.items():
            if later_number <= number:
                continue
            candidate = next((p for p in doc.paragraphs if heading_match(p, later_number, later_aliases)), None)
            if candidate is not None and candidate._p.getparent() is body:
                candidate_index = children.index(candidate._p)
                if candidate_index > start and (next_heading is None or candidate_index < next_heading):
                    next_heading = candidate_index
        end = next_heading if next_heading is not None else len(children)
        for element in children[start:end]:
            if element.getparent() is body:
                body.remove(element)
        removed.append(code)
    return [f"{code}: omitted from the Word financial statements because its disclosure status is Not applicable." for code in removed]


def _insert_saved_note_narratives(doc, note_disclosures):
    """Replace stale template note content with the saved narrative.

    Narrative-only disclosures replace the complete template note section so
    old examples/placeholders cannot appear beside current management wording.
    N02 is handled selectively: its saved paragraphs are removed from the
    static accounting-policy section where they duplicate existing policy text,
    while the other standard policy disclosures remain intact.
    """
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    note_specs = {
        "N01": (1, ("general information",)),
        "N02": (2, ("material accounting policy information", "accounting policies")),
        "N03": (3, ("critical accounting estimates and judgements", "critical accounting estimates and judgments")),
        "N04": (4, ("financial risk management",)),
        "N05": (5, ("revenue",)),
        "N06": (6, ("cost of service", "cost of sales")),
        "N07": (7, ("other income",)),
        "N08": (8, ("operating expenses",)),
        "N09": (9, ("taxation",)),
        "N10": (10, ("property and equipment",)),
        "N11": (11, ("subsidiary",)),
        "N12": (12, ("right of use assets and lease liability", "right of use assets")),
        "N13": (13, ("cash and cash equivalents",)),
        "N14": (14, ("trade and other receivables",)),
        "N15": (15, ("related parties",)),
        "N16": (16, ("stated capital",)),
        "N17": (17, ("trade and other payables",)),
        "N18": (18, ("dividend",)),
        "N19": (19, ("capital commitment and contingent liabilities", "capital commitments")),
        "N20": (20, ("events after the reporting period",)),
        "N21": (21, ("holding company and ultimate beneficial owner", "holding company")),
    }
    saved = {str(x.get("note_code") or "").upper(): x for x in (note_disclosures or [])}
    diagnostics = []

    def find_heading(number, aliases):
        for paragraph in doc.paragraphs:
            match = re.match(r"^\s*(\d{1,2})\s*[.\t]\s*(.*)$", paragraph.text or "")
            if not match or int(match.group(1)) != number:
                continue
            title = _norm(match.group(2))
            if any(title.startswith(_norm(alias)) for alias in aliases):
                return paragraph
        return None

    def section_elements(start_heading, next_heading):
        body = doc._element.body
        children = list(body.iterchildren())
        start_index = children.index(start_heading._p)
        end_index = children.index(next_heading._p) if next_heading is not None else len(children) - 1
        return body, children, start_index, end_index

    def narrative_lines(value, aliases, number):
        lines = str(value or "").replace("\r", "").split("\n")
        # Remove a leading note number/title repeated in the saved narrative.
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines:
            first = re.sub(r"^\s*\d{1,2}\s*[.\t]\s*", "", lines[0]).strip()
            first_norm = _norm(first)
            if any(first_norm == _norm(alias) for alias in aliases):
                lines.pop(0)
        return lines

    for code, (number, aliases) in note_specs.items():
        item = saved.get(code, {})
        if _is_not_applicable_disclosure(item):
            continue
        narrative = str(item.get("narrative") or "").strip()
        if not narrative:
            continue
        heading = find_heading(number, aliases)
        if heading is None:
            diagnostics.append(f"{code}: saved narrative was not applied because its numbered note heading was not found.")
            continue

        lines = narrative_lines(narrative, aliases, number)
        if code == "N02":
            # Avoid repeating exact policy paragraphs already present in the master template.
            saved_blocks = {_norm(x) for x in re.split(r"\n\s*\n", narrative) if len(_norm(x)) > 40}
            next_heading = find_heading(3, note_specs["N03"][1])
            body, children, start_idx, end_idx = section_elements(heading, next_heading)
            removed = 0
            for element in children[start_idx + 1:end_idx]:
                if not element.tag.endswith("}p"):
                    continue
                para = Paragraph(element, heading._parent)
                norm_text = _norm(para.text)
                if norm_text and any(norm_text == block or norm_text in block or block in norm_text for block in saved_blocks):
                    element.getparent().remove(element)
                    removed += 1
            # Insert the saved policy text directly after the section heading for a visible audit trail.
            insert_after = heading._p
            for line in lines:
                p_element = OxmlElement("w:p")
                insert_after.addnext(p_element)
                para = Paragraph(p_element, heading._parent)
                para.style = "Normal"
                if line.strip():
                    para.add_run(line.strip())
                insert_after = p_element
            diagnostics.append(f"N02: saved accounting-policy narrative applied; {removed} duplicate template paragraph(s) removed. Other standard accounting policies were retained.")
            continue

        # Replace the full note section, including stale example tables, placeholders
        # and old static narrative. The next numbered note heading is retained.
        next_number = number + 1
        next_spec = next((spec for spec in note_specs.values() if spec[0] == next_number), None)
        next_heading = find_heading(next_number, next_spec[1]) if next_spec else None
        body, children, start_idx, end_idx = section_elements(heading, next_heading)
        for element in children[start_idx + 1:end_idx]:
            if element.getparent() is body:
                body.remove(element)
        insert_after = heading._p
        inserted = 0
        for line in lines:
            p_element = OxmlElement("w:p")
            insert_after.addnext(p_element)
            para = Paragraph(p_element, heading._parent)
            para.style = "Normal"
            if line.strip():
                para.add_run(line.strip())
            insert_after = p_element
            inserted += 1
        diagnostics.append(f"{code}: replaced the old template note section with the saved narrative ({inserted} paragraph line(s)); stale template wording and tables removed.")

    # Remove any legacy automation markers completely (not merely hidden).
    for paragraph in list(doc.paragraphs):
        if "KULANA_NOTE_" in paragraph.text:
            cleaned = re.sub(r"\[?KULANA_NOTE_N\d{2}\]?", "", paragraph.text)
            _set_paragraph(paragraph, cleaned)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if "KULANA_NOTE_" in paragraph.text:
                        cleaned = re.sub(r"\[?KULANA_NOTE_N\d{2}\]?", "", paragraph.text)
                        _set_paragraph(paragraph, cleaned)
    return diagnostics


def _populate_disclosure_status(doc, note_disclosures):
    """Return clear status diagnostics for manually maintained narrative notes."""
    saved = {str(x.get("note_code") or "").upper(): x for x in (note_disclosures or [])}
    diagnostics = []
    for code, title in (("N01", "General information"), ("N02", "Accounting policies"),
                        ("N03", "Critical estimates and judgements"), ("N04", "Financial risk management"),
                        ("N18", "Dividend"), ("N19", "Commitments and contingencies"),
                        ("N20", "Events after reporting period"), ("N21", "Holding company and ownership")):
        item = saved.get(code, {})
        if _is_not_applicable_disclosure(item):
            continue
        narrative = str(item.get("narrative") or "").strip()
        status = str(item.get("status") or "Management input required")
        if narrative:
            diagnostics.append(f"{code} — {title}: saved disclosure narrative found (status: {status}); ensure it is reflected in the Word note and reviewed.")
        else:
            diagnostics.append(f"{code} — {title}: narrative disclosure is missing; management input is required.")
    # These require dedicated supporting schedules; a TB closing balance is not a movement analysis.
    for code, title in (("N09", "Taxation reconciliation and deferred tax"),
                        ("N10", "Property and equipment movement"),
                        ("N11", "Subsidiary disclosures"),
                        ("N12", "Right-of-use asset and lease liability movements"),
                        ("N15", "Related-party transactions")):
        if _is_not_applicable_disclosure(saved.get(code)):
            continue
        diagnostics.append(f"{code} — {title}: a full supporting schedule is not derivable from the trial balance alone; management confirmation/support is required.")
    return diagnostics




def generate_native_word_report(context):
    """Build the financial statements directly in Word from system data.

    All pages, headings, tables and notes are created programmatically. The
    generator does not load, populate, or depend on any DOCX template.
    """
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from datetime import date
    import calendar

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
    sec.top_margin = Inches(0.91)
    sec.bottom_margin = Inches(0.51)
    sec.left_margin = Inches(1.00)
    sec.right_margin = Inches(0.70)
    sec.header_distance = Inches(0.50)
    sec.footer_distance = Inches(0.33)
    sec.different_first_page_header_footer = True

    # Match the signed Kulana V9 financial statements: Arial,
    # black text, restrained bold headings, compact spacing and no shaded
    # grid on the primary financial statements.
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.0
    for style_name, size in (("Title", 18), ("Heading 1", 12), ("Heading 2", 10), ("Heading 3", 10)):
        style = doc.styles[style_name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(8 if style_name != "Title" else 0)
        style.paragraph_format.space_after = Pt(4)

    entity = str(context.get("entity_name") or "Company")
    year = int(context.get("year") or date.today().year)
    month = int(context.get("month") or 12)
    start_month = int(context.get("start_month") or 1)
    prior_year = year - 1
    current_start = date(year, start_month, 1)
    prior_start = date(prior_year, start_month, 1)
    current_end = date(year, month, calendar.monthrange(year, month)[1])
    prior_end = date(prior_year, month, calendar.monthrange(prior_year, month)[1])
    date_text = current_end.strftime("%d %B %Y")
    prior_date_text = prior_end.strftime("%d %B %Y")
    # Use concise month-based labels for the reporting period throughout the
    # report (e.g. "Jan 2026" or "Jan - Feb 2026"). Keep the exact closing
    # date separately for the Statement of Financial Position.
    start_month_label = current_start.strftime("%b")
    end_month_label = current_end.strftime("%b")
    period_months_label = (start_month_label if start_month == month
                           else f"{start_month_label} - {end_month_label}")
    period_display_text = f"{period_months_label} {year}"
    prior_period_display_text = f"{period_months_label} {prior_year}"
    period_word = "year" if start_month == 1 and month == 12 else "period"
    currency = str(context.get("currency") or "")

    def set_cell_border(cell, **kwargs):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        borders = tcPr.first_child_found_in("w:tcBorders")
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            tcPr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            if edge in kwargs:
                tag = "w:{}".format(edge)
                element = borders.find(qn(tag))
                if element is None:
                    element = OxmlElement(tag)
                    borders.append(element)
                for key in ["val", "sz", "space", "color"]:
                    if key in kwargs[edge]:
                        element.set(qn("w:" + key), str(kwargs[edge][key]))

    def remove_table_borders(table):
        for row in table.rows:
            for cell in row.cells:
                set_cell_border(cell, top={"val": "nil"}, bottom={"val": "nil"},
                                left={"val": "nil"}, right={"val": "nil"},
                                insideH={"val": "nil"}, insideV={"val": "nil"})

    def set_cell_margins(cell, *, top=60, start=0, bottom=60, end=0):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcMar = tcPr.first_child_found_in("w:tcMar")
        if tcMar is None:
            tcMar = OxmlElement("w:tcMar")
            tcPr.append(tcMar)
        for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
            node = tcMar.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                tcMar.append(node)
            node.set(qn("w:w"), str(value))
            node.set(qn("w:type"), "dxa")

    def set_cell_text(cell, value, *, bold=False, align=None, size=10, italic=False):
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        if align is not None:
            p.alignment = align
        r = p.add_run("" if value is None else str(value))
        r.font.name = "Arial"
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(0, 0, 0)
        r.bold = bold
        r.italic = italic

    def money(value):
        if value is None or value == "":
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(number) < 0.005:
            return "-"
        rounded = int(round(number))
        return f"({abs(rounded):,})" if rounded < 0 else f"{rounded:,}"

    def add_page_heading(title, caption=None):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(5)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(title)
        r.bold = True
        r.font.name = "Arial"
        r.font.size = Pt(12)
        if caption:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            r = p.add_run(caption)
            r.bold = True
            r.font.name = "Arial"
            r.font.size = Pt(10)
        # V9 heading treatment: plain black bold text, no coloured band or rule.
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(5)

    def add_text(value="", *, bold=False, italic=False, size=10, keep=False):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(5)
        p.paragraph_format.keep_together = True
        p.paragraph_format.keep_with_next = keep
        r = p.add_run(str(value or ""))
        r.font.name = "Arial"
        r.font.size = Pt(size)
        r.bold = bold
        r.italic = italic
        return p

    def add_note_paragraphs(value):
        # Convert saved rich-text HTML to readable Word paragraphs while
        # retaining paragraph breaks and bullet-list markers.
        plain = _narrative_to_plain_text(value)
        for block in re.split(r"\n\s*\n|\n", plain):
            block = block.strip()
            if block:
                add_text(block, size=10)

    def add_borderless_table(headers, rows, widths, *, header_size=10, body_size=10,
                             alignments=None, rule_rows=None, bold_rows=None,
                             bold_columns=None, double_rule_rows=None, single_accounting_rule_rows=None,
                             bold_cells=None, regular_columns=None):
        # Comparative financial-year columns need a visible gap so their
        # accounting underlines remain separate rather than joining into one
        # continuous rule. Insert a narrow, borderless spacer immediately
        # before the final comparative year column.
        headers = list(headers)
        rows = [list(row) for row in rows]
        widths = list(widths)
        alignments = list(alignments) if alignments else None
        if len(headers) >= 3:
            last_years = headers[-2:]
            year_tokens = []
            for heading in last_years:
                match = re.search(r"\b(19|20)\d{2}\b", str(heading or ""))
                year_tokens.append(match.group(0) if match else None)
            is_comparative_year_pair = all(year_tokens) and year_tokens[0] != year_tokens[1]
            if is_comparative_year_pair:
                insert_at = len(headers) - 1
                spacer_width = 0.08
                # Keep the table within its previous width by taking half
                # the spacer width from each comparative amount column.
                if len(widths) >= 2:
                    widths[-2] = max(0.1, widths[-2] - spacer_width / 2)
                    widths[-1] = max(0.1, widths[-1] - spacer_width / 2)
                headers.insert(insert_at, "")
                widths.insert(insert_at, spacer_width)
                for row in rows:
                    row.insert(insert_at, "")
                if alignments is not None:
                    alignments.insert(insert_at, WD_ALIGN_PARAGRAPH.LEFT)
        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        remove_table_borders(table)
        rule_rows = set(rule_rows or [])
        bold_rows = set(bold_rows or [])
        bold_columns = set(bold_columns or [])
        double_rule_rows = set(double_rule_rows or [])
        single_accounting_rule_rows = set(single_accounting_rule_rows or [])
        bold_cells = set(bold_cells or [])
        regular_columns = set(regular_columns or [])
        for i, header in enumerate(headers):
            align = (alignments[i] if alignments else
                     (WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.RIGHT))
            set_cell_text(table.rows[0].cells[i], header, bold=True, align=align, size=header_size)
            table.rows[0].cells[i].width = Inches(widths[i])
        for row_idx, row in enumerate(rows):
            cells = table.add_row().cells
            for i, value in enumerate(row[:len(headers)]):
                align = (alignments[i] if alignments else
                         (WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.RIGHT))
                set_cell_text(cells[i], value,
                              bold=((row_idx, i) in bold_cells or i in bold_columns or
                                    (row_idx in bold_rows and i not in regular_columns)),
                              align=align, size=body_size)
                cells[i].width = Inches(widths[i])
                # Give every financial statement and note line item breathing room.
                # The same top/bottom padding keeps labels and amounts on a common baseline.
                set_cell_margins(cells[i], top=75, bottom=75, start=0, end=55)
                for para in cells[i].paragraphs:
                    para.paragraph_format.space_before = Pt(0)
                    para.paragraph_format.space_after = Pt(2.5)
                    para.paragraph_format.line_spacing = 1.08
                    para.paragraph_format.keep_together = True
                if row_idx in rule_rows and i >= 2 and str(value or "").strip():
                    set_cell_border(cells[i], bottom={"val": "single", "sz": "5", "color": "000000"})
                if row_idx in double_rule_rows and i > 0 and str(value or "").strip():
                    # Double accounting rules are retained for tables that explicitly request them.
                    double_rule = {"val": "double", "sz": "6", "color": "000000"}
                    set_cell_border(cells[i], top=double_rule, bottom=double_rule)
                if row_idx in single_accounting_rule_rows and i > 0 and str(value or "").strip():
                    # Detailed note totals use a single accounting line above and below
                    # each comparative amount; the spacer column remains unruled.
                    single_rule = {"val": "single", "sz": "6", "color": "000000"}
                    set_cell_border(cells[i], top=single_rule, bottom=single_rule)
        doc.add_paragraph().paragraph_format.space_after = Pt(3)
        return table

    def note_ref(label):
        s = re.sub(r"[^a-z0-9]+", " ", str(label or "").casefold()).strip()
        rules = [
            (("cost of sales", "cost of service", "cost of operations"), "6"),
            (("revenue", "sales", "turnover"), "5"),
            (("other income",), "7"),
            (("operating expenses", "general and administrative", "administrative expenses"), "8"),
            (("income tax", "tax recoverable", "deferred tax"), "9"),
            (("finance cost", "finance costs", "interest expense"), "12"),
            (("property", "plant and equipment", "ppe", "fixed asset"), "10"),
            (("subsidiary", "investment in subsidiary"), "11"),
            (("right of use", "lease liability", "lease obligation"), "12"),
            (("cash and cash equivalent", "bank balance", "cash at bank"), "13"),
            (("receivable", "prepayment", "tax recoverable"), "14"),
            (("related party", "due from related", "due to related"), "15"),
            (("share capital", "stated capital"), "16"),
            (("payable", "accrued expense", "trade creditor"), "17"),
            (("dividend",), "18"),
        ]
        for terms, code in rules:
            if any(term in s for term in terms):
                return code
        return ""

    def add_financial_statement(title, caption, rows, *, kind="pl"):
        add_page_heading(title, caption)
        widths = [3.65, 0.48, 1.10, 1.10]
        is_full_year = start_month == 1 and month == 12
        if kind in ("pl", "cash"):
            # Activity statement columns use the concise reporting-period labels
            # consistently (e.g. Jan 2026 or Jan - Feb 2026), not exact date ranges.
            current_caption = period_display_text
            prior_caption = prior_period_display_text
        else:
            current_caption = f"As at\n{current_end.strftime('%d %B %Y')}"
            prior_caption = f"As at\n{prior_end.strftime('%d %B %Y')}"
        headers = ["", "Notes", f"{current_caption}\n{currency}", f"{prior_caption}\n{currency}"]
        table_rows, bold_rows, rule_rows = [], set(), set()
        pl_prior_values = context.get("pl_prior") or {}
        for row in rows:
            if isinstance(row, dict):
                label = row.get("label") or row.get("description") or ""
                cur = row.get("current")
                prev = row.get("prior")
                row_kind = row.get("kind", "line")
                note = row.get("note") or note_ref(label)
            else:
                vals = list(row) if isinstance(row, (tuple, list)) else [row]
                label = vals[0] if vals else ""
                cur = vals[1] if len(vals) > 1 else None
                if len(vals) >= 4:
                    prev = vals[2]
                    row_kind = vals[3]
                elif len(vals) == 3 and str(vals[2]).casefold() in {"line", "section", "subtotal", "total"}:
                    prior_aliases = {
                        "Cost of service": "Cost of sales",
                        "Gross profit": "Gross profit/(loss)",
                        "(Loss)/profit before tax": "Profit before tax",
                        "(Loss)/profit for the year/period": "Profit for the year",
                        "Total comprehensive income/(loss) for the year/period": "Total comprehensive income",
                    }
                    prior_key = prior_aliases.get(str(label), str(label))
                    prev = pl_prior_values.get(prior_key) if kind == "pl" else None
                    row_kind = str(vals[2]).casefold()
                else:
                    prev = vals[2] if len(vals) > 2 else None
                    row_kind = "line"
                note = "" if row_kind in ("section", "subtotal", "total") else note_ref(label)
            if row_kind == "section":
                section_label = str(label).strip()
                if kind == "bs" and section_label.casefold() == "non-current assets":
                    table_rows.append(("ASSETS", "", "", ""))
                    bold_rows.add(len(table_rows)-1)
                if kind == "bs" and section_label.casefold() == "non-current liabilities":
                    table_rows.append(("EQUITY AND LIABILITIES", "", "", ""))
                    bold_rows.add(len(table_rows)-1)
                table_rows.append((section_label.upper(), "", "", ""))
                bold_rows.add(len(table_rows)-1)
                continue
            table_rows.append((str(label).strip(), str(note), money(cur), money(prev)))
            idx = len(table_rows)-1
            if row_kind in ("subtotal", "total"):
                bold_rows.add(idx)
                rule_rows.add(idx)
        # The current-year amount column is always bold. The comparative prior-year
        # amount column is explicitly kept regular, including subtotal/total rows.
        # Comparative spacer insertion places the prior-year amount in column 4.
        add_borderless_table(headers, table_rows, widths, header_size=10,
                              body_size=10, rule_rows=rule_rows, bold_rows=bold_rows,
                              bold_columns={2}, regular_columns={4})

    # Header and footer on all pages except the cover. The page number is a
    # Word field, so it updates when the document is opened or repaginated.
    header = sec.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hr = header.add_run(entity)
    hr.bold = True
    hr.font.name = "Arial"
    hr.font.size = Pt(10)
    hp = sec.header.add_paragraph()
    hp.paragraph_format.space_before = Pt(0)
    hp.paragraph_format.space_after = Pt(0)
    hpr = hp.add_run(f"For {period_display_text}")
    hpr.font.name = "Arial"
    hpr.font.size = Pt(10)
    hpr.bold = True
    footer = sec.footer
    ft = footer.add_table(rows=1, cols=2, width=Inches(6.55))
    ft.autofit = False
    ft.columns[0].width = Inches(5.95)
    ft.columns[1].width = Inches(0.60)
    remove_table_borders(ft)
    footer_note_cell = ft.rows[0].cells[0]
    set_cell_text(footer_note_cell,
                  "The notes form an integral part of these financial statements",
                  size=9)
    # Keep the footer note on one continuous line in Word/PDF output.
    footer_note_tcpr = footer_note_cell._tc.get_or_add_tcPr()
    no_wrap = OxmlElement("w:noWrap")
    footer_note_tcpr.append(no_wrap)
    set_cell_margins(footer_note_cell, top=0, start=0, bottom=0, end=0)
    pnum_cell = ft.rows[0].cells[1]
    pnum_cell.text = ""
    pp = pnum_cell.paragraphs[0]
    pp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = pp.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r._r.addnext(fld)

    # Cover page: centered and deliberately sparse, as in the reference.
    for _ in range(7):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(25)
    r = p.add_run(entity.upper())
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(18)
    for line, size in (
        ("Management report and financial statements", 14),
        ("for the reporting period", 14),
        (period_display_text, 14),
    ):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(line)
        r.bold = True
        r.font.name = "Arial"
        r.font.size = Pt(size)
    doc.add_page_break()

    # Contents page: the V9 contents table sits directly beneath the running
    # company/report header, without repeating the reporting-date heading.
    contents = [
        ("Corporate information", "3"),
        ("Financial statements:", ""),
        ("-   Statement of profit or loss and other comprehensive income", "4"),
        ("-   Statement of financial position", "5"),
        ("-   Statement of changes in equity", "6"),
        ("-   Statement of cash flows", "7"),
        ("-   Notes to the financial statements", "8 onwards"),
    ]
    # Give the contents page more breathing room: a little space above the
    # table, taller rows, and clearer separation between statement groups.
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(8)
    spacer.paragraph_format.space_after = Pt(10)
    contents_table = add_borderless_table(
        ["Contents", "Pages"], contents, [5.7, 0.7],
        alignments=[WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT],
        body_size=10, bold_rows={1}
    )
    for row_idx, row in enumerate(contents_table.rows):
        for cell in row.cells:
            set_cell_margins(cell, top=100 if row_idx else 80, bottom=100 if row_idx else 80)
            for para in cell.paragraphs:
                para.paragraph_format.space_before = Pt(2)
                para.paragraph_format.space_after = Pt(8 if row_idx else 5)
                para.paragraph_format.line_spacing = 1.12
    doc.add_page_break()

    # Corporate information: label/value layout, not a shaded data grid.
    add_page_heading("Corporate Information", f"For {period_display_text}")
    profile = context.get("profile") or []
    profile_rows = []
    omitted_profile_fields = []
    for item in profile:
        if not isinstance(item, dict):
            continue
        if _is_not_applicable_profile_field(item):
            omitted_label = str(item.get("description") or item.get("Corporate information") or item.get("label") or item.get("input_code") or item.get("Code") or "Corporate information").strip()
            omitted_profile_fields.append(omitted_label)
            continue
        code = str(item.get("input_code") or item.get("Code") or item.get("code") or "").strip()
        label = str(item.get("description") or item.get("Corporate information") or item.get("label") or code).strip()
        value = str(item.get("narrative") or item.get("Information") or item.get("Commentary") or item.get("commentary") or item.get("value") or "").strip()
        if label and value:
            profile_rows.append((label, value))
    if profile_rows:
        # Reproduce the reference's fixed label/narrative columns.  The
        # narrative column starts at a fixed tab position, and all wrapped
        # lines stay under the narrative (not under the label).
        corporate_order = {
            "board of directors": 0, "directors": 0,
            "registered office": 1,
            "company secretary": 2,
            "auditor": 3, "external auditor": 3,
            "legal advisors": 4, "legal advisers": 4,
            "bankers": 5, "bank": 5,
        }
        profile_rows = sorted(
            enumerate(profile_rows),
            key=lambda pair: (corporate_order.get(_norm(pair[1][0].rstrip(":")), 99), pair[0])
        )
        profile_rows = [row for _, row in profile_rows]

        corporate_table = doc.add_table(rows=0, cols=2)
        corporate_table.alignment = WD_TABLE_ALIGNMENT.LEFT
        corporate_table.autofit = False
        corporate_table.allow_autofit = False
        table_width = 6.57  # A4 width less the report's 1.00in / 0.70in margins
        label_width = 2.35
        narrative_width = table_width - label_width
        tbl_pr = corporate_table._tbl.tblPr
        tbl_layout = tbl_pr.find(qn("w:tblLayout"))
        if tbl_layout is None:
            tbl_layout = OxmlElement("w:tblLayout")
            tbl_pr.append(tbl_layout)
        tbl_layout.set(qn("w:type"), "fixed")
        tbl_w = tbl_pr.find(qn("w:tblW"))
        if tbl_w is None:
            tbl_w = OxmlElement("w:tblW")
            tbl_pr.append(tbl_w)
        tbl_w.set(qn("w:w"), str(int(table_width * 1440)))
        tbl_w.set(qn("w:type"), "dxa")
        # Explicitly remove any inherited table indentation.
        tbl_ind = tbl_pr.find(qn("w:tblInd"))
        if tbl_ind is None:
            tbl_ind = OxmlElement("w:tblInd")
            tbl_pr.append(tbl_ind)
        tbl_ind.set(qn("w:w"), "0")
        tbl_ind.set(qn("w:type"), "dxa")
        grid_cols = corporate_table._tbl.tblGrid.gridCol_lst
        if len(grid_cols) >= 2:
            grid_cols[0].set(qn("w:w"), str(int(label_width * 1440)))
            grid_cols[1].set(qn("w:w"), str(int(narrative_width * 1440)))
        corporate_table.columns[0].width = Inches(label_width)
        corporate_table.columns[1].width = Inches(narrative_width)
        remove_table_borders(corporate_table)

        for label, value in profile_rows:
            cells = corporate_table.add_row().cells
            cells[0].width = Inches(label_width)
            cells[1].width = Inches(narrative_width)
            # Add the colon used in the reference report; do not duplicate it.
            display_label = label.strip().rstrip(":") + ":"
            set_cell_text(cells[0], display_label, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, size=10)
            set_cell_text(cells[1], _narrative_to_plain_text(value), align=WD_ALIGN_PARAGRAPH.LEFT, size=10)
            for cell in cells:
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                set_cell_margins(cell, top=45, bottom=125, start=0, end=80)
                for para in cell.paragraphs:
                    para.paragraph_format.left_indent = Inches(0)
                    para.paragraph_format.first_line_indent = Inches(0)
                    para.paragraph_format.space_before = Pt(0)
                    para.paragraph_format.space_after = Pt(0)
                    para.paragraph_format.line_spacing = 1.0
            # Keep each label with its corresponding narrative when the row
            # wraps across lines or approaches a page boundary.
            trPr = corporate_table.rows[-1]._tr.get_or_add_trPr()
            trPr.append(OxmlElement("w:cantSplit"))
    else:
        add_text("Corporate information has not been entered for this reporting period.")
    doc.add_page_break()

    # Profit or loss statement, with actual subtotals and note references.
    pl_rows = context.get("pl_statement_rows") or []
    if not pl_rows:
        cur, prev = context.get("pl_current") or {}, context.get("pl_prior") or {}
        pl_rows = [(k, v, prev.get(k), "line") for k, v in cur.items()]
    add_financial_statement(
        "Statement of profit or loss and other comprehensive income",
        f"For {period_display_text}",
        pl_rows, kind="pl"
    )
    doc.add_page_break()

    # Statement of financial position with the IFRS section/subtotal structure.
    bs_rows = context.get("bs_statement_rows") or []
    if not bs_rows:
        cur, prev = context.get("bs_notes_current") or {}, context.get("bs_notes_prior") or {}
        bs_rows = [(str(k[1]), v, prev.get(k), "note") for k, v in cur.items() if isinstance(k, tuple)]
    add_financial_statement("Statement of financial position", f"As at {date_text}", bs_rows, kind="bs")

    # Approval and signing block follows the statement of financial position,
    # using only signatories maintained in Corporate Information.
    signatory = next((v for k, v in profile_rows if "approval" in k.casefold() or "sign" in k.casefold()), "")
    if signatory:
        add_text("The financial statements were approved and signed by:", size=10)
        people = [x.strip() for x in re.split(r"\n+", signatory) if x.strip()]
        if people:
            signature_table = doc.add_table(rows=1, cols=min(2, len(people)))
            signature_table.alignment = WD_TABLE_ALIGNMENT.LEFT
            signature_table.autofit = False
            remove_table_borders(signature_table)
            for idx, person in enumerate(people[:2]):
                cell = signature_table.rows[0].cells[idx]
                cell.width = Inches(3.0)
                cell.text = ""
                para = cell.paragraphs[0]
                para.paragraph_format.space_before = Pt(18)
                para.paragraph_format.space_after = Pt(0)
                run = para.add_run("________________________")
                run.font.name = "Arial"
                run.font.size = Pt(10)
                para2 = cell.add_paragraph()
                para2.paragraph_format.space_after = Pt(0)
                run = para2.add_run(person)
                run.font.name = "Arial"
                run.font.size = Pt(10)
    doc.add_page_break()

    # Statement of changes in equity: named columns and movement rows, not
    # generic "Column 1" headings.
    add_page_heading("Statement of changes in equity", f"For {period_display_text}")
    eq_rows = context.get("equity_current_rows") or []
    prior_eq_rows = context.get("equity_prior_rows") or []

    def equity_table(rows, report_year, dividend=None, include_opening=True):
        components = {str(x[0]).casefold(): list(x[1:]) for x in rows if isinstance(x, (tuple, list)) and len(x) >= 7}
        share = components.get("share capital", [0]*6)
        retained = components.get("retained earnings", [0]*6)
        reserves = components.get("other reserves", [0]*6)
        net = components.get("net profit/(loss)", [0]*6)
        opening = [share[0], retained[0], reserves[0]]
        closing = [share[4], retained[4], reserves[4]]
        profit = float(net[1] or 0) if len(net) > 1 else 0.0
        oci = float(reserves[2] or 0) if len(reserves) > 2 else 0.0
        movements = [share[3], retained[3], reserves[3]]
        reserve_values = [reserves[0], reserves[2], reserves[3], reserves[4]]
        include_reserves = any(abs(float(x or 0)) > 0.005 for x in reserve_values)
        def total(vals):
            return sum(float(x or 0) for x in vals)
        output = []
        if include_opening:
            output.append((f"At {start_month} {date(report_year, start_month, 1).strftime('%B')} {report_year}", "", opening[0], opening[1], opening[2], total(opening)))
        if dividend is not None and abs(float(dividend or 0)) > 0.005:
            output.append(("Dividend paid", "18", 0.0, float(dividend), 0.0, float(dividend)))
        output.append((f"Total comprehensive income/(loss) for the {period_word}", "", 0.0, profit, oci, profit + oci))
        other_movement = [float(movements[i] or 0) for i in range(3)]
        if dividend is not None:
            other_movement[1] -= float(dividend or 0)
        if any(abs(x) > 0.005 for x in other_movement):
            output.append(("Other movements", "", *other_movement, total(other_movement)))
        output.append((f"At {date_text if report_year == year else prior_date_text}", "", closing[0], closing[1], closing[2], total(closing)))
        return output, include_reserves

    prior_eq_table, prior_has_reserves = equity_table(
        prior_eq_rows, prior_year, context.get("prior_dividend"), include_opening=True
    ) if prior_eq_rows else ([], False)
    current_eq_table, current_has_reserves = equity_table(
        eq_rows, year, context.get("current_dividend"), include_opening=True
    )
    combined_eq = prior_eq_table + current_eq_table
    include_reserves = prior_has_reserves or current_has_reserves
    if include_reserves:
        eq_headers = ["", "Notes", "Share capital\n" + currency, "Retained earnings\n" + currency,
                      "Other reserves\n" + currency, "Total\n" + currency]
        eq_body = [(label, note, money(sh), money(re), money(orv), money(tot))
                   for label, note, sh, re, orv, tot in combined_eq]
        eq_widths = [2.15, 0.45, 0.9, 1.05, 0.95, 0.75]
    else:
        eq_headers = ["", "Notes", "Share capital\n" + currency, "Retained earnings\n" + currency, "Total\n" + currency]
        eq_body = [(label, note, money(sh), money(re), money(tot))
                   for label, note, sh, re, _orv, tot in combined_eq]
        eq_widths = [2.45, 0.45, 1.0, 1.35, 1.0]
    # Prior-year equity movement rows stay regular. Every current-year figure
    # (all amount columns on the current-year rows) is bold, without changing
    # the prior-year figures or the existing closing-total rule.
    current_eq_start = len(prior_eq_table)
    equity_bold_cells = {
        (row_idx, col_idx)
        for row_idx in range(current_eq_start, len(eq_body))
        for col_idx in range(2, len(eq_headers))
    }
    add_borderless_table(eq_headers, eq_body, eq_widths,
                         header_size=10, body_size=10,
                         rule_rows={len(eq_body)-1},
                         bold_cells=equity_bold_cells)
    doc.add_page_break()

    # Cash flow statement: retain operating/investing/financing groupings.
    cash_rows = context.get("cash_current") or {}
    prior_cash = context.get("cash_prior") or {}
    cash_statement_rows = []
    for label, amount in cash_rows.items():
        cash_statement_rows.append((label, amount, prior_cash.get(label), "section" if str(label).isupper() and amount is None else
                                    ("total" if str(label).casefold().startswith(("net cash", "net increase", "closing cash")) else "line")))
    add_financial_statement("Statement of cash flows",
                            f"For {period_display_text}",
                            cash_statement_rows, kind="cash")
    doc.add_page_break()

    # Notes: ordered by note code, with saved narratives and structured account
    # detail. Not Applicable disclosures are omitted completely from issued output.
    add_page_heading("Notes to the financial statements", f"For {period_display_text}")
    note_titles = [
        ("N01", "General information"), ("N02", "Material accounting policy information"),
        ("N03", "Critical accounting estimates and judgements"), ("N04", "Financial risk management"),
        ("N05", "Revenue"), ("N06", "Cost of service"), ("N07", "Other income"),
        ("N08", "Operating expenses"), ("N09", "Taxation"), ("N10", "Property and equipment"),
        ("N11", "Investment in subsidiary"), ("N12", "Right-of-use assets and lease liability"),
        ("N13", "Cash and cash equivalents"), ("N14", "Trade and other receivables"),
        ("N15", "Related parties"), ("N16", "Stated capital"), ("N17", "Trade and other payables"),
        ("N18", "Dividend"), ("N19", "Capital commitments and contingent liabilities"),
        ("N20", "Events after the reporting period"), ("N21", "Holding company and ultimate beneficial owner"),
    ]
    saved = {str(x.get("note_code") or "").upper(): x for x in (context.get("note_disclosures") or []) if isinstance(x, dict)}
    standard_codes = {code for code, _title in note_titles}
    custom_note_codes = sorted(
        set(saved) - standard_codes,
        key=lambda code: tuple(int(x) for x in re.findall(r"\d+", str(code))) or (9999,)
    )
    note_title_map = dict(note_titles)
    for custom_code in custom_note_codes:
        note_title_map[custom_code] = str(saved[custom_code].get("note_title") or custom_code)
    # Sort all notes numerically by their hierarchy so N02.1 and N02.2 appear
    # immediately after N02, while N10 remains after N09.
    note_titles = sorted(
        note_title_map.items(),
        key=lambda item: tuple(int(x) for x in re.findall(r"\d+", str(item[0]))) or (9999,)
    )
    detail_cur = context.get("notes_detail_current") or {}
    detail_prev = context.get("notes_detail_prior") or {}
    note_detail_names = {
        "N05": "Revenue", "N06": "Cost of service", "N07": "Other income",
        "N08": "Operating expenses", "N09": "Taxation", "N10": "Property and equipment",
        "N11": "Investment in subsidiary", "N12": "Right-of-use assets and lease liability",
        "N13": "Cash and cash equivalents", "N14": "Trade and other receivables",
        "N15": "Related parties", "N16": "Stated capital", "N17": "Trade and other payables",
    }
    not_applicable = []
    included_notes = 0
    for code, default_title in note_titles:
        item = saved.get(code, {})
        if _is_not_applicable_disclosure(item):
            not_applicable.append(code)
            continue
        narrative = str(item.get("narrative") or item.get("content") or "").strip()
        title = str(item.get("note_title") or item.get("title") or default_title).strip()
        cur_lines = detail_cur.get(code, []) or []
        prev_lines = detail_prev.get(code, []) or []
        if not narrative and not cur_lines and not prev_lines:
            continue
        included_notes += 1
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_with_next = True
        # Preserve hierarchical note numbering: N02.1 is displayed as 2.1,
        # rather than being flattened to note 2.
        number_text = re.sub(r"^N", "", str(code), flags=re.I).lstrip("0")
        if number_text.startswith("."):
            number_text = "0" + number_text
        if not number_text:
            number_text = str(22 + custom_note_codes.index(code))
        rr = p.add_run(f"{number_text}.  {title}")
        rr.bold = True
        rr.font.name = "Arial"
        rr.font.size = Pt(10)
        if narrative:
            add_note_paragraphs(narrative)
        if cur_lines or prev_lines:
            cur_map = {str(k): float(v or 0) for k, v in cur_lines}
            prev_map = {str(k): float(v or 0) for k, v in prev_lines}
            labels = sorted(set(cur_map) | set(prev_map), key=str.casefold)
            note_rows = [(label, money(cur_map.get(label)), money(prev_map.get(label))) for label in labels]

            # Add a comparative total for every detailed note schedule. This
            # covers Revenue, Cost of service/sales and any other note with
            # account-level items and values. Totals use the displayed lines.
            if note_rows:
                current_total = sum(cur_map.values())
                prior_total = sum(prev_map.values())
                total_label = f"Total {title.casefold()}"
                note_rows.append((total_label, money(current_total), money(prior_total)))
                total_row_index = len(note_rows) - 1
                add_borderless_table(
                    ["", period_display_text, prior_period_display_text],
                    note_rows, [4.0, 1.25, 1.25],
                    header_size=10, body_size=10,
                    bold_rows={total_row_index},
                    bold_columns={1},  # Emphasise all current-period note figures.
                    single_accounting_rule_rows={total_row_index},
                )
            else:
                add_borderless_table(
                    ["", period_display_text, prior_period_display_text],
                    note_rows, [4.0, 1.25, 1.25],
                    header_size=10, body_size=10,
                    bold_columns={1},
                )

    if included_notes == 0:
        add_text("No applicable note narratives or mapped supporting note details were available for this reporting period.")
    # Enforce Arial consistently, including runs inside tables, headers and footers.
    # Setting both the python-docx font and OOXML font slots avoids Word falling
    # back to a theme font for non-ASCII or complex-script text.
    for style in doc.styles:
        try:
            style.font.name = "Arial"
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.rFonts
            if rfonts is None:
                rfonts = OxmlElement("w:rFonts")
                rpr.insert(0, rfonts)
            for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
                rfonts.set(qn(f"w:{slot}"), "Arial")
        except Exception:
            pass

    def _apply_arial_to_paragraph(paragraph):
        for run in paragraph.runs:
            run.font.name = "Arial"
            rpr = run._element.get_or_add_rPr()
            rfonts = rpr.rFonts
            if rfonts is None:
                rfonts = OxmlElement("w:rFonts")
                rpr.insert(0, rfonts)
            for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
                rfonts.set(qn(f"w:{slot}"), "Arial")

    for paragraph in doc.paragraphs:
        _apply_arial_to_paragraph(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _apply_arial_to_paragraph(paragraph)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            for paragraph in part.paragraphs:
                _apply_arial_to_paragraph(paragraph)
            for table in part.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            _apply_arial_to_paragraph(paragraph)

    output = io.BytesIO()
    doc.save(output)

    diagnostics = []
    if not profile_rows:
        diagnostics.append("Corporate Information is blank. Complete and save the company profile before issuing the report.")
    if omitted_profile_fields:
        diagnostics.append(
            "Corporate information marked Not applicable was excluded: "
            + ", ".join(omitted_profile_fields) + "."
        )
    if not pl_rows:
        diagnostics.append("No Profit or Loss rows were supplied for this reporting period.")
    if not bs_rows:
        diagnostics.append("No mapped Statement of Financial Position rows were supplied; review IFRS and Notes Line mappings.")
    if not cash_rows:
        diagnostics.append("No cash flow rows were supplied; review cash flow classifications and supporting inputs.")
    for code, title in note_titles:
        if code in not_applicable:
            continue
        item = saved.get(code, {})
        if not str(item.get("narrative") or item.get("content") or "").strip() and code in {"N01", "N02", "N03", "N04", "N18", "N19", "N20", "N21"}:
            diagnostics.append(f"{code} — {title}: no saved narrative was found; management input is required.")
    if not_applicable:
        diagnostics.append(f"{len(not_applicable)} disclosure(s) marked Not Applicable were excluded from the generated Word report.")
    diagnostics.append("The report was generated directly by the system in Python. No Word template or raw supplementary-input audit data was used.")
    return output.getvalue(), diagnostics

def populate_word_template(template_path, context):
    """Return (docx_bytes, diagnostics) for an ordinary Word template."""
    if isinstance(template_path, (bytes, bytearray)):
        doc = Document(io.BytesIO(template_path))
    elif hasattr(template_path, "read"):
        doc = Document(template_path)
    else:
        doc = Document(str(Path(template_path)))
    entity_name = str(context.get("entity_name") or "")
    year = int(context.get("year"))
    month = int(context.get("month", 12))
    comparative_year = year - 1
    currency = str(context.get("currency") or "")

    _populate_cover_and_dates(doc, entity_name, year, month)
    _populate_year_headers(doc, year, comparative_year, currency, month)

    diagnostics = []
    diagnostics.extend(_populate_corporate_information(doc, context.get("profile", [])))
    diagnostics.extend(_populate_pl(doc, context.get("pl_current", {}), context.get("pl_prior", {})) or [])
    diagnostics.extend(_populate_bs(
        doc, context.get("bs_current", {}), context.get("bs_prior", {}),
        context.get("bs_totals_current", {}), context.get("bs_totals_prior", {}),
        context.get("bs_notes_current", {}), context.get("bs_notes_prior", {}),
    ) or [])
    diagnostics.extend(_populate_cashflow(doc, context.get("cash_current", {}), context.get("cash_prior", {})) or [])
    diagnostics.extend(_populate_soce(
        doc, context.get("equity_current_rows", []), context.get("equity_prior_rows", []),
        context.get("current_dividend"), context.get("prior_dividend"),
        context.get("current_comprehensive"), context.get("prior_comprehensive"),
    ))

    diagnostics.extend(_populate_detailed_pl_notes(
        doc, context.get("notes_detail_current", {}), context.get("notes_detail_prior", {}),
        context.get("note_disclosures", [])
    ))
    diagnostics.extend(_populate_detailed_balance_notes(
        doc, context.get("notes_detail_current", {}), context.get("notes_detail_prior", {}),
        context.get("note_disclosures", [])
    ))
    diagnostics.extend(_remove_not_applicable_note_sections(doc, context.get("note_disclosures", [])))
    diagnostics.extend(_insert_saved_note_narratives(doc, context.get("note_disclosures", [])))
    diagnostics.extend(_populate_disclosure_status(doc, context.get("note_disclosures", [])))
    saved_note_status = {str(x.get("note_code") or "").upper(): x for x in (context.get("note_disclosures", []) or [])}
    outstanding_schedule_notes = [
        label for code, label in (("N09", "tax"), ("N10", "fixed-asset"),
                                  ("N11", "subsidiary"), ("N12", "lease"),
                                  ("N15", "related-party transaction"))
        if not _is_not_applicable_disclosure(saved_note_status.get(code))
    ]
    if outstanding_schedule_notes:
        diagnostics.append(
            "Important: The following disclosures still require their dedicated supporting schedules: "
            + ", ".join(outstanding_schedule_notes)
            + ". No unsupported movements or sensitivities have been estimated."
        )
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue(), diagnostics
