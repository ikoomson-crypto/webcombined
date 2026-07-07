#!/usr/bin/env python
"""
Script to fix the Asset Movement Report routes in app.py
Run this script to repair the corrupted route decorators
"""

import os
import re
import shutil

print("=" * 70)
print("FIXING ASSET MOVEMENT REPORT ROUTES")
print("=" * 70)

# Create backup before fixing
backup_file = 'app.py.backup'
if os.path.exists('app.py'):
    shutil.copy2('app.py', backup_file)
    print(f"✓ Backup created: {backup_file}")
else:
    print("✗ app.py not found!")
    exit(1)

# Read the current app.py
with open('app.py', 'r', encoding='utf-8') as file:
    content = file.read()

# Find and fix the broken section
# Look for the pattern where route decorator is concatenated
broken_pattern = r'return render_template\(\'asset_movement_report\.html\',\s*entities=entities,\s*categories=categories\)@app\.route\(\'/api/reports/asset-movement\',\s*methods=\[\'POST\'\]\)'

# Replace with correct separation
fixed_section = r'''return render_template('asset_movement_report.html',
                           entities=entities,
                           categories=categories)


@app.route('/api/reports/asset-movement', methods=['POST'])'''

content = re.sub(broken_pattern, fixed_section, content)

# Also check for any other concatenation issues
# Fix pattern: categories=categories)@app.route
content = re.sub(r'categories=categories\)@app\.route', r'categories=categories)\n\n\n@app.route', content)

# Fix pattern: }@app.route
content = re.sub(r'\}\s*@app\.route', r'}\n\n\n@app.route', content)

# Write the fixed content back
with open('app.py', 'w', encoding='utf-8') as file:
    file.write(content)

print("✓ Fixed route decorator separation")

# Verify the fix
with open('app.py', 'r', encoding='utf-8') as file:
    fixed_content = file.read()

# Check if the fix was successful
if '@app.route' in fixed_content and 'def asset_movement_report' in fixed_content:
    print("✓ Asset Movement Report route found")
else:
    print("⚠ Could not verify fix - please check manually")

# Check for proper function definitions
if 'def asset_movement_report():' in fixed_content:
    print("✓ asset_movement_report function defined correctly")
else:
    print("⚠ asset_movement_report function may need manual check")

print("\n" + "=" * 70)
print("FIX COMPLETE!")
print("=" * 70)
print("""
Next steps:
  1. Restart your Flask application:
     python app.py

  2. Test the Asset Schedule report:
     http://localhost:5000/reports/asset-movement

  3. If the issue persists, restore from backup:
     copy app.py.backup app.py

The backup file 'app.py.backup' has been created in case you need to restore.
""")
print("=" * 70)