Kulana Financial Reporting — Entity-Specific Mapping Catalogues

CHANGES
- IFRS presentation lines, Notes lines and Account Types are now stored and maintained by entity_code.
- The Mapping Catalogue page and Chart of Accounts selectors load only the currently selected entity's catalogues.
- Catalogue imports, additions, edits, deactivations and Account Type renames affect only the selected entity.
- Chart of Accounts validation checks the selected entity's catalogue values.
- Existing Trial Balance imports and entity-specific COA/account mappings are retained.
- Existing shared ('*') catalogue rows are NOT copied into entity catalogues. Each entity starts with an empty IFRS, Notes and Account Type catalogue and must be populated independently.
- Existing shared ('*') catalogue rows are left in the database as legacy data; they are not used to populate or maintain entity catalogues.
- Streamlit catalogue widget keys are entity-specific to avoid carrying editor/upload state across entity switches.

DEPLOYMENT
1. Replace the corresponding Python modules in the project with the files in this package.
2. Keep the existing database and Render DATABASE_URL / FINREPORT_DATABASE_URL settings. No database reset is required.
3. Deploy/restart the service. The additive catalogue migration runs from AM.init_mapping_catalogues().
4. Ensure requirements.txt contains python-docx (the package is imported by automated_report_generator.py), plus the project's existing dependencies.

VALIDATION
- All nine Python modules were syntax-compiled.
- SQLite smoke tests confirmed each entity sees only its own IFRS, Notes and Account Type catalogues.
- Catalogue imports and COA validation were tested for entity isolation.
- Source inspection confirms initialization no longer copies shared ('*') catalogue rows into active entities.

IMPORTANT
- Each entity starts with a blank catalogue. Import or add its IFRS lines, Notes lines and Account Types separately in Mapping Catalogue.
- Do not delete the existing production database. This update is designed to preserve current TB imports and mappings.
