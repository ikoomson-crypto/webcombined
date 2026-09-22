# app.py - Complete Web-Based Payroll System with SQLite Database
# Features: Tax Exempt, Social Security Exemption, Date Ranges, Bulk Delete, Invoicing

import os
import json
import datetime
import io
import sqlite3
import calendar
import traceback
from functools import wraps
from io import BytesIO

import psycopg2
import psycopg2.extras
import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_file, jsonify, session, g
)
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from decimal import Decimal

# ============================================
# APPLICATION CONFIGURATION
# ============================================

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============================================
# DATABASE SETUP
# ============================================

DATABASE_URL = os.environ.get('DATABASE_URL', '')
IS_PRODUCTION = bool(DATABASE_URL)

if IS_PRODUCTION:
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    print(f"✅ Using PostgreSQL database on Render")
    DATABASE = None
else:
    DATABASE = 'payroll.db'
    print(f"✅ Using SQLite database: {DATABASE}")


# ============================================
# DATABASE CURSOR WITH AUTO PARAMETER CONVERSION
# ============================================

class AutoCursor:
    """A wrapper class that automatically converts ? to %s for PostgreSQL"""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        """Execute a query, automatically converting ? to %s for PostgreSQL"""
        if IS_PRODUCTION and params is not None:
            # Convert ? to %s for PostgreSQL
            query = query.replace('?', '%s')
        if params is not None:
            return self._cursor.execute(query, params)
        else:
            return self._cursor.execute(query)

    def __getattr__(self, name):
        """Forward all other attribute/method calls to the underlying cursor"""
        return getattr(self._cursor, name)

    def __iter__(self):
        """Support iteration over cursor results"""
        return iter(self._cursor)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

# ============================================
# DATABASE HELPERS
# ============================================

def get_db():
    """Get database connection - supports both SQLite and PostgreSQL"""
    db = getattr(g, '_database', None)
    if db is None:
        if IS_PRODUCTION:
            db = psycopg2.connect(DATABASE_URL)
            db.autocommit = False
        else:
            db = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row
        g._database = db
    return db


def get_cursor(db=None):
    """Get a cursor from the database connection"""
    if db is None:
        db = get_db()

    if IS_PRODUCTION:
        # PostgreSQL - returns dict-like rows
        raw_cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        # SQLite - returns dict-like rows with sqlite3.Row
        db.row_factory = sqlite3.Row
        raw_cursor = db.cursor()

    # Wrap the cursor with auto-parameter conversion
    return AutoCursor(raw_cursor)

@app.teardown_appcontext
def close_connection(exception):
    """Close database connection"""
    db = getattr(g, '_database', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


def execute_query(db, query, params=None):
    """Execute a query with proper parameter handling"""
    cursor = get_cursor(db)
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor
    except Exception as e:
        print(f"❌ Database error: {e}")
        print(f"Query: {query}")
        if params:
            print(f"Params: {params}")
        raise


def dict_from_row(row):
    """Convert a row to dict, handling both sqlite3.Row and psycopg2 RealDictCursor"""
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return dict(row)
    return dict(zip(row.keys(), row)) if hasattr(row, 'keys') else dict(row)


def rows_to_list(rows):
    """Convert a list of rows to list of dicts"""
    if rows is None:
        return []
    return [dict_from_row(row) for row in rows]


# ============================================
# DATABASE INITIALIZATION
# ============================================

def init_db():
    """Initialize database with tables"""
    db = get_db()
    cursor = get_cursor(db)
    is_postgres = IS_PRODUCTION

    # Define table schemas
    tables = {
        'companies': ('''
            CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                base_currency TEXT NOT NULL,
                address TEXT,
                tax_id TEXT,
                email TEXT,
                phone TEXT,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_currency TEXT NOT NULL,
                address TEXT,
                tax_id TEXT,
                email TEXT,
                phone TEXT,
                created_date TEXT
            )
        '''),
        'employees': ('''
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL,
                position TEXT NOT NULL,
                department TEXT NOT NULL,
                base_salary REAL NOT NULL,
                hire_date TEXT NOT NULL,
                status TEXT NOT NULL,
                is_tax_exempt INTEGER DEFAULT 0,
                exempt_from_social_security INTEGER DEFAULT 0,
                bank_name TEXT,
                bank_currency TEXT,
                bank_account_number TEXT,
                bank_iban TEXT,
                bank_account_name TEXT,
                bank_swift_code TEXT,
                bank_address TEXT,
                id_type TEXT,
                id_number TEXT,
                street_location TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL,
                position TEXT NOT NULL,
                department TEXT NOT NULL,
                base_salary REAL NOT NULL,
                hire_date TEXT NOT NULL,
                status TEXT NOT NULL,
                is_tax_exempt INTEGER DEFAULT 0,
                exempt_from_social_security INTEGER DEFAULT 0,
                bank_name TEXT,
                bank_currency TEXT,
                bank_account_number TEXT,
                bank_iban TEXT,
                bank_account_name TEXT,
                bank_swift_code TEXT,
                bank_address TEXT,
                id_type TEXT,
                id_number TEXT,
                street_location TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'monthly_salaries': ('''
            CREATE TABLE IF NOT EXISTS monthly_salaries (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                salary REAL NOT NULL,
                UNIQUE(employee_id, year, month)
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS monthly_salaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                salary REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                UNIQUE(employee_id, year, month)
            )
        '''),
        'tax_configs': ('''
            CREATE TABLE IF NOT EXISTS tax_configs (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                year INTEGER NOT NULL,
                country TEXT NOT NULL,
                standard_deduction REAL NOT NULL,
                social_security_rate REAL NOT NULL,
                social_security_threshold REAL NOT NULL,
                brackets TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS tax_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                country TEXT NOT NULL,
                standard_deduction REAL NOT NULL,
                social_security_rate REAL NOT NULL,
                social_security_threshold REAL NOT NULL,
                brackets TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'social_security_thresholds': ('''
            CREATE TABLE IF NOT EXISTS social_security_thresholds (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                threshold REAL NOT NULL,
                created_date TEXT,
                UNIQUE(company_id, year, month)
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS social_security_thresholds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                threshold REAL NOT NULL,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id),
                UNIQUE(company_id, year, month)
            )
        '''),
        'bonus_records': ('''
            CREATE TABLE IF NOT EXISTS bonus_records (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                company_id INTEGER NOT NULL REFERENCES companies(id),
                start_date TEXT NOT NULL,
                end_date TEXT,
                bonus_amount REAL NOT NULL,
                bonus_type TEXT NOT NULL,
                description TEXT,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS bonus_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                bonus_amount REAL NOT NULL,
                bonus_type TEXT NOT NULL,
                description TEXT,
                created_date TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'bonus_tax_configs': ('''
            CREATE TABLE IF NOT EXISTS bonus_tax_configs (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                year INTEGER NOT NULL,
                bonus_threshold_percentage REAL NOT NULL,
                bonus_tax_rate REAL NOT NULL,
                created_date TEXT,
                UNIQUE(company_id, year)
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS bonus_tax_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                bonus_threshold_percentage REAL NOT NULL,
                bonus_tax_rate REAL NOT NULL,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id),
                UNIQUE(company_id, year)
            )
        '''),
        'bik_definitions': ('''
            CREATE TABLE IF NOT EXISTS bik_definitions (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_taxable INTEGER DEFAULT 1,
                description TEXT,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS bik_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_taxable INTEGER DEFAULT 1,
                description TEXT,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'employee_bik': ('''
            CREATE TABLE IF NOT EXISTS employee_bik (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                bik_id INTEGER NOT NULL REFERENCES bik_definitions(id),
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS employee_bik (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                bik_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (bik_id) REFERENCES bik_definitions(id)
            )
        '''),
        'allowance_definitions': ('''
            CREATE TABLE IF NOT EXISTS allowance_definitions (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_taxable INTEGER DEFAULT 0,
                description TEXT,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS allowance_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_taxable INTEGER DEFAULT 0,
                description TEXT,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'employee_allowances': ('''
            CREATE TABLE IF NOT EXISTS employee_allowances (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                allowance_id INTEGER NOT NULL REFERENCES allowance_definitions(id),
                value REAL NOT NULL
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS employee_allowances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                allowance_id INTEGER NOT NULL,
                value REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (allowance_id) REFERENCES allowance_definitions(id)
            )
        '''),
        'monthly_allowances': ('''
            CREATE TABLE IF NOT EXISTS monthly_allowances (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                allowance_id INTEGER NOT NULL REFERENCES allowance_definitions(id),
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                value REAL NOT NULL,
                created_date TEXT,
                UNIQUE(employee_id, allowance_id, year, month)
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS monthly_allowances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                allowance_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                value REAL NOT NULL,
                created_date TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (allowance_id) REFERENCES allowance_definitions(id),
                UNIQUE(employee_id, allowance_id, year, month)
            )
        '''),
        'deduction_definitions': ('''
            CREATE TABLE IF NOT EXISTS deduction_definitions (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_percentage INTEGER DEFAULT 0,
                description TEXT,
                created_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS deduction_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                default_value REAL NOT NULL,
                is_percentage INTEGER DEFAULT 0,
                description TEXT,
                created_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'employee_deductions': ('''
            CREATE TABLE IF NOT EXISTS employee_deductions (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                deduction_id INTEGER NOT NULL REFERENCES deduction_definitions(id),
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS employee_deductions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                deduction_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (deduction_id) REFERENCES deduction_definitions(id)
            )
        '''),
        'payroll_records': ('''
            CREATE TABLE IF NOT EXISTS payroll_records (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                company_id INTEGER NOT NULL REFERENCES companies(id),
                period TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                base_salary REAL NOT NULL,
                allowances_total REAL NOT NULL,
                allowance_details TEXT,
                bonus_amount REAL DEFAULT 0,
                bonus_details TEXT,
                bik_total REAL DEFAULT 0,
                bik_details TEXT,
                deductions_total REAL NOT NULL,
                deduction_details TEXT,
                gross_salary REAL NOT NULL,
                annual_gross REAL NOT NULL,
                annual_taxable REAL NOT NULL,
                annual_tax REAL NOT NULL,
                monthly_tax REAL NOT NULL,
                bonus_tax_flat REAL DEFAULT 0,
                total_tax REAL NOT NULL,
                social_security REAL NOT NULL,
                social_security_threshold_applied REAL NOT NULL,
                total_deductions REAL NOT NULL,
                net_pay REAL NOT NULL,
                currency TEXT NOT NULL,
                tax_year INTEGER NOT NULL,
                tax_config_id INTEGER NOT NULL,
                processed_date TEXT,
                is_tax_exempt INTEGER DEFAULT 0,
                exempt_from_social_security INTEGER DEFAULT 0
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                base_salary REAL NOT NULL,
                allowances_total REAL NOT NULL,
                allowance_details TEXT,
                bonus_amount REAL DEFAULT 0,
                bonus_details TEXT,
                bik_total REAL DEFAULT 0,
                bik_details TEXT,
                deductions_total REAL NOT NULL,
                deduction_details TEXT,
                gross_salary REAL NOT NULL,
                annual_gross REAL NOT NULL,
                annual_taxable REAL NOT NULL,
                annual_tax REAL NOT NULL,
                monthly_tax REAL NOT NULL,
                bonus_tax_flat REAL DEFAULT 0,
                total_tax REAL NOT NULL,
                social_security REAL NOT NULL,
                social_security_threshold_applied REAL NOT NULL,
                total_deductions REAL NOT NULL,
                net_pay REAL NOT NULL,
                currency TEXT NOT NULL,
                tax_year INTEGER NOT NULL,
                tax_config_id INTEGER NOT NULL,
                processed_date TEXT,
                is_tax_exempt INTEGER DEFAULT 0,
                exempt_from_social_security INTEGER DEFAULT 0,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        '''),
        'consultant_invoices': ('''
            CREATE TABLE IF NOT EXISTS consultant_invoices (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                invoice_number TEXT NOT NULL UNIQUE,
                invoice_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                description TEXT,
                hourly_rate REAL NOT NULL,
                hours_worked REAL NOT NULL,
                total_amount REAL NOT NULL,
                tax_amount REAL DEFAULT 0,
                discount_amount REAL DEFAULT 0,
                final_amount REAL NOT NULL,
                status TEXT DEFAULT 'Draft',
                notes TEXT,
                created_date TEXT,
                updated_date TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS consultant_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                employee_id INTEGER NOT NULL,
                invoice_number TEXT NOT NULL UNIQUE,
                invoice_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                description TEXT,
                hourly_rate REAL NOT NULL,
                hours_worked REAL NOT NULL,
                total_amount REAL NOT NULL,
                tax_amount REAL DEFAULT 0,
                discount_amount REAL DEFAULT 0,
                final_amount REAL NOT NULL,
                status TEXT DEFAULT 'Draft',
                notes TEXT,
                created_date TEXT,
                updated_date TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id),
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            )
        '''),
        'invoice_items': ('''
            CREATE TABLE IF NOT EXISTS invoice_items (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER NOT NULL REFERENCES consultant_invoices(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                quantity REAL NOT NULL,
                rate REAL NOT NULL,
                amount REAL NOT NULL
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                quantity REAL NOT NULL,
                rate REAL NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES consultant_invoices(id) ON DELETE CASCADE
            )
        '''),
        'invoice_payments': ('''
            CREATE TABLE IF NOT EXISTS invoice_payments (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER NOT NULL REFERENCES consultant_invoices(id) ON DELETE CASCADE,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                reference TEXT,
                notes TEXT
            )
        ''', '''
            CREATE TABLE IF NOT EXISTS invoice_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                reference TEXT,
                notes TEXT,
                FOREIGN KEY (invoice_id) REFERENCES consultant_invoices(id) ON DELETE CASCADE
            )
        ''')
    }

    for table_name, (pg_sql, sqlite_sql) in tables.items():
        sql = pg_sql if is_postgres else sqlite_sql
        cursor.execute(sql)

    db.commit()
    print("✅ Database initialized successfully")


# ============================================
# MIGRATION FUNCTIONS
# ============================================

def migrate_to_date_ranges():
    """Migrate tables to use start_date and end_date"""
    db = get_db()
    cursor = db.cursor()

    migrations = [
        ('employee_deductions', 'start_date', '''
            CREATE TABLE employee_deductions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                deduction_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (deduction_id) REFERENCES deduction_definitions(id)
            )
        ''', '''
            INSERT INTO employee_deductions_new (employee_id, deduction_id, start_date, end_date, value)
            SELECT employee_id, deduction_id, printf('%04d-%02d-01', year, month) as start_date,
                   printf('%04d-%02d-01', year, month) as end_date, value
            FROM employee_deductions
        '''),
        ('employee_bik', 'start_date', '''
            CREATE TABLE employee_bik_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                bik_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                value REAL NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (bik_id) REFERENCES bik_definitions(id)
            )
        ''', '''
            INSERT INTO employee_bik_new (employee_id, bik_id, start_date, end_date, value)
            SELECT employee_id, bik_id, printf('%04d-%02d-01', year, month) as start_date,
                   printf('%04d-%02d-01', year, month) as end_date, value
            FROM employee_bik
        '''),
        ('bonus_records', 'start_date', '''
            CREATE TABLE bonus_records_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                bonus_amount REAL NOT NULL,
                bonus_type TEXT NOT NULL,
                description TEXT,
                created_date TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        ''', '''
            INSERT INTO bonus_records_new (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description, created_date)
            SELECT employee_id, company_id, printf('%04d-%02d-01', year, month) as start_date,
                   printf('%04d-%02d-01', year, month) as end_date, bonus_amount, bonus_type, description, created_date
            FROM bonus_records
        ''')
    ]

    for table_name, column_check, create_sql, insert_sql in migrations:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            if column_check not in columns:
                print(f"🔄 Migrating {table_name} to use start_date and end_date...")
                cursor.execute(create_sql)
                cursor.execute(insert_sql)
                cursor.execute(f"DROP TABLE {table_name}")
                cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
                print(f"✅ {table_name} migrated successfully!")

    db.commit()
    print("✅ All date range migrations completed successfully!")


def migrate_database():
    """Check and migrate database schema if needed"""
    db = get_db()
    cursor = db.cursor()

    try:
        # Check for new columns in employees table
        cursor.execute("PRAGMA table_info(employees)")
        columns = [column[1] for column in cursor.fetchall()]

        # Bank details columns
        bank_fields = [
            ('bank_name', 'TEXT'),
            ('bank_currency', 'TEXT'),
            ('bank_account_number', 'TEXT'),
            ('bank_iban', 'TEXT'),
            ('bank_account_name', 'TEXT'),
            ('bank_swift_code', 'TEXT'),
            ('bank_address', 'TEXT'),
            ('id_type', 'TEXT'),
            ('id_number', 'TEXT'),
            ('street_location', 'TEXT')
        ]

        for field, field_type in bank_fields:
            if field not in columns:
                print(f"🔄 Adding '{field}' column to employees table...")
                cursor.execute(f"ALTER TABLE employees ADD COLUMN {field} {field_type}")
                db.commit()
                print(f"✅ {field} column added successfully!")

        # Check payroll_records columns
        cursor.execute("PRAGMA table_info(payroll_records)")
        columns = [column[1] for column in cursor.fetchall()]

        # Add month column if missing
        if 'month' not in columns:
            print("🔄 Adding 'month' column to payroll_records...")
            cursor.execute("ALTER TABLE payroll_records ADD COLUMN month INTEGER DEFAULT 1")
            db.commit()

            cursor.execute("SELECT id, period FROM payroll_records WHERE month IS NULL OR month = 1")
            records = cursor.fetchall()
            for rec in records:
                rec_id = rec[0]
                period = rec[1]
                if period and '-' in period:
                    try:
                        month = int(period.split('-')[1])
                    except:
                        month = 1
                else:
                    month = 1
                cursor.execute("UPDATE payroll_records SET month = ? WHERE id = ?", (month, rec_id))
            db.commit()
            print(f"✅ Updated {len(records)} records with month values")

        # Add other payroll columns if missing
        payroll_columns = [
            ('deductions_total', "ALTER TABLE payroll_records ADD COLUMN deductions_total REAL DEFAULT 0"),
            ('deduction_details', "ALTER TABLE payroll_records ADD COLUMN deduction_details TEXT DEFAULT '[]'"),
            ('social_security_threshold_applied', "ALTER TABLE payroll_records ADD COLUMN social_security_threshold_applied REAL DEFAULT 0"),
            ('bonus_amount', "ALTER TABLE payroll_records ADD COLUMN bonus_amount REAL DEFAULT 0"),
            ('bonus_details', "ALTER TABLE payroll_records ADD COLUMN bonus_details TEXT"),
            ('bonus_tax_flat', "ALTER TABLE payroll_records ADD COLUMN bonus_tax_flat REAL DEFAULT 0"),
            ('total_tax', "ALTER TABLE payroll_records ADD COLUMN total_tax REAL DEFAULT 0"),
            ('bik_total', "ALTER TABLE payroll_records ADD COLUMN bik_total REAL DEFAULT 0"),
            ('bik_details', "ALTER TABLE payroll_records ADD COLUMN bik_details TEXT"),
            ('is_tax_exempt', "ALTER TABLE payroll_records ADD COLUMN is_tax_exempt INTEGER DEFAULT 0"),
            ('exempt_from_social_security', "ALTER TABLE payroll_records ADD COLUMN exempt_from_social_security INTEGER DEFAULT 0")
        ]

        for col_name, alter_sql in payroll_columns:
            if col_name not in columns:
                print(f"🔄 Adding '{col_name}' column to payroll_records...")
                cursor.execute(alter_sql)
                db.commit()
                print(f"✅ {col_name} column added successfully!")

        # Run date range migration
        if not IS_PRODUCTION:
            migrate_to_date_ranges()

        print("✅ Database schema is up to date")

    except Exception as e:
        print(f"⚠️ Migration error: {e}")
        db.rollback()


# ============================================
# UTILITY FUNCTIONS
# ============================================

def get_month_name(month_num):
    """Get month name from month number"""
    months = {
        1: 'January', 2: 'February', 3: 'March', 4: 'April',
        5: 'May', 6: 'June', 7: 'July', 8: 'August',
        9: 'September', 10: 'October', 11: 'November', 12: 'December'
    }
    return months.get(month_num, 'Unknown')


def format_currency(value):
    """Format currency with comma separators"""
    try:
        return f"{value:,.2f}"
    except:
        return "0.00"


def get_month_start_end(year, month):
    """Get the first and last day of a month"""
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def is_date_active(start_date, end_date, year, month):
    """Check if a date range covers a specific month"""
    target_start = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    target_end = datetime.date(year, month, last_day)

    if isinstance(start_date, str):
        start = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
    else:
        start = start_date

    if start <= target_end:
        if end_date is None:
            return True
        if isinstance(end_date, str):
            end = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end = end_date
        return end >= target_start

    return False


def get_default_tax_rates(year=2024):
    """Get default tax rates for a specific year"""
    ss_thresholds = {
        2020: 137700, 2021: 142800, 2022: 147000,
        2023: 160200, 2024: 168600, 2025: 176100
    }

    tax_rates = {
        2020: {
            'brackets': [
                {'min': 0, 'max': 9875, 'rate': 10},
                {'min': 9876, 'max': 40125, 'rate': 12},
                {'min': 40126, 'max': 85525, 'rate': 22},
                {'min': 85526, 'max': 163300, 'rate': 24},
                {'min': 163301, 'max': 207350, 'rate': 32},
                {'min': 207351, 'max': 518400, 'rate': 35},
                {'min': 518401, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 12400,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2020, 137700)
        },
        2021: {
            'brackets': [
                {'min': 0, 'max': 9950, 'rate': 10},
                {'min': 9951, 'max': 40525, 'rate': 12},
                {'min': 40526, 'max': 86375, 'rate': 22},
                {'min': 86376, 'max': 164925, 'rate': 24},
                {'min': 164926, 'max': 209425, 'rate': 32},
                {'min': 209426, 'max': 523600, 'rate': 35},
                {'min': 523601, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 12550,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2021, 142800)
        },
        2022: {
            'brackets': [
                {'min': 0, 'max': 10275, 'rate': 10},
                {'min': 10276, 'max': 41775, 'rate': 12},
                {'min': 41776, 'max': 89075, 'rate': 22},
                {'min': 89076, 'max': 170050, 'rate': 24},
                {'min': 170051, 'max': 215950, 'rate': 32},
                {'min': 215951, 'max': 539900, 'rate': 35},
                {'min': 539901, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 12950,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2022, 147000)
        },
        2023: {
            'brackets': [
                {'min': 0, 'max': 11000, 'rate': 10},
                {'min': 11001, 'max': 44725, 'rate': 12},
                {'min': 44726, 'max': 95375, 'rate': 22},
                {'min': 95376, 'max': 182100, 'rate': 24},
                {'min': 182101, 'max': 231250, 'rate': 32},
                {'min': 231251, 'max': 578125, 'rate': 35},
                {'min': 578126, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 13850,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2023, 160200)
        },
        2024: {
            'brackets': [
                {'min': 0, 'max': 11600, 'rate': 10},
                {'min': 11601, 'max': 47150, 'rate': 12},
                {'min': 47151, 'max': 100525, 'rate': 22},
                {'min': 100526, 'max': 191950, 'rate': 24},
                {'min': 191951, 'max': 243725, 'rate': 32},
                {'min': 243726, 'max': 609350, 'rate': 35},
                {'min': 609351, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 14600,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2024, 168600)
        },
        2025: {
            'brackets': [
                {'min': 0, 'max': 11925, 'rate': 10},
                {'min': 11926, 'max': 48475, 'rate': 12},
                {'min': 48476, 'max': 103350, 'rate': 22},
                {'min': 103351, 'max': 197300, 'rate': 24},
                {'min': 197301, 'max': 250525, 'rate': 32},
                {'min': 250526, 'max': 626350, 'rate': 35},
                {'min': 626351, 'max': float('inf'), 'rate': 37}
            ],
            'standard_deduction': 15000,
            'social_security_rate': 6.2,
            'social_security_threshold': ss_thresholds.get(2025, 176100)
        }
    }
    return tax_rates.get(year, tax_rates[2024])


def calculate_progressive_tax(annual_income, tax_config):
    """Calculate tax using progressive tax system"""
    if not tax_config:
        return 0

    brackets = json.loads(tax_config['brackets'])
    standard_deduction = tax_config['standard_deduction']

    taxable_income = max(0, annual_income - standard_deduction)
    tax = 0
    remaining_income = taxable_income

    for bracket in brackets:
        if remaining_income <= 0:
            break
        if bracket['max'] == float('inf'):
            tax += remaining_income * (bracket['rate'] / 100)
            break
        bracket_amount = min(remaining_income, bracket['max'] - bracket['min'])
        if bracket_amount > 0:
            tax += bracket_amount * (bracket['rate'] / 100)
            remaining_income -= bracket_amount

    return tax


# ============================================
# DATABASE QUERY FUNCTIONS
# ============================================

def get_all_companies():
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM companies ORDER BY id")
    return rows_to_list(cursor.fetchall())


def get_company(company_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    return dict_from_row(cursor.fetchone())


def get_employees_by_company(company_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM employees WHERE company_id = ? ORDER BY id", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_employee(employee_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    return dict_from_row(cursor.fetchone())


def get_all_employees():
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM employees ORDER BY id")
    return rows_to_list(cursor.fetchall())


def get_tax_configs_by_company(company_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM tax_configs WHERE company_id = ? ORDER BY year", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_tax_config(company_id, year):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM tax_configs WHERE company_id = ? AND year = ?", (company_id, year))
    return dict_from_row(cursor.fetchone())


def get_active_tax_config(company_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM tax_configs WHERE company_id = ? AND is_active = 1", (company_id,))
    return dict_from_row(cursor.fetchone())


def get_payroll_records_by_company(company_id, year=None):
    db = get_db()
    cursor = get_cursor(db)
    if year:
        cursor.execute("SELECT * FROM payroll_records WHERE company_id = ? AND year = ? ORDER BY id", (company_id, year))
    else:
        cursor.execute("SELECT * FROM payroll_records WHERE company_id = ? ORDER BY id", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_payroll_by_month(company_id, year, month):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT * FROM payroll_records 
        WHERE company_id = ? AND year = ? AND month = ?
        ORDER BY id
    """, (company_id, year, month))
    return rows_to_list(cursor.fetchall())


def get_processed_months(company_id):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT DISTINCT year, month FROM payroll_records 
        WHERE company_id = ? 
        ORDER BY year DESC, month DESC
    """, (company_id,))
    return rows_to_list(cursor.fetchall())


def get_all_payroll_records():
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM payroll_records ORDER BY id")
    return rows_to_list(cursor.fetchall())


def get_all_tax_configs():
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM tax_configs ORDER BY company_id, year")
    return rows_to_list(cursor.fetchall())


def get_employee_monthly_salary(employee_id, year, month):
    """Get employee's salary for a specific month"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT salary FROM monthly_salaries 
        WHERE employee_id = ? AND year = ? AND month = ?
    """, (employee_id, year, month))
    result = cursor.fetchone()
    if result:
        return result['salary']
    employee = get_employee(employee_id)
    return employee['base_salary'] if employee else 0


def set_employee_monthly_salary(employee_id, year, month, salary, commit=True):
    """Set employee's salary for a specific month.

    When commit=False, the caller controls the transaction, allowing
    PostgreSQL row-level SAVEPOINT handling.
    """
    db = get_db()
    cursor = get_cursor(db)
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO monthly_salaries (employee_id, year, month, salary)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (employee_id, year, month) 
            DO UPDATE SET salary = EXCLUDED.salary
        """, (employee_id, year, month, salary))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO monthly_salaries (employee_id, year, month, salary)
            VALUES (?, ?, ?, ?)
        """, (employee_id, year, month, salary))
    if commit:
        db.commit()


def get_social_security_threshold(company_id, year, month):
    """Get the social security threshold for a specific month"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT threshold FROM social_security_thresholds 
        WHERE company_id = ? AND year = ? AND month = ?
    """, (company_id, year, month))
    result = cursor.fetchone()

    if result:
        return result['threshold']

    tax_config = get_tax_config(company_id, year)
    if tax_config:
        return tax_config['social_security_threshold']

    default_thresholds = {
        2020: 137700, 2021: 142800, 2022: 147000,
        2023: 160200, 2024: 168600, 2025: 176100
    }
    return default_thresholds.get(year, 168600)


def set_social_security_threshold(company_id, year, month, threshold):
    """Set a monthly social security threshold override"""
    db = get_db()
    cursor = get_cursor(db)
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO social_security_thresholds (company_id, year, month, threshold, created_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (company_id, year, month) 
            DO UPDATE SET threshold = EXCLUDED.threshold, created_date = EXCLUDED.created_date
        """, (company_id, year, month, threshold, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO social_security_thresholds (company_id, year, month, threshold, created_date)
            VALUES (?, ?, ?, ?, ?)
        """, (company_id, year, month, threshold, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()


# ============================================
# ALLOWANCE FUNCTIONS
# ============================================

def get_allowance_definitions(company_id):
    """Get all allowance definitions for a company"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM allowance_definitions WHERE company_id = ? ORDER BY id", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_allowance_definition(allowance_id):
    """Get a allowance definition by ID"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM allowance_definitions WHERE id = ?", (allowance_id,))
    return dict_from_row(cursor.fetchone())


def get_employee_allowances(employee_id):
    """Get current allowances for an employee"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT ea.*, ad.name, ad.is_taxable, ad.default_value 
        FROM employee_allowances ea
        JOIN allowance_definitions ad ON ea.allowance_id = ad.id
        WHERE ea.employee_id = ?
    """, (employee_id,))
    return rows_to_list(cursor.fetchall())


def get_employee_allowance_dict(employee_id):
    """Get employee allowances as dictionary {allowance_id: value}"""
    allowances = get_employee_allowances(employee_id)
    return {a['allowance_id']: a['value'] for a in allowances}


def get_employee_monthly_allowance(employee_id, allowance_id, year, month):
    """Get a specific employee's allowance for a specific month"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT value FROM monthly_allowances 
        WHERE employee_id = ? AND allowance_id = ? AND year = ? AND month = ?
    """, (employee_id, allowance_id, year, month))
    result = cursor.fetchone()

    if result:
        return result['value']

    cursor.execute("""
        SELECT value FROM employee_allowances 
        WHERE employee_id = ? AND allowance_id = ?
    """, (employee_id, allowance_id))
    result = cursor.fetchone()

    if result:
        return result['value']

    allowance_def = get_allowance_definition(allowance_id)
    return allowance_def['default_value'] if allowance_def else 0


def get_all_employee_monthly_allowances(employee_id, year, month):
    """Get all allowances for an employee for a specific month"""
    employee = get_employee(employee_id)
    if not employee:
        return []

    definitions = get_allowance_definitions(employee['company_id'])
    result = []
    for defn in definitions:
        value = get_employee_monthly_allowance(employee_id, defn['id'], year, month)
        result.append({
            'allowance_id': defn['id'],
            'name': defn['name'],
            'value': value,
            'is_taxable': defn['is_taxable'],
            'default_value': defn['default_value']
        })
    return result


def set_employee_monthly_allowance(employee_id, allowance_id, year, month, value, commit=True):
    """Set an employee's allowance for a specific month.

    When commit=False, the caller controls the transaction, allowing
    PostgreSQL row-level SAVEPOINT handling.
    """
    db = get_db()
    cursor = get_cursor(db)

    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO monthly_allowances (employee_id, allowance_id, year, month, value, created_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, allowance_id, year, month) 
            DO UPDATE SET value = EXCLUDED.value, created_date = EXCLUDED.created_date
        """, (employee_id, allowance_id, year, month, value, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    else:
        cursor.execute("""
            SELECT id FROM monthly_allowances 
            WHERE employee_id = ? AND allowance_id = ? AND year = ? AND month = ?
        """, (employee_id, allowance_id, year, month))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE monthly_allowances 
                SET value = ?, created_date = ?
                WHERE employee_id = ? AND allowance_id = ? AND year = ? AND month = ?
            """, (value, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), employee_id, allowance_id, year, month))
        else:
            cursor.execute("""
                INSERT INTO monthly_allowances (employee_id, allowance_id, year, month, value, created_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (employee_id, allowance_id, year, month, value, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    # Update employee_allowances as well
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO employee_allowances (employee_id, allowance_id, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (employee_id, allowance_id) 
            DO UPDATE SET value = EXCLUDED.value
        """, (employee_id, allowance_id, value))
    else:
        cursor.execute("""
            SELECT id FROM employee_allowances 
            WHERE employee_id = ? AND allowance_id = ?
        """, (employee_id, allowance_id))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE employee_allowances SET value = ?
                WHERE employee_id = ? AND allowance_id = ?
            """, (value, employee_id, allowance_id))
        else:
            cursor.execute("""
                INSERT INTO employee_allowances (employee_id, allowance_id, value)
                VALUES (?, ?, ?)
            """, (employee_id, allowance_id, value))

    if commit:
        db.commit()


def calculate_employee_allowances(employee_id, year, month):
    """Calculate total allowances for an employee for a specific month"""
    allowances = get_all_employee_monthly_allowances(employee_id, year, month)
    total = 0
    details = []
    for a in allowances:
        total += a['value']
        details.append({
            'name': a['name'],
            'value': a['value'],
            'is_taxable': bool(a['is_taxable'])
        })
    return {'total': total, 'details': details}


# ============================================
# DEDUCTION FUNCTIONS
# ============================================

def get_deduction_definitions(company_id):
    """Get all deduction definitions for a company"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM deduction_definitions WHERE company_id = ? ORDER BY id", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_deduction_definition(deduction_id):
    """Get a deduction definition by ID"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM deduction_definitions WHERE id = ?", (deduction_id,))
    return dict_from_row(cursor.fetchone())


def get_employee_deductions(employee_id, year, month):
    """Get all deductions for an employee active for a specific month"""
    db = get_db()
    cursor = get_cursor(db)
    start_of_month, end_of_month = get_month_start_end(year, month)

    cursor.execute("""
        SELECT ed.*, dd.name, dd.type, dd.default_value, dd.is_percentage
        FROM employee_deductions ed
        JOIN deduction_definitions dd ON ed.deduction_id = dd.id
        WHERE ed.employee_id = ? 
          AND ed.start_date <= ? 
          AND (ed.end_date IS NULL OR ed.end_date >= ?)
    """, (employee_id, end_of_month, start_of_month))
    return rows_to_list(cursor.fetchall())


def get_employee_deduction_value(employee_id, deduction_id, year, month):
    """Get a specific employee's deduction value for a specific month"""
    db = get_db()
    cursor = get_cursor(db)
    start_of_month, end_of_month = get_month_start_end(year, month)

    cursor.execute("""
        SELECT value FROM employee_deductions 
        WHERE employee_id = ? AND deduction_id = ? 
          AND start_date <= ? 
          AND (end_date IS NULL OR end_date >= ?)
        ORDER BY start_date DESC LIMIT 1
    """, (employee_id, deduction_id, end_of_month, start_of_month))
    result = cursor.fetchone()

    if result:
        return result['value']

    defn = get_deduction_definition(deduction_id)
    return defn['default_value'] if defn else 0


def set_employee_deduction(employee_id, deduction_id, start_date, end_date, value):
    """Set employee deduction with a date range"""
    db = get_db()
    cursor = get_cursor(db)
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO employee_deductions (employee_id, deduction_id, start_date, end_date, value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, deduction_id, start_date) 
            DO UPDATE SET end_date = EXCLUDED.end_date, value = EXCLUDED.value
        """, (employee_id, deduction_id, start_date, end_date, value))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO employee_deductions (employee_id, deduction_id, start_date, end_date, value)
            VALUES (?, ?, ?, ?, ?)
        """, (employee_id, deduction_id, start_date, end_date, value))
    db.commit()


def calculate_employee_deductions(employee_id, year, month, gross_salary):
    """Calculate total deductions for an employee for a specific month"""
    deductions = get_employee_deductions(employee_id, year, month)
    total = 0
    details = []
    for d in deductions:
        if d['is_percentage']:
            value = (d['value'] / 100) * gross_salary
        else:
            value = d['value']
        total += value
        details.append({
            'name': d['name'],
            'value': value,
            'is_percentage': bool(d['is_percentage']),
            'rate': d['value'] if d['is_percentage'] else None
        })
    return {'total': total, 'details': details}


# ============================================
# BONUS FUNCTIONS
# ============================================

def get_employee_annual_basic_salary(employee_id, year):
    """Get employee's annual basic salary for a specific year"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT salary FROM monthly_salaries 
        WHERE employee_id = ? AND year = ?
        ORDER BY month
    """, (employee_id, year))
    monthly_salaries = cursor.fetchall()

    if monthly_salaries and len(monthly_salaries) == 12:
        return sum(record['salary'] for record in monthly_salaries)
    else:
        employee = get_employee(employee_id)
        return employee['base_salary'] * 12


def get_bonus_tax_config(company_id, year):
    """Get bonus tax configuration for a company and year"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT * FROM bonus_tax_configs 
        WHERE company_id = ? AND year = ?
    """, (company_id, year))
    result = cursor.fetchone()
    if result:
        return dict_from_row(result)
    return {'bonus_threshold_percentage': 15.0, 'bonus_tax_rate': 5.0}


def set_bonus_tax_config(company_id, year, threshold_percentage, tax_rate):
    """Set bonus tax configuration"""
    db = get_db()
    cursor = get_cursor(db)
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO bonus_tax_configs (company_id, year, bonus_threshold_percentage, bonus_tax_rate, created_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (company_id, year) 
            DO UPDATE SET bonus_threshold_percentage = EXCLUDED.bonus_threshold_percentage,
                          bonus_tax_rate = EXCLUDED.bonus_tax_rate,
                          created_date = EXCLUDED.created_date
        """, (company_id, year, threshold_percentage, tax_rate, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO bonus_tax_configs (company_id, year, bonus_threshold_percentage, bonus_tax_rate, created_date)
            VALUES (?, ?, ?, ?, ?)
        """, (company_id, year, threshold_percentage, tax_rate, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()


def get_employee_bonus(employee_id, year, month):
    """Get bonus for an employee for a specific month"""
    db = get_db()
    cursor = get_cursor(db)
    start_of_month, end_of_month = get_month_start_end(year, month)

    cursor.execute("""
        SELECT * FROM bonus_records 
        WHERE employee_id = ? 
          AND start_date <= ? 
          AND (end_date IS NULL OR end_date >= ?)
        ORDER BY start_date DESC LIMIT 1
    """, (employee_id, end_of_month, start_of_month))
    return dict_from_row(cursor.fetchone())


def get_all_employee_bonuses(employee_id):
    """Get all bonuses for an employee"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT * FROM bonus_records 
        WHERE employee_id = ? 
        ORDER BY start_date DESC
    """, (employee_id,))
    return rows_to_list(cursor.fetchall())


def set_employee_bonus(employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description):
    """Set employee bonus with date range"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        INSERT INTO bonus_records (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description, created_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description,
          datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()


def delete_employee_bonus(employee_id, start_date):
    """Delete a bonus entry by start_date"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        DELETE FROM bonus_records 
        WHERE employee_id = ? AND start_date = ?
    """, (employee_id, start_date))
    db.commit()


def calculate_bonus_tax(bonus_amount, annual_basic_salary, bonus_tax_config):
    """Calculate tax on bonus according to Ghana rules"""
    threshold_percentage = bonus_tax_config['bonus_threshold_percentage'] / 100
    threshold_amount = annual_basic_salary * threshold_percentage
    flat_tax_rate = bonus_tax_config['bonus_tax_rate'] / 100

    if bonus_amount <= threshold_amount:
        flat_tax = bonus_amount * flat_tax_rate
        excess_amount = 0
    else:
        flat_tax = threshold_amount * flat_tax_rate
        excess_amount = bonus_amount - threshold_amount

    return {
        'flat_tax_amount': flat_tax,
        'excess_amount': excess_amount,
        'threshold_amount': threshold_amount,
        'flat_rate': bonus_tax_config['bonus_tax_rate'],
        'threshold_percentage': bonus_tax_config['bonus_threshold_percentage']
    }


# ============================================
# BIK FUNCTIONS
# ============================================

def get_bik_definitions(company_id):
    """Get all BIK definitions for a company"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM bik_definitions WHERE company_id = ? ORDER BY id", (company_id,))
    return rows_to_list(cursor.fetchall())


def get_bik_definition(bik_id):
    """Get a BIK definition by ID"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM bik_definitions WHERE id = ?", (bik_id,))
    return dict_from_row(cursor.fetchone())


def get_employee_bik(employee_id, year, month):
    """Get all BIK for an employee active for a specific month"""
    db = get_db()
    cursor = get_cursor(db)
    start_of_month, end_of_month = get_month_start_end(year, month)

    cursor.execute("""
        SELECT eb.*, bd.name, bd.type, bd.default_value, bd.is_taxable
        FROM employee_bik eb
        JOIN bik_definitions bd ON eb.bik_id = bd.id
        WHERE eb.employee_id = ? 
          AND eb.start_date <= ? 
          AND (eb.end_date IS NULL OR eb.end_date >= ?)
    """, (employee_id, end_of_month, start_of_month))
    return rows_to_list(cursor.fetchall())


def get_employee_bik_dict(employee_id, year, month):
    """Get employee BIK as dictionary {bik_id: value}"""
    bik_list = get_employee_bik(employee_id, year, month)
    return {b['bik_id']: b['value'] for b in bik_list}


def calculate_employee_bik(employee_id, year, month):
    """Calculate total BIK for an employee for a specific month"""
    bik_list = get_employee_bik(employee_id, year, month)
    total = 0
    details = []
    for b in bik_list:
        value = b['value']
        total += value
        details.append({
            'name': b['name'],
            'value': value,
            'is_taxable': bool(b['is_taxable'])
        })
    return {'total': total, 'details': details}


def set_employee_bik(employee_id, bik_id, start_date, end_date, value):
    """Set employee BIK with a date range"""
    db = get_db()
    cursor = get_cursor(db)
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO employee_bik (employee_id, bik_id, start_date, end_date, value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, bik_id, start_date) 
            DO UPDATE SET end_date = EXCLUDED.end_date, value = EXCLUDED.value
        """, (employee_id, bik_id, start_date, end_date, value))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO employee_bik (employee_id, bik_id, start_date, end_date, value)
            VALUES (?, ?, ?, ?, ?)
        """, (employee_id, bik_id, start_date, end_date, value))
    db.commit()


# ============================================
# PAYROLL CALCULATION
# ============================================

def calculate_payroll(employee_id, period, year, month, tax_config=None):
    """Calculate complete payroll for an employee including allowances, deductions, bonus, and BIK"""
    employee = get_employee(employee_id)
    if not employee:
        return None

    company = get_company(employee['company_id'])
    if not company:
        return None

    if not tax_config:
        tax_config = get_active_tax_config(employee['company_id'])
        if not tax_config:
            tax_config = get_tax_config(employee['company_id'], year)

    if not tax_config:
        return None

    # Check exemptions
    is_tax_exempt = employee.get('is_tax_exempt', 0) == 1
    exempt_from_ss = employee.get('exempt_from_social_security', 0) == 1

    # Get monthly salary
    monthly_salary = get_employee_monthly_salary(employee_id, year, month)

    # Calculate allowances
    allowance_data = calculate_employee_allowances(employee_id, year, month)
    monthly_allowances = allowance_data['total']
    taxable_allowances = sum(
        detail['value'] for detail in allowance_data['details']
        if detail['is_taxable']
    )

    # Get bonus
    bonus_record = get_employee_bonus(employee_id, year, month)
    bonus_amount = bonus_record['bonus_amount'] if bonus_record else 0
    bonus_details = None
    bonus_tax_flat = 0
    bonus_excess = 0

    if bonus_amount > 0 and not is_tax_exempt:
        annual_basic = get_employee_annual_basic_salary(employee_id, year)
        bonus_tax_config = get_bonus_tax_config(employee['company_id'], year)
        bonus_calc = calculate_bonus_tax(bonus_amount, annual_basic, bonus_tax_config)
        bonus_tax_flat = bonus_calc['flat_tax_amount']
        bonus_excess = bonus_calc['excess_amount']
        bonus_details = {
            'amount': bonus_amount,
            'annual_basic_salary': annual_basic,
            'threshold_percentage': bonus_tax_config['bonus_threshold_percentage'],
            'threshold_amount': bonus_calc['threshold_amount'],
            'flat_rate': bonus_tax_config['bonus_tax_rate'],
            'flat_tax': bonus_tax_flat,
            'excess_amount': bonus_excess
        }

    # Calculate BIK
    bik_data = calculate_employee_bik(employee_id, year, month)
    monthly_bik = bik_data['total']
    taxable_bik = sum(
        detail['value'] for detail in bik_data['details']
        if detail['is_taxable']
    )

    # Cash salary = Salary + Allowances + Bonus
    cash_salary = monthly_salary + monthly_allowances + bonus_amount

    # Gross salary = Cash + BIK
    gross_salary = cash_salary + monthly_bik

    # Calculate deductions
    deduction_data = calculate_employee_deductions(employee_id, year, month, gross_salary)
    monthly_deductions = deduction_data['total']

    # Calculate Social Security
    if exempt_from_ss:
        social_security = 0
        monthly_threshold = 0
    else:
        monthly_threshold = get_social_security_threshold(employee['company_id'], year, month)
        ss_taxable_amount = min(monthly_salary, monthly_threshold)
        social_security = ss_taxable_amount * (tax_config['social_security_rate'] / 100)

    # Calculate tax
    if is_tax_exempt:
        annual_tax = 0
        monthly_tax = 0
        annual_taxable = 0
    else:
        monthly_taxable_income = monthly_salary + taxable_allowances + bonus_excess + taxable_bik - social_security
        annual_taxable = monthly_taxable_income * 12
        annual_tax = calculate_progressive_tax(annual_taxable, tax_config)
        monthly_tax = annual_tax / 12

    total_tax = monthly_tax + bonus_tax_flat
    total_deductions = total_tax + social_security + monthly_deductions
    net_pay = cash_salary - total_deductions

    return {
        'employee_id': employee_id,
        'company_id': employee['company_id'],
        'period': period,
        'year': year,
        'month': month,
        'base_salary': monthly_salary,
        'allowances_total': monthly_allowances,
        'allowance_details': allowance_data['details'],
        'bonus_amount': bonus_amount,
        'bonus_details': bonus_details,
        'bik_total': monthly_bik,
        'bik_details': bik_data['details'],
        'cash_salary': cash_salary,
        'deductions_total': monthly_deductions,
        'deduction_details': deduction_data['details'],
        'gross_salary': gross_salary,
        'annual_gross': (monthly_salary * 12) + (monthly_allowances * 12) + bonus_amount + (monthly_bik * 12),
        'annual_taxable': annual_taxable,
        'annual_tax': annual_tax,
        'monthly_tax': monthly_tax,
        'bonus_tax_flat': bonus_tax_flat,
        'total_tax': total_tax,
        'social_security': social_security,
        'social_security_threshold_applied': monthly_threshold,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'currency': company['base_currency'],
        'tax_year': tax_config['year'],
        'tax_config_id': tax_config['id'],
        'is_tax_exempt': is_tax_exempt,
        'exempt_from_social_security': exempt_from_ss
    }


# ============================================
# INVOICE FUNCTIONS
# ============================================

def generate_invoice_number(company_id):
    """Generate a unique invoice number"""
    db = get_db()
    cursor = get_cursor(db)

    company = get_company(company_id)
    prefix = company['name'][:3].upper() if company else 'INV'
    year = datetime.datetime.now().year

    cursor.execute("""
        SELECT invoice_number FROM consultant_invoices 
        WHERE company_id = ? AND invoice_number LIKE ?
        ORDER BY id DESC LIMIT 1
    """, (company_id, f'{prefix}-{year}-%'))

    result = cursor.fetchone()

    if result:
        parts = result['invoice_number'].split('-')
        seq = int(parts[2]) + 1 if len(parts) >= 3 and parts[2].isdigit() else 1
    else:
        seq = 1

    return f"{prefix}-{year}-{seq:04d}"


def get_invoice(invoice_id):
    """Get invoice by ID"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT i.*, 
               e.first_name, e.last_name, e.email, e.position,
               c.name as company_name, c.base_currency, c.address, c.tax_id
        FROM consultant_invoices i
        JOIN employees e ON i.employee_id = e.id
        JOIN companies c ON i.company_id = c.id
        WHERE i.id = ?
    """, (invoice_id,))

    invoice = dict_from_row(cursor.fetchone())

    if invoice:
        cursor.execute('SELECT * FROM invoice_items WHERE invoice_id = ?', (invoice_id,))
        invoice['items'] = rows_to_list(cursor.fetchall())

        cursor.execute('SELECT * FROM invoice_payments WHERE invoice_id = ? ORDER BY payment_date DESC', (invoice_id,))
        payments = rows_to_list(cursor.fetchall())
        invoice['payments'] = payments

        total_paid = sum(p['amount'] for p in payments)
        invoice['amount_paid'] = total_paid
        invoice['balance_due'] = (
                Decimal(str(invoice['final_amount'] or 0))
                - Decimal(str(total_paid or 0))
        )

        if invoice['balance_due'] <= 0 and invoice['status'] != 'Paid':
            cursor.execute('UPDATE consultant_invoices SET status = ? WHERE id = ?', ('Paid', invoice_id))
            db.commit()
            invoice['status'] = 'Paid'

    return invoice


def get_invoices_by_company(company_id, status=None):
    """Get all invoices for a company"""
    db = get_db()
    cursor = get_cursor(db)

    query = """
        SELECT i.*, 
               e.first_name, e.last_name, e.email, e.position,
               c.base_currency
        FROM consultant_invoices i
        JOIN employees e ON i.employee_id = e.id
        JOIN companies c ON i.company_id = c.id
        WHERE i.company_id = ?
    """
    params = [company_id]

    if status:
        query += ' AND i.status = ?'
        params.append(status)

    query += ' ORDER BY i.created_date DESC'

    cursor.execute(query, params)
    invoices = rows_to_list(cursor.fetchall())

    result = []
    for inv in invoices:
        cursor.execute('SELECT * FROM invoice_items WHERE invoice_id = ?', (inv['id'],))
        inv['items'] = rows_to_list(cursor.fetchall())

        cursor.execute('SELECT * FROM invoice_payments WHERE invoice_id = ?', (inv['id'],))
        payments = rows_to_list(cursor.fetchall())
        inv['payments'] = payments

        total_paid = sum(p['amount'] for p in payments)
        inv['amount_paid'] = total_paid
        inv['balance_due'] = inv['final_amount'] - total_paid

        result.append(inv)

    return result


def get_invoices_by_period(company_id, year, month):
    """Get all invoices for a specific period"""
    db = get_db()
    cursor = get_cursor(db)

    last_day = calendar.monthrange(year, month)[1]
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT i.*, e.first_name, e.last_name, e.position
        FROM consultant_invoices i
        JOIN employees e ON i.employee_id = e.id
        WHERE i.company_id = ? AND i.period_start = ? AND i.period_end = ?
        ORDER BY i.created_date DESC
    """, (company_id, period_start, period_end))

    return rows_to_list(cursor.fetchall())


def get_consultant_invoices(employee_id):
    """Get all invoices for a specific consultant"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT * FROM consultant_invoices 
        WHERE employee_id = ?
        ORDER BY created_date DESC
    """, (employee_id,))

    return rows_to_list(cursor.fetchall())


def create_invoice_from_payroll(company_id, employee_id, year, month, description=None, notes=None):
    """Create an invoice from payroll data for a consultant"""
    db = get_db()
    cursor = get_cursor(db)

    # Get the payroll record
    cursor.execute("""
        SELECT * FROM payroll_records 
        WHERE employee_id = ? AND year = ? AND month = ?
        ORDER BY id DESC LIMIT 1
    """, (employee_id, year, month))

    payroll = cursor.fetchone()

    if not payroll:
        return None

    # Check if invoice already exists
    last_day = calendar.monthrange(year, month)[1]
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT id FROM consultant_invoices 
        WHERE employee_id = ? AND period_start = ? AND period_end = ?
    """, (employee_id, period_start, period_end))

    existing = cursor.fetchone()
    if existing:
        return get_invoice(existing['id'])

    employee = get_employee(employee_id)
    if not employee:
        return None

    gross_salary = payroll['gross_salary']
    invoice_number = generate_invoice_number(company_id)

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    due_date = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime('%Y-%m-%d')
    invoice_date = datetime.datetime.now().strftime('%Y-%m-%d')

    # ✅ FIX: Use proper INSERT with RETURNING for PostgreSQL and lastrowid for SQLite
    if IS_PRODUCTION:
        cursor.execute("""
            INSERT INTO consultant_invoices (
                company_id, employee_id, invoice_number, invoice_date, due_date,
                period_start, period_end, description, hourly_rate, hours_worked,
                total_amount, tax_amount, discount_amount, final_amount, status,
                notes, created_date, updated_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            company_id,
            employee_id,
            invoice_number,
            invoice_date,
            due_date,
            period_start,
            period_end,
            description or f"Consulting services for {get_month_name(month)} {year}",
            0, 0,
            gross_salary,
            0, 0,
            gross_salary,
            'Sent',
            notes,
            now,
            now
        ))
        invoice_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO consultant_invoices (
                company_id, employee_id, invoice_number, invoice_date, due_date,
                period_start, period_end, description, hourly_rate, hours_worked,
                total_amount, tax_amount, discount_amount, final_amount, status,
                notes, created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id,
            employee_id,
            invoice_number,
            invoice_date,
            due_date,
            period_start,
            period_end,
            description or f"Consulting services for {get_month_name(month)} {year}",
            0, 0,
            gross_salary,
            0, 0,
            gross_salary,
            'Sent',
            notes,
            now,
            now
        ))
        invoice_id = cursor.lastrowid

    db.commit()

    return get_invoice(invoice_id)

def create_invoices_for_consultants(company_id, year, month):
    """Create invoices for all consultants for a specific period"""
    db = get_db()
    cursor = get_cursor(db)

    # Get all consultants
    cursor.execute("""
        SELECT * FROM employees 
        WHERE company_id = ? 
        AND (is_tax_exempt = 1 OR exempt_from_social_security = 1)
    """, (company_id,))

    consultants = rows_to_list(cursor.fetchall())

    created_invoices = []
    failed_employees = []

    for consultant in consultants:
        cursor.execute("""
            SELECT * FROM payroll_records 
            WHERE employee_id = ? AND year = ? AND month = ?
        """, (consultant['id'], year, month))

        payroll = cursor.fetchone()

        if payroll:
            invoice = create_invoice_from_payroll(company_id, consultant['id'], year, month)
            if invoice:
                created_invoices.append(invoice)
            else:
                failed_employees.append(consultant['id'])
        else:
            failed_employees.append(consultant['id'])

    return {
        'created': created_invoices,
        'failed': failed_employees,
        'total_consultants': len(consultants),
        'created_count': len(created_invoices),
        'failed_count': len(failed_employees)
    }


def update_invoice_status(invoice_id, status):
    """Update invoice status"""
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        UPDATE consultant_invoices 
        SET status = ?, updated_date = ?
        WHERE id = ?
    """, (status, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), invoice_id))
    db.commit()


def add_invoice_payment(invoice_id, amount, payment_method, reference=None, notes=None):
    """Add a payment to an invoice"""
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        INSERT INTO invoice_payments (invoice_id, payment_date, amount, payment_method, reference, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (invoice_id, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), amount, payment_method, reference, notes))

    db.commit()

    invoice = get_invoice(invoice_id)
    if invoice and invoice['balance_due'] <= 0:
        update_invoice_status(invoice_id, 'Paid')

    return invoice


# ============================================
# PDF GENERATION
# ============================================

def generate_payslip_pdf(employee_id, year, month):
    """Generate a PDF payslip for an employee"""
    payslip_data = generate_payslip_data(employee_id, year, month)
    if not payslip_data:
        return None

    employee = payslip_data['employee']
    company = payslip_data['company']
    payroll = payslip_data['payroll']
    allowance_details = payslip_data['allowance_details']
    deduction_details = payslip_data['deduction_details']
    bonus_details = payslip_data['bonus_details']
    bik_details = payslip_data['bik_details']
    ytd = payslip_data['ytd']

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=20
    )

    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7f8c8d'),
        alignment=TA_CENTER
    )

    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=15
    )

    bold_style = ParagraphStyle(
        'BoldStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold'
    )

    white_bold_style = ParagraphStyle(
        'WhiteBoldStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )

    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12
    )

    # Company Header
    story.append(Paragraph(f"<b>{company['name']}</b>", title_style))
    if company.get('address'):
        story.append(Paragraph(company['address'], header_style))
    if company.get('email'):
        story.append(Paragraph(f"Email: {company['email']} | Phone: {company.get('phone', 'N/A')}", header_style))
    story.append(Spacer(1, 5))
    story.append(Paragraph("<b>PAYSLIP</b>", styles['Heading1']))
    story.append(Paragraph(f"Period: {payslip_data['period']}", header_style))
    story.append(Spacer(1, 20))

    # Employee Information
    story.append(Paragraph("Employee Information", section_title_style))

    emp_data = [
        ['Employee Name:', f"{employee['first_name']} {employee['last_name']}"],
        ['Position:', employee['position']],
        ['Department:', employee['department']],
        ['Employee ID:', str(employee['id'])],
        ['Pay Period:', payslip_data['period']]
    ]

    emp_table = Table(emp_data, colWidths=[120, 300])
    emp_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#34495e')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 15))

    # Earnings Section
    story.append(Paragraph("Earnings", section_title_style))

    earnings_data = [
        ['Description', 'Amount'],
        ['Basic Salary', f"{company['base_currency']} {format_currency(payroll['base_salary'])}"]
    ]

    for detail in allowance_details:
        earnings_data.append([detail['name'], f"{company['base_currency']} {format_currency(detail['value'])}"])

    if payroll['bonus_amount'] > 0:
        earnings_data.append(['Bonus', f"{company['base_currency']} {format_currency(payroll['bonus_amount'])}"])

    if payroll['bik_total'] > 0:
        earnings_data.append(['BIK (Non-Cash)', f"{company['base_currency']} {format_currency(payroll['bik_total'])}"])

    earnings_data.append(['Total Earnings', f"{company['base_currency']} {format_currency(payroll['gross_salary'])}"])

    earnings_table = Table(earnings_data, colWidths=[300, 120])
    earnings_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#d4edda')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#155724')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    story.append(earnings_table)
    story.append(Spacer(1, 15))

    # Deductions Section
    story.append(Paragraph("Deductions", section_title_style))

    deductions_data = [['Description', 'Amount']]

    for detail in deduction_details:
        deductions_data.append([detail['name'], f"{company['base_currency']} {format_currency(detail['value'])}"])

    deductions_data.append(['Income Tax', f"{company['base_currency']} {format_currency(payroll['total_tax'])}"])

    if payroll['social_security'] > 0:
        deductions_data.append(['Social Security', f"{company['base_currency']} {format_currency(payroll['social_security'])}"])

    if payroll['bonus_tax_flat'] > 0:
        deductions_data.append(['Bonus Tax', f"{company['base_currency']} {format_currency(payroll['bonus_tax_flat'])}"])

    deductions_data.append(['Total Deductions', f"{company['base_currency']} {format_currency(payroll['total_deductions'])}"])

    deductions_table = Table(deductions_data, colWidths=[300, 120])
    deductions_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8d7da')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#721c24')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    story.append(deductions_table)
    story.append(Spacer(1, 15))

    # Net Pay Summary
    story.append(Paragraph("Net Pay Summary", section_title_style))

    net_data = [
        ['Total Earnings', f"{company['base_currency']} {format_currency(payroll['gross_salary'])}"],
        ['Total Deductions', f"{company['base_currency']} {format_currency(payroll['total_deductions'])}"],
        ['NET PAY', f"{company['base_currency']} {format_currency(payroll['net_pay'])}"]
    ]

    net_table = Table(net_data, colWidths=[300, 120])
    net_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#d4edda')),
        ('TEXTCOLOR', (0, -1), (1, -1), colors.HexColor('#155724')),
        ('FONTSIZE', (0, -1), (1, -1), 14),
        ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
    ]))
    story.append(net_table)
    story.append(Spacer(1, 15))

    # Year-to-Date Summary
    if ytd:
        story.append(Paragraph("Year-to-Date Summary", section_title_style))
        ytd_data = [
            ['Metric', 'Total'],
            ['Gross Pay', f"{company['base_currency']} {format_currency(ytd.get('total_gross', 0))}"],
            ['Tax', f"{company['base_currency']} {format_currency(ytd.get('total_tax', 0))}"],
            ['Social Security', f"{company['base_currency']} {format_currency(ytd.get('total_ss', 0))}"],
            ['Net Pay', f"{company['base_currency']} {format_currency(ytd.get('total_net', 0))}"]
        ]

        ytd_table = Table(ytd_data, colWidths=[300, 120])
        ytd_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))
        story.append(ytd_table)

    # Footer
    story.append(Spacer(1, 20))
    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#95a5a6'),
        alignment=TA_CENTER
    )
    story.append(Paragraph("This is a computer-generated payslip. Please verify all details.", footer_style))
    story.append(Paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_payslip_data(employee_id, year, month):
    """Generate payslip data for a specific employee and period"""
    employee = get_employee(employee_id)
    if not employee:
        return None

    company = get_company(employee['company_id'])
    if not company:
        return None

    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT * FROM payroll_records 
        WHERE employee_id = ? AND year = ? AND month = ?
        ORDER BY id DESC LIMIT 1
    """, (employee_id, year, month))
    payroll = cursor.fetchone()

    if not payroll:
        return None

    allowance_details = json.loads(payroll['allowance_details']) if payroll['allowance_details'] else []
    deduction_details = json.loads(payroll['deduction_details']) if payroll['deduction_details'] else []
    bonus_details = json.loads(payroll['bonus_details']) if payroll['bonus_details'] else None
    bik_details = json.loads(payroll['bik_details']) if payroll['bik_details'] else []
    tax_config = get_tax_config(company['id'], year)

    cursor.execute("""
        SELECT 
            SUM(gross_salary) as total_gross,
            SUM(total_tax) as total_tax,
            SUM(social_security) as total_ss,
            SUM(net_pay) as total_net,
            SUM(allowances_total) as total_allowances,
            SUM(deductions_total) as total_deductions,
            SUM(bonus_amount) as total_bonus
        FROM payroll_records 
        WHERE employee_id = ? AND year = ? AND month <= ?
    """, (employee_id, year, month))
    ytd = cursor.fetchone()

    return {
        'employee': employee,
        'company': company,
        'payroll': dict_from_row(payroll),
        'allowance_details': allowance_details,
        'deduction_details': deduction_details,
        'bonus_details': bonus_details,
        'bik_details': bik_details,
        'tax_config': dict_from_row(tax_config) if tax_config else None,
        'ytd': dict_from_row(ytd) if ytd else None,
        'year': year,
        'month': month,
        'period': f"{get_month_name(month)} {year}"
    }


def generate_invoice_pdf(invoice_id):
    """Generate a PDF invoice for a consultant with allowances and deductions"""
    invoice = get_invoice(invoice_id)
    if not invoice:
        return None

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=20
    )

    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7f8c8d')
    )

    bold_style = ParagraphStyle(
        'BoldStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold'
    )

    white_bold_style = ParagraphStyle(
        'WhiteBoldStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )

    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12
    )

    # Get employee and payroll data
    employee = get_employee(invoice['employee_id'])
    employee_dict = dict_from_row(employee) if employee else None

    # Get payroll record
    db = get_db()
    cursor = get_cursor(db)
    year = int(invoice['period_start'][:4])
    month = int(invoice['period_start'][5:7])

    cursor.execute("""
        SELECT * FROM payroll_records 
        WHERE employee_id = ? AND year = ? AND month = ?
        ORDER BY id DESC LIMIT 1
    """, (invoice['employee_id'], year, month))
    payroll = cursor.fetchone()
    payroll_dict = dict_from_row(payroll) if payroll else None

    allowance_details = json.loads(payroll_dict['allowance_details']) if payroll_dict and payroll_dict.get(
        'allowance_details') else []
    deduction_details = json.loads(payroll_dict['deduction_details']) if payroll_dict and payroll_dict.get(
        'deduction_details') else []

    # Build consultant name - try multiple sources
    consultant_full_name = f"{invoice.get('first_name', '')} {invoice.get('last_name', '')}".strip()
    if not consultant_full_name and employee_dict:
        consultant_full_name = f"{employee_dict.get('first_name', '')} {employee_dict.get('last_name', '')}".strip()
    if not consultant_full_name:
        consultant_full_name = f"Consultant #{invoice['employee_id']}"

    # Get consultant position
    consultant_position_text = invoice.get('position', '')
    if not consultant_position_text and employee_dict:
        consultant_position_text = employee_dict.get('position', '')

    # Invoice Header with Consultant Name prominently displayed
    story.append(Paragraph("INVOICE", title_style))

    # Consultant Name - prominently displayed
    consultant_title_style = ParagraphStyle(
        'ConsultantTitle',
        parent=styles['Heading2'],
        fontSize=20,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=5,
        fontName='Helvetica-Bold'
    )
    story.append(Paragraph(consultant_full_name, consultant_title_style))
    if consultant_position_text:
        story.append(Paragraph(f"<i>{consultant_position_text}</i>", header_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Invoice #: {invoice['invoice_number']}", header_style))
    story.append(Paragraph(f"Date: {invoice['invoice_date']}", header_style))
    story.append(Spacer(1, 20))

    # Company and Consultant Info Table
    consultant_name_para = Paragraph(f"<b>{consultant_full_name}</b>", bold_style)
    consultant_position = Paragraph(consultant_position_text, cell_style)

    consultant_details = [consultant_name_para, consultant_position]
    if employee_dict:
        id_type = employee_dict.get('id_type')
        id_number = employee_dict.get('id_number')
        if id_type and id_number:
            consultant_details.append(Paragraph(f"ID: {id_type} - {id_number}", cell_style))
        street_location = employee_dict.get('street_location')
        if street_location:
            consultant_details.append(Paragraph(f"Location: {street_location}", cell_style))

    company_name = Paragraph(f"<b>{invoice['company_name']}</b>", bold_style)
    company_address = Paragraph(invoice.get('address', ''), cell_style)

    company_details = [company_name, company_address]
    if invoice.get('phone'):
        company_details.append(Paragraph(f"Phone: {invoice.get('phone', '')}", cell_style))

    # Build the info table
    info_data = [
        [Paragraph('<b>Consultant:</b>', bold_style), Paragraph('<b>Company:</b>', bold_style)],
    ]

    # Create consultant rows with name first
    consultant_rows = []
    # Add name as first row
    consultant_rows.append([consultant_name_para, ''])
    # Add position and other details
    for item in consultant_details[1:]:  # Skip the name since we already added it
        consultant_rows.append([item, ''])

    # Fill in company details
    for i, item in enumerate(company_details):
        if i < len(consultant_rows):
            consultant_rows[i][1] = item
        else:
            consultant_rows.append(['', item])

    max_rows = max(len(consultant_details), len(company_details))
    while len(consultant_rows) < max_rows:
        consultant_rows.append(['', ''])

    for row in consultant_rows:
        info_data.append(row)

    info_table = Table(info_data, colWidths=[250, 250])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))

    # Combined Invoice Table
    month_name = get_month_name(int(invoice['period_start'][5:7]))
    year_val = int(invoice['period_start'][:4])
    consulting_period = f"{month_name} {year_val}"

    invoice_data = [
        [Paragraph('<b>Description</b>', white_bold_style), Paragraph('<b>Amount</b>', white_bold_style)]
    ]

    # Consulting Services (Base Salary)
    if payroll_dict:
        desc = Paragraph(f'Consulting services for {consulting_period}', cell_style)
        amount = Paragraph(f"{invoice['base_currency']} {format_currency(payroll_dict.get('base_salary', 0))}",
                           cell_style)
        invoice_data.append([desc, amount])

    # Allowances
    for detail in allowance_details:
        desc = Paragraph(detail.get('name', 'Allowance'), cell_style)
        amount = Paragraph(f"{invoice['base_currency']} {format_currency(detail.get('value', 0))}", cell_style)
        invoice_data.append([desc, amount])

    # Bonus
    if payroll_dict and payroll_dict.get('bonus_amount', 0) > 0:
        desc = Paragraph('Bonus', cell_style)
        amount = Paragraph(f"{invoice['base_currency']} {format_currency(payroll_dict.get('bonus_amount', 0))}",
                           cell_style)
        invoice_data.append([desc, amount])

    # BIK
    if payroll_dict and payroll_dict.get('bik_total', 0) > 0:
        desc = Paragraph('BIK (Non-Cash)', cell_style)
        amount = Paragraph(f"{invoice['base_currency']} {format_currency(payroll_dict.get('bik_total', 0))}",
                           cell_style)
        invoice_data.append([desc, amount])

    # Spacer
    if deduction_details or payroll_dict:
        invoice_data.append([Paragraph('', cell_style), Paragraph('', cell_style)])

    # Deductions
    for detail in deduction_details:
        desc = Paragraph(detail.get('name', 'Deduction'), cell_style)
        amount = Paragraph(f"({invoice['base_currency']} {format_currency(detail.get('value', 0))})", cell_style)
        invoice_data.append([desc, amount])

    # Income Tax
    if payroll_dict and payroll_dict.get('total_tax', 0) > 0:
        desc = Paragraph('Income Tax', cell_style)
        amount = Paragraph(f"({invoice['base_currency']} {format_currency(payroll_dict.get('total_tax', 0))})",
                           cell_style)
        invoice_data.append([desc, amount])

    # Social Security
    if payroll_dict and payroll_dict.get('social_security', 0) > 0:
        desc = Paragraph('Social Security', cell_style)
        amount = Paragraph(f"({invoice['base_currency']} {format_currency(payroll_dict.get('social_security', 0))})",
                           cell_style)
        invoice_data.append([desc, amount])

    # Bonus Tax
    if payroll_dict and payroll_dict.get('bonus_tax_flat', 0) > 0:
        desc = Paragraph('Bonus Tax', cell_style)
        amount = Paragraph(f"({invoice['base_currency']} {format_currency(payroll_dict.get('bonus_tax_flat', 0))})",
                           cell_style)
        invoice_data.append([desc, amount])

    # Spacer before Net Amount
    invoice_data.append([Paragraph('', cell_style), Paragraph('', cell_style)])

    # Net Amount
    if payroll_dict:
        gross_salary = payroll_dict.get('gross_salary', 0)
        total_deductions = payroll_dict.get('total_deductions', 0)
        net_amount = gross_salary - total_deductions

        desc = Paragraph('<b>Net Amount</b>', bold_style)
        amount = Paragraph(f"<b>{invoice['base_currency']} {format_currency(net_amount)}</b>", bold_style)
        invoice_data.append([desc, amount])

    # Create the table
    invoice_table = Table(invoice_data, colWidths=[300, 120])
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TEXTCOLOR', (1, 5), (1, -3), colors.HexColor('#e74c3c')),
        ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#d4edda')),
        ('TEXTCOLOR', (0, -1), (1, -1), colors.HexColor('#155724')),
        ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (1, -1), 12),
    ]))
    story.append(invoice_table)

    # Footer with bank details
    if employee_dict:
        story.append(Spacer(1, 20))
        footer_parts = ["Payment Instructions:"]

        if employee_dict.get('bank_name'):
            footer_parts.append(f"Bank: {employee_dict['bank_name']}")
        if employee_dict.get('bank_account_name'):
            footer_parts.append(f"Account Name: {employee_dict['bank_account_name']}")
        if employee_dict.get('bank_account_number'):
            footer_parts.append(f"Account Number: {employee_dict['bank_account_number']}")
        if employee_dict.get('bank_swift_code'):
            footer_parts.append(f"SWIFT Code: {employee_dict['bank_swift_code']}")
        if employee_dict.get('bank_iban') and employee_dict['bank_iban'] != 'None':
            footer_parts.append(f"IBAN: {employee_dict['bank_iban']}")
        if employee_dict.get('bank_address'):
            footer_parts.append(f"Bank Address: {employee_dict['bank_address']}")

        if len(footer_parts) > 1:
            footer_style = ParagraphStyle(
                'FooterStyle',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#34495e'),
                alignment=TA_CENTER,
                spaceAfter=5
            )
            story.append(Paragraph(" | ".join(footer_parts), footer_style))

            thanks_style = ParagraphStyle(
                'ThanksStyle',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#7f8c8d'),
                alignment=TA_CENTER,
                spaceAfter=5
            )
            story.append(Paragraph("Thank you for your business!", thanks_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_bulk_payslip_pdf(company_id, year, month):
    """Generate bulk payslips for all employees in a period"""
    employees = get_employees_by_company(company_id)
    payslip_buffers = []

    for emp in employees:
        buffer = generate_payslip_pdf(emp['id'], year, month)
        if buffer:
            payslip_buffers.append({
                'employee': emp,
                'buffer': buffer
            })

    return payslip_buffers


# ============================================
# SAMPLE DATA
# ============================================

def init_sample_data():
    """Initialize sample data if database is empty"""
    db = get_db()
    cursor = get_cursor(db)

    # Check if companies already exist
    cursor.execute("SELECT COUNT(*) as count FROM companies")
    row = cursor.fetchone()
    count = row['count'] if row else 0

    if count > 0:
        print(f"📊 Database already has {count} companies, skipping sample data")
        return

    # Insert Companies
    companies = [
        (1, 'Tech Solutions Inc.', 'USD', '123 Tech Park, Silicon Valley, CA', 'TAX-78945',
         'hr@techsolutions.com', '+1 (555) 123-4567', '2024-01-01'),
        (2, 'Global Innovations Ltd.', 'EUR', '456 Innovation Hub, Berlin, Germany', 'TAX-45678',
         'hr@globalinnovations.com', '+49 30 1234567', '2023-06-15'),
        (3, 'Ghana Tech Solutions', 'GHS', '123 Accra Mall, Accra, Ghana', 'TAX-GH-12345',
         'hr@ghanatech.com', '+233 24 123 4567', '2024-01-01')
    ]

    for comp in companies:
        cursor.execute("""
            INSERT INTO companies (id, name, base_currency, address, tax_id, email, phone, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, comp)

    # Insert Employees
    employees = [
        (1, 1, 'John', 'Doe', 'john.doe@techsolutions.com', 'Senior Developer', 'Engineering', 6250.00, '2023-01-15', 'Active', 0, 0),
        (2, 1, 'Jane', 'Smith', 'jane.smith@techsolutions.com', 'Project Manager', 'Management', 7083.33, '2023-03-01', 'Active', 0, 0),
        (3, 1, 'Robert', 'Johnson', 'robert.johnson@techsolutions.com', 'Data Analyst', 'Analytics', 5416.67, '2024-01-10', 'Active', 0, 0),
        (4, 2, 'Maria', 'Garcia', 'maria.garcia@globalinnovations.com', 'Marketing Director', 'Marketing', 7666.67, '2023-07-01', 'Active', 0, 0),
        (5, 2, 'Hans', 'Muller', 'hans.muller@globalinnovations.com', 'Software Architect', 'Engineering', 7333.33, '2023-08-15', 'Active', 0, 0),
        (6, 3, 'Kwame', 'Mensah', 'kwame.mensah@ghanatech.com', 'Software Engineer', 'Engineering', 10000.00, '2024-01-15', 'Active', 0, 0),
        (7, 3, 'Ama', 'Asare', 'ama.asare@ghanatech.com', 'Project Manager', 'Management', 12500.00, '2024-02-01', 'Active', 0, 0),
        (8, 3, 'Yaw', 'Osei', 'yaw.osei@ghanatech.com', 'Data Analyst', 'Analytics', 8000.00, '2024-03-10', 'Active', 0, 0),
        (9, 3, 'Kofi', 'Adjei', 'kofi.adjei@ghanatech.com', 'Consultant', 'Consulting', 15000.00, '2024-06-01', 'Consultant', 1, 1)
    ]

    for emp in employees:
        cursor.execute("""
            INSERT INTO employees (id, company_id, first_name, last_name, email, position, department,
                                   base_salary, hire_date, status, is_tax_exempt, exempt_from_social_security)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, emp)

    # Insert Bonus Records
    bonuses = [
        (1, 1, '2024-12-01', '2024-12-31', 5000.00, 'annual', 'Annual Performance Bonus', '2024-12-20'),
        (2, 1, '2024-12-01', '2024-12-31', 7500.00, 'annual', 'Annual Performance Bonus', '2024-12-20'),
        (6, 3, '2024-12-01', '2024-12-31', 3000.00, 'christmas', 'Christmas Bonus', '2024-12-20')
    ]

    for bonus in bonuses:
        cursor.execute("""
            INSERT INTO bonus_records (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, bonus)

    # Insert Bonus Tax Configs
    for company_id in [1, 2, 3]:
        cursor.execute("""
            INSERT INTO bonus_tax_configs (company_id, year, bonus_threshold_percentage, bonus_tax_rate, created_date)
            VALUES (?, 2024, 15.0, 5.0, '2024-01-01')
        """, (company_id,))

    # Insert BIK Definitions
    bik_defs = [
        (1, 1, 'Company Car', 'fixed', 500.00, 1, 'Monthly company car benefit', '2024-01-01'),
        (2, 1, 'Housing', 'fixed', 800.00, 1, 'Monthly housing benefit', '2024-01-01'),
        (3, 1, 'Medical Insurance', 'fixed', 200.00, 0, 'Monthly medical insurance benefit (non-taxable)', '2024-01-01'),
        (4, 2, 'Company Car', 'fixed', 400.00, 1, 'Monthly company car benefit', '2023-06-15'),
        (5, 2, 'Housing', 'fixed', 600.00, 1, 'Monthly housing benefit', '2023-06-15'),
        (6, 3, 'Company Car', 'fixed', 1000.00, 1, 'Monthly company car benefit in GHS', '2024-01-01'),
        (7, 3, 'Housing', 'fixed', 1500.00, 1, 'Monthly housing benefit in GHS', '2024-01-01'),
        (8, 3, 'Medical Insurance', 'fixed', 300.00, 0, 'Monthly medical insurance benefit (non-taxable) in GHS', '2024-01-01')
    ]

    for bik in bik_defs:
        cursor.execute("""
            INSERT INTO bik_definitions (id, company_id, name, type, default_value, is_taxable, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, bik)

    # Insert Employee BIK
    employee_biks = [
        (1, 1, '2024-01-01', '2024-12-31', 500.00),
        (1, 2, '2024-01-01', '2024-12-31', 800.00),
        (1, 3, '2024-01-01', '2024-12-31', 200.00),
        (2, 1, '2024-01-01', '2024-12-31', 600.00),
        (2, 2, '2024-01-01', '2024-12-31', 900.00),
        (2, 3, '2024-01-01', '2024-12-31', 200.00),
        (6, 6, '2024-01-01', '2024-12-31', 1000.00),
        (6, 7, '2024-01-01', '2024-12-31', 1500.00),
        (6, 8, '2024-01-01', '2024-12-31', 300.00)
    ]

    for eb in employee_biks:
        cursor.execute("""
            INSERT INTO employee_bik (employee_id, bik_id, start_date, end_date, value)
            VALUES (?, ?, ?, ?, ?)
        """, eb)

    # Insert Deduction Definitions
    deduction_defs = [
        (1, 1, 'Union Dues', 'fixed', 50.00, 0, 'Monthly union membership dues', '2024-01-01'),
        (2, 1, 'Pension Contribution', 'percentage', 5.00, 1, 'Employee pension contribution', '2024-01-01'),
        (3, 1, 'Health Insurance', 'fixed', 120.00, 0, 'Monthly health insurance premium', '2024-01-01'),
        (4, 2, 'Union Dues', 'fixed', 40.00, 0, 'Monthly union membership dues', '2023-06-15'),
        (5, 2, 'Pension Contribution', 'percentage', 4.00, 1, 'Employee pension contribution', '2023-06-15'),
        (6, 3, 'Union Dues', 'fixed', 100.00, 0, 'Monthly union membership dues in GHS', '2024-01-01'),
        (7, 3, 'Pension Contribution', 'percentage', 5.00, 1, 'Employee pension contribution', '2024-01-01'),
        (8, 3, 'Health Insurance', 'fixed', 250.00, 0, 'Monthly health insurance premium in GHS', '2024-01-01')
    ]

    for dd in deduction_defs:
        cursor.execute("""
            INSERT INTO deduction_definitions (id, company_id, name, type, default_value, is_percentage, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, dd)

    # Insert Employee Deductions
    employee_deds = [
        (1, 1, '2024-01-01', '2024-12-31', 50.00),
        (1, 2, '2024-01-01', '2024-12-31', 5.00),
        (1, 3, '2024-01-01', '2024-12-31', 120.00),
        (2, 1, '2024-01-01', '2024-12-31', 50.00),
        (2, 2, '2024-01-01', '2024-12-31', 5.00),
        (2, 3, '2024-01-01', '2024-12-31', 120.00)
    ]

    for ed in employee_deds:
        cursor.execute("""
            INSERT INTO employee_deductions (employee_id, deduction_id, start_date, end_date, value)
            VALUES (?, ?, ?, ?, ?)
        """, ed)

    # Insert Allowance Definitions
    allowance_defs = [
        (1, 1, 'Housing Allowance', 'fixed', 500.00, 0, 'Monthly housing allowance', '2024-01-01'),
        (2, 1, 'Transport Allowance', 'fixed', 200.00, 1, 'Monthly transport allowance', '2024-01-01'),
        (3, 1, 'Meal Allowance', 'fixed', 150.00, 1, 'Monthly meal allowance', '2024-01-01'),
        (4, 2, 'Housing Allowance', 'fixed', 400.00, 0, 'Monthly housing allowance', '2023-06-15'),
        (5, 2, 'Transport Allowance', 'fixed', 150.00, 1, 'Monthly transport allowance', '2023-06-15'),
        (6, 3, 'Housing Allowance', 'fixed', 1000.00, 0, 'Monthly housing allowance in GHS', '2024-01-01'),
        (7, 3, 'Transport Allowance', 'fixed', 500.00, 1, 'Monthly transport allowance in GHS', '2024-01-01'),
        (8, 3, 'Meal Allowance', 'fixed', 300.00, 1, 'Monthly meal allowance in GHS', '2024-01-01')
    ]

    for ad in allowance_defs:
        cursor.execute("""
            INSERT INTO allowance_definitions (id, company_id, name, type, default_value, is_taxable, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ad)

    # Insert Employee Allowances
    employee_allowances = [
        (1, 1, 600.00), (1, 2, 200.00), (1, 3, 150.00),
        (2, 1, 700.00), (2, 2, 250.00), (2, 3, 180.00),
        (3, 1, 500.00), (3, 2, 200.00), (3, 3, 150.00),
        (4, 4, 450.00), (4, 5, 180.00),
        (5, 4, 400.00), (5, 5, 150.00),
        (6, 6, 1200.00), (6, 7, 500.00), (6, 8, 300.00),
        (7, 6, 1500.00), (7, 7, 600.00), (7, 8, 350.00),
        (8, 6, 1000.00), (8, 7, 500.00), (8, 8, 300.00)
    ]

    for ea in employee_allowances:
        cursor.execute("""
            INSERT INTO employee_allowances (employee_id, allowance_id, value)
            VALUES (?, ?, ?)
        """, ea)

    # Insert Monthly Salaries
    monthly_salaries = [(1, 2024, 2, 6500.00), (2, 2024, 3, 7333.33)]
    for ms in monthly_salaries:
        cursor.execute("""
            INSERT INTO monthly_salaries (employee_id, year, month, salary)
            VALUES (?, ?, ?, ?)
        """, ms)

    # Insert Tax Configs
    tax_config_id = 0
    for company_id in [1, 2, 3]:
        for year in [2023, 2024, 2025]:
            tax_config_id += 1
            rates = get_default_tax_rates(year)
            brackets_json = json.dumps(rates['brackets'])
            is_active = 1 if year == 2024 else 0

            if company_id == 3:
                standard_deduction = 0
            else:
                standard_deduction = rates['standard_deduction'] if company_id == 1 else rates['standard_deduction'] * 0.9

            cursor.execute("""
                INSERT INTO tax_configs (id, company_id, year, country, standard_deduction,
                                         social_security_rate, social_security_threshold, brackets, is_active, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tax_config_id, company_id, year,
                'USA' if company_id == 1 else 'Germany' if company_id == 2 else 'Ghana',
                standard_deduction,
                rates['social_security_rate'] if company_id == 1 else rates['social_security_rate'] * 0.8 if company_id == 2 else 5.5,
                rates['social_security_threshold'] if company_id == 1 else rates['social_security_threshold'] * 0.9 if company_id == 2 else rates['social_security_threshold'] * 2.5,
                brackets_json, is_active, datetime.datetime.now().strftime('%Y-%m-%d')
            ))

    db.commit()
    print("✅ Sample data inserted successfully")

# ============================================
# COMPANY SWITCHER CONTEXT PROCESSOR
# ============================================

@app.context_processor
def inject_company_switcher():
    """Make company switcher and all helper functions available in all templates"""
    def get_all_companies_ctx():
        return get_all_companies()

    def get_current_company_ctx():
        company_id = session.get('current_company_id')
        if company_id:
            company = get_company(company_id)
            if company:
                return company
        companies = get_all_companies()
        if companies:
            first_company = companies[0]
            session['current_company_id'] = first_company['id']
            return first_company
        return None

    def get_month_name_ctx(month_num):
        return get_month_name(month_num)

    def get_available_months_ctx():
        return list(range(1, 13))

    def format_currency_ctx(value):
        return format_currency(value)

    def get_all_employee_bonuses_ctx(employee_id):
        return get_all_employee_bonuses(employee_id)

    def get_current_year_ctx():
        return datetime.datetime.now().year

    def is_date_active_ctx(start_date, end_date, year, month):
        return is_date_active(start_date, end_date, year, month)

    def get_employee_annual_basic_salary_ctx(employee_id, year):
        return get_employee_annual_basic_salary(employee_id, year)

    def get_employee_ctx(employee_id):
        return get_employee(employee_id)

    def get_payroll_by_month_ctx(company_id, year, month):
        return get_payroll_by_month(company_id, year, month)

    def payslips_dashboard_url_ctx(company_id):
        return url_for('payslips_dashboard', company_id=company_id)

    def bulk_payslip_url_ctx(company_id, year=None, month=None):
        if year and month:
            return url_for('bulk_payslip', company_id=company_id, year=year, month=month)
        return url_for('bulk_payslip', company_id=company_id)

    def view_payslip_url_ctx(employee_id, year=None, month=None):
        if year and month:
            return url_for('view_payslip', employee_id=employee_id, year=year, month=month)
        return url_for('view_payslip', employee_id=employee_id)

    def download_payslip_url_ctx(employee_id, year=None, month=None):
        if year and month:
            return url_for('download_payslip', employee_id=employee_id, year=year, month=month)
        return url_for('download_payslip', employee_id=employee_id)

    def get_employee_payroll_ctx(employee_id, year, month):
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            SELECT * FROM payroll_records 
            WHERE employee_id = ? AND year = ? AND month = ?
            ORDER BY id DESC LIMIT 1
        """, (employee_id, year, month))
        return dict_from_row(cursor.fetchone())

    def get_employee_payslip_status_ctx(employee_id, year, month):
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            SELECT COUNT(*) as count FROM payroll_records 
            WHERE employee_id = ? AND year = ? AND month = ?
        """, (employee_id, year, month))
        result = cursor.fetchone()
        return result['count'] > 0 if result else False

    def get_available_years_for_company_ctx(company_id):
        configs = get_tax_configs_by_company(company_id)
        return [c['year'] for c in configs]

    def get_processed_months_for_company_ctx(company_id):
        return get_processed_months(company_id)

    def get_employee_count_ctx(company_id):
        employees = get_employees_by_company(company_id)
        return len(employees)

    def get_total_net_pay_ctx(company_id, year, month):
        records = get_payroll_by_month(company_id, year, month)
        return sum(rec['net_pay'] for rec in records)

    def get_total_gross_pay_ctx(company_id, year, month):
        records = get_payroll_by_month(company_id, year, month)
        return sum(rec['gross_salary'] for rec in records)

    def get_total_tax_ctx(company_id, year, month):
        records = get_payroll_by_month(company_id, year, month)
        return sum(rec['total_tax'] for rec in records)

    def format_datetime_ctx(value, format='%Y-%m-%d %H:%M'):
        if value is None:
            return ''
        if isinstance(value, str):
            try:
                value = datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except:
                try:
                    value = datetime.datetime.strptime(value, '%Y-%m-%d')
                except:
                    return value
        return value.strftime(format)

    def get_exempt_employees_count_ctx(company_id):
        employees = get_employees_by_company(company_id)
        return sum(1 for emp in employees if emp.get('is_tax_exempt', 0) == 1)

    def get_ss_exempt_employees_count_ctx(company_id):
        employees = get_employees_by_company(company_id)
        return sum(1 for emp in employees if emp.get('exempt_from_social_security', 0) == 1)

    def get_invoice_ctx(invoice_id):
        return get_invoice(invoice_id)

    def get_invoices_by_company_ctx(company_id, status=None):
        return get_invoices_by_company(company_id, status)

    def invoice_dashboard_url_ctx(company_id):
        return url_for('invoice_dashboard', company_id=company_id)

    def create_invoice_url_ctx(company_id):
        return url_for('create_invoice', company_id=company_id)

    def view_invoice_url_ctx(invoice_id):
        return url_for('view_invoice', invoice_id=invoice_id)

    def download_invoice_url_ctx(invoice_id):
        return url_for('download_invoice', invoice_id=invoice_id)

    return {
        'all_companies': get_all_companies_ctx(),
        'current_company': get_current_company_ctx(),
        'company_count': len(get_all_companies()),
        'get_month_name': get_month_name_ctx,
        'get_available_months': get_available_months_ctx,
        'format_currency': format_currency_ctx,
        'current_year': get_current_year_ctx(),
        'datetime': datetime.datetime,
        'get_all_employee_bonuses': get_all_employee_bonuses_ctx,
        'get_employee_annual_basic_salary': get_employee_annual_basic_salary_ctx,
        'is_date_active': is_date_active_ctx,
        'get_employee': get_employee_ctx,
        'get_payroll_by_month': get_payroll_by_month_ctx,
        'get_employee_payroll': get_employee_payroll_ctx,
        'get_employee_payslip_status': get_employee_payslip_status_ctx,
        'get_available_years': get_available_years_for_company_ctx,
        'get_processed_months': get_processed_months_for_company_ctx,
        'get_employee_count': get_employee_count_ctx,
        'get_total_net_pay': get_total_net_pay_ctx,
        'get_total_gross_pay': get_total_gross_pay_ctx,
        'get_total_tax': get_total_tax_ctx,
        'get_exempt_employees_count': get_exempt_employees_count_ctx,
        'get_ss_exempt_employees_count': get_ss_exempt_employees_count_ctx,
        'payslips_dashboard_url': payslips_dashboard_url_ctx,
        'bulk_payslip_url': bulk_payslip_url_ctx,
        'view_payslip_url': view_payslip_url_ctx,
        'download_payslip_url': download_payslip_url_ctx,
        'get_invoice': get_invoice_ctx,
        'get_invoices_by_company': get_invoices_by_company_ctx,
        'invoice_dashboard_url': invoice_dashboard_url_ctx,
        'create_invoice_url': create_invoice_url_ctx,
        'view_invoice_url': view_invoice_url_ctx,
        'download_invoice_url': download_invoice_url_ctx,
        'format_datetime': format_datetime_ctx,
        'now': datetime.datetime.now()
    }


# ============================================
# ROUTES - Company Management
# ============================================

@app.route('/')
def index():
    companies = get_all_companies()
    employees = get_all_employees()
    payroll_records = get_all_payroll_records()
    tax_configs = get_all_tax_configs()

    return render_template('index.html',
                           companies=companies,
                           employees=employees,
                           payroll_records=payroll_records,
                           tax_configs=tax_configs)


@app.route('/switch_company/<int:company_id>')
def switch_company(company_id):
    """Switch to a different company"""
    company = get_company(company_id)
    if company:
        session['current_company_id'] = company_id
        flash(f'Switched to {company["name"]}', 'success')
    else:
        flash('Company not found!', 'error')

    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    return redirect(url_for('index'))


@app.route('/companies')
def list_companies():
    companies = get_all_companies()
    return render_template('companies.html', companies=companies)


@app.route('/companies/add', methods=['GET', 'POST'])
def add_company():
    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        # Check if code column exists
        if IS_PRODUCTION:
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='companies' AND column_name='code'
            """)
            has_code_column = cursor.fetchone() is not None
        else:
            cursor.execute("PRAGMA table_info(companies)")
            columns = [col[1] for col in cursor.fetchall()]
            has_code_column = 'code' in columns

        # Insert company with or without code
        if has_code_column:
            # Generate optional code from name
            company_name = request.form['name']
            company_code = ''.join(word[0].upper() for word in company_name.split())[:10]
            if not company_code:
                company_code = company_name[:10].upper()

            if IS_PRODUCTION:
                cursor.execute("""
                    INSERT INTO companies (name, code, base_currency, address, tax_id, email, phone, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    request.form['name'],
                    company_code,
                    request.form['base_currency'],
                    request.form.get('address', ''),
                    request.form.get('tax_id', ''),
                    request.form.get('email', ''),
                    request.form.get('phone', ''),
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))
                company_id = cursor.fetchone()[0]
            else:
                cursor.execute("""
                    INSERT INTO companies (name, code, base_currency, address, tax_id, email, phone, created_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    request.form['name'],
                    company_code,
                    request.form['base_currency'],
                    request.form.get('address', ''),
                    request.form.get('tax_id', ''),
                    request.form.get('email', ''),
                    request.form.get('phone', ''),
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))
                company_id = cursor.lastrowid
        else:
            # Insert without code column
            if IS_PRODUCTION:
                cursor.execute("""
                    INSERT INTO companies (name, base_currency, address, tax_id, email, phone, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    request.form['name'],
                    request.form['base_currency'],
                    request.form.get('address', ''),
                    request.form.get('tax_id', ''),
                    request.form.get('email', ''),
                    request.form.get('phone', ''),
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))
                company_id = cursor.fetchone()[0]
            else:
                cursor.execute("""
                    INSERT INTO companies (name, base_currency, address, tax_id, email, phone, created_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    request.form['name'],
                    request.form['base_currency'],
                    request.form.get('address', ''),
                    request.form.get('tax_id', ''),
                    request.form.get('email', ''),
                    request.form.get('phone', ''),
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))
                company_id = cursor.lastrowid

        db.commit()

        if not company_id:
            raise Exception("Failed to get company ID")

        # Create tax configurations (existing code)
        current_year = datetime.datetime.now().year
        is_ghana = request.form['base_currency'] == 'GHS'

        for year in [current_year - 1, current_year, current_year + 1]:
            rates = get_default_tax_rates(year)
            brackets_json = json.dumps(rates['brackets'])
            standard_deduction = 0 if is_ghana else rates['standard_deduction'] * 2.5

            if IS_PRODUCTION:
                cursor.execute("""
                    INSERT INTO tax_configs (company_id, year, country, standard_deduction,
                                             social_security_rate, social_security_threshold, brackets, is_active, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    company_id,
                    year,
                    'Ghana' if is_ghana else 'USA',
                    standard_deduction,
                    rates['social_security_rate'] * 0.887 if is_ghana else rates['social_security_rate'],
                    rates['social_security_threshold'] * 2.5,
                    brackets_json,
                    1 if year == current_year else 0,
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))
            else:
                cursor.execute("""
                    INSERT INTO tax_configs (company_id, year, country, standard_deduction,
                                             social_security_rate, social_security_threshold, brackets, is_active, created_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    company_id,
                    year,
                    'Ghana' if is_ghana else 'USA',
                    standard_deduction,
                    rates['social_security_rate'] * 0.887 if is_ghana else rates['social_security_rate'],
                    rates['social_security_threshold'] * 2.5,
                    brackets_json,
                    1 if year == current_year else 0,
                    datetime.datetime.now().strftime('%Y-%m-%d')
                ))

            if IS_PRODUCTION:
                cursor.execute("""
                    INSERT INTO bonus_tax_configs (company_id, year, bonus_threshold_percentage, bonus_tax_rate, created_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (company_id, year, 15.0, 5.0, datetime.datetime.now().strftime('%Y-%m-%d')))
            else:
                cursor.execute("""
                    INSERT INTO bonus_tax_configs (company_id, year, bonus_threshold_percentage, bonus_tax_rate, created_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (company_id, year, 15.0, 5.0, datetime.datetime.now().strftime('%Y-%m-%d')))

        db.commit()
        session['current_company_id'] = company_id

        flash('Company added successfully!', 'success')
        return redirect(url_for('list_companies'))

    return render_template('company_form.html', company=None, action='Add')

@app.route('/companies/edit/<int:company_id>', methods=['GET', 'POST'])
def edit_company(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            UPDATE companies 
            SET name = ?, base_currency = ?, address = ?, tax_id = ?, email = ?, phone = ?
            WHERE id = ?
        """, (
            request.form['name'],
            request.form['base_currency'],
            request.form.get('address', ''),
            request.form.get('tax_id', ''),
            request.form.get('email', ''),
            request.form.get('phone', ''),
            company_id
        ))
        db.commit()
        flash('Company updated successfully!', 'success')
        return redirect(url_for('list_companies'))

    return render_template('company_form.html', company=company, action='Edit')


@app.route('/companies/delete/<int:company_id>')
def delete_company(company_id):
    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("DELETE FROM payroll_records WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM employee_deductions WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)", (company_id,))
    cursor.execute("DELETE FROM monthly_salaries WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)", (company_id,))
    cursor.execute("DELETE FROM employee_allowances WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)", (company_id,))
    cursor.execute("DELETE FROM monthly_allowances WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)", (company_id,))
    cursor.execute("DELETE FROM bonus_records WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM bonus_tax_configs WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM social_security_thresholds WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM employee_bik WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)", (company_id,))
    cursor.execute("DELETE FROM bik_definitions WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM employees WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM deduction_definitions WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM allowance_definitions WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM tax_configs WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM consultant_invoices WHERE company_id = ?", (company_id,))
    cursor.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    db.commit()

    if session.get('current_company_id') == company_id:
        session.pop('current_company_id', None)

    flash('Company and all associated data deleted!', 'success')
    return redirect(url_for('list_companies'))


# ============================================
# ROUTES - Employee Management
# ============================================

@app.route('/employees/<int:company_id>')
def list_employees(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employee_list = get_employees_by_company(company_id)
    return render_template('employees.html', company=company, employees=employee_list)


@app.route('/employees/add/<int:company_id>', methods=['GET', 'POST'])
def add_employee(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        monthly_salary = float(request.form['base_salary'])
        is_tax_exempt = 1 if request.form.get('is_tax_exempt') == 'on' else 0
        exempt_from_social_security = 1 if request.form.get('exempt_from_social_security') == 'on' else 0

        cursor.execute("""
            INSERT INTO employees (
                company_id, first_name, last_name, email, position, department, 
                base_salary, hire_date, status, is_tax_exempt, exempt_from_social_security,
                bank_name, bank_currency, bank_account_number, bank_iban, 
                bank_account_name, bank_swift_code, bank_address,
                id_type, id_number, street_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id,
            request.form['first_name'],
            request.form['last_name'],
            request.form['email'],
            request.form['position'],
            request.form['department'],
            monthly_salary,
            request.form['hire_date'],
            request.form['status'],
            is_tax_exempt,
            exempt_from_social_security,
            request.form.get('bank_name', ''),
            request.form.get('bank_currency', ''),
            request.form.get('bank_account_number', ''),
            request.form.get('bank_iban', ''),
            request.form.get('bank_account_name', ''),
            request.form.get('bank_swift_code', ''),
            request.form.get('bank_address', ''),
            request.form.get('id_type', ''),
            request.form.get('id_number', ''),
            request.form.get('street_location', '')
        ))

        if IS_PRODUCTION:
            cursor.execute("""INSERT INTO employees (...) VALUES (...) RETURNING id""", (...))
            employee_id = cursor.fetchone()['id']
        else:
            cursor.execute("""INSERT INTO employees (...) VALUES (...)""", (...))
            employee_id = cursor.lastrowid
        db.commit()

        # Add default allowances
        allowance_defs = get_allowance_definitions(company_id)
        for defn in allowance_defs:
            cursor.execute("""
                INSERT INTO employee_allowances (employee_id, allowance_id, value)
                VALUES (?, ?, ?)
            """, (employee_id, defn['id'], defn['default_value']))

        db.commit()

        flash('Employee added successfully!', 'success')
        return redirect(url_for('list_employees', company_id=company_id))

    return render_template('employee_form.html', company=company, employee=None, action='Add')


@app.route('/employees/edit/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        monthly_salary = float(request.form['base_salary'])
        is_tax_exempt = 1 if request.form.get('is_tax_exempt') == 'on' else 0
        exempt_from_social_security = 1 if request.form.get('exempt_from_social_security') == 'on' else 0

        cursor.execute("""
            UPDATE employees 
            SET first_name = ?, last_name = ?, email = ?, position = ?, department = ?, 
                base_salary = ?, hire_date = ?, status = ?, is_tax_exempt = ?, exempt_from_social_security = ?,
                bank_name = ?, bank_currency = ?, bank_account_number = ?, bank_iban = ?, 
                bank_account_name = ?, bank_swift_code = ?, bank_address = ?,
                id_type = ?, id_number = ?, street_location = ?
            WHERE id = ?
        """, (
            request.form['first_name'],
            request.form['last_name'],
            request.form['email'],
            request.form['position'],
            request.form['department'],
            monthly_salary,
            request.form['hire_date'],
            request.form['status'],
            is_tax_exempt,
            exempt_from_social_security,
            request.form.get('bank_name', ''),
            request.form.get('bank_currency', ''),
            request.form.get('bank_account_number', ''),
            request.form.get('bank_iban', ''),
            request.form.get('bank_account_name', ''),
            request.form.get('bank_swift_code', ''),
            request.form.get('bank_address', ''),
            request.form.get('id_type', ''),
            request.form.get('id_number', ''),
            request.form.get('street_location', ''),
            employee_id
        ))
        db.commit()
        flash('Employee updated successfully!', 'success')
        return redirect(url_for('list_employees', company_id=employee['company_id']))

    return render_template('employee_form.html', company=company, employee=employee, action='Edit')


@app.route('/employees/delete/<int:employee_id>')
def delete_employee(employee_id):
    employee = get_employee(employee_id)
    if employee:
        company_id = employee['company_id']
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("DELETE FROM employee_allowances WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM employee_deductions WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM monthly_salaries WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM bonus_records WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM employee_bik WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM monthly_allowances WHERE employee_id = ?", (employee_id,))
        cursor.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        db.commit()
        flash('Employee deleted successfully!', 'success')
        return redirect(url_for('list_employees', company_id=company_id))
    return redirect(url_for('list_companies'))


# ============================================
# ROUTES - Monthly Salary Management
# ============================================

@app.route('/employees/salary/<int:employee_id>', methods=['GET', 'POST'])
def manage_monthly_salary(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    current_year = datetime.datetime.now().year

    if request.method == 'POST':
        year = int(request.form.get('year', current_year))
        month = int(request.form.get('month', 1))
        salary = float(request.form.get('salary', 0))

        if salary > 0:
            set_employee_monthly_salary(employee_id, year, month, salary)
            flash(f'Salary for {get_month_name(month)} {year} set to {company["base_currency"]} {format_currency(salary)}', 'success')
        else:
            flash('Invalid salary amount!', 'error')

        return redirect(url_for('manage_monthly_salary', employee_id=employee_id))

    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("""
        SELECT * FROM monthly_salaries 
        WHERE employee_id = ? 
        ORDER BY year DESC, month DESC
    """, (employee_id,))
    salary_history = rows_to_list(cursor.fetchall())

    return render_template('monthly_salary.html',
                           employee=employee,
                           company=company,
                           salary_history=salary_history,
                           current_year=current_year,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


# ============================================
# ROUTES - Allowance Management
# ============================================

@app.route('/allowances/<int:company_id>')
def manage_allowances(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    definitions = get_allowance_definitions(company_id)
    return render_template('allowances.html', company=company, definitions=definitions)

@app.route('/allowances/add/<int:company_id>', methods=['GET', 'POST'])
def add_allowance(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        if IS_PRODUCTION:
            # PostgreSQL - use RETURNING id
            cursor.execute("""
                INSERT INTO allowance_definitions (company_id, name, type, default_value, is_taxable, description, created_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                company_id,
                request.form['name'],
                request.form['type'],
                float(request.form['default_value']),
                1 if request.form.get('is_taxable') == 'on' else 0,
                request.form.get('description', ''),
                datetime.datetime.now().strftime('%Y-%m-%d')
            ))
            allowance_id = cursor.fetchone()['id']
        else:
            # SQLite - use lastrowid
            cursor.execute("""
                INSERT INTO allowance_definitions (company_id, name, type, default_value, is_taxable, description, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                company_id,
                request.form['name'],
                request.form['type'],
                float(request.form['default_value']),
                1 if request.form.get('is_taxable') == 'on' else 0,
                request.form.get('description', ''),
                datetime.datetime.now().strftime('%Y-%m-%d')
            ))
            allowance_id = cursor.lastrowid

        db.commit()

        employees = get_employees_by_company(company_id)
        allowance_errors = []
        allowance_value = float(request.form['default_value'])

        for emp in employees:
            if IS_PRODUCTION:
                cursor.execute("SAVEPOINT allowance_row")

            try:
                cursor.execute("""
                    INSERT INTO employee_allowances (employee_id, allowance_id, value)
                    VALUES (?, ?, ?)
                """, (emp['id'], allowance_id, allowance_value))

                if IS_PRODUCTION:
                    cursor.execute("RELEASE SAVEPOINT allowance_row")

            except Exception as e:
                if IS_PRODUCTION:
                    cursor.execute("ROLLBACK TO SAVEPOINT allowance_row")
                allowance_errors.append(
                    f"Employee {emp['id']} ({emp['first_name']} {emp['last_name']}): {str(e)}"
                )

        db.commit()

        if allowance_errors:
            flash(
                f'Allowance created, but {len(allowance_errors)} employee allowance(s) '
                f'could not be created.',
                'warning'
            )
            for err in allowance_errors[:5]:
                print(f'⚠️ {err}')
        else:
            flash('Allowance added successfully!', 'success')
        return redirect(url_for('manage_allowances', company_id=company_id))

    return render_template('allowance_form.html', company=company, allowance=None, action='Add')

@app.route('/allowances/edit/<int:allowance_id>', methods=['GET', 'POST'])
def edit_allowance(allowance_id):
    allowance = get_allowance_definition(allowance_id)
    if not allowance:
        flash('Allowance not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(allowance['company_id'])
    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            UPDATE allowance_definitions 
            SET name = ?, type = ?, default_value = ?, is_taxable = ?, description = ?
            WHERE id = ?
        """, (
            request.form['name'],
            request.form['type'],
            float(request.form['default_value']),
            1 if request.form.get('is_taxable') == 'on' else 0,
            request.form.get('description', ''),
            allowance_id
        ))
        db.commit()
        flash('Allowance updated successfully!', 'success')
        return redirect(url_for('manage_allowances', company_id=allowance['company_id']))

    return render_template('allowance_form.html', company=company, allowance=allowance, action='Edit')


@app.route('/allowances/delete/<int:allowance_id>')
def delete_allowance(allowance_id):
    allowance = get_allowance_definition(allowance_id)
    if allowance:
        company_id = allowance['company_id']
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("DELETE FROM employee_allowances WHERE allowance_id = ?", (allowance_id,))
        cursor.execute("DELETE FROM monthly_allowances WHERE allowance_id = ?", (allowance_id,))
        cursor.execute("DELETE FROM allowance_definitions WHERE id = ?", (allowance_id,))
        db.commit()
        flash('Allowance deleted successfully!', 'success')
        return redirect(url_for('manage_allowances', company_id=company_id))
    return redirect(url_for('list_companies'))


@app.route('/employees/allowances/<int:employee_id>', methods=['GET', 'POST'])
def manage_employee_allowances(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    definitions = get_allowance_definitions(company['id'])
    current_allowances = get_employee_allowance_dict(employee_id)

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        for defn in definitions:
            value = float(request.form.get(f'allowance_{defn["id"]}', defn['default_value']))
            if IS_PRODUCTION:
                cursor.execute("""
                    INSERT INTO employee_allowances (employee_id, allowance_id, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (employee_id, allowance_id) 
                    DO UPDATE SET value = EXCLUDED.value
                """, (employee_id, defn['id'], value))
            else:
                cursor.execute("SELECT id FROM employee_allowances WHERE employee_id = ? AND allowance_id = ?",
                               (employee_id, defn['id']))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute("UPDATE employee_allowances SET value = ? WHERE employee_id = ? AND allowance_id = ?",
                                   (value, employee_id, defn['id']))
                else:
                    cursor.execute("INSERT INTO employee_allowances (employee_id, allowance_id, value) VALUES (?, ?, ?)",
                                   (employee_id, defn['id'], value))

        db.commit()
        flash('Employee allowances updated successfully!', 'success')
        return redirect(url_for('list_employees', company_id=company['id']))

    return render_template('employee_allowances.html',
                           employee=employee,
                           company=company,
                           definitions=definitions,
                           current_allowances=current_allowances)


@app.route('/employees/allowances/monthly/<int:employee_id>', methods=['GET', 'POST'])
def manage_employee_monthly_allowances(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    definitions = get_allowance_definitions(company['id'])
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    year = request.args.get('year', type=int, default=current_year)
    month = request.args.get('month', type=int, default=current_month)

    if request.method == 'POST':
        year = int(request.form.get('year', current_year))
        month = int(request.form.get('month', current_month))

        for defn in definitions:
            value = float(request.form.get(f'allowance_{defn["id"]}', defn['default_value']))
            set_employee_monthly_allowance(employee_id, defn['id'], year, month, value)

        flash(f'Employee allowances for {get_month_name(month)} {year} updated successfully!', 'success')
        return redirect(url_for('manage_employee_monthly_allowances', employee_id=employee_id, year=year, month=month))

    current_allowances = {}
    for defn in definitions:
        current_allowances[defn['id']] = get_employee_monthly_allowance(employee_id, defn['id'], year, month)

    history = get_employee_allowance_history(employee_id)

    return render_template('employee_monthly_allowances.html',
                           employee=employee,
                           company=company,
                           definitions=definitions,
                           current_allowances=current_allowances,
                           year=year,
                           month=month,
                           history=history,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


def get_employee_allowance_history(employee_id, allowance_id=None):
    """Get allowance history for an employee"""
    db = get_db()
    cursor = get_cursor(db)

    if allowance_id:
        cursor.execute("""
            SELECT * FROM monthly_allowances 
            WHERE employee_id = ? AND allowance_id = ?
            ORDER BY year DESC, month DESC
        """, (employee_id, allowance_id))
    else:
        cursor.execute("""
            SELECT * FROM monthly_allowances 
            WHERE employee_id = ? 
            ORDER BY year DESC, month DESC
        """, (employee_id,))

    return rows_to_list(cursor.fetchall())


# ============================================
# ROUTES - Deduction Management
# ============================================

@app.route('/deductions/<int:company_id>')
def manage_deductions(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    definitions = get_deduction_definitions(company_id)
    return render_template('deductions.html', company=company, definitions=definitions)


@app.route('/deductions/add/<int:company_id>', methods=['GET', 'POST'])
def add_deduction(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        cursor.execute("""
            INSERT INTO deduction_definitions (company_id, name, type, default_value, is_percentage, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id,
            request.form['name'],
            request.form['type'],
            float(request.form['default_value']),
            1 if request.form.get('is_percentage') == 'on' else 0,
            request.form.get('description', ''),
            datetime.datetime.now().strftime('%Y-%m-%d')
        ))

        if IS_PRODUCTION:
            cursor.execute("""INSERT INTO deduction_definitions (...) VALUES (...) RETURNING id""", (...))
            deduction_id = cursor.fetchone()['id']
        else:
            cursor.execute("""INSERT INTO deduction_definitions (...) VALUES (...)""", (...))
            deduction_id = cursor.lastrowid
        db.commit()

        flash('Deduction added successfully!', 'success')
        return redirect(url_for('manage_deductions', company_id=company_id))

    return render_template('deduction_form.html', company=company, deduction=None, action='Add')


@app.route('/deductions/edit/<int:deduction_id>', methods=['GET', 'POST'])
def edit_deduction(deduction_id):
    deduction = get_deduction_definition(deduction_id)
    if not deduction:
        flash('Deduction not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(deduction['company_id'])
    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            UPDATE deduction_definitions 
            SET name = ?, type = ?, default_value = ?, is_percentage = ?, description = ?
            WHERE id = ?
        """, (
            request.form['name'],
            request.form['type'],
            float(request.form['default_value']),
            1 if request.form.get('is_percentage') == 'on' else 0,
            request.form.get('description', ''),
            deduction_id
        ))
        db.commit()
        flash('Deduction updated successfully!', 'success')
        return redirect(url_for('manage_deductions', company_id=deduction['company_id']))

    return render_template('deduction_form.html', company=company, deduction=deduction, action='Edit')


@app.route('/deductions/delete/<int:deduction_id>')
def delete_deduction(deduction_id):
    deduction = get_deduction_definition(deduction_id)
    if deduction:
        company_id = deduction['company_id']
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("DELETE FROM employee_deductions WHERE deduction_id = ?", (deduction_id,))
        cursor.execute("DELETE FROM deduction_definitions WHERE id = ?", (deduction_id,))
        db.commit()
        flash('Deduction deleted successfully!', 'success')
        return redirect(url_for('manage_deductions', company_id=company_id))
    return redirect(url_for('list_companies'))


@app.route('/employees/deductions/<int:employee_id>', methods=['GET', 'POST'])
def manage_employee_deductions(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    definitions = get_deduction_definitions(company['id'])
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    year = request.args.get('year', type=int, default=current_year)
    month = request.args.get('month', type=int, default=current_month)

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date') or None

        for defn in definitions:
            value = float(request.form.get(f'deduction_{defn["id"]}', defn['default_value']))
            set_employee_deduction(employee_id, defn['id'], start_date, end_date, value)

        db.commit()
        flash(f'Employee deductions updated successfully!', 'success')
        return redirect(url_for('manage_employee_deductions', employee_id=employee_id, year=year, month=month))

    current_deductions = {}
    for defn in definitions:
        current_deductions[defn['id']] = get_employee_deduction_value(employee_id, defn['id'], year, month)

    return render_template('employee_deductions.html',
                           employee=employee,
                           company=company,
                           definitions=definitions,
                           current_deductions=current_deductions,
                           year=year,
                           month=month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


# ============================================
# ROUTES - BIK Management
# ============================================

@app.route('/bik/<int:company_id>')
def manage_bik(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    definitions = get_bik_definitions(company_id)
    return render_template('bik_management.html', company=company, definitions=definitions)


@app.route('/bik/add/<int:company_id>', methods=['GET', 'POST'])
def add_bik(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        cursor.execute("""
            INSERT INTO bik_definitions (company_id, name, type, default_value, is_taxable, description, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id,
            request.form['name'],
            request.form['type'],
            float(request.form['default_value']),
            1 if request.form.get('is_taxable') == 'on' else 0,
            request.form.get('description', ''),
            datetime.datetime.now().strftime('%Y-%m-%d')
        ))

        if IS_PRODUCTION:
            cursor.execute("""INSERT INTO deduction_definitions (...) VALUES (...) RETURNING id""", (...))
            bik_id = cursor.fetchone()['id']
        else:
            cursor.execute("""INSERT INTO deduction_definitions (...) VALUES (...)""", (...))
            bik_id = cursor.lastrowid

        db.commit()

        flash('Benefit-in-Kind added successfully!', 'success')
        return redirect(url_for('manage_bik', company_id=company_id))

    return render_template('bik_form.html', company=company, bik=None, action='Add')


@app.route('/bik/edit/<int:bik_id>', methods=['GET', 'POST'])
def edit_bik(bik_id):
    bik = get_bik_definition(bik_id)
    if not bik:
        flash('Benefit-in-Kind not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(bik['company_id'])
    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("""
            UPDATE bik_definitions 
            SET name = ?, type = ?, default_value = ?, is_taxable = ?, description = ?
            WHERE id = ?
        """, (
            request.form['name'],
            request.form['type'],
            float(request.form['default_value']),
            1 if request.form.get('is_taxable') == 'on' else 0,
            request.form.get('description', ''),
            bik_id
        ))
        db.commit()
        flash('Benefit-in-Kind updated successfully!', 'success')
        return redirect(url_for('manage_bik', company_id=bik['company_id']))

    return render_template('bik_form.html', company=company, bik=bik, action='Edit')


@app.route('/bik/delete/<int:bik_id>')
def delete_bik(bik_id):
    bik = get_bik_definition(bik_id)
    if bik:
        company_id = bik['company_id']
        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("DELETE FROM employee_bik WHERE bik_id = ?", (bik_id,))
        cursor.execute("DELETE FROM bik_definitions WHERE id = ?", (bik_id,))
        db.commit()
        flash('Benefit-in-Kind deleted successfully!', 'success')
        return redirect(url_for('manage_bik', company_id=company_id))
    return redirect(url_for('list_companies'))


@app.route('/employees/bik/<int:employee_id>', methods=['GET', 'POST'])
def manage_employee_bik(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    definitions = get_bik_definitions(company['id'])
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    year = request.args.get('year', type=int, default=current_year)
    month = request.args.get('month', type=int, default=current_month)

    if request.method == 'POST':
        db = get_db()
        cursor = get_cursor(db)

        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date') or None

        for defn in definitions:
            value = float(request.form.get(f'bik_{defn["id"]}', defn['default_value']))
            set_employee_bik(employee_id, defn['id'], start_date, end_date, value)

        db.commit()
        flash(f'Employee Benefit-in-Kind updated successfully!', 'success')
        return redirect(url_for('manage_employee_bik', employee_id=employee_id, year=year, month=month))

    current_bik = get_employee_bik_dict(employee_id, year, month)

    return render_template('employee_bik.html',
                           employee=employee,
                           company=company,
                           definitions=definitions,
                           current_bik=current_bik,
                           year=year,
                           month=month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


# ============================================
# ROUTES - Bonus Management
# ============================================

@app.route('/bonus/<int:company_id>')
def manage_bonuses(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    current_year = datetime.datetime.now().year
    current_config = get_bonus_tax_config(company_id, current_year)

    return render_template('bonus_management.html',
                           company=company,
                           employees=employees,
                           current_year=current_year,
                           current_config=current_config,
                           get_month_name=get_month_name,
                           format_currency=format_currency,
                           get_all_employee_bonuses=get_all_employee_bonuses)


@app.route('/bonus/add/<int:company_id>', methods=['GET', 'POST'])
def add_bonus(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employee_id = request.args.get('employee_id', type=int)
    employee = get_employee(employee_id) if employee_id else None
    current_year = datetime.datetime.now().year
    current_config = get_bonus_tax_config(company_id, current_year)

    if request.method == 'POST':
        employee_id = int(request.form['employee_id'])
        start_date = request.form['start_date']
        end_date = request.form.get('end_date') or None
        bonus_amount = float(request.form['bonus_amount'])
        bonus_type = request.form['bonus_type']
        description = request.form.get('description', '')

        db = get_db()
        cursor = get_cursor(db)
        cursor.execute("SELECT id FROM bonus_records WHERE employee_id = ? AND start_date = ?", (employee_id, start_date))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE bonus_records 
                SET end_date = ?, bonus_amount = ?, bonus_type = ?, description = ?, created_date = ?
                WHERE employee_id = ? AND start_date = ?
            """, (end_date, bonus_amount, bonus_type, description,
                  datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), employee_id, start_date))
            flash('Bonus updated successfully!', 'success')
        else:
            cursor.execute("""
                INSERT INTO bonus_records (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (employee_id, company_id, start_date, end_date, bonus_amount, bonus_type, description,
                  datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            flash('Bonus added successfully!', 'success')

        db.commit()
        return redirect(url_for('manage_bonuses', company_id=company_id))

    return render_template('bonus_form.html',
                           company=company,
                           employee=employee,
                           employees=get_employees_by_company(company_id),
                           current_year=current_year,
                           current_config=current_config,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/bonus/delete/<int:company_id>/<int:employee_id>/<string:start_date>')
def delete_bonus(company_id, employee_id, start_date):
    delete_employee_bonus(employee_id, start_date)
    flash('Bonus deleted successfully!', 'success')
    return redirect(url_for('manage_bonuses', company_id=company_id))


@app.route('/bonus/config/<int:company_id>', methods=['GET', 'POST'])
def bonus_tax_config(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    current_year = datetime.datetime.now().year

    if request.method == 'POST':
        year = int(request.form['year'])
        threshold_percentage = float(request.form['threshold_percentage'])
        tax_rate = float(request.form['tax_rate'])

        set_bonus_tax_config(company_id, year, threshold_percentage, tax_rate)
        flash(f'Bonus tax configuration for {year} saved successfully!', 'success')
        return redirect(url_for('bonus_tax_config', company_id=company_id))

    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("SELECT * FROM bonus_tax_configs WHERE company_id = ? ORDER BY year DESC", (company_id,))
    configs = rows_to_list(cursor.fetchall())

    current_config = get_bonus_tax_config(company_id, current_year)

    return render_template('bonus_tax_config.html',
                           company=company,
                           configs=configs,
                           current_config=current_config,
                           current_year=current_year,
                           format_currency=format_currency)


# ============================================
# ROUTES - Social Security Threshold Management
# ============================================

@app.route('/social_security/<int:company_id>')
def manage_social_security(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    tax_configs = get_tax_configs_by_company(company_id)
    thresholds = get_social_security_threshold_history(company_id)

    return render_template('social_security.html',
                           company=company,
                           tax_configs=tax_configs,
                           thresholds=thresholds,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


def get_social_security_threshold_history(company_id, year=None):
    """Get all threshold history for a company"""
    db = get_db()
    cursor = get_cursor(db)
    if year:
        cursor.execute("""
            SELECT * FROM social_security_thresholds 
            WHERE company_id = ? AND year = ?
            ORDER BY year DESC, month DESC
        """, (company_id, year))
    else:
        cursor.execute("""
            SELECT * FROM social_security_thresholds 
            WHERE company_id = ?
            ORDER BY year DESC, month DESC
        """, (company_id,))
    return rows_to_list(cursor.fetchall())


@app.route('/social_security/set/<int:company_id>', methods=['POST'])
def set_social_security_threshold_route(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = int(request.form.get('year', datetime.datetime.now().year))
    month = int(request.form.get('month', datetime.datetime.now().month))
    threshold = float(request.form.get('threshold', 0))

    if threshold <= 0:
        flash('Invalid threshold amount!', 'error')
        return redirect(url_for('manage_social_security', company_id=company_id))

    set_social_security_threshold(company_id, year, month, threshold)
    flash(f'Social Security threshold for {get_month_name(month)} {year} set to {company["base_currency"]} {format_currency(threshold)}', 'success')
    return redirect(url_for('manage_social_security', company_id=company_id))


@app.route('/social_security/delete/<int:company_id>/<int:year>/<int:month>')
def delete_social_security_threshold(company_id, year, month):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("DELETE FROM social_security_thresholds WHERE company_id = ? AND year = ? AND month = ?",
                   (company_id, year, month))
    db.commit()
    flash(f'Threshold override for {get_month_name(month)} {year} removed!', 'success')
    return redirect(url_for('manage_social_security', company_id=company_id))


# ============================================
# ROUTES - Tax Configuration
# ============================================

@app.route('/tax_config/<int:company_id>', methods=['GET', 'POST'])
def manage_tax_config(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    company_tax_configs = get_tax_configs_by_company(company_id)
    available_years = [c['year'] for c in company_tax_configs]

    if request.method == 'POST':
        year = int(request.form['year'])
        existing_config = get_tax_config(company_id, year)

        bracket_count = int(request.form.get('bracket_count', 0))
        brackets = []
        for i in range(bracket_count):
            min_val = float(request.form.get(f'bracket_min_{i}', 0))
            max_val = request.form.get(f'bracket_max_{i}', '')
            if max_val == '' or max_val == 'inf' or max_val == '∞':
                max_val = float('inf')
            else:
                max_val = float(max_val)
            rate = float(request.form.get(f'bracket_rate_{i}', 0))
            brackets.append({'min': min_val, 'max': max_val, 'rate': rate})

        is_active = 1 if request.form.get('is_active') == 'on' else 0
        brackets_json = json.dumps(brackets)

        db = get_db()
        cursor = get_cursor(db)

        if existing_config:
            cursor.execute("""
                UPDATE tax_configs 
                SET country = ?, standard_deduction = ?, social_security_rate = ?,
                    social_security_threshold = ?, brackets = ?, is_active = ?
                WHERE company_id = ? AND year = ?
            """, (
                request.form['country'],
                float(request.form['standard_deduction']),
                float(request.form['social_security_rate']),
                float(request.form['social_security_threshold']),
                brackets_json,
                is_active,
                company_id,
                year
            ))
            config_id = existing_config['id']
        else:
            cursor.execute("""
                INSERT INTO tax_configs (company_id, year, country, standard_deduction,
                                         social_security_rate, social_security_threshold, brackets, is_active, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_id,
                year,
                request.form['country'],
                float(request.form['standard_deduction']),
                float(request.form['social_security_rate']),
                float(request.form['social_security_threshold']),
                brackets_json,
                is_active,
                datetime.datetime.now().strftime('%Y-%m-%d')
            ))
            config_id = cursor.lastrowid

        if is_active:
            cursor.execute("UPDATE tax_configs SET is_active = 0 WHERE company_id = ? AND id != ?", (company_id, config_id))

        db.commit()
        flash(f'Tax configuration for {year} saved successfully!', 'success')
        return redirect(url_for('manage_tax_config', company_id=company_id))

    selected_year = request.args.get('year', type=int)
    if not selected_year and available_years:
        selected_year = max(available_years)

    tax_config = get_tax_config(company_id, selected_year) if selected_year else None

    if tax_config:
        brackets = json.loads(tax_config['brackets'])
        for bracket in brackets:
            if bracket.get('max') == float('inf'):
                bracket['max_display'] = '∞'
            else:
                bracket['max_display'] = bracket.get('max')
        tax_config_dict = dict(tax_config)
        tax_config_dict['brackets'] = brackets
    else:
        tax_config_dict = None

    default_brackets = get_default_tax_rates(selected_year or 2024)['brackets']
    for bracket in default_brackets:
        if bracket.get('max') == float('inf'):
            bracket['max_display'] = '∞'
        else:
            bracket['max_display'] = bracket.get('max')

    return render_template('tax_config.html',
                           company=company,
                           tax_config=tax_config_dict,
                           available_years=available_years,
                           selected_year=selected_year,
                           default_brackets=default_brackets,
                           all_configs=company_tax_configs)


@app.route('/tax_config/delete/<int:company_id>/<int:year>')
def delete_tax_config(company_id, year):
    db = get_db()
    cursor = get_cursor(db)
    cursor.execute("DELETE FROM tax_configs WHERE company_id = ? AND year = ?", (company_id, year))
    db.commit()
    flash(f'Tax configuration for {year} deleted!', 'success')
    return redirect(url_for('manage_tax_config', company_id=company_id))


# ============================================
# ROUTES - Payroll
# ============================================

@app.route('/payroll/<int:company_id>')
def payroll_dashboard(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employee_list = get_employees_by_company(company_id)
    available_years = get_available_years(company_id)

    selected_year = request.args.get('year', type=int)
    selected_month = request.args.get('month', type=int)

    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    if not selected_year:
        selected_year = current_year if current_year in available_years else (available_years[-1] if available_years else current_year)

    if not selected_month:
        selected_month = current_month

    tax_config = get_tax_config(company_id, selected_year) if selected_year else None

    payroll_data = []
    total_net = 0
    total_gross = 0
    total_tax = 0
    total_allowances = 0
    total_deductions = 0
    total_social_security = 0
    total_bonus = 0
    total_bik = 0

    for emp in employee_list:
        period = f'{selected_year}-{selected_month:02d}'
        payroll = calculate_payroll(emp['id'], period, selected_year, selected_month, tax_config)
        if payroll:
            payroll_data.append(payroll)
            total_net += payroll['net_pay']
            total_gross += payroll['gross_salary']
            total_tax += payroll['total_tax']
            total_allowances += payroll['allowances_total']
            total_deductions += payroll['deductions_total']
            total_social_security += payroll['social_security']
            total_bonus += payroll['bonus_amount']
            total_bik += payroll['bik_total']

    existing_records = get_payroll_by_month(company_id, selected_year, selected_month)
    processed_months = get_processed_months(company_id)

    year_comparison = []
    for year in available_years:
        year_config = get_tax_config(company_id, year)
        if year_config:
            year_total_net = 0
            year_total_gross = 0
            year_total_tax = 0
            for emp in employee_list:
                payroll = calculate_payroll(emp['id'], f'{year}-{selected_month:02d}', year, selected_month, year_config)
                if payroll:
                    year_total_net += payroll['net_pay']
                    year_total_gross += payroll['gross_salary']
                    year_total_tax += payroll['total_tax']
            year_comparison.append({
                'year': year,
                'total_net': year_total_net,
                'total_gross': year_total_gross,
                'total_tax': year_total_tax
            })

    return render_template('payroll_dashboard.html',
                           company=company,
                           employees=employee_list,
                           payroll_data=payroll_data,
                           total_net=total_net,
                           total_gross=total_gross,
                           total_tax=total_tax,
                           total_allowances=total_allowances,
                           total_deductions=total_deductions,
                           total_social_security=total_social_security,
                           total_bonus=total_bonus,
                           total_bik=total_bik,
                           employee_count=len(employee_list),
                           available_years=available_years,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           year_comparison=year_comparison,
                           existing_records=existing_records,
                           processed_months=processed_months,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


def get_available_years(company_id):
    configs = get_tax_configs_by_company(company_id)
    return [c['year'] for c in configs]


@app.route('/payroll/process/<int:company_id>', methods=['POST'])
def process_payroll(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = int(request.form.get('year', datetime.datetime.now().year))
    month = int(request.form.get('month', datetime.datetime.now().month))

    existing = get_payroll_by_month(company_id, year, month)
    if existing:
        flash(f'Payroll for {get_month_name(month)} {year} has already been processed!', 'warning')
        return redirect(url_for('payroll_dashboard', company_id=company_id, year=year, month=month))

    tax_config = get_tax_config(company_id, year)
    if not tax_config:
        flash(f'Tax configuration not found for year {year}!', 'error')
        return redirect(url_for('payroll_dashboard', company_id=company_id))

    employee_list = get_employees_by_company(company_id)
    if not employee_list:
        flash('No employees found for this company!', 'warning')
        return redirect(url_for('payroll_dashboard', company_id=company_id))

    db = get_db()
    cursor = get_cursor(db)
    processed_count = 0

    errors = []

    for emp in employee_list:
        if IS_PRODUCTION:
            cursor.execute("SAVEPOINT payroll_row")

        try:
            period = f'{year}-{month:02d}'
            payroll = calculate_payroll(emp['id'], period, year, month, tax_config)

            if payroll:
                cursor.execute("""
                    INSERT INTO payroll_records (
                        employee_id, company_id, period, year, month, base_salary, allowances_total, allowance_details,
                        bonus_amount, bonus_details, bik_total, bik_details, deductions_total, deduction_details,
                        gross_salary, annual_gross, annual_taxable, annual_tax, monthly_tax, bonus_tax_flat, total_tax,
                        social_security, social_security_threshold_applied, total_deductions, net_pay,
                        currency, tax_year, tax_config_id, processed_date, is_tax_exempt, exempt_from_social_security
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    payroll['employee_id'],
                    payroll['company_id'],
                    payroll['period'],
                    payroll['year'],
                    payroll['month'],
                    payroll['base_salary'],
                    payroll['allowances_total'],
                    json.dumps(payroll['allowance_details']),
                    payroll['bonus_amount'],
                    json.dumps(payroll['bonus_details']) if payroll['bonus_details'] else None,
                    payroll['bik_total'],
                    json.dumps(payroll['bik_details']),
                    payroll['deductions_total'],
                    json.dumps(payroll['deduction_details']),
                    payroll['gross_salary'],
                    payroll['annual_gross'],
                    payroll['annual_taxable'],
                    payroll['annual_tax'],
                    payroll['monthly_tax'],
                    payroll['bonus_tax_flat'],
                    payroll['total_tax'],
                    payroll['social_security'],
                    payroll['social_security_threshold_applied'],
                    payroll['total_deductions'],
                    payroll['net_pay'],
                    payroll['currency'],
                    payroll['tax_year'],
                    payroll['tax_config_id'],
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    1 if payroll['is_tax_exempt'] else 0,
                    1 if payroll['exempt_from_social_security'] else 0
                ))
                processed_count += 1

            if IS_PRODUCTION:
                cursor.execute("RELEASE SAVEPOINT payroll_row")

        except Exception as e:
            if IS_PRODUCTION:
                cursor.execute("ROLLBACK TO SAVEPOINT payroll_row")
            errors.append(
                f"Employee {emp.get('id')}: "
                f"{emp.get('first_name', '')} {emp.get('last_name', '')}: {str(e)}"
            )

    db.commit()

    if errors:
        flash(
            f'Payroll for {get_month_name(month)} {year} processed for '
            f'{processed_count} employees with {len(errors)} error(s).',
            'warning'
        )
        for err in errors[:5]:
            print(f'⚠️ {err}')
    else:
        flash(
            f'Payroll for {get_month_name(month)} {year} processed successfully '
            f'for {processed_count} employees!',
            'success'
        )
    return redirect(url_for('payroll_dashboard', company_id=company_id, year=year, month=month))


# ============================================
# ROUTES - Payslips
# ============================================

@app.route('/payslips/<int:company_id>')
def payslips_dashboard(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    selected_year = request.args.get('year', type=int, default=current_year)
    selected_month = request.args.get('month', type=int, default=current_month)

    payslips = []
    total_net = 0
    total_gross = 0
    total_tax = 0
    generated_count = 0

    for emp in employees:
        payslip_data = generate_payslip_data(emp['id'], selected_year, selected_month)
        if payslip_data:
            generated_count += 1
            total_net += payslip_data['payroll']['net_pay']
            total_gross += payslip_data['payroll']['gross_salary']
            total_tax += payslip_data['payroll']['total_tax']
        payslips.append({
            'employee': dict(emp),
            'payroll': payslip_data['payroll'] if payslip_data else None
        })

    return render_template('payslips_dashboard.html',
                           company=company,
                           employees=employees,
                           payslips=payslips,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           total_net=total_net,
                           total_gross=total_gross,
                           total_tax=total_tax,
                           generated_count=generated_count,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/payslips/bulk/<int:company_id>')
def bulk_payslip(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    payslips = generate_bulk_payslip_pdf(company_id, year, month)

    if not payslips:
        flash(f'No payroll records found for {get_month_name(month)} {year}', 'warning')
        return redirect(url_for('payslips_dashboard', company_id=company_id))

    return render_template('bulk_payslip.html',
                           company=company,
                           payslips=payslips,
                           year=year,
                           month=month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/payslip/view/<int:employee_id>')
def view_payslip(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    payslip_data = generate_payslip_data(employee_id, year, month)

    if not payslip_data:
        flash(f'No payroll record found for {get_month_name(month)} {year}', 'warning')
        return redirect(url_for('payroll_dashboard', company_id=company['id']))

    return render_template('payslip_view.html',
                           payslip=payslip_data,
                           employee=employee,
                           company=company,
                           year=year,
                           month=month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/payslip/download/<int:employee_id>')
def download_payslip(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    buffer = generate_payslip_pdf(employee_id, year, month)

    if not buffer:
        flash(f'No payroll record found for {get_month_name(month)} {year}', 'warning')
        return redirect(url_for('payroll_dashboard', company_id=company['id']))

    filename = f"payslip_{employee['first_name']}_{employee['last_name']}_{year}_{month:02d}.pdf"

    return send_file(
        buffer,
        download_name=filename,
        as_attachment=True,
        mimetype='application/pdf'
    )


@app.route('/payslip/download_bulk/<int:company_id>')
def download_bulk_payslip(company_id):
    import zipfile
    from io import BytesIO

    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    employees = get_employees_by_company(company_id)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for emp in employees:
            buffer = generate_payslip_pdf(emp['id'], year, month)
            if buffer:
                filename = f"payslip_{emp['first_name']}_{emp['last_name']}_{year}_{month:02d}.pdf"
                zip_file.writestr(filename, buffer.getvalue())

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        download_name=f"payslips_{company['name']}_{year}_{month:02d}.zip",
        as_attachment=True,
        mimetype='application/zip'
    )


# ============================================
# ROUTES - Invoices
# ============================================

@app.route('/invoices/<int:company_id>')
def invoice_dashboard(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    invoices = get_invoices_by_company(company_id)

    consultants = []
    for emp in employees:
        is_tax_exempt = emp.get('is_tax_exempt', 0) == 1
        exempt_from_ss = emp.get('exempt_from_social_security', 0) == 1
        if is_tax_exempt or exempt_from_ss:
            consultants.append(emp)

    total_invoices = len(invoices)
    total_amount = sum(inv['final_amount'] for inv in invoices)
    total_paid = sum(inv.get('amount_paid', 0) for inv in invoices)
    total_due = total_amount - total_paid

    status_counts = {
        'Draft': len([i for i in invoices if i['status'] == 'Draft']),
        'Sent': len([i for i in invoices if i['status'] == 'Sent']),
        'Paid': len([i for i in invoices if i['status'] == 'Paid']),
        'Overdue': len([i for i in invoices if i['status'] == 'Overdue'])
    }

    return render_template('invoice_dashboard.html',
                           company=company,
                           employees=employees,
                           consultants=consultants,
                           invoices=invoices,
                           total_invoices=total_invoices,
                           total_amount=total_amount,
                           total_paid=total_paid,
                           total_due=total_due,
                           status_counts=status_counts,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/invoices/generate/<int:company_id>', methods=['GET', 'POST'])
def generate_invoices(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    if request.method == 'POST':
        try:
            year_str = request.form.get('year', '')
            month_str = request.form.get('month', '')
            selected_year = int(year_str) if year_str and year_str.strip() else current_year
            selected_month = int(month_str) if month_str and month_str.strip() else current_month
        except (ValueError, TypeError):
            selected_year = current_year
            selected_month = current_month

        result = create_invoices_for_consultants(company_id, selected_year, selected_month)

        if result['created_count'] > 0:
            flash(f'✅ Successfully generated {result["created_count"]} invoices for {get_month_name(selected_month)} {selected_year}!', 'success')
        else:
            flash(f'⚠️ No invoices generated. Make sure consultants have payroll records for {get_month_name(selected_month)} {selected_year}.', 'warning')

        if result['failed_count'] > 0:
            flash(f'⚠️ {result["failed_count"]} consultant(s) had no payroll records.', 'warning')

        return redirect(url_for('generate_invoices', company_id=company_id, year=selected_year, month=selected_month))

    try:
        year_str = request.args.get('year', '')
        month_str = request.args.get('month', '')
        selected_year = int(year_str) if year_str and year_str.strip() else current_year
        selected_month = int(month_str) if month_str and month_str.strip() else current_month
    except (ValueError, TypeError):
        selected_year = current_year
        selected_month = current_month

    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT DISTINCT e.id, e.first_name, e.last_name, e.position,
               pr.gross_salary
        FROM employees e
        JOIN payroll_records pr ON e.id = pr.employee_id
        WHERE e.company_id = ? 
        AND (e.is_tax_exempt = 1 OR e.exempt_from_social_security = 1)
        AND pr.year = ? AND pr.month = ?
    """, (company_id, selected_year, selected_month))

    consultants_with_payroll = rows_to_list(cursor.fetchall())

    last_day = calendar.monthrange(selected_year, selected_month)[1]
    period_start = f"{selected_year}-{selected_month:02d}-01"
    period_end = f"{selected_year}-{selected_month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT employee_id FROM consultant_invoices 
        WHERE company_id = ? AND period_start = ? AND period_end = ?
    """, (company_id, period_start, period_end))

    existing_invoice_employees = [row['employee_id'] for row in cursor.fetchall()]

    return render_template('generate_invoices.html',
                           company=company,
                           consultants_with_payroll=consultants_with_payroll,
                           existing_invoice_employees=existing_invoice_employees,
                           current_year=current_year,
                           current_month=current_month,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/invoices/view/<int:invoice_id>')
def view_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    if not invoice:
        flash('Invoice not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(invoice['company_id'])
    employee = get_employee(invoice['employee_id'])

    return render_template('view_invoice.html',
                           invoice=invoice,
                           company=company,
                           employee=employee,
                           format_currency=format_currency)


@app.route('/invoices/download/<int:invoice_id>')
def download_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    if not invoice:
        flash('Invoice not found!', 'error')
        return redirect(url_for('list_companies'))

    buffer = generate_invoice_pdf(invoice_id)
    if not buffer:
        flash('Error generating invoice PDF!', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))

    return send_file(
        buffer,
        download_name=f"invoice_{invoice['invoice_number']}.pdf",
        as_attachment=True,
        mimetype='application/pdf'
    )


@app.route('/invoices/update_status/<int:invoice_id>', methods=['POST'])
def update_invoice_status_route(invoice_id):
    invoice = get_invoice(invoice_id)
    if not invoice:
        flash('Invoice not found!', 'error')
        return redirect(url_for('list_companies'))

    status = request.form.get('status')
    if status not in ['Draft', 'Sent', 'Paid', 'Overdue']:
        flash('Invalid status!', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))

    update_invoice_status(invoice_id, status)
    flash(f'Invoice status updated to {status}!', 'success')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/add_payment/<int:invoice_id>', methods=['POST'])
def add_invoice_payment_route(invoice_id):
    invoice = get_invoice(invoice_id)
    if not invoice:
        flash('Invoice not found!', 'error')
        return redirect(url_for('list_companies'))

    amount = float(request.form['amount'])
    payment_method = request.form['payment_method']
    reference = request.form.get('reference', '')
    notes = request.form.get('notes', '')

    if amount <= 0:
        flash('Payment amount must be greater than 0!', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))

    if amount > invoice['balance_due']:
        flash(f'Payment amount cannot exceed balance due ({format_currency(invoice["balance_due"])})!', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))

    add_invoice_payment(invoice_id, amount, payment_method, reference, notes)
    flash('Payment added successfully!', 'success')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/delete/<int:invoice_id>')
def delete_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    if not invoice:
        flash('Invoice not found!', 'error')
        return redirect(url_for('list_companies'))

    company_id = invoice['company_id']

    db = get_db()
    cursor = get_cursor(db)
    cursor.execute('DELETE FROM consultant_invoices WHERE id = ?', (invoice_id,))
    db.commit()

    flash('Invoice deleted successfully!', 'success')
    return redirect(url_for('invoice_dashboard', company_id=company_id))


@app.route('/invoices/consultant/<int:employee_id>')
def consultant_invoices(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    company = get_company(employee['company_id'])
    invoices = get_consultant_invoices(employee_id)

    total_amount = sum(inv['final_amount'] for inv in invoices)
    total_paid = sum(inv.get('amount_paid', 0) for inv in invoices)
    total_due = total_amount - total_paid

    return render_template('consultant_invoices.html',
                           employee=employee,
                           company=company,
                           invoices=invoices,
                           total_amount=total_amount,
                           total_paid=total_paid,
                           total_due=total_due,
                           format_currency=format_currency)


@app.route('/invoices/download_by_employee/<int:employee_id>')
def download_invoice_by_employee(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    db = get_db()
    cursor = get_cursor(db)

    last_day = calendar.monthrange(year, month)[1]
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT id FROM consultant_invoices 
        WHERE employee_id = ? AND period_start = ? AND period_end = ?
    """, (employee_id, period_start, period_end))

    result = cursor.fetchone()

    if not result:
        flash('No invoice found for this period!', 'warning')
        return redirect(url_for('generate_invoices', company_id=employee['company_id']))

    return redirect(url_for('download_invoice', invoice_id=result['id']))


@app.route('/invoices/view_by_employee/<int:employee_id>')
def view_invoice_by_employee(employee_id):
    employee = get_employee(employee_id)
    if not employee:
        flash('Employee not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    db = get_db()
    cursor = get_cursor(db)

    last_day = calendar.monthrange(year, month)[1]
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT id FROM consultant_invoices 
        WHERE employee_id = ? AND period_start = ? AND period_end = ?
    """, (employee_id, period_start, period_end))

    result = cursor.fetchone()

    if not result:
        flash('No invoice found for this period!', 'warning')
        return redirect(url_for('generate_invoices', company_id=employee['company_id']))

    return redirect(url_for('view_invoice', invoice_id=result['id']))


@app.route('/invoices/download_bulk/<int:company_id>')
def download_bulk_invoices(company_id):
    import zipfile
    from io import BytesIO

    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int, default=datetime.datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.datetime.now().month)

    db = get_db()
    cursor = get_cursor(db)

    last_day = calendar.monthrange(year, month)[1]
    period_start = f"{year}-{month:02d}-01"
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    cursor.execute("""
        SELECT i.*, e.first_name, e.last_name
        FROM consultant_invoices i
        JOIN employees e ON i.employee_id = e.id
        WHERE i.company_id = ? AND i.period_start = ? AND i.period_end = ?
    """, (company_id, period_start, period_end))

    invoices = rows_to_list(cursor.fetchall())

    if not invoices:
        flash('No invoices found for this period!', 'warning')
        return redirect(url_for('generate_invoices', company_id=company_id))

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for inv in invoices:
            buffer = generate_invoice_pdf(inv['id'])
            if buffer:
                filename = f"invoice_{inv['invoice_number']}_{inv['first_name']}_{inv['last_name']}.pdf"
                zip_file.writestr(filename, buffer.getvalue())

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        download_name=f"invoices_{company['name']}_{year}_{month:02d}.zip",
        as_attachment=True,
        mimetype='application/zip'
    )


# ============================================
# ROUTES - Bulk Import / Delete
# ============================================

@app.route('/bulk_import/<int:company_id>', methods=['GET', 'POST'])
def bulk_import(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    allowance_defs = get_allowance_definitions(company_id)
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded!', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'error')
            return redirect(request.url)

        if file and file.filename.endswith(('.xlsx', '.xls')):
            try:
                df = pd.read_excel(file)

                start_year = int(request.form.get('start_year', current_year))
                start_month = int(request.form.get('start_month', current_month))
                end_year = int(request.form.get('end_year', current_year + 1))
                end_month = int(request.form.get('end_month', 12))
                copy_type = request.form.get('copy_type', 'monthly')

                if start_year > end_year or (start_year == end_year and start_month > end_month):
                    flash('Start month must be before end month!', 'error')
                    return redirect(request.url)

                required_cols = ['employee_id', 'salary']
                for col in required_cols:
                    if col not in df.columns:
                        flash(f'Missing required column: {col}', 'error')
                        return redirect(request.url)

                db = get_db()
                cursor = get_cursor(db)

                total_months_processed = 0
                total_employees_updated = 0
                total_allowances_updated = 0
                errors = []

                for _, row in df.iterrows():
                    if IS_PRODUCTION:
                        cursor.execute("SAVEPOINT bulk_import_row")

                    try:
                        employee_id = int(row['employee_id'])

                        employee = get_employee(employee_id)
                        if not employee:
                            errors.append(f"Employee ID {employee_id} not found")
                            if IS_PRODUCTION:
                                cursor.execute("RELEASE SAVEPOINT bulk_import_row")
                            continue

                        if employee['company_id'] != company_id:
                            errors.append(f"Employee ID {employee_id} does not belong to this company")
                            if IS_PRODUCTION:
                                cursor.execute("RELEASE SAVEPOINT bulk_import_row")
                            continue

                        if pd.notna(row['salary']) and row['salary'] > 0:
                            salary = float(row['salary'])
                            set_employee_monthly_salary(
                                employee_id, start_year, start_month, salary, commit=False
                            )
                            total_employees_updated += 1

                        for defn in allowance_defs:
                            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
                            if col_name in df.columns and pd.notna(row[col_name]):
                                value = float(row[col_name])
                                set_employee_monthly_allowance(
                                    employee_id, defn['id'], start_year, start_month, value, commit=False
                                )
                                total_allowances_updated += 1

                        if IS_PRODUCTION:
                            cursor.execute("RELEASE SAVEPOINT bulk_import_row")

                    except Exception as e:
                        if IS_PRODUCTION:
                            cursor.execute("ROLLBACK TO SAVEPOINT bulk_import_row")
                        errors.append(
                            f"Error processing employee row "
                            f"{employee_id if 'employee_id' in locals() else 'unknown'}: {str(e)}"
                        )

                if copy_type == 'monthly':
                    month_count = 0
                    copy_year = start_year
                    copy_month = start_month + 1
                    if copy_month > 12:
                        copy_month = 1
                        copy_year += 1

                    while copy_year < end_year or (copy_year == end_year and copy_month <= end_month):
                        cursor.execute("""
                            SELECT COUNT(*) as count FROM monthly_salaries 
                            WHERE employee_id IN (SELECT id FROM employees WHERE company_id = ?)
                            AND year = ? AND month = ?
                        """, (company_id, copy_year, copy_month))
                        result = cursor.fetchone()
                        count = result['count'] if result else 0  # ✅ Works on both

                        if count == 0:
                            prev_year = copy_year
                            prev_month = copy_month - 1
                            if prev_month < 1:
                                prev_month = 12
                                prev_year -= 1

                            for emp in get_employees_by_company(company_id):
                                emp_id = emp['id']

                                source_salary = get_employee_monthly_salary(emp_id, prev_year, prev_month)
                                if source_salary > 0:
                                    set_employee_monthly_salary(emp_id, copy_year, copy_month, source_salary)

                                for defn in allowance_defs:
                                    source_value = get_employee_monthly_allowance(emp_id, defn['id'], prev_year, prev_month)
                                    if source_value > 0:
                                        set_employee_monthly_allowance(emp_id, defn['id'], copy_year, copy_month, source_value)

                            month_count += 1

                        copy_month += 1
                        if copy_month > 12:
                            copy_month = 1
                            copy_year += 1

                    db.commit()

                    total_months_processed = month_count
                    msg = f'✅ Successfully imported data for period: {get_month_name(start_month)} {start_year} → {get_month_name(end_month)} {end_year}!'
                    msg += f' Applied data to {total_months_processed} months.'
                    msg += f' Updated {total_employees_updated} employees.'
                    if total_allowances_updated > 0:
                        msg += f' Updated {total_allowances_updated} allowances.'
                    if errors:
                        msg += f' ⚠️ {len(errors)} errors encountered.'
                        for err in errors[:5]:
                            print(f'⚠️ {err}')

                    flash(msg, 'success' if not errors else 'warning')

                    return redirect(url_for('payroll_dashboard', company_id=company_id, year=end_year, month=end_month))

                else:
                    db.commit()
                    flash(f'✅ Successfully imported data for {get_month_name(start_month)} {start_year}!', 'success')
                    return redirect(url_for('payroll_dashboard', company_id=company_id, year=start_year, month=start_month))

            except Exception as e:
                flash(f'Error importing file: {str(e)}', 'error')
                traceback.print_exc()
        else:
            flash('Please upload an Excel file (.xlsx or .xls)', 'error')

        return redirect(url_for('bulk_import', company_id=company_id))

    return render_template('bulk_import.html',
                           company=company,
                           employees=employees,
                           allowance_defs=allowance_defs,
                           current_year=current_year,
                           current_month=current_month,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/bulk_import/download_template/<int:company_id>')
def download_bulk_import_template(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    allowance_defs = get_allowance_definitions(company_id)

    template_data = {
        'employee_id': [],
        'employee_name': [],
        'salary': [],
        'department': []
    }

    for defn in allowance_defs:
        col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
        template_data[col_name] = []

    for emp in employees:
        template_data['employee_id'].append(emp['id'])
        template_data['employee_name'].append(f"{emp['first_name']} {emp['last_name']}")
        template_data['salary'].append(emp['base_salary'])
        template_data['department'].append(emp['department'])

        for defn in allowance_defs:
            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
            template_data[col_name].append(defn['default_value'])

    df = pd.DataFrame(template_data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Bulk_Import_Template', index=False)

        worksheet = writer.sheets['Bulk_Import_Template']

        column_keys = list(template_data.keys())

        from openpyxl.comments import Comment
        from openpyxl.utils import get_column_letter

        if 'salary' in column_keys:
            salary_col = get_column_letter(column_keys.index('salary') + 1)
            worksheet[f'{salary_col}1'].comment = Comment(
                'Enter monthly salary for this employee. Leave blank to keep current.',
                'System'
            )

        for defn in allowance_defs:
            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
            if col_name in column_keys:
                col_idx = column_keys.index(col_name) + 1
                col_letter = get_column_letter(col_idx)
                worksheet[f'{col_letter}1'].comment = Comment(
                    f'Enter {defn["name"]} for this month. Leave blank to keep current. ({"Taxable" if defn["is_taxable"] else "Non-Taxable"})',
                    'System'
                )

        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        worksheet.freeze_panes = 'A2'

    output.seek(0)

    return send_file(
        output,
        download_name=f'bulk_import_template_{company["name"]}_{datetime.datetime.now().strftime("%Y%m%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.route('/bulk_import/sample/<int:company_id>')
def download_bulk_import_sample(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    allowance_defs = get_allowance_definitions(company_id)

    sample_data = {
        'employee_id': [],
        'employee_name': [],
        'salary': [],
        'department': []
    }

    for defn in allowance_defs:
        col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
        sample_data[col_name] = []

    import random
    for emp in employees:
        sample_data['employee_id'].append(emp['id'])
        sample_data['employee_name'].append(f"{emp['first_name']} {emp['last_name']}")
        variation = random.uniform(-0.05, 0.05)
        sample_data['salary'].append(round(emp['base_salary'] * (1 + variation), 2))
        sample_data['department'].append(emp['department'])

        for defn in allowance_defs:
            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
            variation = random.uniform(-0.1, 0.1)
            sample_data[col_name].append(round(defn['default_value'] * (1 + variation), 2))

    df = pd.DataFrame(sample_data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Sample_Data', index=False)

        worksheet = writer.sheets['Sample_Data']

        note_row = len(employees) + 2
        worksheet[f'A{note_row}'] = '📌 INSTRUCTIONS:'
        worksheet[f'A{note_row + 1}'] = '1. Update salary and allowance values as needed'
        worksheet[f'A{note_row + 2}'] = '2. Leave blank to keep current values'
        worksheet[f'A{note_row + 3}'] = '3. DO NOT change employee_id or employee_name columns'
        worksheet[f'A{note_row + 4}'] = '4. Use this file for the selected month/year'

        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        worksheet.freeze_panes = 'A2'

    output.seek(0)

    return send_file(
        output,
        download_name=f'bulk_import_sample_{company["name"]}_{datetime.datetime.now().strftime("%Y%m%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


def delete_bulk_import_data(company_id, start_year, start_month, end_year, end_month):
    """Delete all bulk imported data for a specific period"""
    db = get_db()
    cursor = get_cursor(db)

    employees = get_employees_by_company(company_id)
    employee_ids = [emp['id'] for emp in employees]

    if not employee_ids:
        return {'deleted': 0, 'message': 'No employees found'}

    placeholders = ','.join(['?'] * len(employee_ids))

    cursor.execute(f"""
        DELETE FROM monthly_salaries 
        WHERE employee_id IN ({placeholders}) 
        AND (year > ? OR (year = ? AND month >= ?))
        AND (year < ? OR (year = ? AND month <= ?))
    """, employee_ids + [start_year, start_year, start_month, end_year, end_year, end_month])

    salary_deleted = cursor.rowcount

    cursor.execute(f"""
        DELETE FROM monthly_allowances 
        WHERE employee_id IN ({placeholders}) 
        AND (year > ? OR (year = ? AND month >= ?))
        AND (year < ? OR (year = ? AND month <= ?))
    """, employee_ids + [start_year, start_year, start_month, end_year, end_year, end_month])

    allowance_deleted = cursor.rowcount

    db.commit()

    return {
        'deleted': salary_deleted + allowance_deleted,
        'salary_deleted': salary_deleted,
        'allowance_deleted': allowance_deleted,
        'message': f'Deleted {salary_deleted} salary records and {allowance_deleted} allowance records'
    }


@app.route('/bulk_delete/<int:company_id>', methods=['GET', 'POST'])
def bulk_delete(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employees = get_employees_by_company(company_id)
    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    if request.method == 'POST':
        start_year = int(request.form.get('start_year', current_year))
        start_month = int(request.form.get('start_month', 1))
        end_year = int(request.form.get('end_year', current_year))
        end_month = int(request.form.get('end_month', 12))

        confirm = request.form.get('confirm', 'no')
        if confirm != 'yes':
            flash('Please confirm deletion by checking the confirmation box.', 'warning')
            return redirect(url_for('bulk_delete', company_id=company_id))

        if start_year > end_year or (start_year == end_year and start_month > end_month):
            flash('Start month must be before or equal to end month!', 'error')
            return redirect(url_for('bulk_delete', company_id=company_id))

        result = delete_bulk_import_data(company_id, start_year, start_month, end_year, end_month)

        flash(f'✅ {result["message"]} for period {get_month_name(start_month)} {start_year} to {get_month_name(end_month)} {end_year}!', 'success')
        return redirect(url_for('payroll_dashboard', company_id=company_id, year=end_year, month=end_month))

    db = get_db()
    cursor = get_cursor(db)

    cursor.execute("""
        SELECT COUNT(*) as count FROM monthly_salaries ms
        JOIN employees e ON ms.employee_id = e.id
        WHERE e.company_id = ?
        AND (ms.year > ? OR (ms.year = ? AND ms.month >= ?))
        AND (ms.year < ? OR (ms.year = ? AND ms.month <= ?))
    """, (company_id, current_year, current_year, 1, current_year, current_year, 12))

    salary_result = cursor.fetchone()
    salary_count = salary_result['count'] if salary_result else 0

    cursor.execute("""
        SELECT COUNT(*) as count FROM monthly_allowances ma
        JOIN employees e ON ma.employee_id = e.id
        WHERE e.company_id = ?
        AND (ma.year > ? OR (ma.year = ? AND ma.month >= ?))
        AND (ma.year < ? OR (ma.year = ? AND ma.month <= ?))
    """, (company_id, current_year, current_year, 1, current_year, current_year, 12))

    allowance_result = cursor.fetchone()
    allowance_count = allowance_result['count'] if allowance_result else 0

    return render_template('bulk_delete.html',
                           company=company,
                           employees=employees,
                           current_year=current_year,
                           current_month=current_month,
                           salary_count=salary_count,
                           allowance_count=allowance_count,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


@app.route('/payroll/delete/<int:company_id>', methods=['GET', 'POST'])
def delete_payroll(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employee_list = get_employees_by_company(company_id)
    available_years = get_available_years(company_id)

    current_year = datetime.datetime.now().year
    current_month = datetime.datetime.now().month

    selected_year = request.args.get('year', type=int, default=current_year)
    selected_month = request.args.get('month', type=int, default=current_month)

    if request.method == 'POST':
        year = int(request.form.get('year', current_year))
        month = int(request.form.get('month', current_month))

        existing = get_payroll_by_month(company_id, year, month)

        if not existing:
            flash(f'No payroll records found for {get_month_name(month)} {year}.', 'warning')
            return redirect(url_for('delete_payroll', company_id=company_id, year=year, month=month))

        confirm = request.form.get('confirm', 'no')
        if confirm != 'yes':
            flash('Please confirm deletion by checking the confirmation box.', 'warning')
            return redirect(url_for('delete_payroll', company_id=company_id, year=year, month=month))

        db = get_db()
        cursor = get_cursor(db)

        cursor.execute("""
            DELETE FROM payroll_records 
            WHERE company_id = ? AND year = ? AND month = ?
        """, (company_id, year, month))

        deleted_count = cursor.rowcount
        db.commit()

        flash(f'✅ Successfully deleted {deleted_count} payroll record(s) for {get_month_name(month)} {year}!', 'success')
        flash(f'💡 You can now use "Process Payroll" to reprocess {get_month_name(month)} {year}.', 'info')

        return redirect(url_for('payroll_dashboard', company_id=company_id, year=year, month=month))

    existing_records = get_payroll_by_month(company_id, selected_year, selected_month)

    total_gross = sum(rec['gross_salary'] for rec in existing_records) if existing_records else 0
    total_net = sum(rec['net_pay'] for rec in existing_records) if existing_records else 0
    total_tax = sum(rec['total_tax'] for rec in existing_records) if existing_records else 0

    return render_template('delete_payroll.html',
                           company=company,
                           employees=employee_list,
                           available_years=available_years,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           existing_records=existing_records,
                           employee_count=len(employee_list),
                           total_gross=total_gross,
                           total_net=total_net,
                           total_tax=total_tax,
                           get_month_name=get_month_name,
                           format_currency=format_currency)


# ============================================
# ROUTES - Employee Import/Export
# ============================================
@app.route('/employees/import/<int:company_id>', methods=['GET', 'POST'])
def import_employees(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded!', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'error')
            return redirect(request.url)

        if file and file.filename.endswith(('.xlsx', '.xls')):
            try:
                df = pd.read_excel(file)
                required_cols = ['first_name', 'last_name', 'email', 'position',
                                 'department', 'base_salary', 'hire_date']

                for col in required_cols:
                    if col not in df.columns:
                        flash(f'Missing required column: {col}', 'error')
                        return redirect(request.url)

                db = get_db()
                cursor = get_cursor(db)
                imported_count = 0
                errors = []

                allowance_defs = get_allowance_definitions(company_id)

                for idx, row in df.iterrows():
                    # ⚠️ Wrap each row in a SAVEPOINT so a failure on one row
                    # doesn't abort the whole transaction (PostgreSQL behavior)
                    if IS_PRODUCTION:
                        cursor.execute("SAVEPOINT row_import")
                    try:
                        # Basic required fields
                        first_name = str(row['first_name']).strip()
                        last_name = str(row['last_name']).strip()
                        email = str(row['email']).strip()
                        position = str(row['position']).strip()
                        department = str(row['department']).strip()
                        base_salary = float(row['base_salary'])
                        hire_date = str(row['hire_date']).strip()

                        # Status
                        status = str(row.get('status', 'Active')).strip()
                        if status not in ['Active', 'Inactive', 'On Leave', 'Terminated', 'Consultant']:
                            status = 'Active'

                        # Exemptions
                        is_tax_exempt = 0
                        exempt_from_ss = 0

                        tax_exempt_val = row.get('is_tax_exempt', 'No')
                        if pd.notna(tax_exempt_val):
                            if str(tax_exempt_val).upper() in ['YES', '1', 'TRUE']:
                                is_tax_exempt = 1

                        ss_exempt_val = row.get('exempt_from_social_security', 'No')
                        if pd.notna(ss_exempt_val):
                            if str(ss_exempt_val).upper() in ['YES', '1', 'TRUE']:
                                exempt_from_ss = 1

                        # Bank details
                        bank_name = str(row.get('bank_name', '')).strip() if pd.notna(row.get('bank_name')) else ''
                        bank_currency = str(row.get('bank_currency', '')).strip() if pd.notna(row.get('bank_currency')) else ''
                        bank_account_number = str(row.get('bank_account_number', '')).strip() if pd.notna(row.get('bank_account_number')) else ''
                        bank_iban = str(row.get('bank_iban', '')).strip() if pd.notna(row.get('bank_iban')) else ''
                        bank_account_name = str(row.get('bank_account_name', '')).strip() if pd.notna(row.get('bank_account_name')) else ''
                        bank_swift_code = str(row.get('bank_swift_code', '')).strip() if pd.notna(row.get('bank_swift_code')) else ''
                        bank_address = str(row.get('bank_address', '')).strip() if pd.notna(row.get('bank_address')) else ''

                        # ID details
                        id_type = str(row.get('id_type', '')).strip() if pd.notna(row.get('id_type')) else ''
                        id_number = str(row.get('id_number', '')).strip() if pd.notna(row.get('id_number')) else ''
                        street_location = str(row.get('street_location', '')).strip() if pd.notna(row.get('street_location')) else ''

                        # ✅ FIX: Use RETURNING id for PostgreSQL
                        if IS_PRODUCTION:
                            cursor.execute("""
                                INSERT INTO employees (
                                    company_id, first_name, last_name, email, position, department,
                                    base_salary, hire_date, status, is_tax_exempt, exempt_from_social_security,
                                    bank_name, bank_currency, bank_account_number, bank_iban,
                                    bank_account_name, bank_swift_code, bank_address,
                                    id_type, id_number, street_location
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (
                                company_id, first_name, last_name, email, position, department,
                                base_salary, hire_date, status, is_tax_exempt, exempt_from_ss,
                                bank_name, bank_currency, bank_account_number, bank_iban,
                                bank_account_name, bank_swift_code, bank_address,
                                id_type, id_number, street_location
                            ))
                            employee_id = cursor.fetchone()['id']
                        else:
                            cursor.execute("""
                                INSERT INTO employees (
                                    company_id, first_name, last_name, email, position, department,
                                    base_salary, hire_date, status, is_tax_exempt, exempt_from_social_security,
                                    bank_name, bank_currency, bank_account_number, bank_iban,
                                    bank_account_name, bank_swift_code, bank_address,
                                    id_type, id_number, street_location
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                company_id, first_name, last_name, email, position, department,
                                base_salary, hire_date, status, is_tax_exempt, exempt_from_ss,
                                bank_name, bank_currency, bank_account_number, bank_iban,
                                bank_account_name, bank_swift_code, bank_address,
                                id_type, id_number, street_location
                            ))
                            employee_id = cursor.lastrowid

                        # Sanity check
                        if not employee_id:
                            raise Exception("Failed to obtain new employee ID")

                        # Add allowances
                        for defn in allowance_defs:
                            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
                            if col_name in df.columns and pd.notna(row[col_name]):
                                value = float(row[col_name])
                            else:
                                value = defn['default_value']

                            cursor.execute("""
                                INSERT INTO employee_allowances (employee_id, allowance_id, value)
                                VALUES (?, ?, ?)
                            """, (employee_id, defn['id'], value))

                        # ✅ Release savepoint on success
                        if IS_PRODUCTION:
                            cursor.execute("RELEASE SAVEPOINT row_import")

                        imported_count += 1

                    except Exception as e:
                        # ✅ Roll back just this row's changes
                        if IS_PRODUCTION:
                            cursor.execute("ROLLBACK TO SAVEPOINT row_import")
                        errors.append(f"Row {idx + 2}: {str(e)}")

                db.commit()

                if errors:
                    flash(f'Imported {imported_count} employees with {len(errors)} errors. Check logs for details.',
                          'warning')
                    for err in errors[:5]:
                        print(f'⚠️ {err}')
                else:
                    flash(f'Successfully imported {imported_count} employees!', 'success')

            except Exception as e:
                flash(f'Error importing file: {str(e)}', 'error')
                traceback.print_exc()
        else:
            flash('Please upload an Excel file (.xlsx or .xls)', 'error')

        return redirect(url_for('list_employees', company_id=company_id))

    return render_template('import_employees.html', company=company)

@app.route('/employees/export/<int:company_id>')
def export_employees(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    employee_list = get_employees_by_company(company_id)
    allowance_defs = get_allowance_definitions(company_id)

    data = []
    for emp in employee_list:
        row = {
            'id': emp['id'],
            'first_name': emp['first_name'],
            'last_name': emp['last_name'],
            'email': emp['email'],
            'position': emp['position'],
            'department': emp['department'],
            'base_salary': emp['base_salary'],
            'hire_date': emp['hire_date'],
            'status': emp['status'],
            'is_tax_exempt': 'Yes' if emp.get('is_tax_exempt') else 'No',
            'exempt_from_social_security': 'Yes' if emp.get('exempt_from_social_security') else 'No',
            # Bank Details
            'bank_name': emp.get('bank_name', ''),
            'bank_currency': emp.get('bank_currency', ''),
            'bank_account_number': emp.get('bank_account_number', ''),
            'bank_iban': emp.get('bank_iban', ''),
            'bank_account_name': emp.get('bank_account_name', ''),
            'bank_swift_code': emp.get('bank_swift_code', ''),
            'bank_address': emp.get('bank_address', ''),
            # ID Details
            'id_type': emp.get('id_type', ''),
            'id_number': emp.get('id_number', ''),
            'street_location': emp.get('street_location', '')
        }

        emp_allow = get_employee_allowance_dict(emp['id'])
        for defn in allowance_defs:
            col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
            row[col_name] = emp_allow.get(defn['id'], defn['default_value'])

        data.append(row)

    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Employees', index=False)

        worksheet = writer.sheets['Employees']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)

    return send_file(
        output,
        download_name=f'employees_{company["name"]}_{datetime.datetime.now().strftime("%Y%m%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/employees/download_template/<int:company_id>')
def download_employee_template(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    template_data = {
        'first_name': ['John'],
        'last_name': ['Doe'],
        'email': ['john.doe@example.com'],
        'position': ['Developer'],
        'department': ['Engineering'],
        'base_salary': [5000.00],
        'hire_date': ['2024-01-01'],
        'status': ['Active'],
        'is_tax_exempt': ['No'],
        'exempt_from_social_security': ['No'],
        # Bank Details
        'bank_name': ['First Bank'],
        'bank_currency': ['USD'],
        'bank_account_number': ['1234567890'],
        'bank_iban': ['GB29NWBK60161331926819'],
        'bank_account_name': ['John Doe'],
        'bank_swift_code': ['FIRSTUS33'],
        'bank_address': ['123 Main Street, New York, NY 10001'],
        # ID Details
        'id_type': ['National ID'],
        'id_number': ['ID-123456789'],
        'street_location': ['123 Main Street, Accra']
    }

    allowance_defs = get_allowance_definitions(company_id)
    for defn in allowance_defs:
        col_name = f'allowance_{defn["name"].lower().replace(" ", "_")}'
        template_data[col_name] = [defn['default_value']]

    df = pd.DataFrame(template_data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Employee_Template', index=False)

        worksheet = writer.sheets['Employee_Template']

        # Add column descriptions as comments
        from openpyxl.comments import Comment
        from openpyxl.utils import get_column_letter

        comments = {
            'first_name': 'Employee first name (required)',
            'last_name': 'Employee last name (required)',
            'email': 'Employee email address (required)',
            'position': 'Job position/title (required)',
            'department': 'Department name (required)',
            'base_salary': 'Monthly salary in company currency (required)',
            'hire_date': 'Hire date in YYYY-MM-DD format (required)',
            'status': 'Status: Active, Inactive, On Leave, Terminated, Consultant',
            'is_tax_exempt': 'Yes or No - If Yes, no income tax deducted',
            'exempt_from_social_security': 'Yes or No - If Yes, no Social Security deducted',
            'bank_name': 'Name of the bank',
            'bank_currency': 'Currency: USD, EUR, GBP, GHS, NGN, ZAR, KES',
            'bank_account_number': 'Bank account number',
            'bank_iban': 'IBAN number (International)',
            'bank_account_name': 'Name on the bank account',
            'bank_swift_code': 'SWIFT/BIC code',
            'bank_address': 'Bank branch address',
            'id_type': 'ID Type: National ID, Passport, Drivers License, Voter ID, SSNIT Number, Tax ID, Other',
            'id_number': 'ID number',
            'street_location': 'Physical address/street location'
        }

        # Add comments to header row
        for col_idx, (col_name, comment_text) in enumerate(comments.items(), 1):
            if col_name in template_data:
                col_letter = get_column_letter(col_idx)
                worksheet[f'{col_letter}1'].comment = Comment(comment_text, 'System')

        # Add instructions at the bottom
        instruction_row = len(template_data) + 2
        worksheet[f'A{instruction_row}'] = '📌 INSTRUCTIONS:'
        worksheet[f'A{instruction_row + 1}'] = '1. Fill in employee details - required columns are marked'
        worksheet[
            f'A{instruction_row + 2}'] = '2. For allowance columns, use the format: allowance_[name_lowercase_with_underscores]'
        worksheet[f'A{instruction_row + 3}'] = '3. Date format: YYYY-MM-DD (e.g., 2024-01-15)'
        worksheet[f'A{instruction_row + 4}'] = '4. For Yes/No columns, use: Yes or No'
        worksheet[
            f'A{instruction_row + 5}'] = '5. Bank details and ID details are optional but recommended for invoices'

        # Auto-size columns
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        worksheet.freeze_panes = 'A2'

    output.seek(0)

    return send_file(
        output,
        download_name=f'employee_template_{company["name"]}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================
# ROUTES - Payroll Export
# ============================================

@app.route('/payroll/export/<int:company_id>')
def export_payroll(company_id):
    company = get_company(company_id)
    if not company:
        flash('Company not found!', 'error')
        return redirect(url_for('list_companies'))

    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)

    if year and month:
        records = get_payroll_by_month(company_id, year, month)
    else:
        records = get_payroll_records_by_company(company_id)

    if not records:
        flash('No payroll records found for this company!', 'warning')
        return redirect(url_for('payroll_dashboard', company_id=company_id))

    data = []
    for rec in records:
        employee = get_employee(rec['employee_id'])
        if employee:
            allowance_details = json.loads(rec['allowance_details']) if rec['allowance_details'] else []
            deduction_details = json.loads(rec['deduction_details']) if rec['deduction_details'] else []
            bonus_details = json.loads(rec['bonus_details']) if rec['bonus_details'] else None

            row = {
                'Employee': f"{employee['first_name']} {employee['last_name']}",
                'Position': employee['position'],
                'Period': rec['period'],
                'Year': rec['year'],
                'Month': get_month_name(rec['month']),
                'Base Salary (Monthly)': rec['base_salary'],
                'Allowances Total': rec['allowances_total'],
                'Bonus': rec['bonus_amount'],
                'BIK': rec['bik_total'],
                'Deductions Total': rec['deductions_total'],
                'Gross Salary': rec['gross_salary'],
                'Annual Gross': rec['annual_gross'],
                'Annual Tax': rec['annual_tax'],
                'Monthly Tax': rec['monthly_tax'],
                'Bonus Flat Tax': rec['bonus_tax_flat'],
                'Total Tax': rec['total_tax'],
                'Social Security': rec['social_security'],
                'Social Security Threshold': rec['social_security_threshold_applied'],
                'Total Deductions': rec['total_deductions'],
                'Net Pay': rec['net_pay'],
                'Currency': rec['currency'],
                'Tax Year': rec['tax_year'],
                'Processed Date': rec['processed_date'],
                'Tax Exempt': 'Yes' if rec['is_tax_exempt'] else 'No',
                'SS Exempt': 'Yes' if rec['exempt_from_social_security'] else 'No'
            }

            for detail in allowance_details:
                row[f'Allowance_{detail["name"]}'] = detail['value']

            for detail in deduction_details:
                row[f'Deduction_{detail["name"]}'] = detail['value']

            if bonus_details:
                row['Bonus Threshold %'] = bonus_details.get('threshold_percentage', '')
                row['Bonus Threshold Amount'] = bonus_details.get('threshold_amount', '')
                row['Bonus Excess Amount'] = bonus_details.get('excess_amount', '')

            data.append(row)

    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Payroll_Report', index=False)

        worksheet = writer.sheets['Payroll_Report']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)

    return send_file(
        output,
        download_name=f'payroll_report_{company["name"]}_{datetime.datetime.now().strftime("%Y%m%d")}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================
# ROUTES - API
# ============================================

@app.route('/api/tax_brackets/<int:company_id>/<int:year>')
def get_tax_brackets_api(company_id, year):
    try:
        print(f"🔍 Fetching tax brackets for company {company_id}, year {year}")

        company = get_company(company_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        tax_config = get_tax_config(company_id, year)
        if not tax_config:
            return jsonify({'error': f'Tax configuration not found for year {year}'}), 404

        try:
            brackets_data = json.loads(tax_config['brackets'])
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing brackets JSON: {e}")
            return jsonify({'error': 'Invalid tax brackets configuration'}), 500

        processed_brackets = []
        for bracket in brackets_data:
            max_value = bracket.get('max')
            if max_value == float('inf') or max_value == 'Infinity' or max_value == 'inf':
                max_value = None
            processed_brackets.append({
                'min': bracket.get('min', 0),
                'max': max_value,
                'rate': bracket.get('rate', 0)
            })

        social_security_rate = tax_config['social_security_rate']
        social_security_threshold = tax_config['social_security_threshold']

        standard_deduction = tax_config.get('standard_deduction', 0)

        country = tax_config['country']
        if country.upper() == 'GHANA':
            standard_deduction = 0

        current_month = datetime.datetime.now().month
        monthly_threshold = get_social_security_threshold(company_id, year, current_month)

        response_data = {
            'brackets': processed_brackets,
            'social_security_rate': social_security_rate,
            'social_security_threshold': monthly_threshold,
            'standard_deduction': standard_deduction,
            'currency': company['base_currency'],
            'country': country
        }

        print(f"✅ API response: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        print(f"❌ Error in get_tax_brackets_api: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/available_years/<int:company_id>')
def get_available_years_api(company_id):
    try:
        company = get_company(company_id)
        if not company:
            return jsonify({'error': 'Company not found'}), 404

        configs = get_tax_configs_by_company(company_id)
        years = [c['year'] for c in configs]

        active_config = get_active_tax_config(company_id)
        active_year = active_config['year'] if active_config else (years[-1] if years else None)

        return jsonify({
            'years': sorted(years),
            'active_year': active_year
        })
    except Exception as e:
        print(f"Error in get_available_years_api: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/test')
def test_api():
    try:
        return jsonify({
            'status': 'success',
            'message': 'API is working',
            'timestamp': datetime.datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# APPLICATION INITIALIZATION
# ============================================

def initialize():
    """Initialize the payroll app's database"""
    with app.app_context():
        # Create database directory for SQLite
        if not IS_PRODUCTION and DATABASE:
            os.makedirs(os.path.dirname(DATABASE) or '.', exist_ok=True)

        init_db()
        migrate_database()
        # init_sample_data()

        if IS_PRODUCTION:
            print("✅ Payroll app initialized with PostgreSQL")
        else:
            print(f"✅ Payroll app initialized with SQLite: {DATABASE}")


# Initialize the app when module is imported (runs for both direct execution and wrapper)
initialize()


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Payroll Management System")
    print("=" * 60)
    print(f"📁 Database: {DATABASE if not IS_PRODUCTION else 'PostgreSQL (Render)'}")
    print("📍 Starting server at http://127.0.0.1:5000/paysys/")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)