"""IFRS financial report presentation helpers for Kulana.

Balances are supplied by the application grouped by (IFRS Line, Notes Line).
This module arranges and totals the supplied values; it does not access the DB.
"""
from __future__ import annotations


def _section(ifrs_line: str) -> str:
    s = str(ifrs_line or "").casefold()
    if any(k in s for k in ("equity", "capital", "retained earning", "share", "reserves", "net profit", "net loss", "profit/(loss)")):
        return "Equity"
    if any(k in s for k in ("liabilit", "payable", "borrow", "loan", "lease obligation", "deferred income", "contract liabilit", "provision", "tax payable")):
        return "Liabilities"
    return "Assets"


def _asset_class(ifrs_line: str) -> str:
    s = str(ifrs_line or "").casefold().replace("–", "-")
    noncurrent = ("property", "plant", "equipment", "ppe", "intangible", "goodwill", "right-of-use", "right of use", "investment property", "non-current", "non current", "deferred tax asset", "long-term investment", "long term investment")
    return "Non-current assets" if any(k in s for k in noncurrent) else "Current assets"


def _liability_class(ifrs_line: str) -> str:
    s = str(ifrs_line or "").casefold().replace("–", "-")
    return "Non-current liabilities" if any(k in s for k in ("non-current", "non current", "long-term", "long term", "deferred tax liability")) else "Current liabilities"


def _is_section_label(line: str) -> bool:
    s = " ".join(str(line or "").casefold().replace("–", "-").split())
    return s in {"assets", "current assets", "non-current assets", "non current assets", "liabilities", "current liabilities", "non-current liabilities", "non current liabilities", "equity"}


def build_balance_sheet_rows(current: dict, prior: dict) -> list[tuple]:
    """Return (label, current, prior, kind); figures appear on Notes Line subrows.

    IFRS Line labels are authoritative classifications from the COA. Some
    installations use broad labels such as "Non-current assets", "Current
    assets", "Current liabilities" and "Equity" as IFRS Lines. These must NOT
    be discarded as section headings: their Notes Line balances are the
    account-level detail and must carry the amounts.
    """
    current, prior = current or {}, prior or {}
    cur_totals, prev_totals = {}, {}
    for (line, _note), value in current.items():
        cur_totals[str(line)] = cur_totals.get(str(line), 0.0) + float(value or 0.0)
    for (line, _note), value in prior.items():
        prev_totals[str(line)] = prev_totals.get(str(line), 0.0) + float(value or 0.0)

    # Keep every mapped IFRS line, including broad section labels. Their
    # amounts are displayed on the associated Notes Line beneath the heading.
    labels = list(dict.fromkeys(list(cur_totals) + list(prev_totals)))
    groups = {k: [] for k in (
        "Non-current assets", "Current assets",
        "Non-current liabilities", "Current liabilities", "Equity"
    )}
    for line in labels:
        section = _section(line)
        if section == "Assets":
            groups[_asset_class(line)].append(line)
        elif section == "Liabilities":
            groups[_liability_class(line)].append(line)
        else:
            groups["Equity"].append(line)

    def line_sort(line):
        s = str(line).casefold()
        ppe_first = 0 if any(k in s for k in (
            "property, plant", "property plant", "plant and equipment",
            "property and equipment", "ppe"
        )) else 1
        # Broad classification labels should precede detail lines within
        # their respective group, while PPE remains first among non-current.
        broad = 0 if _is_section_label(line) else 1
        return (ppe_first, broad, s)

    output = []
    all_keys = set(current) | set(prior)

    def add_group(title, lines, total_title):
        output.append((title, 0.0, 0.0, "section"))
        for line in sorted(lines, key=line_sort):
            notes = sorted(
                {str(n).strip() or "Notes line not assigned"
                 for (ln, n) in all_keys if str(ln) == line},
                key=str.casefold
            )
            # If an IFRS line exists but no notes were present in either
            # period, still provide a visible detail row.
            if not notes:
                notes = ["Notes line not assigned"]
            for note in notes:
                output.append((
                    f"    {note}",
                    float(current.get((line, note), 0.0) or 0.0),
                    float(prior.get((line, note), 0.0) or 0.0),
                    "note"
                ))
        output.append((
            total_title,
            sum(cur_totals.get(x, 0.0) for x in lines),
            sum(prev_totals.get(x, 0.0) for x in lines),
            "subtotal"
        ))

    add_group("Non-current assets", groups["Non-current assets"], "Total Non-current Assets")
    add_group("Current assets", groups["Current assets"], "Total Current Assets")
    total_assets_cur = sum(cur_totals.get(x, 0.0) for x in groups["Non-current assets"] + groups["Current assets"])
    total_assets_prev = sum(prev_totals.get(x, 0.0) for x in groups["Non-current assets"] + groups["Current assets"])
    output.append(("Total Assets", total_assets_cur, total_assets_prev, "total"))

    add_group("Non-current liabilities", groups["Non-current liabilities"], "Total Non-current Liabilities")
    add_group("Current liabilities", groups["Current liabilities"], "Total Current Liabilities")
    total_liab_cur = sum(cur_totals.get(x, 0.0) for x in groups["Non-current liabilities"] + groups["Current liabilities"])
    total_liab_prev = sum(prev_totals.get(x, 0.0) for x in groups["Non-current liabilities"] + groups["Current liabilities"])
    output.append(("Total Liabilities", total_liab_cur, total_liab_prev, "subtotal"))

    add_group("Equity", groups["Equity"], "Total Equity")
    total_equity_cur = sum(cur_totals.get(x, 0.0) for x in groups["Equity"])
    total_equity_prev = sum(prev_totals.get(x, 0.0) for x in groups["Equity"])
    output.append(("Total Equity and Liabilities", total_equity_cur + total_liab_cur, total_equity_prev + total_liab_prev, "total"))
    return output
