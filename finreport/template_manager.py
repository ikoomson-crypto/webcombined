"""Company-specific DOCX/XLSX financial statement templates.

Templates and approved placeholder mappings are stored in the reporting database,
so they survive application restarts and Render instance replacement.
"""
from __future__ import annotations
import io, json, uuid, re
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import database as DB


def _ph():
    return "%s" if DB.is_postgres() else "?"


def init_schema():
    blob_type = "BYTEA" if DB.is_postgres() else "BLOB"
    sql = f"""CREATE TABLE IF NOT EXISTS fr_report_templates (
        template_id TEXT PRIMARY KEY, entity_code TEXT NOT NULL, template_name TEXT NOT NULL,
        original_filename TEXT NOT NULL, file_type TEXT NOT NULL, file_data {blob_type} NOT NULL,
        mapping_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )"""
    with DB.connection() as (conn, _):
        conn.cursor().execute(sql)


def list_templates(entity_code):
    p = _ph()
    return DB.rows(f"SELECT template_id,template_name,original_filename,file_type,mapping_json,created_at,updated_at FROM fr_report_templates WHERE entity_code={p} ORDER BY updated_at DESC", (entity_code,))


def get_template(template_id, entity_code):
    p = _ph()
    rows = DB.rows(f"SELECT * FROM fr_report_templates WHERE template_id={p} AND entity_code={p}", (template_id, entity_code))
    return rows[0] if rows else None


def delete_template(template_id, entity_code):
    """Delete one template only for the selected entity."""
    p = _ph()
    with DB.connection() as (conn, _):
        conn.cursor().execute(
            f"DELETE FROM fr_report_templates WHERE template_id={p} AND entity_code={p}",
            (template_id, entity_code),
        )


def save_template(entity_code, name, filename, payload):
    p = _ph(); now = datetime.now(timezone.utc).isoformat()
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext not in ('docx', 'xlsx'):
        raise ValueError('Only Word (.docx) and Excel (.xlsx) templates are supported.')
    with DB.connection() as (conn, _):
        conn.cursor().execute(
            "INSERT INTO fr_report_templates (template_id,entity_code,template_name,original_filename,file_type,file_data,mapping_json,created_at,updated_at) VALUES (" + ','.join([p]*9) + ")",
            (str(uuid.uuid4()), entity_code, name.strip(), filename, ext, payload, '[]', now, now)
        )


def _placeholder_tokens(text):
    """Return normalized placeholder tokens in the order they occur in text."""
    return [
        match.strip().upper().replace(" ", "_")
        for match in re.findall(r"\{\{\s*([A-Za-z0-9_. -]+?)\s*\}\}", text or "")
        if match.strip()
    ]


def _clean_word_context(text):
    """Keep the Word row/paragraph wording while making placeholders readable."""
    text = re.sub(r"\{\{\s*([A-Za-z0-9_. -]+?)\s*\}\}", r"[\1]", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _docx_placeholder_layout(payload):
    """Read placeholders in actual DOCX body order, retaining paragraph/table context."""
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    doc = Document(io.BytesIO(payload))
    occurrences = []
    sequence = 0
    table_number = 0
    body_paragraph_number = 0

    def add_paragraph(paragraph, location, context_prefix=""):
        nonlocal sequence
        raw = "".join(run.text for run in paragraph.runs)
        tokens = _placeholder_tokens(raw)
        if not tokens:
            return
        context = _clean_word_context(raw)
        if context_prefix:
            context = (context_prefix + " | " + context).strip(" |")
        for token in tokens:
            sequence += 1
            occurrences.append({
                "sequence": sequence,
                "location": location,
                "context": context,
                "placeholder": token,
            })

    def walk_table(table, location):
        nonlocal table_number
        for row_index, row in enumerate(table.rows, start=1):
            # Include the complete row labels to make numeric cells identifiable
            # when the workbook is opened independently of the Word document.
            cell_texts = []
            for cell in row.cells:
                cell_texts.append(_clean_word_context(" ".join(p.text for p in cell.paragraphs)))
            row_context = " | ".join(x for x in cell_texts if x)
            row_location = f"{location} > Row {row_index}"
            for cell_index, cell in enumerate(row.cells, start=1):
                cell_location = f"{row_location} > Cell {cell_index}"
                for paragraph_index, paragraph in enumerate(cell.paragraphs, start=1):
                    add_paragraph(
                        paragraph,
                        f"{cell_location} > Paragraph {paragraph_index}",
                        row_context,
                    )
                for nested_index, nested in enumerate(cell.tables, start=1):
                    walk_table(nested, f"{cell_location} > Nested Table {nested_index}")

    # Iterate the underlying Word XML so paragraphs and tables remain interleaved
    # in the same order in which they appear in the document.
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            body_paragraph_number += 1
            add_paragraph(Paragraph(child, doc), f"Document > Paragraph {body_paragraph_number}")
        elif child.tag.endswith("}tbl"):
            table_number += 1
            walk_table(Table(child, doc), f"Document > Table {table_number}")

    # Headers and footers are appended after the main document, in section order.
    for section_index, section in enumerate(doc.sections, start=1):
        for part_name, part in (("Header", section.header), ("Footer", section.footer)):
            for paragraph_index, paragraph in enumerate(part.paragraphs, start=1):
                add_paragraph(
                    paragraph,
                    f"Section {section_index} > {part_name} > Paragraph {paragraph_index}",
                )
            for table_index, table in enumerate(part.tables, start=1):
                walk_table(table, f"Section {section_index} > {part_name} > Table {table_index}")

    return occurrences


def scan_placeholders(template):
    """Scan template placeholders, preserving their first-occurrence document order."""
    payload = bytes(template["file_data"])
    if template["file_type"] == "docx":
        occurrences = _docx_placeholder_layout(payload)
        ordered = []
        seen = set()
        for item in occurrences:
            token = item["placeholder"]
            if token not in seen:
                seen.add(token)
                ordered.append(token)
        return ordered

    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(payload), data_only=False)
    ordered, seen = [], set()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    for token in _placeholder_tokens(cell.value):
                        if token not in seen:
                            seen.add(token)
                            ordered.append(token)
    return ordered


def save_mapping(template_id, entity_code, records):
    """Persist and verify the complete mapping set for one entity/template."""
    p = _ph(); now = datetime.now(timezone.utc).isoformat()
    clean_by_token = {}
    for row in records:
        token = str(row.get("Placeholder") or row.get("placeholder") or "").strip()
        token = token.replace("{{", "").replace("}}", "").strip().upper().replace(" ", "_")
        source = str(row.get("Source") or row.get("source") or row.get("Source Key") or "").strip()
        if token and source:
            clean_by_token[token] = {"placeholder": token, "source": source}
    clean = list(clean_by_token.values())
    payload = json.dumps(clean, ensure_ascii=False)
    with DB.connection() as (conn, _):
        cur = conn.cursor()
        cur.execute(
            f"UPDATE fr_report_templates SET mapping_json={p}, updated_at={p} WHERE template_id={p} AND entity_code={p}",
            (payload, now, template_id, entity_code),
        )
        if getattr(cur, "rowcount", 1) == 0:
            raise ValueError("The selected template was not found for this reporting entity. No mappings were saved.")
    # Read back from the database so a failed/incorrect write is never reported as saved.
    saved = get_template(template_id, entity_code)
    persisted = json.loads((saved or {}).get("mapping_json") or "[]")
    if persisted != clean:
        raise RuntimeError("Mapping save could not be verified. Please try again.")
    return len(clean)


def mapping_workbook(template, source_values):
    """Export placeholders in Word-document sequence without location/context columns."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Placeholder Mappings"
    ws.append(["Template Placeholder", "Reporting Source", "Source Key"])

    payload = bytes(template["file_data"])
    if template["file_type"] == "docx":
        occurrences = _docx_placeholder_layout(payload)
    else:
        occurrences = []
        for index, token in enumerate(scan_placeholders(template), start=1):
            occurrences.append({
                "sequence": index,
                "location": "Excel Workbook",
                "context": "",
                "placeholder": token,
            })

    # One editable row per unique placeholder, ordered by first appearance in Word.
    first_occurrence = {}
    for item in occurrences:
        first_occurrence.setdefault(item["placeholder"], item)
    detected = list(first_occurrence.keys())
    saved = json.loads(template.get("mapping_json") or "[]")
    saved_map = {str(x.get("placeholder", "")).upper(): x.get("source", "") for x in saved}

    for index, token in enumerate(detected, start=1):
        item = first_occurrence[token]
        key = saved_map.get(token, "")
        ws.append([
            "{{" + token + "}}",
            _source_display(key) if key else "",
            key,
        ])

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    for col, width in {"A": 46, "B": 52, "C": 72}.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    src = wb.create_sheet("Reporting Sources")
    src.append(["Reporting Source", "Source Key", "Illustrative Value"])
    for key, value in sorted((source_values or {}).items(), key=lambda x: _source_display(x[0]).casefold()):
        src.append([_source_display(key), key, "" if value is None else str(value)])
    src.freeze_panes = "A2"
    src.auto_filter.ref = src.dimensions
    src.sheet_view.showGridLines = False
    for cell in src[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    src.row_dimensions[1].height = 30
    for col, width in {"A": 52, "B": 72, "C": 58}.items():
        src.column_dimensions[col].width = width
    for row in src.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def import_mapping_workbook(upload, template, entity_code, source_values):
    """Validate and import mappings from the exported Excel workbook."""
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(upload.getvalue()), data_only=True)
    if "Placeholder Mappings" not in wb.sheetnames:
        raise ValueError("The workbook must contain a 'Placeholder Mappings' sheet. Export the current mappings workbook and edit that file.")
    ws = wb["Placeholder Mappings"]
    headers = {str(c.value or "").strip().casefold(): c.column for c in ws[1]}
    token_col = headers.get("template placeholder") or headers.get("placeholder")
    source_col = headers.get("source key") or headers.get("reporting source") or headers.get("source")
    if not token_col or not source_col:
        raise ValueError("The Placeholder Mappings sheet needs 'Template Placeholder' and 'Source Key' columns.")
    valid_tokens = set(scan_placeholders(template))
    valid_sources = set((source_values or {}).keys())
    records, errors = [], []
    for row_num in range(2, ws.max_row + 1):
        raw_token = ws.cell(row_num, token_col).value
        raw_source = ws.cell(row_num, source_col).value
        if raw_token is None and raw_source is None:
            continue
        token = str(raw_token or "").replace("{{", "").replace("}}", "").strip().upper().replace(" ", "_")
        source = str(raw_source or "").strip()
        if not token and not source:
            continue
        if token not in valid_tokens:
            errors.append(f"Row {row_num}: placeholder '{token}' is not in the selected template.")
        elif source and source not in valid_sources:
            errors.append(f"Row {row_num}: source key '{source}' is not available for this entity/reporting setup.")
        elif token and source:
            records.append({"Placeholder": token, "Source": source})
    if errors:
        raise ValueError("Import cancelled. " + " ".join(errors[:10]))
    count = save_mapping(template["template_id"], entity_code, records)
    return count


def _replace_docx(payload, replacements):
    from docx import Document
    doc = Document(io.BytesIO(payload))
    def replace_paragraph(paragraph):
        # Handle tokens split across multiple Word formatting runs.
        runs = paragraph.runs
        if not runs:
            return
        original = "".join(run.text for run in runs)
        updated = original
        for token, value in replacements.items():
            updated = updated.replace("{{" + token + "}}", str(value))
        if updated != original:
            runs[0].text = updated
            for run in runs[1:]:
                run.text = ""
    def walk_table(table):
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs: replace_paragraph(paragraph)
                for nested in cell.tables: walk_table(nested)
    for p in doc.paragraphs: replace_paragraph(p)
    for table in doc.tables: walk_table(table)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for p in part.paragraphs: replace_paragraph(p)
            for table in part.tables: walk_table(table)
    out = io.BytesIO(); doc.save(out); return out.getvalue()


def _replace_xlsx(payload, replacements):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(payload))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    value = cell.value
                    for token, replacement in replacements.items():
                        value = value.replace('{{' + token + '}}', replacement)
                    if value != cell.value: cell.value = value
    out = io.BytesIO(); wb.save(out); return out.getvalue()


def populate(template, source_values):
    mappings = json.loads(template.get('mapping_json') or '[]')
    replacements = {}
    missing = []
    for item in mappings:
        token = item['placeholder']; source = item['source']
        if source not in source_values or source_values[source] is None:
            missing.append((token, source)); continue
        value = source_values[source]
        if isinstance(value, (int, float)):
            value = f"{value:,.2f}"
        replacements[token] = str(value)
    if template['file_type'] == 'docx':
        result = _replace_docx(bytes(template['file_data']), replacements)
        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ext = 'docx'
    else:
        result = _replace_xlsx(bytes(template['file_data']), replacements)
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ext = 'xlsx'
    return result, mime, ext, missing



_SOURCE_CATEGORY_ORDER = [
    "Statement of Cash Flow",
    "Balance Sheet",
    "Profit and Loss",
    "Equity",
    "Corporate Information",
    "Changes in Equity",
]


def _source_category(source):
    """Return the report category for IFRS lines, Notes Lines, totals, or corporate sources."""
    parts = str(source or "").split("|")
    source_type = parts[0].strip().upper() if parts else ""
    if source_type in {"CORPORATE", "CORPORATE INFORMATION"}:
        return "Corporate Information"
    if source_type not in {"IFRS LINE", "NOTES LINE", "REPORT TOTAL"}:
        return ""
    statement = parts[1].strip().upper() if len(parts) > 1 else ""
    if statement in {"CF", "CASH FLOW", "CASH_FLOW"}:
        return "Statement of Cash Flow"
    if statement in {"BS", "BALANCE SHEET"}:
        return "Balance Sheet"
    if statement in {"PL", "P&L", "PROFIT AND LOSS", "PROFIT & LOSS"}:
        return "Profit and Loss"
    if statement in {"EQUITY", "EQ"}:
        return "Equity"
    if statement in {"SOCE", "CHANGES IN EQUITY", "STATEMENT OF CHANGES IN EQUITY"}:
        return "Changes in Equity"
    return ""


def _source_display(source):
    parts = str(source).split("|")
    source_type = parts[0].strip().upper() if parts else ""
    if len(parts) >= 4 and source_type == "IFRS LINE":
        return f"{parts[3]} | {parts[2]} (IFRS Line)"
    if len(parts) >= 4 and source_type == "NOTES LINE":
        return f"{parts[3]} | {parts[2]} (Notes Line)"
    if len(parts) >= 4 and source_type == "REPORT TOTAL":
        return f"{parts[3]} | {parts[2]} (Report Total)"
    if len(parts) >= 2 and source_type in {"CORPORATE", "CORPORATE INFORMATION"}:
        label = parts[1].replace("_", " ").strip().title()
        return f"Corporate Information | {label}"
    return str(source)


def render_template_manager(entity, source_values, source_values_by_period=None):
    st.subheader("Financial Statement Template Manager")
    st.caption(
        "Upload and manage templates here. Placeholder mappings are stored per entity/template "
        "and are reused across all reporting months and years. Choose the reporting period only when generating a populated copy."
    )

    tab_upload, tab_map, tab_generate = st.tabs([
        "Upload / Delete templates",
        "Map template placeholders",
        "Generate populated template",
    ])

    templates = list_templates(entity["entity_code"])

    with tab_upload:
        st.markdown("#### Upload a new template")
        st.caption("Supported formats: Word (.docx) and Excel (.xlsx). Uploading a new file creates a separate saved template.")
        upload = st.file_uploader(
            "Choose a Word or Excel template",
            type=["docx", "xlsx"],
            key=f"template_upload_{entity['entity_code']}",
        )
        default_name = upload.name.rsplit(".", 1)[0] if upload else ""
        name = st.text_input(
            "Template name",
            value=default_name,
            key=f"template_name_{entity['entity_code']}",
        )
        if st.button(
            "Upload and save new template",
            type="primary",
            disabled=(upload is None or not name.strip()),
            key=f"save_template_{entity['entity_code']}",
        ):
            try:
                save_template(entity["entity_code"], name, upload.name, upload.getvalue())
                st.success("New template uploaded and saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not upload template: {type(exc).__name__}: {exc}")

        st.divider()
        st.markdown("#### Existing templates")
        templates = list_templates(entity["entity_code"])
        if not templates:
            st.info("No templates have been uploaded for this entity.")
        else:
            for item in templates:
                c1, c2, c3 = st.columns([5, 2, 2])
                c1.write(f"**{item['template_name']}**")
                c1.caption(f"{item['original_filename']} · {item['file_type'].upper()}")
                c2.caption(f"Updated: {str(item.get('updated_at',''))[:10]}")
                confirm_key = f"confirm_delete_template_{item['template_id']}"
                if c3.button("Delete", key=f"delete_template_{item['template_id']}"):
                    st.session_state[confirm_key] = True
                if st.session_state.get(confirm_key):
                    st.warning(f"Delete '{item['template_name']}'? This removes only this saved template and its mappings.")
                    d1, d2 = st.columns(2)
                    if d1.button("Confirm delete", type="primary", key=f"confirm_delete_btn_{item['template_id']}"):
                        try:
                            delete_template(item["template_id"], entity["entity_code"])
                            st.session_state.pop(confirm_key, None)
                            st.success("Template deleted.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not delete template: {type(exc).__name__}: {exc}")
                    if d2.button("Cancel", key=f"cancel_delete_btn_{item['template_id']}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()

    templates = list_templates(entity["entity_code"])
    if not templates:
        with tab_map:
            st.info("Upload a template first. The mapping tab will then list every placeholder detected in it.")
        with tab_generate:
            st.info("Upload and map a template before generating a populated copy.")
        return

    choices = {
        f"{x['template_name']} — {x['original_filename']} ({x['file_type'].upper()})": x["template_id"]
        for x in templates
    }
    selected = st.selectbox(
        "Select template",
        list(choices),
        key=f"template_selected_{entity['entity_code']}",
    )
    template = get_template(choices[selected], entity["entity_code"])
    detected = scan_placeholders(template)
    saved = json.loads(template.get("mapping_json") or "[]")
    saved_map = {x.get("placeholder", "").upper(): x.get("source", "") for x in saved}

    with tab_map:
        st.markdown("#### Map template placeholders")
        st.caption(
            f"{len(detected)} unique placeholder(s) detected in the selected template. "
            "Mappings are saved once and reused across all reporting periods."
        )
        io_col1, io_col2 = st.columns(2)
        export_bytes = mapping_workbook(template, source_values or {})
        safe_template_name = re.sub(r"[^A-Za-z0-9_-]+", "_", template["template_name"]).strip("_") or "template"
        io_col1.download_button(
            "Export placeholders and reporting sources (Excel)",
            data=export_bytes,
            file_name=f"{safe_template_name}_placeholder_mappings.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"export_mapping_{template['template_id']}",
            use_container_width=True,
        )
        mapping_upload = io_col2.file_uploader(
            "Import edited mappings (Excel)",
            type=["xlsx"],
            key=f"import_mapping_{template['template_id']}",
            label_visibility="visible",
        )
        if mapping_upload is not None and st.button(
            "Import and save mappings",
            type="primary",
            key=f"apply_mapping_import_{template['template_id']}",
        ):
            try:
                imported_count = import_mapping_workbook(
                    mapping_upload, template, entity["entity_code"], source_values or {}
                )
                st.success(f"Imported and verified {imported_count} placeholder mapping(s).")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not import mappings: {type(exc).__name__}: {exc}")
        if not source_values:
            st.warning("No IFRS Line, Notes Line, report subtotal/total, or Corporate Information sources are currently available. Assign Notes Lines to accounts in the Chart of Accounts and complete the Corporate Information profile.")
        elif not detected:
            st.warning("No double-curly-bracket placeholders were found in this template.")
        else:
            # Show every detected placeholder in one table and allow any reporting
            # source to be selected for any placeholder. This avoids category-based
            # filtering that can make the template appear to contain fewer fields.
            source_lookup = {}
            for source_key in sorted(source_values, key=lambda item: _source_display(item).casefold()):
                display = _source_display(source_key)
                if display in source_lookup:
                    display = f"{display} — {source_key}"
                source_lookup[display] = source_key
            key_to_display = {source_key: display for display, source_key in source_lookup.items()}
            source_options = [""] + list(source_lookup.keys())
            table_rows = []
            for token in detected:
                current_key = saved_map.get(token, "")
                current_display = key_to_display.get(current_key, "")
                table_rows.append({
                    "Template Placeholder": "{{" + token + "}}",
                    "Reporting Field": current_display,
                })

            mapping_df = pd.DataFrame(table_rows)
            edited_mapping = st.data_editor(
                mapping_df,
                key=f"placeholder_table_all_sources_{template['template_id']}_{str(template.get('updated_at', '')).replace(':', '').replace('-', '').replace('.', '')}",
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Template Placeholder": st.column_config.TextColumn(
                        "Template Placeholder", disabled=True, width="large"
                    ),
                    "Reporting Field": st.column_config.SelectboxColumn(
                        "Reporting Field – select any IFRS Line, Notes Line, Subtotal, Total or Corporate Information field",
                        options=source_options,
                        required=False,
                        width="large",
                    ),
                },
            )
            mapped_count = sum(bool(str(v or "").strip()) for v in edited_mapping["Reporting Field"].tolist())
            st.caption(f"{mapped_count} of {len(detected)} placeholders mapped across all reporting sources.")

            if st.button(
                "Save placeholder mappings",
                type="primary",
                key=f"save_placeholder_table_all_sources_{template['template_id']}",
            ):
                updated_map = dict(saved_map)
                for row in edited_mapping.to_dict("records"):
                    token = str(row["Template Placeholder"]).replace("{{", "").replace("}}", "").strip().upper()
                    chosen_display = str(row.get("Reporting Field") or "").strip()
                    if chosen_display:
                        updated_map[token] = source_lookup[chosen_display]
                    else:
                        updated_map.pop(token, None)
                records = [
                    {"Placeholder": token, "Source": updated_map[token]}
                    for token in detected
                    if updated_map.get(token, "")
                ]
                try:
                    saved_count = save_mapping(template["template_id"], entity["entity_code"], records)
                    st.session_state[f"mapping_saved_{template['template_id']}"] = saved_count
                    st.success(f"{saved_count} placeholder mapping(s) saved and verified in the database.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save placeholder mappings: {type(exc).__name__}: {exc}")
