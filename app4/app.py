# app4/app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, FloatField, SelectField, DateField, FieldList, FormField, HiddenField, \
    BooleanField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, ValidationError
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
import os
import re
import json
import traceback
import uuid
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-app4-secret-key-change-in-production')

# Initialize CSRF protection
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)

# Get base path for subpath mounting
BASE_PATH = os.environ.get('BASE_PATH', '')
if BASE_PATH:
    print(f"📁 App4 mounted at: {BASE_PATH}")

# ============ DATABASE CONFIGURATION ============
if os.environ.get('DATABASE_URL'):
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print(f"✅ App4 using shared PostgreSQL database")
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'app4.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f"✅ App4 using SQLite database at: {db_path}")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False

# ============ FOLDER CONFIGURATION ============
base_dir = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'static/uploads/logos')
app.config['SIGNATURE_FOLDER'] = os.path.join(base_dir, 'static/uploads/signatures')
app.config['ATTACHMENT_FOLDER'] = os.path.join(base_dir, 'static/uploads/attachments')
app.config['INVOICE_ATTACHMENT_FOLDER'] = os.path.join(base_dir, 'static/uploads/invoice_attachments')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'doc', 'docx', 'xls', 'xlsx'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SIGNATURE_FOLDER'], exist_ok=True)
os.makedirs(app.config['ATTACHMENT_FOLDER'], exist_ok=True)
os.makedirs(app.config['INVOICE_ATTACHMENT_FOLDER'], exist_ok=True)

# Initialize database
db = SQLAlchemy(app)


# ==================== CSRF EXEMPTION FOR API ROUTES ====================
def csrf_exempt_api(view_func):
    """Decorator to exempt API routes from CSRF protection"""
    csrf.exempt(view_func)
    return view_func


# ==================== CONTEXT PROCESSOR ====================
@app.context_processor
def inject_base_path():
    return dict(base_path=BASE_PATH)


# ==================== DATABASE MIGRATION HELPER ====================
def migrate_database():
    """Add new columns to existing tables without losing data"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)

        # Check if invoice tables exist, create them if not
        if 'invoices' not in inspector.get_table_names():
            print("🔧 Creating invoice tables...")
            db.create_all()
            print("✅ Invoice tables created")
            return

        # Check for new columns in invoices
        if 'invoices' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('invoices')]

            with db.engine.connect() as conn:
                # Add bank_id column
                if 'bank_id' not in columns:
                    print("🔧 Adding bank_id column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN bank_id INTEGER REFERENCES bank(id)"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN bank_id INTEGER REFERENCES bank(id)"))
                        conn.commit()
                        print("✅ Added bank_id column")
                    except Exception as e:
                        print(f"⚠️ Could not add bank_id column: {e}")

                # Add currency column
                if 'currency' not in columns:
                    print("🔧 Adding currency column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN currency VARCHAR(3) DEFAULT 'USD'"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN currency VARCHAR(3) DEFAULT 'USD'"))
                        conn.commit()
                        print("✅ Added currency column")
                    except Exception as e:
                        print(f"⚠️ Could not add currency column: {e}")

                # Add exchange_rate column
                if 'exchange_rate' not in columns:
                    print("🔧 Adding exchange_rate column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN exchange_rate NUMERIC(10, 4) DEFAULT 1.0000"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN exchange_rate FLOAT DEFAULT 1.0"))
                        conn.commit()
                        print("✅ Added exchange_rate column")
                    except Exception as e:
                        print(f"⚠️ Could not add exchange_rate column: {e}")

                # Add amount_paid column
                if 'amount_paid' not in columns:
                    print("🔧 Adding amount_paid column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN amount_paid NUMERIC(15, 2) DEFAULT 0.00"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN amount_paid FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added amount_paid column")
                    except Exception as e:
                        print(f"⚠️ Could not add amount_paid column: {e}")

                # Add payment_status column
                if 'payment_status' not in columns:
                    print("🔧 Adding payment_status column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'"))
                        else:
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'"))
                        conn.commit()
                        print("✅ Added payment_status column")
                    except Exception as e:
                        print(f"⚠️ Could not add payment_status column: {e}")

                # Add base currency columns
                if 'base_currency_subtotal' not in columns:
                    print("🔧 Adding base_currency_subtotal column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(text(
                                "ALTER TABLE invoices ADD COLUMN base_currency_subtotal NUMERIC(15, 2) DEFAULT 0.00"))
                        else:
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN base_currency_subtotal FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added base_currency_subtotal column")
                    except Exception as e:
                        print(f"⚠️ Could not add base_currency_subtotal column: {e}")

                if 'base_currency_tax' not in columns:
                    print("🔧 Adding base_currency_tax column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN base_currency_tax NUMERIC(15, 2) DEFAULT 0.00"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN base_currency_tax FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added base_currency_tax column")
                    except Exception as e:
                        print(f"⚠️ Could not add base_currency_tax column: {e}")

                if 'base_currency_total' not in columns:
                    print("🔧 Adding base_currency_total column to invoices...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoices ADD COLUMN base_currency_total NUMERIC(15, 2) DEFAULT 0.00"))
                        else:
                            conn.execute(text("ALTER TABLE invoices ADD COLUMN base_currency_total FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added base_currency_total column")
                    except Exception as e:
                        print(f"⚠️ Could not add base_currency_total column: {e}")

        # Check for new columns in invoice_items
        if 'invoice_items' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('invoice_items')]

            with db.engine.connect() as conn:
                if 'vat_rate' not in columns:
                    print("🔧 Adding vat_rate column to invoice_items...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoice_items ADD COLUMN vat_rate NUMERIC(5, 2) DEFAULT 0.0"))
                        else:
                            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN vat_rate FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added vat_rate column")
                    except Exception as e:
                        print(f"⚠️ Could not add vat_rate column: {e}")

                if 'vat_amount' not in columns:
                    print("🔧 Adding vat_amount column to invoice_items...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoice_items ADD COLUMN vat_amount NUMERIC(15, 2) DEFAULT 0.0"))
                        else:
                            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN vat_amount FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added vat_amount column")
                    except Exception as e:
                        print(f"⚠️ Could not add vat_amount column: {e}")

                if 'levy_rate' not in columns:
                    print("🔧 Adding levy_rate column to invoice_items...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoice_items ADD COLUMN levy_rate NUMERIC(5, 2) DEFAULT 0.0"))
                        else:
                            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN levy_rate FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added levy_rate column")
                    except Exception as e:
                        print(f"⚠️ Could not add levy_rate column: {e}")

                if 'levy_amount' not in columns:
                    print("🔧 Adding levy_amount column to invoice_items...")
                    try:
                        if os.environ.get('DATABASE_URL'):
                            conn.execute(
                                text("ALTER TABLE invoice_items ADD COLUMN levy_amount NUMERIC(15, 2) DEFAULT 0.0"))
                        else:
                            conn.execute(text("ALTER TABLE invoice_items ADD COLUMN levy_amount FLOAT DEFAULT 0.0"))
                        conn.commit()
                        print("✅ Added levy_amount column")
                    except Exception as e:
                        print(f"⚠️ Could not add levy_amount column: {e}")

        print("✅ Database migration completed successfully")
    except Exception as e:
        print(f"⚠️ Migration warning: {e}")


# ==================== DATABASE INITIALIZATION FUNCTION ====================
def init_db():
    """Initialize database - create tables and default data"""
    with app.app_context():
        db.create_all()
        print(f"✅ Database tables created/verified")

        migrate_database()

        if Company.query.count() == 0:
            company = Company(
                name='Default Company',
                base_currency='GHS',
                is_active=True
            )
            db.session.add(company)
            db.session.commit()
            print('✅ Default company created: Default Company (GHS)')
        else:
            active_company = Company.query.filter_by(is_active=True).first()
            if not active_company:
                first_company = Company.query.first()
                if first_company:
                    first_company.is_active = True
                    db.session.commit()
                    print(f'✅ Activated existing company: {first_company.name}')

        if User.query.count() == 0:
            active_company = get_active_company()
            if active_company:
                admin = User(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    email='admin@example.com',
                    full_name='Administrator',
                    role='admin',
                    company_id=active_company.id,
                    is_active=True
                )
                db.session.add(admin)
                db.session.commit()
                print('✅ Default admin user created: admin / admin123')

        if Customer.query.count() == 0:
            active_company = get_active_company()
            if active_company:
                admin = User.query.filter_by(username='admin').first()
                customer = Customer(
                    name='Sample Client',
                    email='client@example.com',
                    phone='+1 (555) 987-6543',
                    address='456 Client Ave, City, State',
                    company_id=active_company.id,
                    created_by=admin.id if admin else None
                )
                db.session.add(customer)
                db.session.commit()
                print('✅ Sample customer created!')


# ==================== MODELS ====================
class Company(db.Model):
    __tablename__ = 'company'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    base_currency = db.Column(db.String(3), nullable=False, default='GHS')
    logo_filename = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=False)

    suppliers = db.relationship('Supplier', backref='company', lazy=True)
    payments = db.relationship('Payment', backref='company', lazy=True)
    signatures = db.relationship('AuthorizedSignature', backref='company', lazy=True)
    banks = db.relationship('Bank', backref='company', lazy=True)
    customers = db.relationship('Customer', backref='company', lazy=True)
    invoices = db.relationship('Invoice', backref='company', lazy=True)
    users = db.relationship('User', backref='company', lazy=True)


class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(50), default='user')
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)


class Customer(db.Model):
    __tablename__ = 'customers'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    address = db.Column(db.String(500))
    tax_id = db.Column(db.String(50))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # This needs to be a ForeignKey to users.id
    created_by = db.Column(db.Integer, nullable=True)

    invoices = db.relationship('Invoice', backref='customer', lazy=True)

class Invoice(db.Model):
    __tablename__ = 'invoices'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    created_by = db.Column(db.Integer, nullable=True)  # No ForeignKey

    invoice_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)

    # Currency fields
    currency = db.Column(db.String(3), nullable=False, default='USD')
    exchange_rate = db.Column(db.Numeric(10, 4), default=1.0000)

    subtotal = db.Column(db.Numeric(15, 2), default=0.00)
    tax_rate = db.Column(db.Numeric(5, 2), default=0.00)
    tax_amount = db.Column(db.Numeric(15, 2), default=0.00)
    discount = db.Column(db.Numeric(15, 2), default=0.00)
    total = db.Column(db.Numeric(15, 2), default=0.00)

    # Payment tracking fields
    amount_paid = db.Column(db.Numeric(15, 2), default=0.00)
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid, partial, paid

    # Bank selection for payment
    bank_id = db.Column(db.Integer, db.ForeignKey('bank.id'))

    # Base currency equivalent (for reporting in company currency)
    base_currency_subtotal = db.Column(db.Numeric(15, 2), default=0.00)
    base_currency_tax = db.Column(db.Numeric(15, 2), default=0.00)
    base_currency_total = db.Column(db.Numeric(15, 2), default=0.00)

    status = db.Column(db.String(20), default='draft')  # draft, sent, paid, overdue, cancelled
    notes = db.Column(db.Text)
    terms = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('InvoicePayment', backref='invoice', lazy=True, cascade='all, delete-orphan')

    # Relationship to bank
    bank = db.relationship('Bank', backref='invoices', lazy=True)


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))

    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), default=1.00)
    unit_price = db.Column(db.Numeric(15, 2), default=0.00)
    total = db.Column(db.Numeric(15, 2), default=0.00)

    vat_rate = db.Column(db.Numeric(5, 2), default=0.00)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00)
    levy_rate = db.Column(db.Numeric(5, 2), default=0.00)
    levy_amount = db.Column(db.Numeric(15, 2), default=0.00)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InvoicePayment(db.Model):
    __tablename__ = 'invoice_payments'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))

    payment_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    payment_method = db.Column(db.String(50))
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=True)  # No ForeignKey


class Supplier(db.Model):
    __tablename__ = 'supplier'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text)
    telephone = db.Column(db.String(20))
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    account_name = db.Column(db.String(100))
    swift_code = db.Column(db.String(20))
    bank_address = db.Column(db.Text)
    email = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    payments = db.relationship('Payment', backref='supplier', lazy=True)


class AuthorizedSignature(db.Model):
    __tablename__ = 'authorized_signature'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100))
    signature_filename = db.Column(db.String(200))
    role = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    prepared_payments = db.relationship('Payment', foreign_keys='Payment.prepared_by_id', backref='preparer')
    approved_payments = db.relationship('Payment', foreign_keys='Payment.approved_by_id', backref='approver')
    received_payments = db.relationship('Payment', foreign_keys='Payment.received_by_id', backref='receiver')


class Bank(db.Model):
    __tablename__ = 'bank'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    bank_code = db.Column(db.String(20))
    account_number = db.Column(db.String(50))
    account_name = db.Column(db.String(100))
    branch = db.Column(db.String(100))
    address = db.Column(db.Text)
    swift_code = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    payments = db.relationship('Payment', backref='source_bank', lazy=True)


class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(20), unique=True, nullable=False)
    invoice_number = db.Column(db.String(50))
    currency = db.Column(db.String(3), nullable=False)
    exchange_rate = db.Column(db.Float, default=1.0)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.Text)
    reference = db.Column(db.String(100))
    attachment_filename = db.Column(db.String(200))
    attachment_original_name = db.Column(db.String(200))
    attachment_size = db.Column(db.Integer)
    attachment_uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    prepared_by_id = db.Column(db.Integer, db.ForeignKey('authorized_signature.id'))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('authorized_signature.id'))
    received_by_id = db.Column(db.Integer, db.ForeignKey('authorized_signature.id'))
    source_bank_id = db.Column(db.Integer, db.ForeignKey('bank.id'))
    total_gross_amount = db.Column(db.Float, default=0.0)
    total_wht_amount = db.Column(db.Float, default=0.0)
    total_vat_amount = db.Column(db.Float, default=0.0)
    total_net_amount = db.Column(db.Float, default=0.0)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    line_items = db.relationship('PaymentLineItem', backref='payment', lazy=True, cascade='all, delete-orphan')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentLineItem(db.Model):
    __tablename__ = 'payment_line_item'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    withholding_tax_rate = db.Column(db.Float, default=0.0)
    vat_rate = db.Column(db.Float, default=0.0)
    withholding_tax_amount = db.Column(db.Float, default=0.0)
    vat_amount = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==================== UTILITY FUNCTIONS ====================
def generate_password_hash(password):
    from werkzeug.security import generate_password_hash as _generate_password_hash
    return _generate_password_hash(password)


def get_active_company():
    return Company.query.filter_by(is_active=True).first()


def get_attachment_url(filename):
    if filename:
        return url_for('static', filename=f'uploads/attachments/{filename}')
    return None


def delete_attachment_file(filename):
    if filename:
        file_path = os.path.join(app.config['ATTACHMENT_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    return False


def format_file_size(size_bytes):
    if not size_bytes:
        return 'N/A'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"


def generate_invoice_number():
    """Generate a unique invoice number"""
    db_session = db.session
    year = datetime.now().strftime('%Y')
    month = datetime.now().strftime('%m')

    last_invoice = db_session.query(Invoice).filter(
        Invoice.invoice_number.like(f'INV-{year}{month}%')
    ).order_by(Invoice.invoice_number.desc()).first()

    if last_invoice:
        seq = int(last_invoice.invoice_number.split('-')[-1]) + 1
    else:
        seq = 1

    return f"INV-{year}{month}-{seq:04d}"


def get_exchange_rate(currency):
    exchange_rates = {
        'USD': 1.0, 'EUR': 0.92, 'GBP': 0.79, 'GHS': 15.0, 'JPY': 149.0,
        'CHF': 0.88, 'CAD': 1.36, 'AUD': 1.53, 'CNY': 7.25, 'INR': 83.0,
        'BRL': 5.10, 'ZAR': 18.50, 'AED': 3.67, 'NGN': 1500.0, 'KES': 150.0,
        'TZS': 2500.0, 'UGX': 3700.0, 'ZMW': 26.0
    }
    return exchange_rates.get(currency, 1.0)


def calculate_line_item_totals(quantity, unit_price, wht_rate, vat_rate):
    total = quantity * unit_price
    wht_amount = (total * wht_rate) / 100 if wht_rate else 0
    vat_amount = (total * vat_rate) / 100 if vat_rate else 0
    net_amount = total - wht_amount + vat_amount
    return {
        'total': round(total, 2),
        'wht_amount': round(wht_amount, 2),
        'vat_amount': round(vat_amount, 2),
        'net_amount': round(net_amount, 2)
    }


def calculate_invoice_item_totals(quantity, unit_price, vat_rate, levy_rate):
    subtotal = quantity * unit_price
    vat_amount = (subtotal * vat_rate) / 100 if vat_rate else 0
    levy_amount = (subtotal * levy_rate) / 100 if levy_rate else 0
    total = subtotal + vat_amount + levy_amount
    return {
        'subtotal': round(subtotal, 2),
        'vat_amount': round(vat_amount, 2),
        'levy_amount': round(levy_amount, 2),
        'total': round(total, 2)
    }


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_user_by_id(user_id):
    """Get a user by ID from the auth system"""
    if not user_id:
        return None
    return User.query.get(user_id)

# ==================== FORMS ====================
class CustomerForm(FlaskForm):
    name = StringField('Customer Name', validators=[DataRequired(), Length(max=200)])
    email = StringField('Email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    address = TextAreaField('Address', validators=[Optional()])
    tax_id = StringField('Tax ID', validators=[Optional(), Length(max=50)])


class InvoiceItemForm(FlaskForm):
    description = StringField('Description', validators=[DataRequired(), Length(max=500)])
    quantity = FloatField('Quantity', validators=[DataRequired(), NumberRange(min=0.01)], default=1.0)
    unit_price = FloatField('Unit Price', validators=[DataRequired(), NumberRange(min=0.01)])
    vat_rate = FloatField('VAT Rate (%)', validators=[Optional(), NumberRange(min=0, max=100)], default=0.0)
    levy_rate = FloatField('Levy Rate (%)', validators=[Optional(), NumberRange(min=0, max=100)], default=0.0)


class InvoiceForm(FlaskForm):
    customer_id = SelectField('Customer', coerce=int, validators=[DataRequired()])
    invoice_date = DateField('Invoice Date', format='%Y-%m-%d', validators=[DataRequired()])
    due_date = DateField('Due Date', format='%Y-%m-%d', validators=[DataRequired()])
    currency = SelectField('Currency', choices=[
        ('USD', 'USD - US Dollar'), ('EUR', 'EUR - Euro'), ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'), ('JPY', 'JPY - Japanese Yen'), ('CHF', 'CHF - Swiss Franc'),
        ('CAD', 'CAD - Canadian Dollar'), ('AUD', 'AUD - Australian Dollar'), ('CNY', 'CNY - Chinese Yuan'),
        ('INR', 'INR - Indian Rupee'), ('BRL', 'BRL - Brazilian Real'), ('ZAR', 'ZAR - South African Rand'),
        ('AED', 'AED - UAE Dirham'), ('NGN', 'NGN - Nigerian Naira'), ('KES', 'KES - Kenyan Shilling'),
        ('TZS', 'TZS - Tanzanian Shilling'), ('UGX', 'UGX - Ugandan Shilling'), ('ZMW', 'ZMW - Zambian Kwacha')
    ], validators=[DataRequired()], default='USD')
    exchange_rate = FloatField('Exchange Rate (1 USD = ?)', validators=[Optional(), NumberRange(min=0.01)], default=1.0)
    bank_id = SelectField('Bank Account', coerce=int, validators=[Optional()])
    discount = FloatField('Discount', validators=[Optional(), NumberRange(min=0)], default=0.0)
    notes = TextAreaField('Notes', validators=[Optional()])
    terms = TextAreaField('Terms', validators=[Optional()])
    items = FieldList(FormField(InvoiceItemForm), min_entries=1)

    def __init__(self, *args, **kwargs):
        super(InvoiceForm, self).__init__(*args, **kwargs)
        active_company = get_active_company()
        if active_company:
            customers = Customer.query.filter_by(company_id=active_company.id).all()
            customers = sorted(customers, key=lambda c: c.name.lower())
            self.customer_id.choices = [(0, '-- Select Customer --')] + [(c.id, c.name) for c in customers]

            # Add bank choices
            banks = Bank.query.filter_by(company_id=active_company.id, is_active=True).all()
            banks = sorted(banks, key=lambda b: b.name.lower())
            self.bank_id.choices = [(0, '-- Select Bank --')] + [(b.id, f"{b.name} - {b.account_number or 'N/A'}") for b
                                                                 in banks]
        else:
            self.customer_id.choices = [(0, '-- No customers available --')]
            self.bank_id.choices = [(0, '-- No banks available --')]


class InvoicePaymentForm(FlaskForm):
    payment_date = DateField('Payment Date', format='%Y-%m-%d', validators=[DataRequired()])
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'), ('bank_transfer', 'Bank Transfer'), ('cheque', 'Cheque'),
        ('credit_card', 'Credit Card'), ('mobile_money', 'Mobile Money'), ('other', 'Other')
    ], validators=[DataRequired()])
    reference = StringField('Reference Number', validators=[Optional(), Length(max=100)])
    notes = TextAreaField('Notes', validators=[Optional()])


class InvoiceImportForm(FlaskForm):
    file = FileField('Excel File', validators=[
        DataRequired(),
        FileAllowed(['xlsx', 'xls', 'xlsm'], 'Excel files only!')
    ])


class SignatureForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    title = StringField('Title/Position', validators=[Optional(), Length(max=100)])
    role = SelectField('Role', choices=[('Preparer', 'Preparer'), ('Approver', 'Approver'), ('Receiver', 'Receiver')],
                       validators=[DataRequired()])
    signature_image = FileField('Signature Image',
                                validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    is_active = SelectField('Status', choices=[('True', 'Active'), ('False', 'Inactive')], default='True')


class LineItemForm(FlaskForm):
    description = StringField('Description', validators=[DataRequired(), Length(max=200)])
    quantity = FloatField('Quantity', validators=[DataRequired(), NumberRange(min=0.01)], default=1.0)
    unit_price = FloatField('Unit Price', validators=[DataRequired(), NumberRange(min=0.01)])
    withholding_tax_rate = FloatField('WHT Rate (%)', validators=[Optional(), NumberRange(min=0, max=100)], default=0.0)
    vat_rate = FloatField('VAT Rate (%)', validators=[Optional(), NumberRange(min=0, max=100)], default=0.0)


class PaymentForm(FlaskForm):
    supplier_id = SelectField('Supplier', coerce=int, validators=[DataRequired()])
    invoice_number = StringField('Invoice Number', validators=[Optional(), Length(max=50)])
    currency = SelectField('Currency', choices=[
        ('', '-- Select Currency --'), ('USD', 'USD - US Dollar'), ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'), ('GHS', 'GHS - Ghana Cedi'), ('JPY', 'JPY - Japanese Yen'),
        ('CHF', 'CHF - Swiss Franc'), ('CAD', 'CAD - Canadian Dollar'), ('AUD', 'AUD - Australian Dollar'),
        ('CNY', 'CNY - Chinese Yuan'), ('INR', 'INR - Indian Rupee'), ('BRL', 'BRL - Brazilian Real'),
        ('ZAR', 'ZAR - South African Rand'), ('AED', 'AED - UAE Dirham'), ('NGN', 'NGN - Nigerian Naira'),
        ('KES', 'KES - Kenyan Shilling'), ('TZS', 'TZS - Tanzanian Shilling'), ('UGX', 'UGX - Ugandan Shilling'),
        ('ZMW', 'ZMW - Zambian Kwacha')
    ], validators=[DataRequired()], default='')
    exchange_rate = FloatField('Exchange Rate (1 USD = ?)', validators=[Optional(), NumberRange(min=0.01)], default=1.0)
    payment_date = DateField('Payment Date', format='%Y-%m-%d', validators=[Optional()])
    description = TextAreaField('Payment Description', validators=[Optional()])
    reference = StringField('Reference Number', validators=[Optional()])
    attachment = FileField('Attachment', validators=[Optional(), FileAllowed(
        ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx'], 'Allowed: PDF, Images, Word, Excel')])
    prepared_by_id = SelectField('Prepared By', coerce=int, validators=[Optional()])
    approved_by_id = SelectField('Approved By', coerce=int, validators=[Optional()])
    received_by_id = SelectField('Received By', coerce=int, validators=[Optional()])
    source_bank_id = SelectField('Source Bank', coerce=int, validators=[Optional()])
    line_items = FieldList(FormField(LineItemForm), min_entries=1)

    def __init__(self, *args, **kwargs):
        super(PaymentForm, self).__init__(*args, **kwargs)
        active_company = get_active_company()
        if active_company:
            suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
            suppliers = sorted(suppliers, key=lambda s: s.name.lower())
            self.supplier_id.choices = [(0, '-- Select Supplier --')] + [(s.id, s.name) for s in suppliers]
        else:
            self.supplier_id.choices = [(0, '-- No suppliers available --')]
        default_choices = [(0, '-- Select --')]
        if active_company:
            signatures = AuthorizedSignature.query.filter_by(company_id=active_company.id, is_active=True).all()
            if signatures:
                signature_choices = [(s.id, f"{s.name} ({s.role})") for s in signatures]
                self.prepared_by_id.choices = default_choices + signature_choices
                self.approved_by_id.choices = default_choices + signature_choices
                self.received_by_id.choices = default_choices + signature_choices
            else:
                self.prepared_by_id.choices = [(0, '-- No signatures available --')]
                self.approved_by_id.choices = [(0, '-- No signatures available --')]
                self.received_by_id.choices = [(0, '-- No signatures available --')]
            banks = Bank.query.filter_by(company_id=active_company.id, is_active=True).all()
            if banks:
                bank_choices = [(b.id, b.name) for b in banks]
                self.source_bank_id.choices = [(0, '-- Select Bank --')] + bank_choices
            else:
                self.source_bank_id.choices = [(0, '-- No banks available --')]
        else:
            self.prepared_by_id.choices = [(0, '-- Select --')]
            self.approved_by_id.choices = [(0, '-- Select --')]
            self.received_by_id.choices = [(0, '-- Select --')]
            self.source_bank_id.choices = [(0, '-- Select Bank --')]


class SupplierForm(FlaskForm):
    name = StringField('Supplier Name', validators=[DataRequired(), Length(max=100)])
    address = TextAreaField('Address', validators=[Optional()])
    telephone = StringField('Telephone Number', validators=[Optional(), Length(max=20)])
    bank_name = StringField('Bank Name', validators=[Optional(), Length(max=100)])
    account_number = StringField('Account Number/IBAN', validators=[Optional(), Length(max=50)])
    account_name = StringField('Account Name', validators=[Optional(), Length(max=100)])
    swift_code = StringField('SWIFT Code', validators=[Optional(), Length(max=20)])
    bank_address = TextAreaField('Bank Address', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    tax_id = StringField('Tax ID/VAT Number', validators=[Optional()])

    def validate_swift_code(self, field):
        if field.data and not re.match(r'^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$', field.data):
            raise ValidationError('Invalid SWIFT code format. Format: 8-11 characters, letters and numbers')


class CompanyForm(FlaskForm):
    name = StringField('Company Name', validators=[DataRequired(), Length(max=100)])
    base_currency = SelectField('Base Currency', choices=[
        ('USD', 'USD - US Dollar'), ('EUR', 'EUR - Euro'), ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'), ('JPY', 'JPY - Japanese Yen'), ('CHF', 'CHF - Swiss Franc'),
        ('CAD', 'CAD - Canadian Dollar'), ('AUD', 'AUD - Australian Dollar'), ('CNY', 'CNY - Chinese Yuan'),
        ('INR', 'INR - Indian Rupee'), ('BRL', 'BRL - Brazilian Real'), ('ZAR', 'ZAR - South African Rand'),
        ('AED', 'AED - UAE Dirham'), ('NGN', 'NGN - Nigerian Naira'), ('KES', 'KES - Kenyan Shilling'),
        ('TZS', 'TZS - Tanzanian Shilling'), ('UGX', 'UGX - Ugandan Shilling'), ('ZMW', 'ZMW - Zambian Kwacha')
    ], validators=[DataRequired()])
    logo = FileField('Company Logo',
                     validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'svg'], 'Images only!')])


class BankForm(FlaskForm):
    name = StringField('Bank Name', validators=[DataRequired(), Length(max=100)])
    bank_code = StringField('Bank Code', validators=[Optional(), Length(max=20)])
    account_number = StringField('Account Number', validators=[Optional(), Length(max=50)])
    account_name = StringField('Account Name', validators=[Optional(), Length(max=100)])
    branch = StringField('Branch', validators=[Optional(), Length(max=100)])
    address = TextAreaField('Bank Address', validators=[Optional()])
    swift_code = StringField('SWIFT Code', validators=[Optional(), Length(max=20)])
    is_active = SelectField('Status', choices=[('True', 'Active'), ('False', 'Inactive')], default='True')


class ReportForm(FlaskForm):
    date_from = DateField('Date From', format='%Y-%m-%d', validators=[DataRequired()])
    date_to = DateField('Date To', format='%Y-%m-%d', validators=[DataRequired()])
    supplier_id = SelectField('Supplier', coerce=int, validators=[Optional()])
    format = SelectField('Download Format', choices=[('pdf', 'PDF'), ('excel', 'Excel')], validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        super(ReportForm, self).__init__(*args, **kwargs)
        active_company = get_active_company()
        if active_company:
            suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
            suppliers = sorted(suppliers, key=lambda s: s.name.lower())
            self.supplier_id.choices = [(0, '-- All Suppliers --')] + [(s.id, s.name) for s in suppliers]
        else:
            self.supplier_id.choices = [(0, '-- No Suppliers --')]


class PaymentImportForm(FlaskForm):
    file = FileField('Excel File', validators=[
        DataRequired(),
        FileAllowed(['xlsx', 'xls', 'xlsm'], 'Excel files only!')
    ])

class InvoicePaymentReportForm(FlaskForm):
    date_from = DateField('Date From', format='%Y-%m-%d', validators=[DataRequired()])
    date_to = DateField('Date To', format='%Y-%m-%d', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    payment_status = SelectField('Payment Status', choices=[
        ('', 'All Statuses'),
        ('unpaid', 'Unpaid'),
        ('partial', 'Partial'),
        ('paid', 'Paid')
    ], validators=[Optional()])
    format = SelectField('Download Format', choices=[('pdf', 'PDF'), ('excel', 'Excel')], validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        super(InvoicePaymentReportForm, self).__init__(*args, **kwargs)
        active_company = get_active_company()
        if active_company:
            customers = Customer.query.filter_by(company_id=active_company.id).all()
            customers = sorted(customers, key=lambda c: c.name.lower())
            self.customer_id.choices = [(0, '-- All Customers --')] + [(c.id, c.name) for c in customers]
        else:
            self.customer_id.choices = [(0, '-- No Customers --')]

# ==================== REPORT FUNCTIONS ====================
def generate_wht_report(company_id, date_from, date_to, supplier_id=None):
    query = Payment.query.filter(
        Payment.company_id == company_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to,
        Payment.total_wht_amount > 0
    )
    if supplier_id:
        query = query.filter(Payment.supplier_id == supplier_id)
    payments = query.all()
    report_data = []
    total_wht = 0
    total_gross = 0
    for payment in payments:
        for item in payment.line_items:
            if item.withholding_tax_amount > 0:
                report_data.append({
                    'Transaction #': payment.transaction_number,
                    'Date': payment.payment_date.strftime('%d-%m-%Y'),
                    'Supplier': payment.supplier.name,
                    'Invoice #': payment.invoice_number or 'N/A',
                    'Description': item.description,
                    'Gross Amount': item.total_amount,
                    'WHT Rate (%)': item.withholding_tax_rate,
                    'WHT Amount': item.withholding_tax_amount,
                    'Currency': payment.currency
                })
                total_wht += item.withholding_tax_amount
                total_gross += item.total_amount
    return report_data, total_wht, total_gross


def generate_vat_report(company_id, date_from, date_to, supplier_id=None):
    query = Payment.query.filter(
        Payment.company_id == company_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to,
        Payment.total_vat_amount > 0
    )
    if supplier_id:
        query = query.filter(Payment.supplier_id == supplier_id)
    payments = query.all()
    report_data = []
    total_vat = 0
    total_gross = 0
    for payment in payments:
        for item in payment.line_items:
            if item.vat_amount > 0:
                report_data.append({
                    'Transaction #': payment.transaction_number,
                    'Date': payment.payment_date.strftime('%d-%m-%Y'),
                    'Supplier': payment.supplier.name,
                    'Invoice #': payment.invoice_number or 'N/A',
                    'Description': item.description,
                    'Gross Amount': item.total_amount,
                    'VAT Rate (%)': item.vat_rate,
                    'VAT Amount': item.vat_amount,
                    'Currency': payment.currency
                })
                total_vat += item.vat_amount
                total_gross += item.total_amount
    return report_data, total_vat, total_gross


def generate_supplier_transactions_report(company_id, date_from, date_to, supplier_id=None):
    query = Payment.query.filter(
        Payment.company_id == company_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    )
    if supplier_id:
        query = query.filter(Payment.supplier_id == supplier_id)
    payments = query.all()
    payments = sorted(payments, key=lambda p: p.supplier.name.lower())
    report_data = []
    total_net = 0
    for payment in payments:
        for item in payment.line_items:
            report_data.append({
                'Transaction #': payment.transaction_number,
                'Date': payment.payment_date.strftime('%d-%m-%Y'),
                'Supplier': payment.supplier.name,
                'Invoice #': payment.invoice_number or 'N/A',
                'Description': item.description,
                'Quantity': item.quantity,
                'Unit Price': item.unit_price,
                'Gross Amount': item.total_amount,
                'WHT Amount': item.withholding_tax_amount or 0,
                'VAT Amount': item.vat_amount or 0,
                'Net Amount': item.net_amount,
                'Currency': payment.currency,
                'Source Bank': payment.source_bank.name if payment.source_bank else 'N/A'
            })
            total_net += item.net_amount
    return report_data, total_net


def generate_report_excel(report_data, title, total_amount, currency):
    if not report_data:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(report_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Report', index=False)
        summary_data = {
            'Report Title': [title],
            'Generated On': [datetime.now().strftime('%d-%m-%Y %H:%M')],
            'Total Records': [len(report_data)],
            'Total Amount': [f"{total_amount:,.2f} {currency}"]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
    output.seek(0)
    return output.getvalue()


def generate_report_pdf(report_data, title, total_amount, currency, report_type):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=8,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6,
        textColor=colors.black,
        fontName='Helvetica-Bold',
        alignment=TA_CENTER
    )
    normal_style = ParagraphStyle(
        'NormalStyle',
        parent=styles['Normal'],
        fontSize=8,
        spaceAfter=2,
        textColor=colors.black,
        fontName='Helvetica'
    )
    elements = []
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 6))
    if report_data:
        date_from = report_data[0]['Date']
        date_to = report_data[-1]['Date']
        elements.append(Paragraph(f'Period: {date_from} to {date_to}', heading_style))
    elements.append(Spacer(1, 6))
    if report_data:
        if report_type == 'wht':
            col_headers = ['#', 'Transaction #', 'Date', 'Supplier', 'Invoice #', 'Description', 'Gross Amount',
                           'WHT Rate', 'WHT Amount', 'Currency']
            col_widths = [0.3 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch, 0.7 * inch, 1.2 * inch, 0.7 * inch,
                          0.6 * inch, 0.7 * inch, 0.5 * inch]
            data = []
            for idx, row in enumerate(report_data, 1):
                data.append([
                    str(idx), row['Transaction #'], row['Date'], row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:30] + '...' if len(row['Description']) > 30 else row['Description'],
                    f"{row['Gross Amount']:,.2f}", f"{row['WHT Rate (%)']:.2f}%",
                    f"{row['WHT Amount']:,.2f}", row['Currency']
                ])
        elif report_type == 'vat':
            col_headers = ['#', 'Transaction #', 'Date', 'Supplier', 'Invoice #', 'Description', 'Gross Amount',
                           'VAT Rate', 'VAT Amount', 'Currency']
            col_widths = [0.3 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch, 0.7 * inch, 1.2 * inch, 0.7 * inch,
                          0.6 * inch, 0.7 * inch, 0.5 * inch]
            data = []
            for idx, row in enumerate(report_data, 1):
                data.append([
                    str(idx), row['Transaction #'], row['Date'], row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:30] + '...' if len(row['Description']) > 30 else row['Description'],
                    f"{row['Gross Amount']:,.2f}", f"{row['VAT Rate (%)']:.2f}%",
                    f"{row['VAT Amount']:,.2f}", row['Currency']
                ])
        else:
            col_headers = ['#', 'Transaction #', 'Date', 'Supplier', 'Invoice #', 'Description', 'Gross', 'WHT', 'VAT',
                           'Net', 'Currency']
            col_widths = [0.3 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch, 0.7 * inch, 1.0 * inch, 0.6 * inch,
                          0.6 * inch, 0.6 * inch, 0.6 * inch, 0.5 * inch]
            data = []
            for idx, row in enumerate(report_data, 1):
                data.append([
                    str(idx), row['Transaction #'], row['Date'], row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:25] + '...' if len(row['Description']) > 25 else row['Description'],
                    f"{row['Gross Amount']:,.2f}", f"{row['WHT Amount']:,.2f}",
                    f"{row['VAT Amount']:,.2f}", f"{row['Net Amount']:,.2f}", row['Currency']
                ])
        table_data = [col_headers] + data
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('FONTSIZE', (0, 1), (-1, -2), 7),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f'Total {title}: {total_amount:,.2f} {currency}', normal_style))
        elements.append(Paragraph(f'Total Records: {len(report_data)}', normal_style))
    elements.append(Spacer(1, 20))
    footer_text = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M')}"
    elements.append(Paragraph(footer_text, normal_style))
    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data


def generate_invoice_pdf(invoice):
    """Generate PDF for an invoice with simplified line items"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()

    # Create custom styles with Helvetica
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=24,
        alignment=TA_CENTER,
        spaceAfter=8,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=4,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    normal_style = ParagraphStyle(
        'NormalStyle',
        parent=styles['Normal'],
        fontSize=9,
        spaceAfter=2,
        textColor=colors.black,
        fontName='Helvetica'
    )
    value_style = ParagraphStyle(
        'ValueStyle',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Helvetica-Bold',
        spaceAfter=2,
        textColor=colors.black
    )

    # Get currency code
    currency_code = invoice.currency or 'USD'

    elements = []
    company = invoice.company

    # Company header
    if company and company.logo_filename:
        try:
            logo_path = os.path.join(app.config['UPLOAD_FOLDER'], company.logo_filename)
            if os.path.exists(logo_path):
                img = Image(logo_path, width=1.5 * inch, height=0.75 * inch)
                elements.append(img)
                elements.append(Spacer(1, 4))
        except:
            pass
    if company:
        elements.append(Paragraph(company.name, title_style))
        elements.append(Paragraph("INVOICE", heading_style))
    elements.append(Spacer(1, 10))

    # Invoice header info
    col_widths = [3 * inch, 3 * inch]
    info_data = []
    left_info = [
        f"<b>Invoice Number:</b> {invoice.invoice_number}",
        f"<b>Date:</b> {invoice.invoice_date.strftime('%B %d, %Y') if invoice.invoice_date else 'N/A'}",
        f"<b>Due Date:</b> {invoice.due_date.strftime('%B %d, %Y') if invoice.due_date else 'N/A'}",
        f"<b>Currency:</b> {currency_code}"
    ]
    if invoice.exchange_rate and float(invoice.exchange_rate) != 1.0:
        left_info.append(
            f"<b>Exchange Rate:</b> 1 {invoice.company.base_currency if invoice.company else 'USD'} = {float(invoice.exchange_rate):.4f} {currency_code}")
    right_info = []
    if invoice.customer:
        right_info = [
            f"<b>Bill To:</b>",
            f"{invoice.customer.name}",
            f"{invoice.customer.address}" if invoice.customer.address else "",
            f"Tel: {invoice.customer.phone}" if invoice.customer.phone else "",
            f"Email: {invoice.customer.email}" if invoice.customer.email else "",
            f"Tax ID: {invoice.customer.tax_id}" if invoice.customer.tax_id else ""
        ]
    max_rows = max(len(left_info), len(right_info))
    while len(left_info) < max_rows:
        left_info.append('')
    while len(right_info) < max_rows:
        right_info.append('')
    for i in range(max_rows):
        info_data.append([Paragraph(left_info[i], normal_style), Paragraph(right_info[i], normal_style)])
    info_table = Table(info_data, colWidths=col_widths)
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # Simplified Line items: Description, Qty, Unit Price, Total
    if invoice.items:
        elements.append(Paragraph("Line Items", heading_style))
        elements.append(Spacer(1, 4))
        line_data = []

        # Simple headers - only 5 columns
        headers = [
            '#',
            'Description',
            'Qty',
            f'Unit Price\n({currency_code})',
            f'Total\n({currency_code})'
        ]
        line_data.append([Paragraph(h, normal_style) for h in headers])

        total_amount = 0

        # Track max content length for ALL columns with minimum values
        max_lengths = [1, 10, 3, 8, 8]  # Minimum lengths for each column
        # Index 0: #, 1: Description, 2: Qty, 3: Unit Price, 4: Total

        for idx, item in enumerate(invoice.items, 1):
            total = float(item.total)
            total_amount += total

            # Track lengths for each column
            desc_len = len(item.description)
            if desc_len > max_lengths[1]:
                max_lengths[1] = desc_len

            # Format quantity as whole number (remove decimals)
            qty = float(item.quantity)
            if qty.is_integer():
                qty_str = f"{int(qty)}"
            else:
                qty_str = f"{qty:,.2f}"
            if len(qty_str) > max_lengths[2]:
                max_lengths[2] = len(qty_str)

            price_str = f"{float(item.unit_price):,.2f}"
            if len(price_str) > max_lengths[3]:
                max_lengths[3] = len(price_str)

            total_str = f"{total:,.2f}"
            if len(total_str) > max_lengths[4]:
                max_lengths[4] = len(total_str)

            line_data.append([
                Paragraph(str(idx), normal_style),
                Paragraph(item.description, normal_style),
                Paragraph(qty_str, normal_style),
                Paragraph(f"{float(item.unit_price):,.2f}", normal_style),
                Paragraph(f"{total:,.2f}", normal_style)
            ])

        # Update max lengths with header lengths
        header_texts = ['#', 'Description', 'Qty', f'Unit Price ({currency_code})', f'Total ({currency_code})']
        for i, text in enumerate(header_texts):
            if len(text) > max_lengths[i]:
                max_lengths[i] = len(text)

        # Totals row - only Total column has a value
        line_data.append([
            Paragraph('', normal_style),
            Paragraph('', normal_style),
            Paragraph('', normal_style),
            Paragraph('', normal_style),
            Paragraph(f"{total_amount:,.2f}", value_style)
        ])

        # Calculate dynamic column widths based on content
        total_available_width = 7.0 * inch
        min_column_width = 0.25 * inch
        max_column_width = 3.0 * inch

        # Base width per character (approximate)
        char_width = 0.065 * inch

        # Calculate initial widths based on content for ALL columns
        initial_widths = []
        for i in range(5):
            content_width = (max_lengths[i] + 3) * char_width  # Add padding
            clamped_width = max(min_column_width, min(content_width, max_column_width))
            initial_widths.append(clamped_width)

        # Calculate total initial width
        total_initial = sum(initial_widths)

        # Scale widths to fit total_available_width
        if total_initial > total_available_width:
            # Need to shrink columns proportionally
            scale_factor = total_available_width / total_initial
            col_widths = [w * scale_factor for w in initial_widths]
        else:
            # We have extra space, distribute to description column (index 1) first
            extra_space = total_available_width - total_initial
            col_widths = initial_widths.copy()

            # Give extra space to description column, but cap it
            col_widths[1] = min(col_widths[1] + extra_space, max_column_width * 1.6)

            # If still extra space, distribute to Qty, Unit Price, and Total columns
            remaining_extra = total_available_width - sum(col_widths)
            if remaining_extra > 0:
                # Distribute remaining extra to Qty (index 2), Unit Price (index 3), and Total (index 4)
                # Give more weight to Qty since it should resize
                distribute_cols = [2, 3, 4]
                weights = [1.5, 1.0, 1.0]  # Qty gets more weight
                total_weight = sum(weights)

                for i, col_idx in enumerate(distribute_cols):
                    if col_widths[col_idx] < max_column_width:
                        extra = remaining_extra * (weights[i] / total_weight)
                        col_widths[col_idx] = min(col_widths[col_idx] + extra, max_column_width)

            # If still extra space, distribute to # column (index 0)
            remaining_extra = total_available_width - sum(col_widths)
            if remaining_extra > 0 and col_widths[0] < max_column_width:
                col_widths[0] = min(col_widths[0] + remaining_extra, max_column_width * 0.8)

        # Ensure minimum widths
        col_widths = [max(min_column_width, w) for w in col_widths]

        # Ensure total width doesn't exceed available
        total_width = sum(col_widths)
        if total_width > total_available_width:
            # Reduce all columns proportionally
            scale = total_available_width / total_width
            col_widths = [w * scale for w in col_widths]

        # Add a small padding to total width to fill the page
        total_width = sum(col_widths)
        if total_width < total_available_width:
            # Add remaining space to description
            diff = total_available_width - total_width
            col_widths[1] = min(col_widths[1] + diff, max_column_width * 1.8)

        # Ensure Qty column has a minimum width even if content is small
        col_widths[2] = max(col_widths[2], 0.5 * inch)  # Minimum 0.5 inches for Qty

        # Create the table with dynamic widths
        line_table = Table(line_data, colWidths=col_widths)
        line_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#cccccc')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 9),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#cccccc')),
            ('WORDWRAP', (0, 0), (-1, -1), True),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 12))

        # Summary with VAT, Levy, and Discount
        total_subtotal = sum(float(item.quantity) * float(item.unit_price) for item in invoice.items)
        total_vat = sum(float(item.vat_amount or 0) for item in invoice.items)
        total_levy = sum(float(item.levy_amount or 0) for item in invoice.items)

        if float(invoice.discount) > 0:
            summary_data = [
                ['Subtotal:', f"{currency_code} {total_subtotal:,.2f}"],
                ['VAT:', f"{currency_code} {total_vat:,.2f}"],
                ['Levy:', f"{currency_code} {total_levy:,.2f}"],
                ['Discount:', f"-{currency_code} {float(invoice.discount):,.2f}"],
                ['TOTAL:', f"{currency_code} {float(invoice.total):,.2f}"]
            ]
        else:
            summary_data = [
                ['Subtotal:', f"{currency_code} {total_subtotal:,.2f}"],
                ['VAT:', f"{currency_code} {total_vat:,.2f}"],
                ['Levy:', f"{currency_code} {total_levy:,.2f}"],
                ['TOTAL:', f"{currency_code} {float(invoice.total):,.2f}"]
            ]
        summary_table = Table(summary_data, colWidths=[2.0 * inch, 2.5 * inch])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('LINEABOVE', (0, -1), (1, -1), 1, colors.HexColor('#cccccc')),
            ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, -1), (1, -1), colors.black),
            ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (1, -1), 10),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 12))

    # Notes and terms
    if invoice.notes:
        elements.append(Paragraph(f"<b>Notes:</b> {invoice.notes}", normal_style))
    if invoice.terms:
        elements.append(Paragraph(f"<b>Terms:</b> {invoice.terms}", normal_style))

    # Payment Details Section - at the bottom
    if invoice.bank_id:
        bank = invoice.bank
        if bank:
            elements.append(Spacer(1, 12))
            elements.append(Paragraph("PAYMENT DETAILS", heading_style))
            elements.append(Spacer(1, 4))

            bank_info = []
            bank_info.append(f"<b>Bank:</b> {bank.name}")
            if bank.account_name:
                bank_info.append(f"<b>Account Name:</b> {bank.account_name}")
            if bank.account_number:
                bank_info.append(f"<b>Account Number:</b> {bank.account_number}")
            if bank.branch:
                bank_info.append(f"<b>Branch:</b> {bank.branch}")
            if bank.swift_code:
                bank_info.append(f"<b>SWIFT Code:</b> {bank.swift_code}")
            if bank.address:
                bank_info.append(f"<b>Address:</b> {bank.address}")

            bank_data = []
            for info in bank_info:
                bank_data.append([Paragraph(info, normal_style)])

            bank_table = Table(bank_data, colWidths=[5.5 * inch])
            bank_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
            ]))
            elements.append(bank_table)

    # Footer
    elements.append(Spacer(1, 20))
    footer_text = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M')} | This is a computer-generated invoice"
    elements.append(Paragraph(footer_text, normal_style))

    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data
# ==================== IMPORT FUNCTIONS ====================
def generate_invoice_import_template():
    """Generate Excel template for importing invoices"""
    # Make sure all arrays have the same length
    data = {
        'Customer Name': ['Sample Customer', 'Sample Customer', 'Another Customer'],
        'Invoice Date': ['2024-01-15', '2024-01-15', '2024-01-20'],
        'Due Date': ['2024-02-14', '2024-02-14', '2024-02-19'],
        'Item Description': ['Consulting Services', 'Software License', 'Professional Services'],
        'Quantity': ['1', '2', '1'],
        'Unit Price': ['1000.00', '500.00', '1500.00'],
        'VAT Rate (%)': ['15.0', '0.0', '15.0'],
        'Levy Rate (%)': ['2.5', '0.0', '0.0'],
        'Discount': ['0.00', '0.00', '50.00'],
        'Notes': ['Payment for services', '', 'Project completion'],
        'Terms': ['Net 30 days', '', 'Net 15 days']
    }
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Invoices', index=False)

        # Add instructions sheet
        instructions = pd.DataFrame({
            'Instruction': [
                '1. Each row represents one line item',
                '2. Multiple rows with the same Customer Name and Invoice Date will be grouped into one invoice',
                '3. Customer must already exist in the system',
                '4. Date format: YYYY-MM-DD',
                '5. VAT Rate and Levy Rate are percentages (e.g., 15 for 15%)',
                '6. Leave fields blank for optional values',
                '7. The first two rows (Sample Customer) will be combined into a single invoice with 2 line items'
            ]
        })
        instructions.to_excel(writer, sheet_name='Instructions', index=False)

    output.seek(0)
    return output


def import_invoices_from_excel(df, company_id):
    """Import invoices from Excel file"""
    errors = []
    invoices_created = []

    # Column mappings
    column_mappings = {
        'Customer Name': ['Customer Name', 'Customer', 'Client'],
        'Invoice Date': ['Invoice Date', 'Date', 'InvoiceDate'],
        'Due Date': ['Due Date', 'DueDate', 'Due'],
        'Item Description': ['Item Description', 'Description', 'Item'],
        'Quantity': ['Quantity', 'Qty'],
        'Unit Price': ['Unit Price', 'UnitPrice', 'Price'],
        'VAT Rate (%)': ['VAT Rate (%)', 'VAT %', 'VAT'],
        'Levy Rate (%)': ['Levy Rate (%)', 'Levy %', 'Levy'],
        'Discount': ['Discount', 'Disc'],
        'Notes': ['Notes', 'Note'],
        'Terms': ['Terms', 'Term']
    }

    # Find actual columns
    actual_columns = {}
    for expected, variations in column_mappings.items():
        for col in df.columns:
            col_clean = col.strip()
            if col_clean in variations or col_clean.lower() in [v.lower() for v in variations]:
                actual_columns[expected] = col
                break

    # Validate required columns
    required = ['Customer Name', 'Invoice Date', 'Item Description', 'Quantity', 'Unit Price']
    missing = [req for req in required if req not in actual_columns]
    if missing:
        raise ValueError(f'Missing required columns: {", ".join(missing)}')

    # Get existing customers
    db_customers = Customer.query.filter_by(company_id=company_id).all()
    customer_names = {c.name.lower(): c.id for c in db_customers}

    # Group rows by invoice (customer name + invoice date)
    invoice_groups = {}

    for idx, row in df.iterrows():
        try:
            customer_name = str(row[actual_columns['Customer Name']]) if pd.notna(
                row[actual_columns['Customer Name']]) else ''
            if not customer_name or customer_name.strip() == '':
                errors.append(f"Row {idx + 2}: Customer name is required")
                continue

            # Find customer ID
            customer_id = customer_names.get(customer_name.lower())
            if not customer_id:
                # Try fuzzy matching
                for name in customer_names:
                    if customer_name.lower() in name or name in customer_name.lower():
                        customer_id = customer_names[name]
                        break

                if not customer_id:
                    errors.append(f"Row {idx + 2}: Customer '{customer_name}' not found. Please add customer first.")
                    continue

            # Get invoice date
            invoice_date = None
            if 'Invoice Date' in actual_columns and pd.notna(row[actual_columns['Invoice Date']]):
                try:
                    if isinstance(row[actual_columns['Invoice Date']], datetime):
                        invoice_date = row[actual_columns['Invoice Date']].date()
                    else:
                        invoice_date = pd.to_datetime(row[actual_columns['Invoice Date']]).date()
                except:
                    invoice_date = datetime.now().date()
            else:
                invoice_date = datetime.now().date()

            # Get due date (default to 30 days after invoice date)
            due_date = None
            if 'Due Date' in actual_columns and pd.notna(row[actual_columns['Due Date']]):
                try:
                    if isinstance(row[actual_columns['Due Date']], datetime):
                        due_date = row[actual_columns['Due Date']].date()
                    else:
                        due_date = pd.to_datetime(row[actual_columns['Due Date']]).date()
                except:
                    due_date = invoice_date + timedelta(days=30)
            else:
                due_date = invoice_date + timedelta(days=30)

            # Get item details
            item_desc = str(row[actual_columns['Item Description']]) if pd.notna(
                row[actual_columns['Item Description']]) else ''
            quantity = float(row[actual_columns['Quantity']]) if pd.notna(row[actual_columns['Quantity']]) else 1
            unit_price = float(row[actual_columns['Unit Price']]) if pd.notna(row[actual_columns['Unit Price']]) else 0

            if not item_desc or unit_price <= 0:
                errors.append(f"Row {idx + 2}: Invalid item data. Description and Unit Price are required.")
                continue

            # Get VAT and Levy rates
            vat_rate = 0.0
            if 'VAT Rate (%)' in actual_columns and pd.notna(row[actual_columns['VAT Rate (%)']]):
                try:
                    vat_rate = float(row[actual_columns['VAT Rate (%)']])
                except:
                    vat_rate = 0.0

            levy_rate = 0.0
            if 'Levy Rate (%)' in actual_columns and pd.notna(row[actual_columns['Levy Rate (%)']]):
                try:
                    levy_rate = float(row[actual_columns['Levy Rate (%)']])
                except:
                    levy_rate = 0.0

            # Get discount (if provided)
            discount = 0.0
            if 'Discount' in actual_columns and pd.notna(row[actual_columns['Discount']]):
                try:
                    discount = float(row[actual_columns['Discount']])
                except:
                    discount = 0.0

            # Get notes and terms
            notes = ''
            if 'Notes' in actual_columns and pd.notna(row[actual_columns['Notes']]):
                notes = str(row[actual_columns['Notes']])

            terms = ''
            if 'Terms' in actual_columns and pd.notna(row[actual_columns['Terms']]):
                terms = str(row[actual_columns['Terms']])

            # Create unique key for grouping
            key = f"{customer_id}_{invoice_date.strftime('%Y-%m-%d')}"

            if key not in invoice_groups:
                invoice_groups[key] = {
                    'customer_id': customer_id,
                    'customer_name': customer_name,
                    'invoice_date': invoice_date,
                    'due_date': due_date,
                    'discount': discount,
                    'notes': notes,
                    'terms': terms,
                    'items': [],
                    'total_subtotal': 0,
                    'total_vat': 0,
                    'total_levy': 0
                }

            # Calculate item totals
            calc = calculate_invoice_item_totals(quantity, unit_price, vat_rate, levy_rate)

            invoice_groups[key]['items'].append({
                'description': item_desc,
                'quantity': quantity,
                'unit_price': unit_price,
                'vat_rate': vat_rate,
                'levy_rate': levy_rate,
                'subtotal': calc['subtotal'],
                'vat_amount': calc['vat_amount'],
                'levy_amount': calc['levy_amount'],
                'total': calc['total']
            })

            invoice_groups[key]['total_subtotal'] += calc['subtotal']
            invoice_groups[key]['total_vat'] += calc['vat_amount']
            invoice_groups[key]['total_levy'] += calc['levy_amount']

        except Exception as e:
            errors.append(f"Row {idx + 2}: {str(e)}")
            continue

    # Create invoices
    for key, data in invoice_groups.items():
        try:
            # Generate invoice number
            invoice_number = generate_invoice_number()

            # Calculate grand total
            total = data['total_subtotal'] + data['total_vat'] + data['total_levy'] - data['discount']

            # Create invoice
            invoice = Invoice(
                invoice_number=invoice_number,
                customer_id=data['customer_id'],
                company_id=company_id,
                invoice_date=data['invoice_date'],
                due_date=data['due_date'],
                currency='USD',  # Default currency for imported invoices
                exchange_rate=1.0,
                subtotal=data['total_subtotal'],
                tax_rate=0,
                tax_amount=data['total_vat'],
                discount=data['discount'],
                total=total,
                base_currency_subtotal=data['total_subtotal'],
                base_currency_tax=data['total_vat'],
                base_currency_total=total,
                notes=data['notes'],
                terms=data['terms'],
                status='draft'
            )

            db.session.add(invoice)
            db.session.flush()

            # Add items
            for item_data in data['items']:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    description=item_data['description'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    vat_rate=item_data['vat_rate'],
                    vat_amount=item_data['vat_amount'],
                    levy_rate=item_data['levy_rate'],
                    levy_amount=item_data['levy_amount'],
                    total=item_data['total']
                )
                db.session.add(item)

            invoices_created.append({
                'invoice_number': invoice_number,
                'customer_name': data['customer_name'],
                'total': total,
                'items_count': len(data['items'])
            })

        except Exception as e:
            errors.append(f"Error creating invoice for {data['customer_name']}: {str(e)}")

    return invoices_created, errors

def generate_invoice_payment_report(company_id, date_from, date_to, customer_id=None, payment_status=None):
    """Generate invoice payment report with payment details"""
    query = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.invoice_date >= date_from,
        Invoice.invoice_date <= date_to
    )

    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)

    if payment_status:
        query = query.filter(Invoice.payment_status == payment_status)

    invoices = query.order_by(Invoice.invoice_date.desc()).all()

    report_data = []
    total_subtotal = 0
    total_vat = 0
    total_amount = 0
    total_paid = 0
    total_outstanding = 0

    for invoice in invoices:
        # Get the latest payment date if any payments exist
        payment_date = None
        if invoice.payments:
            # Sort payments by date and get the latest
            sorted_payments = sorted(invoice.payments,
                                     key=lambda p: p.payment_date if p.payment_date else datetime.min.date(),
                                     reverse=True)
            if sorted_payments:
                latest_payment = sorted_payments[0]
                payment_date = latest_payment.payment_date.strftime('%d-%m-%Y') if latest_payment.payment_date else None

        # Get all payment dates
        payment_dates = []
        for payment in invoice.payments:
            if payment.payment_date:
                payment_dates.append(payment.payment_date.strftime('%d-%m-%Y'))
        payment_dates_str = ', '.join(payment_dates) if payment_dates else 'No payments'

        subtotal = float(invoice.subtotal or 0)
        vat = float(invoice.tax_amount or 0)
        total = float(invoice.total or 0)
        paid = float(invoice.amount_paid or 0)
        outstanding = total - paid

        total_subtotal += subtotal
        total_vat += vat
        total_amount += total
        total_paid += paid
        total_outstanding += outstanding

        report_data.append({
            'Invoice #': invoice.invoice_number,
            'Date': invoice.invoice_date.strftime('%d-%m-%Y') if invoice.invoice_date else 'N/A',
            'Due Date': invoice.due_date.strftime('%d-%m-%Y') if invoice.due_date else 'N/A',
            'Customer': invoice.customer.name if invoice.customer else 'N/A',
            'Currency': invoice.currency or 'USD',
            'Subtotal': subtotal,
            'VAT': vat,
            'Total': total,
            'Amount Paid': paid,
            'Outstanding': outstanding,
            'Payment Status': invoice.payment_status.upper() if invoice.payment_status else 'UNPAID',
            'Invoice Status': invoice.status.upper() if invoice.status else 'DRAFT',
            'Payment Date(s)': payment_dates_str,
            'Last Payment Date': payment_date or 'No payments'
        })

    return report_data, {
        'total_subtotal': total_subtotal,
        'total_vat': total_vat,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_outstanding': total_outstanding,
        'total_invoices': len(invoices)
    }

def generate_supplier_template():
    data = {
        'Supplier Name': ['Example Supplier'],
        'Address': ['123 Business Street, City, Country'],
        'Telephone': ['+1234567890'],
        'Bank Name': ['Example Bank'],
        'Account Number/IBAN': ['GB82WEST12345698765432'],
        'Account Name': ['Example Account Name'],
        'SWIFT Code': ['ABCDGB2L'],
        'Bank Address': ['Bank Street, City, Country'],
        'Email (Optional)': ['supplier@example.com'],
        'Tax ID (Optional)': ['TAX123456']
    }
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Suppliers', index=False)
    output.seek(0)
    return output


def generate_invoice_payment_report_pdf(report_data, totals, title, currency):
    """Generate PDF for invoice payment report"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=8,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6,
        textColor=colors.black,
        fontName='Helvetica-Bold',
        alignment=TA_CENTER
    )
    normal_style = ParagraphStyle(
        'NormalStyle',
        parent=styles['Normal'],
        fontSize=8,
        spaceAfter=2,
        textColor=colors.black,
        fontName='Helvetica'
    )

    elements = []

    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f'Period: {report_data[0]["Date"] if report_data else ""} to {report_data[-1]["Date"] if report_data else ""}',
        heading_style))
    elements.append(Spacer(1, 6))

    if report_data:
        col_headers = ['#', 'Invoice #', 'Date', 'Due Date', 'Customer', 'Currency',
                       'Subtotal', 'VAT', 'Total', 'Amount Paid', 'Outstanding',
                       'Payment Status', 'Invoice Status', 'Last Payment']
        col_widths = [0.3 * inch, 0.8 * inch, 0.6 * inch, 0.6 * inch, 0.9 * inch, 0.4 * inch,
                      0.6 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch,
                      0.6 * inch, 0.6 * inch, 0.7 * inch]

        data = []
        for idx, row in enumerate(report_data, 1):
            data.append([
                str(idx),
                row['Invoice #'],
                row['Date'],
                row['Due Date'],
                row['Customer'][:20] + '...' if len(row['Customer']) > 20 else row['Customer'],
                row['Currency'],
                f"{row['Subtotal']:,.2f}",
                f"{row['VAT']:,.2f}",
                f"{row['Total']:,.2f}",
                f"{row['Amount Paid']:,.2f}",
                f"{row['Outstanding']:,.2f}",
                row['Payment Status'],
                row['Invoice Status'],
                row['Last Payment Date']
            ])

        table_data = [col_headers] + data
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('FONTSIZE', (0, 1), (-1, -2), 7),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))

        # Summary section
        summary_data = [
            ['TOTALS:'],
            ['Total Invoices:', f"{totals['total_invoices']}"],
            ['Total Subtotal:', f"{currency} {totals['total_subtotal']:,.2f}"],
            ['Total VAT:', f"{currency} {totals['total_vat']:,.2f}"],
            ['Total Amount:', f"{currency} {totals['total_amount']:,.2f}"],
            ['Total Paid:', f"{currency} {totals['total_paid']:,.2f}"],
            ['Total Outstanding:', f"{currency} {totals['total_outstanding']:,.2f}"]
        ]

        summary_table = Table(summary_data, colWidths=[2 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        elements.append(summary_table)

    elements.append(Spacer(1, 20))
    footer_text = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M')}"
    elements.append(Paragraph(footer_text, normal_style))

    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data


def export_suppliers_to_excel(suppliers):
    data = []
    for supplier in suppliers:
        data.append({
            'Supplier Name': supplier.name,
            'Address': supplier.address or '',
            'Telephone': supplier.telephone or '',
            'Bank Name': supplier.bank_name or '',
            'Account Number/IBAN': supplier.account_number or '',
            'Account Name': supplier.account_name or '',
            'SWIFT Code': supplier.swift_code or '',
            'Bank Address': supplier.bank_address or '',
            'Email': supplier.email or '',
            'Tax ID': supplier.tax_id or ''
        })
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Suppliers', index=False)
    output.seek(0)
    return output


def generate_payment_template():
    data = {
        'Supplier Name': ['ABC Ltd', 'ABC Ltd'],
        'Invoice Number': ['INV-001', 'INV-001'],
        'Currency': ['GHS', 'GHS'],
        'Exchange Rate': ['15.0', '15.0'],
        'Payment Date': ['2024-01-15', '2024-01-15'],
        'Description': ['Payment for services', 'Payment for services'],
        'Reference': ['REF-001', 'REF-001'],
        'Source Bank': ['Standard Chartered Bank', 'Standard Chartered Bank'],
        'Prepared By': ['John Doe', 'John Doe'],
        'Approved By': ['Jane Smith', 'Jane Smith'],
        'Received By': ['Bob Wilson', 'Bob Wilson'],
        'Line Item Description': ['Consulting Services', 'Materials'],
        'Quantity': ['1', '2'],
        'Unit Price': ['1000.00', '500.00'],
        'WHT Rate (%)': ['5.0', '0.0'],
        'VAT Rate (%)': ['12.5', '0.0']
    }
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Payments', index=False)
    output.seek(0)
    return output


def import_suppliers_from_excel(df, company_id):
    column_mappings = {
        'Supplier Name': ['Supplier Name', 'Supplier', 'Name', 'SupplierName'],
        'Address': ['Address', 'Supplier Address', 'Address Line'],
        'Telephone': ['Telephone', 'Phone', 'Phone Number', 'Tel', 'Contact'],
        'Bank Name': ['Bank Name', 'Bank', 'BankName'],
        'Account Number/IBAN': ['Account Number/IBAN', 'Account Number', 'IBAN', 'AccountNo'],
        'Account Name': ['Account Name', 'AccountName', 'Beneficiary'],
        'SWIFT Code': ['SWIFT Code', 'SWIFT', 'BIC', 'SWIFTCode'],
        'Bank Address': ['Bank Address', 'BankAddress', 'Bank Address Line'],
        'Email (Optional)': ['Email (Optional)', 'Email', 'Email Address'],
        'Tax ID (Optional)': ['Tax ID (Optional)', 'Tax ID', 'VAT', 'TaxId']
    }
    actual_columns = {}
    for expected, variations in column_mappings.items():
        for col in df.columns:
            col_clean = col.strip()
            if col_clean in variations or col_clean.lower() in [v.lower() for v in variations]:
                actual_columns[expected] = col
                break
    if 'Supplier Name' not in actual_columns:
        for col in df.columns:
            if 'name' in col.lower() or 'supplier' in col.lower():
                actual_columns['Supplier Name'] = col
                break
        if 'Supplier Name' not in actual_columns:
            raise ValueError('Could not find "Supplier Name" column.')
    suppliers = []
    errors = []
    for idx, row in df.iterrows():
        try:
            supplier_name_col = actual_columns['Supplier Name']
            supplier_name = str(row[supplier_name_col]) if pd.notna(row[supplier_name_col]) else ''
            if not supplier_name or supplier_name.strip() == '' or supplier_name == 'nan' or supplier_name == 'None':
                continue
            supplier_data = {
                'name': supplier_name.strip(),
                'address': '', 'telephone': '', 'bank_name': '', 'account_number': '',
                'account_name': '', 'swift_code': '', 'bank_address': '', 'email': '', 'tax_id': ''
            }
            field_mappings = {
                'address': 'Address', 'telephone': 'Telephone', 'bank_name': 'Bank Name',
                'account_number': 'Account Number/IBAN', 'account_name': 'Account Name',
                'swift_code': 'SWIFT Code', 'bank_address': 'Bank Address',
                'email': 'Email (Optional)', 'tax_id': 'Tax ID (Optional)'
            }
            for field, expected_col in field_mappings.items():
                if expected_col in actual_columns:
                    col_name = actual_columns[expected_col]
                    if col_name in row and pd.notna(row[col_name]):
                        value = row[col_name]
                        if isinstance(value, (int, float)):
                            supplier_data[field] = str(value).strip() if pd.notna(value) else ''
                        else:
                            supplier_data[field] = str(value).strip() if pd.notna(value) else ''
            supplier = Supplier(
                name=supplier_data['name'],
                address=supplier_data['address'],
                telephone=supplier_data['telephone'],
                bank_name=supplier_data['bank_name'],
                account_number=supplier_data['account_number'],
                account_name=supplier_data['account_name'],
                swift_code=supplier_data['swift_code'],
                bank_address=supplier_data['bank_address'],
                email=supplier_data['email'],
                tax_id=supplier_data['tax_id'],
                company_id=company_id
            )
            suppliers.append(supplier)
        except Exception as e:
            errors.append(f"Row {idx + 2}: {str(e)}")
            continue
    if errors:
        print(f"Warnings during import: {errors}")
    return suppliers


def import_payments_from_excel(df, company_id):
    errors = []
    column_mappings = {
        'Supplier Name': ['Supplier Name', 'Supplier', 'Name'],
        'Invoice Number': ['Invoice Number', 'Invoice #', 'InvoiceNo'],
        'Currency': ['Currency', 'Curr'],
        'Exchange Rate': ['Exchange Rate', 'Exchange Rate (1 USD = ?)', 'Rate'],
        'Payment Date': ['Payment Date', 'Date'],
        'Description': ['Description', 'Payment Description'],
        'Reference': ['Reference', 'Reference Number', 'Ref'],
        'Source Bank': ['Source Bank', 'Bank', 'Source Bank Name', 'Bank Name'],
        'Prepared By': ['Prepared By', 'Preparer'],
        'Approved By': ['Approved By', 'Approver'],
        'Received By': ['Received By', 'Receiver'],
        'Line Item Description': ['Line Item Description', 'Item Description', 'Description'],
        'Quantity': ['Quantity', 'Qty'],
        'Unit Price': ['Unit Price', 'Unit Price', 'Price'],
        'WHT Rate (%)': ['WHT Rate (%)', 'WHT %', 'WHT Rate'],
        'VAT Rate (%)': ['VAT Rate (%)', 'VAT %', 'VAT Rate']
    }
    actual_columns = {}
    for expected, variations in column_mappings.items():
        for col in df.columns:
            col_clean = col.strip()
            if col_clean in variations or col_clean.lower() in [v.lower() for v in variations]:
                actual_columns[expected] = col
                break
    required = ['Supplier Name', 'Currency', 'Line Item Description', 'Quantity', 'Unit Price']
    missing = [req for req in required if req not in actual_columns]
    if missing:
        raise ValueError(f'Missing required columns: {", ".join(missing)}')
    db_suppliers = Supplier.query.filter_by(company_id=company_id).all()
    supplier_names = {s.name.lower(): s.id for s in db_suppliers}
    db_signatures = AuthorizedSignature.query.filter_by(company_id=company_id, is_active=True).all()
    signature_names = {}
    for sig in db_signatures:
        signature_names[sig.name.lower()] = sig.id
        signature_names[f"{sig.name.lower()}_{sig.role.lower()}"] = sig.id
    db_banks = Bank.query.filter_by(company_id=company_id, is_active=True).all()
    bank_names = {b.name.lower(): b.id for b in db_banks}
    payments_data = {}
    for idx, row in df.iterrows():
        try:
            supplier_name = str(row[actual_columns['Supplier Name']]) if pd.notna(
                row[actual_columns['Supplier Name']]) else ''
            if not supplier_name or supplier_name.strip() == '':
                continue
            supplier_id = supplier_names.get(supplier_name.lower())
            if not supplier_id:
                for name in supplier_names:
                    if supplier_name.lower() in name or name in supplier_name.lower():
                        supplier_id = supplier_names[name]
                        break
                if not supplier_id:
                    errors.append(f"Row {idx + 2}: Supplier '{supplier_name}' not found. Please add supplier first.")
                    continue
            source_bank_id = None
            if 'Source Bank' in actual_columns and pd.notna(row[actual_columns['Source Bank']]):
                bank_name = str(row[actual_columns['Source Bank']])
                source_bank_id = bank_names.get(bank_name.lower())
                if not source_bank_id:
                    for name in bank_names:
                        if bank_name.lower() in name or name in bank_name.lower():
                            source_bank_id = bank_names[name]
                            break
                    if not source_bank_id:
                        errors.append(f"Row {idx + 2}: Bank '{bank_name}' not found. Please add bank first.")
            item_desc = str(row[actual_columns['Line Item Description']]) if pd.notna(
                row[actual_columns['Line Item Description']]) else ''
            quantity = float(row[actual_columns['Quantity']]) if pd.notna(row[actual_columns['Quantity']]) else 1
            unit_price = float(row[actual_columns['Unit Price']]) if pd.notna(row[actual_columns['Unit Price']]) else 0
            if not item_desc or unit_price <= 0:
                errors.append(f"Row {idx + 2}: Invalid line item data. Description and Unit Price are required.")
                continue
            currency = str(row[actual_columns['Currency']]) if 'Currency' in actual_columns and pd.notna(
                row[actual_columns['Currency']]) else 'GHS'
            exchange_rate = 1.0
            if 'Exchange Rate' in actual_columns and pd.notna(row[actual_columns['Exchange Rate']]):
                try:
                    exchange_rate = float(row[actual_columns['Exchange Rate']])
                except:
                    exchange_rate = 1.0
            payment_date = datetime.now().date()
            if 'Payment Date' in actual_columns and pd.notna(row[actual_columns['Payment Date']]):
                try:
                    if isinstance(row[actual_columns['Payment Date']], datetime):
                        payment_date = row[actual_columns['Payment Date']].date()
                    else:
                        payment_date = pd.to_datetime(row[actual_columns['Payment Date']]).date()
                except:
                    payment_date = datetime.now().date()
            invoice_number = str(
                row[actual_columns['Invoice Number']]) if 'Invoice Number' in actual_columns and pd.notna(
                row[actual_columns['Invoice Number']]) else ''
            description = str(row[actual_columns['Description']]) if 'Description' in actual_columns and pd.notna(
                row[actual_columns['Description']]) else ''
            reference = str(row[actual_columns['Reference']]) if 'Reference' in actual_columns and pd.notna(
                row[actual_columns['Reference']]) else ''
            wht_rate = float(row[actual_columns['WHT Rate (%)']]) if 'WHT Rate (%)' in actual_columns and pd.notna(
                row[actual_columns['WHT Rate (%)']]) else 0
            vat_rate = float(row[actual_columns['VAT Rate (%)']]) if 'VAT Rate (%)' in actual_columns and pd.notna(
                row[actual_columns['VAT Rate (%)']]) else 0
            prepared_by_id = None
            approved_by_id = None
            received_by_id = None
            if 'Prepared By' in actual_columns and pd.notna(row[actual_columns['Prepared By']]):
                prepared_name = str(row[actual_columns['Prepared By']])
                prepared_by_id = signature_names.get(prepared_name.lower())
            if 'Approved By' in actual_columns and pd.notna(row[actual_columns['Approved By']]):
                approved_name = str(row[actual_columns['Approved By']])
                approved_by_id = signature_names.get(approved_name.lower())
            if 'Received By' in actual_columns and pd.notna(row[actual_columns['Received By']]):
                received_name = str(row[actual_columns['Received By']])
                received_by_id = signature_names.get(received_name.lower())
            key = f"{supplier_id}_{invoice_number}_{currency}_{payment_date}"
            if key not in payments_data:
                payments_data[key] = {
                    'supplier_id': supplier_id, 'invoice_number': invoice_number,
                    'currency': currency, 'exchange_rate': exchange_rate,
                    'payment_date': payment_date, 'description': description,
                    'reference': reference, 'source_bank_id': source_bank_id,
                    'prepared_by_id': prepared_by_id, 'approved_by_id': approved_by_id,
                    'received_by_id': received_by_id,
                    'line_items': [], 'total_gross': 0, 'total_wht': 0, 'total_vat': 0, 'total_net': 0
                }
            calc = calculate_line_item_totals(quantity, unit_price, wht_rate, vat_rate)
            line_item = {
                'description': item_desc, 'quantity': quantity, 'unit_price': unit_price,
                'total_amount': calc['total'], 'wht_rate': wht_rate, 'vat_rate': vat_rate,
                'wht_amount': calc['wht_amount'], 'vat_amount': calc['vat_amount'],
                'net_amount': calc['net_amount']
            }
            payments_data[key]['line_items'].append(line_item)
            payments_data[key]['total_gross'] += calc['total']
            payments_data[key]['total_wht'] += calc['wht_amount']
            payments_data[key]['total_vat'] += calc['vat_amount']
            payments_data[key]['total_net'] += calc['net_amount']
        except Exception as e:
            errors.append(f"Row {idx + 2}: {str(e)}")
            continue
    existing_payments = Payment.query.with_entities(Payment.transaction_number).all()
    existing_numbers = set()
    for p in existing_payments:
        try:
            if p.transaction_number and p.transaction_number.startswith('PMT-'):
                num = int(p.transaction_number.split('-')[1])
                existing_numbers.add(num)
        except (ValueError, IndexError):
            continue
    current_seq = 1
    while current_seq in existing_numbers:
        current_seq += 1
    payments = []
    payment_groups = list(payments_data.items())
    for key, data in payment_groups:
        transaction_number = f'PMT-{str(current_seq).zfill(3)}'
        current_seq += 1
        payment = Payment(
            transaction_number=transaction_number,
            supplier_id=data['supplier_id'],
            invoice_number=data['invoice_number'],
            currency=data['currency'],
            exchange_rate=data['exchange_rate'],
            payment_date=data['payment_date'],
            description=data['description'],
            reference=data['reference'],
            source_bank_id=data['source_bank_id'],
            prepared_by_id=data['prepared_by_id'],
            approved_by_id=data['approved_by_id'],
            received_by_id=data['received_by_id'],
            total_gross_amount=round(data['total_gross'], 2),
            total_wht_amount=round(data['total_wht'], 2),
            total_vat_amount=round(data['total_vat'], 2),
            total_net_amount=round(data['total_net'], 2),
            company_id=company_id
        )
        for item_data in data['line_items']:
            line_item = PaymentLineItem(
                description=item_data['description'],
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                total_amount=item_data['total_amount'],
                withholding_tax_rate=item_data['wht_rate'],
                vat_rate=item_data['vat_rate'],
                withholding_tax_amount=item_data['wht_amount'],
                vat_amount=item_data['vat_amount'],
                net_amount=item_data['net_amount']
            )
            payment.line_items.append(line_item)
        payments.append(payment)
    if errors:
        print(f"Import warnings: {errors}")
    return payments, errors


# ==================== ROUTES ====================
@app.route('/')
def index():
    active_company = get_active_company()
    supplier_count = payment_count = invoice_count = customer_count = total_amount = 0
    if active_company:
        supplier_count = Supplier.query.filter_by(company_id=active_company.id).count()
        payment_count = Payment.query.filter_by(company_id=active_company.id).count()
        invoice_count = Invoice.query.filter_by(company_id=active_company.id).count()
        customer_count = Customer.query.filter_by(company_id=active_company.id).count()
        total_amount = db.session.query(db.func.sum(Payment.total_net_amount)).filter_by(
            company_id=active_company.id).scalar() or 0
    return render_template('index.html', active_company=active_company, supplier_count=supplier_count,
                           payment_count=payment_count, invoice_count=invoice_count, customer_count=customer_count,
                           total_amount=total_amount)


@app.route('/dashboard')
def dashboard():
    return redirect(url_for('index'))


# ==================== CUSTOMER ROUTES ====================
@app.route('/customers')
def customers():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    customers = Customer.query.filter_by(company_id=active_company.id).all()
    return render_template('customers.html', customers=customers, company=active_company)


# ==================== CUSTOMER API ROUTES ====================
@app.route('/api/customers', methods=['GET'])
@csrf_exempt_api
def get_customers_api():
    active_company = get_active_company()
    if not active_company:
        return jsonify([])
    try:
        customers = Customer.query.filter_by(company_id=active_company.id).all()
        return jsonify([{'id': c.id, 'name': c.name, 'email': c.email or '', 'phone': c.phone or '',
                         'address': c.address or '', 'tax_id': c.tax_id or '',
                         'created_at': c.created_at.isoformat() if c.created_at else None} for c in customers])
    except Exception as e:
        print(f"Error fetching customers: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/customers', methods=['POST'])
@csrf_exempt_api
def create_customer_api():
    active_company = get_active_company()
    if not active_company:
        return jsonify({'error': 'No active company found'}), 400
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        if not data.get('name'):
            return jsonify({'error': 'Customer name is required'}), 400
        existing = Customer.query.filter_by(name=data['name'], company_id=active_company.id).first()
        if existing:
            return jsonify({'error': 'A customer with this name already exists'}), 400
        customer = Customer(name=data['name'].strip(), email=data.get('email', '').strip(),
                            phone=data.get('phone', '').strip(), address=data.get('address', '').strip(),
                            tax_id=data.get('tax_id', '').strip(), company_id=active_company.id)
        db.session.add(customer)
        db.session.commit()
        return jsonify({'id': customer.id, 'name': customer.name, 'email': customer.email, 'phone': customer.phone,
                        'address': customer.address, 'tax_id': customer.tax_id,
                        'created_at': customer.created_at.isoformat() if customer.created_at else None}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error creating customer: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/customers/<int:customer_id>', methods=['PUT'])
@csrf_exempt_api
def update_customer_api(customer_id):
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        if 'name' in data and data['name']:
            customer.name = data['name'].strip()
        if 'email' in data:
            customer.email = data['email'].strip()
        if 'phone' in data:
            customer.phone = data['phone'].strip()
        if 'address' in data:
            customer.address = data['address'].strip()
        if 'tax_id' in data:
            customer.tax_id = data['tax_id'].strip()
        db.session.commit()
        return jsonify({'id': customer.id, 'name': customer.name, 'email': customer.email, 'phone': customer.phone,
                        'address': customer.address, 'tax_id': customer.tax_id,
                        'created_at': customer.created_at.isoformat() if customer.created_at else None})
    except Exception as e:
        db.session.rollback()
        print(f"Error updating customer: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/customers/<int:customer_id>', methods=['DELETE'])
@csrf_exempt_api
def delete_customer_api(customer_id):
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        if customer.invoices:
            return jsonify({'error': 'Cannot delete customer with existing invoices'}), 400
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer deleted successfully'})
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting customer: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==================== INVOICE ROUTES ====================
@app.route('/invoices')
def invoices_list():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    query = Invoice.query.filter_by(company_id=active_company.id)
    status = request.args.get('status')
    if status:
        query = query.filter(Invoice.status == status)
    invoices = query.order_by(Invoice.invoice_date.desc()).all()
    customers = Customer.query.filter_by(company_id=active_company.id).all()
    return render_template('invoices.html', invoices=invoices, customers=customers, company=active_company)


@app.route('/invoices/create', methods=['GET', 'POST'])
def create_invoice():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = InvoiceForm()
    if len(form.items) == 0:
        form.items.append_entry()
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                customer_id = request.form.get('customer_id')
                if not customer_id or customer_id == '0':
                    flash('Please select a customer.', 'warning')
                    return render_template('create_invoice.html', form=form, company=active_company)
                currency = request.form.get('currency', 'USD')
                try:
                    exchange_rate = float(request.form.get('exchange_rate', 1.0))
                except ValueError:
                    exchange_rate = 1.0
                # Get bank_id
                bank_id = request.form.get('bank_id')
                if bank_id and bank_id != '0':
                    bank_id = int(bank_id)
                else:
                    bank_id = None
                total_subtotal = 0
                total_vat = 0
                total_levy = 0
                items_data = []
                item_count = 0
                for key in request.form.keys():
                    if key.startswith('items-') and key.endswith('-description'):
                        parts = key.split('-')
                        if len(parts) >= 3:
                            idx = parts[1]
                            description = request.form.get(f'items-{idx}-description', '').strip()
                            if description:
                                try:
                                    quantity = float(request.form.get(f'items-{idx}-quantity', 1))
                                except ValueError:
                                    quantity = 1
                                try:
                                    unit_price = float(request.form.get(f'items-{idx}-unit_price', 0))
                                except ValueError:
                                    unit_price = 0
                                try:
                                    vat_rate = float(request.form.get(f'items-{idx}-vat_rate', 0))
                                except ValueError:
                                    vat_rate = 0
                                try:
                                    levy_rate = float(request.form.get(f'items-{idx}-levy_rate', 0))
                                except ValueError:
                                    levy_rate = 0
                                subtotal = quantity * unit_price
                                vat_amount = (subtotal * vat_rate) / 100 if vat_rate else 0
                                levy_amount = (subtotal * levy_rate) / 100 if levy_rate else 0
                                total = subtotal + vat_amount + levy_amount
                                items_data.append(
                                    {'description': description, 'quantity': quantity, 'unit_price': unit_price,
                                     'vat_rate': vat_rate, 'levy_rate': levy_rate, 'subtotal': subtotal,
                                     'vat_amount': vat_amount, 'levy_amount': levy_amount, 'total': total})
                                total_subtotal += subtotal
                                total_vat += vat_amount
                                total_levy += levy_amount
                                item_count += 1
                if item_count == 0:
                    flash('Please add at least one item with a description.', 'warning')
                    return render_template('create_invoice.html', form=form, company=active_company)
                try:
                    discount = float(request.form.get('discount', 0))
                except ValueError:
                    discount = 0
                total = total_subtotal + total_vat + total_levy - discount
                invoice_date_str = request.form.get('invoice_date')
                due_date_str = request.form.get('due_date')
                from datetime import datetime
                try:
                    invoice_date = datetime.strptime(invoice_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    invoice_date = datetime.now().date()
                try:
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    due_date = invoice_date + timedelta(days=30)
                invoice_number = generate_invoice_number()
                base_currency = active_company.base_currency
                base_subtotal = total_subtotal * exchange_rate if currency != base_currency else total_subtotal
                base_tax = total_vat * exchange_rate if currency != base_currency else total_vat
                base_total = total * exchange_rate if currency != base_currency else total
                # Check if user wants to send
                action = request.form.get('action', 'save')
                status = 'sent' if action == 'save_send' else 'draft'
                invoice = Invoice(
                    invoice_number=invoice_number,
                    customer_id=int(customer_id),
                    company_id=active_company.id,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    bank_id=bank_id,
                    subtotal=total_subtotal,
                    tax_rate=0,
                    tax_amount=total_vat,
                    discount=discount,
                    total=total,
                    base_currency_subtotal=base_subtotal,
                    base_currency_tax=base_tax,
                    base_currency_total=base_total,
                    notes=request.form.get('notes', ''),
                    terms=request.form.get('terms', ''),
                    status=status
                )
                db.session.add(invoice)
                db.session.flush()
                for item_data in items_data:
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=item_data['description'],
                        quantity=item_data['quantity'],
                        unit_price=item_data['unit_price'],
                        vat_rate=item_data['vat_rate'],
                        vat_amount=item_data['vat_amount'],
                        levy_rate=item_data['levy_rate'],
                        levy_amount=item_data['levy_amount'],
                        total=item_data['total']
                    )
                    db.session.add(item)
                db.session.commit()
                if action == 'save_send':
                    flash(f'Invoice {invoice.invoice_number} created and sent to customer!', 'success')
                else:
                    flash(f'Invoice {invoice.invoice_number} created successfully!', 'success')
                return redirect(url_for('invoices_list'))
            except Exception as e:
                db.session.rollback()
                print(f"Error creating invoice: {str(e)}")
                import traceback
                traceback.print_exc()
                flash(f'Error creating invoice: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'{field}: {error}', 'danger')
    if request.method == 'GET' or not form.invoice_date.data:
        today = date.today()
        due_date = today + timedelta(days=30)
        form.invoice_date.data = today
        form.due_date.data = due_date
        if active_company:
            form.currency.data = active_company.base_currency
    return render_template('create_invoice.html', form=form, company=active_company)


@app.route('/invoices/edit/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.company_id != active_company.id:
        flash('You do not have permission to edit this invoice.', 'danger')
        return redirect(url_for('invoices_list'))
    if invoice.status not in ['draft', 'sent']:
        flash('Only draft or sent invoices can be edited.', 'warning')
        return redirect(url_for('invoices_list'))
    form = InvoiceForm()
    if request.method == 'GET':
        form.customer_id.data = invoice.customer_id
        form.invoice_date.data = invoice.invoice_date
        form.due_date.data = invoice.due_date
        form.currency.data = invoice.currency or 'USD'
        form.exchange_rate.data = float(invoice.exchange_rate) if invoice.exchange_rate else 1.0
        form.bank_id.data = invoice.bank_id or 0
        form.discount.data = float(invoice.discount)
        form.notes.data = invoice.notes or ''
        form.terms.data = invoice.terms or ''
        while len(form.items) > 0:
            form.items.pop_entry()
        for item in invoice.items:
            form.items.append_entry({
                'description': item.description,
                'quantity': float(item.quantity),
                'unit_price': float(item.unit_price),
                'vat_rate': float(item.vat_rate or 0),
                'levy_rate': float(item.levy_rate or 0)
            })
        if len(form.items) == 0:
            form.items.append_entry()
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                customer_id = request.form.get('customer_id')
                if not customer_id or customer_id == '0':
                    flash('Please select a customer.', 'warning')
                    return render_template('edit_invoice.html', form=form, invoice=invoice, company=active_company,
                                           invoice_items=invoice.items)
                currency = request.form.get('currency', 'USD')
                try:
                    exchange_rate = float(request.form.get('exchange_rate', 1.0))
                except ValueError:
                    exchange_rate = 1.0
                bank_id = request.form.get('bank_id')
                if bank_id and bank_id != '0':
                    bank_id = int(bank_id)
                else:
                    bank_id = None
                total_subtotal = 0
                total_vat = 0
                total_levy = 0
                items_data = []
                item_count = 0
                for key in request.form.keys():
                    if key.startswith('items-') and key.endswith('-description'):
                        parts = key.split('-')
                        if len(parts) >= 3:
                            idx = parts[1]
                            description = request.form.get(f'items-{idx}-description', '').strip()
                            if description:
                                try:
                                    quantity = float(request.form.get(f'items-{idx}-quantity', 1))
                                except ValueError:
                                    quantity = 1
                                try:
                                    unit_price = float(request.form.get(f'items-{idx}-unit_price', 0))
                                except ValueError:
                                    unit_price = 0
                                try:
                                    vat_rate = float(request.form.get(f'items-{idx}-vat_rate', 0))
                                except ValueError:
                                    vat_rate = 0
                                try:
                                    levy_rate = float(request.form.get(f'items-{idx}-levy_rate', 0))
                                except ValueError:
                                    levy_rate = 0
                                subtotal = quantity * unit_price
                                vat_amount = (subtotal * vat_rate) / 100 if vat_rate else 0
                                levy_amount = (subtotal * levy_rate) / 100 if levy_rate else 0
                                total = subtotal + vat_amount + levy_amount
                                items_data.append(
                                    {'description': description, 'quantity': quantity, 'unit_price': unit_price,
                                     'vat_rate': vat_rate, 'levy_rate': levy_rate, 'subtotal': subtotal,
                                     'vat_amount': vat_amount, 'levy_amount': levy_amount, 'total': total})
                                total_subtotal += subtotal
                                total_vat += vat_amount
                                total_levy += levy_amount
                                item_count += 1
                if item_count == 0:
                    flash('Please add at least one item with a description.', 'warning')
                    return render_template('edit_invoice.html', form=form, invoice=invoice, company=active_company,
                                           invoice_items=invoice.items)
                try:
                    discount = float(request.form.get('discount', 0))
                except ValueError:
                    discount = 0
                total = total_subtotal + total_vat + total_levy - discount
                invoice_date_str = request.form.get('invoice_date')
                due_date_str = request.form.get('due_date')
                from datetime import datetime
                try:
                    invoice_date = datetime.strptime(invoice_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    invoice_date = datetime.now().date()
                try:
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    due_date = invoice_date + timedelta(days=30)
                base_currency = active_company.base_currency
                base_subtotal = total_subtotal * exchange_rate if currency != base_currency else total_subtotal
                base_tax = total_vat * exchange_rate if currency != base_currency else total_vat
                base_total = total * exchange_rate if currency != base_currency else total
                action = request.form.get('action', 'save')
                new_status = 'sent' if action == 'save_send' else invoice.status
                invoice.customer_id = int(customer_id)
                invoice.invoice_date = invoice_date
                invoice.due_date = due_date
                invoice.currency = currency
                invoice.exchange_rate = exchange_rate
                invoice.bank_id = bank_id
                invoice.subtotal = total_subtotal
                invoice.tax_amount = total_vat
                invoice.discount = discount
                invoice.total = total
                invoice.base_currency_subtotal = base_subtotal
                invoice.base_currency_tax = base_tax
                invoice.base_currency_total = base_total
                invoice.notes = request.form.get('notes', '')
                invoice.terms = request.form.get('terms', '')
                invoice.status = new_status
                for item in invoice.items:
                    db.session.delete(item)
                invoice.items.clear()
                for item_data in items_data:
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=item_data['description'],
                        quantity=item_data['quantity'],
                        unit_price=item_data['unit_price'],
                        vat_rate=item_data['vat_rate'],
                        vat_amount=item_data['vat_amount'],
                        levy_rate=item_data['levy_rate'],
                        levy_amount=item_data['levy_amount'],
                        total=item_data['total']
                    )
                    db.session.add(item)
                invoice.updated_at = datetime.utcnow()
                db.session.commit()
                if action == 'save_send':
                    flash(f'Invoice {invoice.invoice_number} updated and sent to customer!', 'success')
                else:
                    flash(f'Invoice {invoice.invoice_number} updated successfully!', 'success')
                return redirect(url_for('invoices_list'))
            except Exception as e:
                db.session.rollback()
                print(f"Error updating invoice: {str(e)}")
                import traceback
                traceback.print_exc()
                flash(f'Error updating invoice: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'{field}: {error}', 'danger')
    return render_template('edit_invoice.html', form=form, invoice=invoice, company=active_company,
                           invoice_items=invoice.items)


@app.route('/invoices/pay/<int:invoice_id>', methods=['GET', 'POST'])
def record_invoice_payment(invoice_id):
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.company_id != active_company.id:
        flash('You do not have permission to modify this invoice.', 'danger')
        return redirect(url_for('invoices_list'))
    if invoice.status not in ['sent', 'overdue']:
        flash('Payments can only be recorded for sent or overdue invoices.', 'warning')
        return redirect(url_for('invoices_list'))
    outstanding = float(invoice.total) - float(invoice.amount_paid or 0)
    form = InvoicePaymentForm()
    if request.method == 'GET':
        form.payment_date.data = date.today()
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                payment_date = form.payment_date.data
                amount = form.amount.data
                payment_method = form.payment_method.data
                reference = form.reference.data or ''
                notes = form.notes.data or ''
                if amount > outstanding:
                    flash(f'Payment amount (${amount:,.2f}) exceeds outstanding balance (${outstanding:,.2f}).',
                          'danger')
                    return render_template('record_payment.html', form=form, invoice=invoice, outstanding=outstanding)
                payment = InvoicePayment(
                    invoice_id=invoice.id,
                    payment_date=payment_date,
                    amount=amount,
                    payment_method=payment_method,
                    reference=reference,
                    notes=notes
                )
                db.session.add(payment)
                new_amount_paid = float(invoice.amount_paid or 0) + amount
                invoice.amount_paid = new_amount_paid
                if new_amount_paid >= float(invoice.total):
                    invoice.payment_status = 'paid'
                    invoice.status = 'paid'
                else:
                    invoice.payment_status = 'partial'
                invoice.updated_at = datetime.utcnow()
                db.session.commit()
                flash(f'Payment of {invoice.currency} {amount:,.2f} recorded successfully!', 'success')
                return redirect(url_for('invoices_list'))
            except Exception as e:
                db.session.rollback()
                print(f"Error recording payment: {str(e)}")
                import traceback
                traceback.print_exc()
                flash(f'Error recording payment: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'{field}: {error}', 'danger')
    return render_template('record_payment.html', form=form, invoice=invoice, outstanding=outstanding,
                           company=active_company)


# ==================== API INVOICE ROUTES ====================
@app.route('/api/invoices', methods=['GET'])
@csrf_exempt_api
def get_invoices_api():
    active_company = get_active_company()
    if not active_company:
        return jsonify([])
    invoices = Invoice.query.filter_by(company_id=active_company.id).all()
    return jsonify([{
        'id': inv.id,
        'invoice_number': inv.invoice_number,
        'customer_name': inv.customer.name if inv.customer else '',
        'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else None,
        'due_date': inv.due_date.isoformat() if inv.due_date else None,
        'currency': inv.currency or 'USD',
        'exchange_rate': float(inv.exchange_rate) if inv.exchange_rate else 1.0,
        'subtotal': float(inv.subtotal) if inv.subtotal else 0,
        'tax_amount': float(inv.tax_amount) if inv.tax_amount else 0,
        'discount': float(inv.discount) if inv.discount else 0,
        'total': float(inv.total) if inv.total else 0,
        'amount_paid': float(inv.amount_paid) if inv.amount_paid else 0,
        'payment_status': inv.payment_status or 'unpaid',
        'bank_id': inv.bank_id,
        'bank_name': inv.bank.name if inv.bank else None,
        'status': inv.status,
        'created_at': inv.created_at.isoformat() if inv.created_at else None
    } for inv in invoices])


@app.route('/api/invoices/<int:invoice_id>/payments', methods=['GET'])
@csrf_exempt_api
def get_invoice_payments(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    payments = InvoicePayment.query.filter_by(invoice_id=invoice.id).order_by(InvoicePayment.payment_date.desc()).all()
    return jsonify([{
        'id': p.id,
        'payment_date': p.payment_date.isoformat() if p.payment_date else None,
        'amount': float(p.amount),
        'payment_method': p.payment_method,
        'reference': p.reference,
        'notes': p.notes,
        'created_at': p.created_at.isoformat() if p.created_at else None
    } for p in payments])


@app.route('/api/invoices/<int:invoice_id>/payment_summary', methods=['GET'])
@csrf_exempt_api
def get_invoice_payment_summary(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    total_paid = float(invoice.amount_paid or 0)
    total_due = float(invoice.total)
    outstanding = total_due - total_paid
    return jsonify({
        'total_due': total_due,
        'total_paid': total_paid,
        'outstanding': outstanding,
        'payment_status': invoice.payment_status,
        'currency': invoice.currency or 'USD'
    })


@app.route('/reports/invoice_payments', methods=['GET', 'POST'])
def invoice_payment_report():
    """Invoice Payment Report - shows invoice details with payment information"""
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))

    from datetime import datetime, date

    form = InvoicePaymentReportForm()

    if not form.date_from.data:
        form.date_from.data = datetime.now().replace(day=1).date()
    if not form.date_to.data:
        form.date_to.data = datetime.now().date()

    report_data = None
    totals = None
    report_title = 'Invoice Payment Report'

    if request.method == 'GET':
        report_data, totals = generate_invoice_payment_report(
            active_company.id,
            form.date_from.data,
            form.date_to.data,
            None,
            None
        )

    if request.method == 'POST' and form.validate_on_submit():
        customer_id = form.customer_id.data if form.customer_id.data != 0 else None
        payment_status = form.payment_status.data if form.payment_status.data else None
        action = request.form.get('action', 'preview')

        report_data, totals = generate_invoice_payment_report(
            active_company.id,
            form.date_from.data,
            form.date_to.data,
            customer_id,
            payment_status
        )

        if action == 'download':
            if form.format.data == 'pdf':
                pdf_data = generate_invoice_payment_report_pdf(
                    report_data,
                    totals,
                    report_title,
                    active_company.base_currency
                )
                return send_file(
                    BytesIO(pdf_data),
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'Invoice_Payment_Report_{datetime.now().strftime("%Y%m%d")}.pdf'
                )
            else:
                excel_data = generate_report_excel(
                    report_data,
                    report_title,
                    totals['total_amount'],
                    active_company.base_currency
                )
                return send_file(
                    BytesIO(excel_data),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True,
                    download_name=f'Invoice_Payment_Report_{datetime.now().strftime("%Y%m%d")}.xlsx'
                )

    return render_template('invoice_payment_report.html',
                           form=form,
                           report_data=report_data,
                           totals=totals,
                           report_title=report_title,
                           active_company=active_company,
                           now=datetime.now())

@app.route('/api/invoices/<int:invoice_id>/status', methods=['PUT'])
@csrf_exempt_api
def update_invoice_status(invoice_id):
    data = request.get_json()
    invoice = Invoice.query.get_or_404(invoice_id)
    try:
        invoice.status = data.get('status', invoice.status)
        db.session.commit()
        return jsonify({'success': True, 'status': invoice.status})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@app.route('/api/invoices/<int:invoice_id>/pdf', methods=['GET'])
def generate_invoice_pdf_route(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    pdf_data = generate_invoice_pdf(invoice)
    return send_file(BytesIO(pdf_data), mimetype='application/pdf', as_attachment=True,
                     download_name=f'invoice_{invoice.invoice_number}.pdf')


# ==================== COMPANY ROUTES ====================
@app.route('/companies')
def companies():
    companies = Company.query.all()
    return render_template('companies.html', companies=companies)


@app.route('/add_company', methods=['GET', 'POST'])
def add_company():
    form = CompanyForm()
    if form.validate_on_submit():
        company = Company(name=form.name.data, base_currency=form.base_currency.data)
        if form.logo.data and allowed_file(form.logo.data.filename):
            filename = secure_filename(form.logo.data.filename)
            name_parts = filename.rsplit('.', 1)
            filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1]}"
            form.logo.data.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            company.logo_filename = filename
        db.session.add(company)
        db.session.commit()
        flash('Company added successfully!', 'success')
        return redirect(url_for('companies'))
    return render_template('add_company.html', form=form)


@app.route('/switch_company/<int:company_id>')
def switch_company(company_id):
    Company.query.update({Company.is_active: False})
    company = Company.query.get_or_404(company_id)
    company.is_active = True
    db.session.commit()
    flash(f'Switched to {company.name}', 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/delete_company/<int:company_id>')
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    if company.suppliers or company.payments:
        flash('Cannot delete company with existing suppliers or payments.', 'danger')
        return redirect(url_for('companies'))
    db.session.delete(company)
    db.session.commit()
    flash('Company deleted successfully!', 'success')
    return redirect(url_for('companies'))


@app.route('/edit_company/<int:company_id>', methods=['GET', 'POST'])
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)
    form = CompanyForm(obj=company)
    if form.validate_on_submit():
        company.name = form.name.data
        company.base_currency = form.base_currency.data
        if form.logo.data and allowed_file(form.logo.data.filename):
            if company.logo_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], company.logo_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = secure_filename(form.logo.data.filename)
            name_parts = filename.rsplit('.', 1)
            filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1]}"
            form.logo.data.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            company.logo_filename = filename
        db.session.commit()
        flash('Company updated successfully!', 'success')
        return redirect(url_for('companies'))
    return render_template('edit_company.html', form=form, company=company)


@app.route('/invoices/payment/edit/<int:payment_id>', methods=['GET', 'POST'])
def edit_invoice_payment(payment_id):
    """Edit an existing invoice payment"""
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))

    payment = InvoicePayment.query.get_or_404(payment_id)
    invoice = payment.invoice

    # Check if invoice belongs to active company
    if invoice.company_id != active_company.id:
        flash('You do not have permission to modify this payment.', 'danger')
        return redirect(url_for('invoices_list'))

    # Only allow editing if invoice is not fully paid
    if invoice.payment_status == 'paid':
        flash('Cannot edit payments on a fully paid invoice.', 'warning')
        return redirect(url_for('invoices_list'))

    form = InvoicePaymentForm(obj=payment)
    original_amount = float(payment.amount)

    if request.method == 'GET':
        form.payment_date.data = payment.payment_date
        form.amount.data = float(payment.amount)
        form.payment_method.data = payment.payment_method
        form.reference.data = payment.reference or ''
        form.notes.data = payment.notes or ''

    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                new_amount = form.amount.data
                old_amount = float(payment.amount)

                # Calculate the difference
                amount_diff = new_amount - old_amount

                # Check if new amount would exceed total
                new_total_paid = float(invoice.amount_paid or 0) + amount_diff
                if new_total_paid > float(invoice.total):
                    flash(
                        f'Payment amount would exceed invoice total. Current total paid: {invoice.amount_paid}, Invoice total: {invoice.total}',
                        'danger')
                    return render_template('edit_invoice_payment.html', form=form, payment=payment, invoice=invoice)

                # Update payment
                payment.payment_date = form.payment_date.data
                payment.amount = new_amount
                payment.payment_method = form.payment_method.data
                payment.reference = form.reference.data or ''
                payment.notes = form.notes.data or ''

                # Update invoice amount paid
                invoice.amount_paid = new_total_paid

                # Update payment status
                if new_total_paid >= float(invoice.total):
                    invoice.payment_status = 'paid'
                    invoice.status = 'paid'
                elif new_total_paid > 0:
                    invoice.payment_status = 'partial'
                else:
                    invoice.payment_status = 'unpaid'

                invoice.updated_at = datetime.utcnow()
                db.session.commit()

                flash(f'Payment updated successfully! New amount: {invoice.currency} {new_amount:,.2f}', 'success')
                return redirect(url_for('record_invoice_payment', invoice_id=invoice.id))

            except Exception as e:
                db.session.rollback()
                print(f"Error updating payment: {str(e)}")
                import traceback
                traceback.print_exc()
                flash(f'Error updating payment: {str(e)}', 'danger')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'{field}: {error}', 'danger')

    return render_template('edit_invoice_payment.html',
                           form=form,
                           payment=payment,
                           invoice=invoice,
                           company=active_company)


@app.route('/invoices/payment/delete/<int:payment_id>', methods=['POST'])
def delete_invoice_payment(payment_id):
    """Delete an invoice payment"""
    active_company = get_active_company()
    if not active_company:
        return jsonify({'success': False, 'message': 'No active company'}), 400

    payment = InvoicePayment.query.get_or_404(payment_id)
    invoice = payment.invoice

    # Check if invoice belongs to active company
    if invoice.company_id != active_company.id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    # Only allow deletion if invoice is not fully paid
    if invoice.payment_status == 'paid' and float(invoice.amount_paid) >= float(invoice.total):
        return jsonify({'success': False, 'message': 'Cannot delete payment from a fully paid invoice.'}), 400

    try:
        # Get the amount before deletion
        amount_to_remove = float(payment.amount)

        # Update invoice amount paid
        new_amount_paid = float(invoice.amount_paid or 0) - amount_to_remove

        # Delete the payment
        db.session.delete(payment)

        # Update invoice payment status
        if new_amount_paid >= float(invoice.total):
            invoice.payment_status = 'paid'
            invoice.status = 'paid'
        elif new_amount_paid > 0:
            invoice.payment_status = 'partial'
        else:
            invoice.payment_status = 'unpaid'
            # If no payments, revert status to sent if it was paid
            if invoice.status == 'paid':
                invoice.status = 'sent'

        invoice.amount_paid = new_amount_paid
        invoice.updated_at = datetime.utcnow()
        db.session.commit()

        flash(f'Payment of {invoice.currency} {amount_to_remove:,.2f} deleted successfully!', 'success')
        return redirect(url_for('record_invoice_payment', invoice_id=invoice.id))

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting payment: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== SUPPLIER ROUTES ====================
@app.route('/suppliers')
def suppliers():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
    return render_template('suppliers.html', suppliers=suppliers, company=active_company)


@app.route('/add_supplier', methods=['GET', 'POST'])
def add_supplier():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = SupplierForm()
    if form.validate_on_submit():
        supplier = Supplier(
            name=form.name.data,
            address=form.address.data,
            telephone=form.telephone.data,
            bank_name=form.bank_name.data,
            account_number=form.account_number.data,
            account_name=form.account_name.data,
            swift_code=form.swift_code.data,
            bank_address=form.bank_address.data,
            email=form.email.data,
            tax_id=form.tax_id.data,
            company_id=active_company.id
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier added successfully!', 'success')
        return redirect(url_for('suppliers'))
    return render_template('add_supplier.html', form=form)


@app.route('/edit_supplier/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    form = SupplierForm(obj=supplier)
    if form.validate_on_submit():
        supplier.name = form.name.data
        supplier.address = form.address.data
        supplier.telephone = form.telephone.data
        supplier.bank_name = form.bank_name.data
        supplier.account_number = form.account_number.data
        supplier.account_name = form.account_name.data
        supplier.swift_code = form.swift_code.data
        supplier.bank_address = form.bank_address.data
        supplier.email = form.email.data
        supplier.tax_id = form.tax_id.data
        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('suppliers'))
    return render_template('edit_supplier.html', form=form, supplier=supplier)


@app.route('/delete_supplier/<int:supplier_id>')
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    if supplier.payments:
        flash('Cannot delete supplier with existing payments.', 'danger')
        return redirect(url_for('suppliers'))
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully!', 'success')
    return redirect(url_for('suppliers'))


@app.route('/view_supplier/<int:supplier_id>')
def view_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    return render_template('view_supplier.html', supplier=supplier)


@app.route('/export_suppliers')
def export_suppliers():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
    excel_file = export_suppliers_to_excel(suppliers)
    return send_file(excel_file, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'suppliers_{datetime.now().strftime("%Y%m%d")}.xlsx')


@app.route('/download_template')
def download_template():
    excel_file = generate_supplier_template()
    return send_file(excel_file, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='supplier_import_template.xlsx')


@app.route('/import_suppliers', methods=['GET', 'POST'])
def import_suppliers():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        filename = file.filename
        allowed_extensions = {'xlsx', 'xls', 'xlsm'}
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if file_ext not in allowed_extensions:
            flash(f'Invalid file format. Please use .xlsx, .xls, or .xlsm files.', 'danger')
            return redirect(request.url)
        try:
            df = None
            try:
                df = pd.read_excel(file, sheet_name='Suppliers', engine='openpyxl')
            except Exception as e1:
                print(f"Error reading with openpyxl: {e1}")
                try:
                    file.seek(0)
                    df = pd.read_excel(file, sheet_name='Suppliers', engine='xlrd')
                except Exception as e2:
                    print(f"Error reading with xlrd: {e2}")
                    try:
                        file.seek(0)
                        df = pd.read_excel(file, engine='openpyxl')
                    except Exception as e3:
                        flash(f'Could not read the Excel file. Error: {str(e3)}', 'danger')
                        return redirect(request.url)
            if df is None or df.empty:
                flash('The file is empty or could not be read.', 'danger')
                return redirect(request.url)
            if 'Supplier Name' not in df.columns:
                flash('The file does not contain a "Supplier Name" column.', 'danger')
                return redirect(request.url)
            suppliers = import_suppliers_from_excel(df, active_company.id)
            if suppliers:
                for supplier in suppliers:
                    db.session.add(supplier)
                db.session.commit()
                flash(f'Successfully imported {len(suppliers)} suppliers!', 'success')
            else:
                flash('No valid suppliers found in the file.', 'warning')
        except Exception as e:
            flash(f'Error importing suppliers: {str(e)}', 'danger')
            print(f"Import error: {str(e)}")
            traceback.print_exc()
        return redirect(url_for('suppliers'))
    return render_template('import_suppliers.html')


# ==================== INVOICE IMPORT ROUTES ====================
@app.route('/import_invoices', methods=['GET', 'POST'])
def import_invoices():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = InvoiceImportForm()
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        filename = file.filename
        allowed_extensions = {'xlsx', 'xls', 'xlsm'}
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if file_ext not in allowed_extensions:
            flash('Invalid file format. Please use .xlsx, .xls, or .xlsm files.', 'danger')
            return redirect(request.url)
        try:
            df = None
            try:
                df = pd.read_excel(file, sheet_name='Invoices', engine='openpyxl')
            except:
                file.seek(0)
                try:
                    df = pd.read_excel(file, engine='openpyxl')
                except Exception as e:
                    flash(f'Could not read the Excel file: {str(e)}', 'danger')
                    return redirect(request.url)
            if df is None or df.empty:
                flash('The file is empty or could not be read.', 'danger')
                return redirect(request.url)
            invoices_created, errors = import_invoices_from_excel(df, active_company.id)
            if invoices_created:
                db.session.commit()
                flash(f'Successfully imported {len(invoices_created)} invoices!', 'success')
                details = []
                for inv in invoices_created:
                    details.append(
                        f"{inv['invoice_number']} - {inv['customer_name']} (${inv['total']:,.2f}, {inv['items_count']} items)")
                if details:
                    flash(f'Created: {", ".join(details)}', 'info')
                if errors:
                    flash(f'Warning: {len(errors)} rows had issues. Check console for details.', 'warning')
            else:
                flash('No valid invoices found in the file. Please check the data format.', 'warning')
                if errors:
                    flash(f'Errors: {", ".join(errors[:5])}', 'danger')
        except Exception as e:
            flash(f'Error importing invoices: {str(e)}', 'danger')
            print(f"Import error: {str(e)}")
            traceback.print_exc()
        return redirect(url_for('invoices_list'))
    return render_template('import_invoices.html', form=form)


@app.route('/download_invoice_template')
def download_invoice_template():
    try:
        excel_file = generate_invoice_import_template()
        return send_file(excel_file, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='invoice_import_template.xlsx')
    except Exception as e:
        flash(f'Error generating template: {str(e)}', 'danger')
        return redirect(url_for('import_invoices'))


# ==================== SIGNATURE ROUTES ====================
@app.route('/signatures')
def signatures():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    signatures = AuthorizedSignature.query.filter_by(company_id=active_company.id).all()
    return render_template('signatures.html', signatures=signatures, company=active_company)


@app.route('/add_signature', methods=['GET', 'POST'])
def add_signature():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = SignatureForm()
    if form.validate_on_submit():
        signature = AuthorizedSignature(
            name=form.name.data,
            title=form.title.data,
            role=form.role.data,
            is_active=form.is_active.data == 'True',
            company_id=active_company.id
        )
        if form.signature_image.data and allowed_file(form.signature_image.data.filename):
            filename = secure_filename(form.signature_image.data.filename)
            name_parts = filename.rsplit('.', 1)
            filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1]}"
            form.signature_image.data.save(os.path.join(app.config['SIGNATURE_FOLDER'], filename))
            signature.signature_filename = filename
        db.session.add(signature)
        db.session.commit()
        flash('Signature added successfully!', 'success')
        return redirect(url_for('signatures'))
    return render_template('add_signature.html', form=form)


@app.route('/edit_signature/<int:signature_id>', methods=['GET', 'POST'])
def edit_signature(signature_id):
    signature = AuthorizedSignature.query.get_or_404(signature_id)
    form = SignatureForm(obj=signature)
    form.is_active.data = 'True' if signature.is_active else 'False'
    if form.validate_on_submit():
        signature.name = form.name.data
        signature.title = form.title.data
        signature.role = form.role.data
        signature.is_active = form.is_active.data == 'True'
        if form.signature_image.data and allowed_file(form.signature_image.data.filename):
            if signature.signature_filename:
                old_path = os.path.join(app.config['SIGNATURE_FOLDER'], signature.signature_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = secure_filename(form.signature_image.data.filename)
            name_parts = filename.rsplit('.', 1)
            filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1]}"
            form.signature_image.data.save(os.path.join(app.config['SIGNATURE_FOLDER'], filename))
            signature.signature_filename = filename
        db.session.commit()
        flash('Signature updated successfully!', 'success')
        return redirect(url_for('signatures'))
    return render_template('edit_signature.html', form=form, signature=signature)


@app.route('/delete_signature/<int:signature_id>')
def delete_signature(signature_id):
    signature = AuthorizedSignature.query.get_or_404(signature_id)
    if signature.prepared_payments or signature.approved_payments or signature.received_payments:
        flash('Cannot delete signature that is used in existing payments.', 'danger')
        return redirect(url_for('signatures'))
    if signature.signature_filename:
        old_path = os.path.join(app.config['SIGNATURE_FOLDER'], signature.signature_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    db.session.delete(signature)
    db.session.commit()
    flash('Signature deleted successfully!', 'success')
    return redirect(url_for('signatures'))


# ==================== BANK ROUTES ====================
@app.route('/banks')
def banks():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    banks = Bank.query.filter_by(company_id=active_company.id).all()
    return render_template('banks.html', banks=banks, company=active_company)


@app.route('/add_bank', methods=['GET', 'POST'])
def add_bank():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = BankForm()
    if form.validate_on_submit():
        bank = Bank(
            name=form.name.data,
            bank_code=form.bank_code.data,
            account_number=form.account_number.data,
            account_name=form.account_name.data,
            branch=form.branch.data,
            address=form.address.data,
            swift_code=form.swift_code.data,
            is_active=form.is_active.data == 'True',
            company_id=active_company.id
        )
        db.session.add(bank)
        db.session.commit()
        flash('Bank added successfully!', 'success')
        return redirect(url_for('banks'))
    return render_template('add_bank.html', form=form)


@app.route('/edit_bank/<int:bank_id>', methods=['GET', 'POST'])
def edit_bank(bank_id):
    bank = Bank.query.get_or_404(bank_id)
    form = BankForm(obj=bank)
    form.is_active.data = 'True' if bank.is_active else 'False'
    if form.validate_on_submit():
        bank.name = form.name.data
        bank.bank_code = form.bank_code.data
        bank.account_number = form.account_number.data
        bank.account_name = form.account_name.data
        bank.branch = form.branch.data
        bank.address = form.address.data
        bank.swift_code = form.swift_code.data
        bank.is_active = form.is_active.data == 'True'
        db.session.commit()
        flash('Bank updated successfully!', 'success')
        return redirect(url_for('banks'))
    return render_template('edit_bank.html', form=form, bank=bank)


@app.route('/delete_bank/<int:bank_id>')
def delete_bank(bank_id):
    bank = Bank.query.get_or_404(bank_id)
    if bank.payments:
        flash('Cannot delete bank that is used in existing payments.', 'danger')
        return redirect(url_for('banks'))
    db.session.delete(bank)
    db.session.commit()
    flash('Bank deleted successfully!', 'success')
    return redirect(url_for('banks'))


# ==================== PAYMENT ROUTES ====================
@app.route('/payments')
def payments():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    query = Payment.query.filter_by(company_id=active_company.id)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    supplier_id = request.args.get('supplier_id')
    currency = request.args.get('currency')
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Payment.payment_date >= date_from_obj)
        except:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            date_to_obj = date_to_obj + timedelta(days=1)
            query = query.filter(Payment.payment_date < date_to_obj)
        except:
            pass
    if supplier_id and supplier_id.isdigit():
        query = query.filter(Payment.supplier_id == int(supplier_id))
    if currency:
        query = query.filter(Payment.currency == currency)
    payments = query.order_by(Payment.payment_date.desc()).all()
    suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
    suppliers = sorted(suppliers, key=lambda s: s.name.lower())
    currencies = db.session.query(Payment.currency).filter_by(company_id=active_company.id).distinct().all()
    currencies = [c[0] for c in currencies if c[0]]
    return render_template('payments.html', payments=payments, company=active_company, suppliers=suppliers,
                           currencies=currencies)


@app.route('/add_payment', methods=['GET', 'POST'])
def add_payment():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = PaymentForm()
    if len(form.line_items) == 0:
        form.line_items.append_entry()
    if request.method == 'POST':
        line_items_data = []
        for key in request.form.keys():
            if key.startswith('line_items-') and key.endswith('-description'):
                parts = key.split('-')
                if len(parts) >= 3:
                    idx = parts[1]
                    description = request.form.get(f'line_items-{idx}-description', '')
                    quantity = request.form.get(f'line_items-{idx}-quantity', 1)
                    unit_price = request.form.get(f'line_items-{idx}-unit_price', 0)
                    wht_rate = request.form.get(f'line_items-{idx}-withholding_tax_rate', 0)
                    vat_rate = request.form.get(f'line_items-{idx}-vat_rate', 0)
                    if description and description.strip():
                        line_items_data.append({
                            'description': description,
                            'quantity': float(quantity) if quantity else 1,
                            'unit_price': float(unit_price) if unit_price else 0,
                            'wht_rate': float(wht_rate) if wht_rate else 0,
                            'vat_rate': float(vat_rate) if vat_rate else 0
                        })
        if not line_items_data:
            flash('Please add at least one line item with a description.', 'warning')
            return render_template('add_payment.html', form=form, active_company=active_company)
        if not form.supplier_id.data or form.supplier_id.data == 0:
            flash('Please select a supplier.', 'warning')
            return render_template('add_payment.html', form=form, active_company=active_company)
        if not form.currency.data:
            flash('Please select a currency.', 'warning')
            return render_template('add_payment.html', form=form, active_company=active_company)
        try:
            existing_payments = Payment.query.with_entities(Payment.transaction_number).all()
            existing_numbers = set()
            for p in existing_payments:
                try:
                    if p.transaction_number and p.transaction_number.startswith('PMT-'):
                        num = int(p.transaction_number.split('-')[1])
                        existing_numbers.add(num)
                except:
                    continue
            seq = 1
            while seq in existing_numbers:
                seq += 1
            transaction_number = f'PMT-{str(seq).zfill(3)}'
            payment_date = None
            if form.payment_date.data:
                payment_date = form.payment_date.data
            else:
                payment_date = datetime.now().date()
            payment = Payment(
                transaction_number=transaction_number,
                supplier_id=form.supplier_id.data,
                invoice_number=form.invoice_number.data,
                currency=form.currency.data,
                exchange_rate=form.exchange_rate.data or 1.0,
                payment_date=payment_date,
                description=form.description.data,
                reference=form.reference.data,
                prepared_by_id=form.prepared_by_id.data if form.prepared_by_id.data != 0 else None,
                approved_by_id=form.approved_by_id.data if form.approved_by_id.data != 0 else None,
                received_by_id=form.received_by_id.data if form.received_by_id.data != 0 else None,
                source_bank_id=form.source_bank_id.data if form.source_bank_id.data != 0 else None,
                company_id=active_company.id
            )
            if form.attachment.data and allowed_file(form.attachment.data.filename):
                file = form.attachment.data
                original_filename = secure_filename(file.filename)
                name_parts = original_filename.rsplit('.', 1)
                unique_filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1] if len(name_parts) > 1 else 'pdf'}"
                file_path = os.path.join(app.config['ATTACHMENT_FOLDER'], unique_filename)
                file.save(file_path)
                payment.attachment_filename = unique_filename
                payment.attachment_original_name = original_filename
                payment.attachment_size = os.path.getsize(file_path)
                payment.attachment_uploaded_at = datetime.now()
            total_gross = 0
            total_wht = 0
            total_vat = 0
            total_net = 0
            for item_data in line_items_data:
                calc = calculate_line_item_totals(
                    item_data['quantity'],
                    item_data['unit_price'],
                    item_data['wht_rate'],
                    item_data['vat_rate']
                )
                line_item = PaymentLineItem(
                    description=item_data['description'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_amount=calc['total'],
                    withholding_tax_rate=item_data['wht_rate'],
                    vat_rate=item_data['vat_rate'],
                    withholding_tax_amount=calc['wht_amount'],
                    vat_amount=calc['vat_amount'],
                    net_amount=calc['net_amount']
                )
                payment.line_items.append(line_item)
                total_gross += calc['total']
                total_wht += calc['wht_amount']
                total_vat += calc['vat_amount']
                total_net += calc['net_amount']
            payment.total_gross_amount = round(total_gross, 2)
            payment.total_wht_amount = round(total_wht, 2)
            payment.total_vat_amount = round(total_vat, 2)
            payment.total_net_amount = round(total_net, 2)
            db.session.add(payment)
            db.session.commit()
            db.session.refresh(payment)
            flash(
                f'Payment #{payment.transaction_number} added successfully! Net Amount: {payment.total_net_amount} {payment.currency}',
                'success')
            return redirect(url_for('payments'))
        except Exception as e:
            db.session.rollback()
            print(f"ERROR saving payment: {str(e)}")
            traceback.print_exc()
            flash(f'Error saving payment: {str(e)}', 'danger')
    return render_template('add_payment.html', form=form, active_company=active_company)


@app.route('/bulk_delete_payments', methods=['POST'])
@csrf_exempt_api
def bulk_delete_payments():
    try:
        data = request.get_json()
        payment_ids = data.get('payment_ids', [])
        if not payment_ids:
            return jsonify({'success': False, 'message': 'No payment IDs provided'})
        payment_ids = [int(id) for id in payment_ids]
        deleted_count = 0
        for payment_id in payment_ids:
            payment = Payment.query.get(payment_id)
            if payment:
                if payment.attachment_filename:
                    delete_attachment_file(payment.attachment_filename)
                db.session.delete(payment)
                deleted_count += 1
        db.session.commit()
        return jsonify({'success': True, 'message': f'Successfully deleted {deleted_count} payment(s)'})
    except Exception as e:
        db.session.rollback()
        print(f"Error in bulk delete: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/edit_payment/<int:payment_id>', methods=['GET', 'POST'])
def edit_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    form = PaymentForm(obj=payment)
    if request.method == 'GET':
        line_items_data = []
        for item in payment.line_items:
            line_items_data.append({
                'description': item.description,
                'quantity': item.quantity,
                'unit_price': item.unit_price,
                'withholding_tax_rate': item.withholding_tax_rate,
                'vat_rate': item.vat_rate
            })
        return render_template('edit_payment.html', form=form, payment=payment, line_items_data=line_items_data)
    if request.method == 'POST':
        line_items_data = []
        for key in request.form.keys():
            if key.startswith('line_items-') and key.endswith('-description'):
                parts = key.split('-')
                if len(parts) >= 3:
                    idx = parts[1]
                    description = request.form.get(f'line_items-{idx}-description', '')
                    quantity = request.form.get(f'line_items-{idx}-quantity', 1)
                    unit_price = request.form.get(f'line_items-{idx}-unit_price', 0)
                    wht_rate = request.form.get(f'line_items-{idx}-withholding_tax_rate', 0)
                    vat_rate = request.form.get(f'line_items-{idx}-vat_rate', 0)
                    if description and description.strip():
                        line_items_data.append({
                            'description': description,
                            'quantity': float(quantity) if quantity else 1,
                            'unit_price': float(unit_price) if unit_price else 0,
                            'wht_rate': float(wht_rate) if wht_rate else 0,
                            'vat_rate': float(vat_rate) if vat_rate else 0
                        })
        if not line_items_data:
            flash('Please add at least one line item with a description.', 'warning')
            return render_template('edit_payment.html', form=form, payment=payment, line_items_data=[])
        if not form.supplier_id.data:
            flash('Please select a supplier.', 'warning')
            return render_template('edit_payment.html', form=form, payment=payment, line_items_data=[])
        try:
            payment.supplier_id = form.supplier_id.data
            payment.invoice_number = form.invoice_number.data
            payment.currency = form.currency.data
            payment.exchange_rate = form.exchange_rate.data or 1.0
            payment.payment_date = form.payment_date.data or datetime.now().date()
            payment.description = form.description.data
            payment.reference = form.reference.data
            payment.prepared_by_id = form.prepared_by_id.data if form.prepared_by_id.data != 0 else None
            payment.approved_by_id = form.approved_by_id.data if form.approved_by_id.data != 0 else None
            payment.received_by_id = form.received_by_id.data if form.received_by_id.data != 0 else None
            payment.source_bank_id = form.source_bank_id.data if form.source_bank_id.data != 0 else None
            if request.form.get('remove_attachment') == 'on' and payment.attachment_filename:
                delete_attachment_file(payment.attachment_filename)
                payment.attachment_filename = None
                payment.attachment_original_name = None
                payment.attachment_size = None
                payment.attachment_uploaded_at = None
            if form.attachment.data and allowed_file(form.attachment.data.filename):
                if payment.attachment_filename:
                    delete_attachment_file(payment.attachment_filename)
                file = form.attachment.data
                original_filename = secure_filename(file.filename)
                name_parts = original_filename.rsplit('.', 1)
                unique_filename = f"{name_parts[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{name_parts[1] if len(name_parts) > 1 else 'pdf'}"
                file_path = os.path.join(app.config['ATTACHMENT_FOLDER'], unique_filename)
                file.save(file_path)
                payment.attachment_filename = unique_filename
                payment.attachment_original_name = original_filename
                payment.attachment_size = os.path.getsize(file_path)
                payment.attachment_uploaded_at = datetime.now()
            for item in payment.line_items:
                db.session.delete(item)
            payment.line_items.clear()
            total_gross = 0
            total_wht = 0
            total_vat = 0
            total_net = 0
            for item_data in line_items_data:
                calc = calculate_line_item_totals(
                    item_data['quantity'],
                    item_data['unit_price'],
                    item_data['wht_rate'],
                    item_data['vat_rate']
                )
                line_item = PaymentLineItem(
                    description=item_data['description'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_amount=calc['total'],
                    withholding_tax_rate=item_data['wht_rate'],
                    vat_rate=item_data['vat_rate'],
                    withholding_tax_amount=calc['wht_amount'],
                    vat_amount=calc['vat_amount'],
                    net_amount=calc['net_amount']
                )
                payment.line_items.append(line_item)
                total_gross += calc['total']
                total_wht += calc['wht_amount']
                total_vat += calc['vat_amount']
                total_net += calc['net_amount']
            payment.total_gross_amount = round(total_gross, 2)
            payment.total_wht_amount = round(total_wht, 2)
            payment.total_vat_amount = round(total_vat, 2)
            payment.total_net_amount = round(total_net, 2)
            db.session.commit()
            flash(f'Payment #{payment.transaction_number} updated successfully!', 'success')
            return redirect(url_for('payments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating payment: {str(e)}', 'danger')
    return render_template('edit_payment.html', form=form, payment=payment, line_items_data=[])


@app.route('/delete_payment/<int:payment_id>')
def delete_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.attachment_filename:
        delete_attachment_file(payment.attachment_filename)
    db.session.delete(payment)
    db.session.commit()
    flash('Payment deleted successfully!', 'success')
    return redirect(url_for('payments'))


@app.route('/calculate_line_item', methods=['POST'])
@csrf_exempt_api
def calculate_line_item():
    data = request.json
    quantity = float(data.get('quantity', 1))
    unit_price = float(data.get('unit_price', 0))
    wht_rate = float(data.get('wht_rate', 0))
    vat_rate = float(data.get('vat_rate', 0))
    result = calculate_line_item_totals(quantity, unit_price, wht_rate, vat_rate)
    return jsonify(result)


@app.route('/calculate_invoice_item', methods=['POST'])
@csrf_exempt_api
def calculate_invoice_item():
    data = request.json
    quantity = float(data.get('quantity', 1))
    unit_price = float(data.get('unit_price', 0))
    vat_rate = float(data.get('vat_rate', 0))
    levy_rate = float(data.get('levy_rate', 0))
    result = calculate_invoice_item_totals(quantity, unit_price, vat_rate, levy_rate)
    return jsonify(result)


@app.route('/import_payments', methods=['GET', 'POST'])
def import_payments():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    form = PaymentImportForm()
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        filename = file.filename
        allowed_extensions = {'xlsx', 'xls', 'xlsm'}
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if file_ext not in allowed_extensions:
            flash('Invalid file format. Please use .xlsx, .xls, or .xlsm files.', 'danger')
            return redirect(request.url)
        try:
            df = None
            try:
                df = pd.read_excel(file, sheet_name='Payments', engine='openpyxl')
            except:
                file.seek(0)
                try:
                    df = pd.read_excel(file, engine='openpyxl')
                except Exception as e:
                    flash(f'Could not read the Excel file: {str(e)}', 'danger')
                    return redirect(request.url)
            if df is None or df.empty:
                flash('The file is empty or could not be read.', 'danger')
                return redirect(request.url)
            payments, errors = import_payments_from_excel(df, active_company.id)
            if payments:
                for payment in payments:
                    db.session.add(payment)
                db.session.commit()
                flash(f'Successfully imported {len(payments)} payments!', 'success')
                if errors:
                    flash(f'Warning: {len(errors)} rows had issues. Check console for details.', 'warning')
            else:
                flash('No valid payments found in the file. Please check the data format.', 'warning')
                if errors:
                    flash(f'Errors: {", ".join(errors[:5])}', 'danger')
        except Exception as e:
            flash(f'Error importing payments: {str(e)}', 'danger')
            print(f"Import error: {str(e)}")
            traceback.print_exc()
        return redirect(url_for('payments'))
    return render_template('import_payments.html', form=form)


@app.route('/download_payment_template')
def download_payment_template():
    try:
        excel_file = generate_payment_template()
        return send_file(excel_file, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='payment_import_template.xlsx')
    except Exception as e:
        flash(f'Error generating template: {str(e)}', 'danger')
        return redirect(url_for('import_payments'))


# ==================== ATTACHMENT ROUTES ====================
@app.route('/download_attachment/<int:payment_id>')
def download_attachment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if not payment.attachment_filename:
        flash('No attachment found for this payment.', 'warning')
        return redirect(url_for('payments'))
    file_path = os.path.join(app.config['ATTACHMENT_FOLDER'], payment.attachment_filename)
    if not os.path.exists(file_path):
        flash('Attachment file not found.', 'danger')
        return redirect(url_for('payments'))
    return send_file(file_path, as_attachment=True,
                     download_name=payment.attachment_original_name or payment.attachment_filename)


@app.route('/delete_attachment/<int:payment_id>', methods=['POST'])
@csrf_exempt_api
def delete_attachment_route(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if not payment.attachment_filename:
        return jsonify({'success': False, 'message': 'No attachment found'})
    if delete_attachment_file(payment.attachment_filename):
        payment.attachment_filename = None
        payment.attachment_original_name = None
        payment.attachment_size = None
        payment.attachment_uploaded_at = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Attachment deleted successfully'})
    else:
        return jsonify({'success': False, 'message': 'Failed to delete attachment file'})


# ==================== REPORT ROUTES ====================
@app.route('/reports')
def reports_dashboard():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    return render_template('reports.html', active_company=active_company)


@app.route('/reports/<report_type>', methods=['GET', 'POST'])
def report_view(report_type):
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))
    valid_report_types = ['wht', 'vat', 'supplier', 'sales', 'aging', 'customers']
    if report_type not in valid_report_types:
        flash('Invalid report type', 'danger')
        return redirect(url_for('reports_dashboard'))
    form = ReportForm()
    if not form.date_from.data:
        form.date_from.data = datetime.now().replace(day=1).date()
    if not form.date_to.data:
        form.date_to.data = datetime.now().date()
    report_data = None
    total_amount = 0
    report_title = ''
    if report_type == 'wht':
        report_title = 'WHT Report'
    elif report_type == 'vat':
        report_title = 'VAT Report'
    elif report_type == 'supplier':
        report_title = 'Supplier Transactions Report'
    elif report_type == 'sales':
        report_title = 'Sales Summary Report'
    elif report_type == 'aging':
        report_title = 'Invoice Aging Report'
    elif report_type == 'customers':
        report_title = 'Customer Activity Report'
    if request.method == 'GET':
        supplier_id = None
        if report_type == 'wht':
            report_data, total_amount, _ = generate_wht_report(active_company.id, form.date_from.data,
                                                               form.date_to.data, supplier_id)
        elif report_type == 'vat':
            report_data, total_amount, _ = generate_vat_report(active_company.id, form.date_from.data,
                                                               form.date_to.data, supplier_id)
        elif report_type == 'supplier':
            report_data, total_amount = generate_supplier_transactions_report(active_company.id, form.date_from.data,
                                                                              form.date_to.data, supplier_id)
        else:
            query = Invoice.query.filter(
                Invoice.company_id == active_company.id,
                Invoice.invoice_date >= form.date_from.data,
                Invoice.invoice_date <= form.date_to.data
            )
            invoices = query.all()
            report_data = []
            total_amount = 0
            for inv in invoices:
                report_data.append({
                    'Invoice #': inv.invoice_number,
                    'Date': inv.invoice_date.strftime('%d-%m-%Y'),
                    'Due Date': inv.due_date.strftime('%d-%m-%Y'),
                    'Customer': inv.customer.name if inv.customer else 'N/A',
                    'Subtotal': float(inv.subtotal),
                    'VAT': float(inv.tax_amount),
                    'Total': float(inv.total),
                    'Status': inv.status,
                    'Days Overdue': (
                                datetime.now().date() - inv.due_date).days if inv.due_date and inv.status != 'paid' else 0
                })
                total_amount += float(inv.total)
    if request.method == 'POST' and form.validate_on_submit():
        supplier_id = form.supplier_id.data if form.supplier_id.data != 0 else None
        action = request.form.get('action', 'preview')
        if report_type == 'wht':
            report_data, total_amount, _ = generate_wht_report(active_company.id, form.date_from.data,
                                                               form.date_to.data, supplier_id)
        elif report_type == 'vat':
            report_data, total_amount, _ = generate_vat_report(active_company.id, form.date_from.data,
                                                               form.date_to.data, supplier_id)
        elif report_type == 'supplier':
            report_data, total_amount = generate_supplier_transactions_report(active_company.id, form.date_from.data,
                                                                              form.date_to.data, supplier_id)
        else:
            query = Invoice.query.filter(
                Invoice.company_id == active_company.id,
                Invoice.invoice_date >= form.date_from.data,
                Invoice.invoice_date <= form.date_to.data
            )
            invoices = query.all()
            report_data = []
            total_amount = 0
            for inv in invoices:
                report_data.append({
                    'Invoice #': inv.invoice_number,
                    'Date': inv.invoice_date.strftime('%d-%m-%Y'),
                    'Due Date': inv.due_date.strftime('%d-%m-%Y'),
                    'Customer': inv.customer.name if inv.customer else 'N/A',
                    'Subtotal': float(inv.subtotal),
                    'VAT': float(inv.tax_amount),
                    'Total': float(inv.total),
                    'Status': inv.status,
                    'Days Overdue': (
                                datetime.now().date() - inv.due_date).days if inv.due_date and inv.status != 'paid' else 0
                })
                total_amount += float(inv.total)
        if action == 'download':
            if form.format.data == 'pdf':
                pdf_data = generate_report_pdf(report_data, report_title, total_amount, active_company.base_currency,
                                               report_type)
                return send_file(BytesIO(pdf_data), mimetype='application/pdf', as_attachment=True,
                                 download_name=f'{report_title}_{datetime.now().strftime("%Y%m%d")}.pdf')
            else:
                excel_data = generate_report_excel(report_data, report_title, total_amount,
                                                   active_company.base_currency)
                return send_file(BytesIO(excel_data),
                                 mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                 as_attachment=True,
                                 download_name=f'{report_title}_{datetime.now().strftime("%Y%m%d")}.xlsx')
    return render_template('report_view.html', form=form, report_data=report_data, report_title=report_title,
                           total_amount=total_amount, active_company=active_company, now=datetime.now())


@app.route('/download_pdf_voucher/<int:payment_id>')
def download_pdf_voucher(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    company = get_active_company()
    gross_total = 0
    wht_total = 0
    vat_total = 0
    net_total = 0
    for item in payment.line_items:
        gross_total += item.total_amount
        wht_total += item.withholding_tax_amount or 0
        vat_total += item.vat_amount or 0
        net_total += item.net_amount or 0
    gross_total = round(gross_total, 2)
    wht_total = round(wht_total, 2)
    vat_total = round(vat_total, 2)
    net_total = round(net_total, 2)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=20, alignment=TA_CENTER,
                                 spaceAfter=8, textColor=colors.black, fontName='Helvetica-Bold')
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontSize=12, spaceAfter=4,
                                   textColor=colors.black, fontName='Helvetica-Bold', alignment=TA_CENTER)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=8, spaceAfter=2,
                                  textColor=colors.black, fontName='Helvetica')
    value_style = ParagraphStyle('ValueStyle', parent=styles['Normal'], fontSize=8, fontName='Helvetica-Bold',
                                 spaceAfter=2, textColor=colors.black)
    section_title_style = ParagraphStyle('SectionTitleStyle', parent=styles['Normal'], fontSize=10,
                                         fontName='Helvetica-Bold', textColor=colors.black, spaceAfter=4,
                                         alignment=TA_CENTER)
    signature_style = ParagraphStyle('SignatureStyle', parent=styles['Normal'], fontSize=10, fontName='Helvetica',
                                     textColor=colors.black, alignment=TA_CENTER, leading=14)
    elements = []
    if company.logo_filename:
        try:
            logo_path = os.path.join(app.config['UPLOAD_FOLDER'], company.logo_filename)
            if os.path.exists(logo_path):
                img = Image(logo_path, width=1.5 * inch, height=0.75 * inch)
                img.hAlign = 'CENTER'
                elements.append(img)
                elements.append(Spacer(1, 4))
        except:
            pass
    elements.append(Paragraph(company.name, title_style))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph('PAYMENT VOUCHER', heading_style))
    elements.append(Spacer(1, 10))
    col_widths = [2.2 * inch, 2.2 * inch, 2.2 * inch]
    col_data = []
    col_data.append([
        Paragraph('TRANSACTION DETAILS', section_title_style),
        Paragraph('SUPPLIER INFORMATION', section_title_style),
        Paragraph('PAYMENT INFORMATION', section_title_style)
    ])
    trans_details = [
        f'<b>Transaction #:</b> {payment.transaction_number}',
        f'<b>Date:</b> {payment.payment_date.strftime("%d-%m-%Y") if payment.payment_date else "N/A"}'
    ]
    supplier_details = [f'<b>Supplier:</b> {payment.supplier.name}']
    if payment.supplier.address:
        supplier_details.append(f'<b>Address:</b> {payment.supplier.address[:50]}...' if len(
            payment.supplier.address) > 50 else f'<b>Address:</b> {payment.supplier.address}')
    if payment.supplier.telephone:
        supplier_details.append(f'<b>Telephone:</b> {payment.supplier.telephone}')
    if payment.supplier.tax_id:
        supplier_details.append(f'<b>Tax ID:</b> {payment.supplier.tax_id}')
    payment_details = [
        f'<b>Invoice #:</b> {payment.invoice_number or "N/A"}',
        f'<b>Currency:</b> {payment.currency}',
        f'<b>Exchange Rate:</b> {payment.exchange_rate:.4f}',
        f'<b>Source Bank:</b> {payment.source_bank.name if payment.source_bank else "N/A"}',
    ]
    if payment.reference:
        payment_details.append(f'<b>Reference:</b> {payment.reference}')
    if payment.description:
        payment_details.append(f'<b>Description:</b> {payment.description[:40]}...' if len(
            payment.description) > 40 else f'<b>Description:</b> {payment.description}')
    if payment.attachment_filename:
        payment_details.append(f'<b>Attachment:</b> {payment.attachment_original_name or payment.attachment_filename}')
        payment_details.append(f'<b>Attachment Size:</b> {format_file_size(payment.attachment_size)}')
    max_rows = max(len(trans_details), len(supplier_details), len(payment_details))
    while len(trans_details) < max_rows:
        trans_details.append('')
    while len(supplier_details) < max_rows:
        supplier_details.append('')
    while len(payment_details) < max_rows:
        payment_details.append('')
    for i in range(max_rows):
        col_data.append([Paragraph(trans_details[i], normal_style), Paragraph(supplier_details[i], normal_style),
                         Paragraph(payment_details[i], normal_style)])
    info_table = Table(col_data, colWidths=col_widths)
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10), ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6), ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#cccccc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))
    if payment.line_items:
        elements.append(Paragraph('LINE ITEMS', heading_style))
        elements.append(Spacer(1, 4))
        line_data = []
        line_data.append([
            Paragraph('S/N', normal_style), Paragraph('Description', normal_style),
            Paragraph('Qty', normal_style), Paragraph('Unit Price', normal_style),
            Paragraph('Total', normal_style), Paragraph('WHT Rate', normal_style),
            Paragraph('WHT Amount', normal_style), Paragraph('VAT Rate', normal_style),
            Paragraph('VAT Amount', normal_style), Paragraph('Net', normal_style)
        ])
        for idx, item in enumerate(payment.line_items, 1):
            line_data.append([
                Paragraph(str(idx), normal_style), Paragraph(item.description, normal_style),
                Paragraph(f"{item.quantity:,.2f}", normal_style), Paragraph(f"{item.unit_price:,.2f}", normal_style),
                Paragraph(f"{item.total_amount:,.2f}", normal_style),
                Paragraph(f"{item.withholding_tax_rate or 0:.2f}%", normal_style),
                Paragraph(f"{item.withholding_tax_amount or 0:,.2f}", normal_style),
                Paragraph(f"{item.vat_rate or 0:.2f}%", normal_style),
                Paragraph(f"{item.vat_amount or 0:,.2f}", normal_style),
                Paragraph(f"{item.net_amount or 0:,.2f}", normal_style)
            ])
        line_data.append([
            Paragraph('', normal_style), Paragraph('TOTALS', value_style),
            Paragraph('', normal_style), Paragraph('', normal_style),
            Paragraph(f"{gross_total:,.2f}", value_style), Paragraph('', normal_style),
            Paragraph(f"{wht_total:,.2f}", value_style), Paragraph('', normal_style),
            Paragraph(f"{vat_total:,.2f}", value_style), Paragraph(f"{net_total:,.2f}", value_style)
        ])
        line_table = Table(line_data, colWidths=[0.35 * inch, 2.0 * inch, 0.5 * inch, 0.7 * inch, 0.7 * inch,
                                                 0.55 * inch, 0.7 * inch, 0.55 * inch, 0.7 * inch, 0.7 * inch])
        line_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (0, -2), 'CENTER'),
            ('ALIGN', (2, 1), (2, -2), 'CENTER'),
            ('ALIGN', (3, 1), (9, -2), 'RIGHT'),
            ('ALIGN', (5, 1), (5, -2), 'CENTER'),
            ('ALIGN', (7, 1), (7, -2), 'CENTER'),
            ('ALIGN', (1, 1), (1, -2), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#cccccc')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 8),
            ('SPAN', (0, -1), (1, -1)), ('SPAN', (2, -1), (3, -1)),
            ('SPAN', (5, -1), (5, -1)), ('SPAN', (7, -1), (7, -1)),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#cccccc')),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 12))
    elements.append(Paragraph('PAYMENT SUMMARY', heading_style))
    elements.append(Spacer(1, 4))
    currency = payment.currency
    summary_data = [
        ['Total Gross Amount:', f"{gross_total:,.2f} {currency}"],
        ['Less: Withholding Tax:', f"({wht_total:,.2f} {currency})"],
        ['Add: VAT:', f"{vat_total:,.2f} {currency}"],
    ]
    summary_table = Table(summary_data, colWidths=[2.8 * inch, 2.2 * inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2), ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10), ('GRID', (0, 0), (1, 2), 0.5, colors.HexColor('#dddddd')),
        ('BACKGROUND', (0, 0), (0, 2), colors.HexColor('#f8f9fa')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 6))
    net_data = [['NET PAYMENT AMOUNT:', f"{net_total:,.2f} {currency}"]]
    net_table = Table(net_data, colWidths=[2.8 * inch, 2.2 * inch])
    net_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica'), ('FONTSIZE', (0, 0), (1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (1, 0), 4), ('TOPPADDING', (0, 0), (1, 0), 4),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'), ('LEFTPADDING', (0, 0), (1, 0), 10),
        ('RIGHTPADDING', (0, 0), (1, 0), 10), ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#f0f0f0')),
        ('LINEABOVE', (0, 0), (1, 0), 1, colors.HexColor('#cccccc')),
        ('LINEBELOW', (0, 0), (1, 0), 1, colors.HexColor('#cccccc')),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph('AUTHORIZED SIGNATURES', heading_style))
    elements.append(Spacer(1, 4))
    preparer = payment.preparer
    approver = payment.approver
    receiver = payment.receiver
    preparer_name = preparer.name if preparer else ''
    preparer_title = preparer.title if preparer else ''
    approver_name = approver.name if approver else ''
    approver_title = approver.title if approver else ''
    receiver_name = receiver.name if receiver else ''
    receiver_title = receiver.title if receiver else ''
    sig_col_widths = [2.2 * inch, 2.2 * inch, 2.2 * inch]
    sig_data = []
    sig_data.append([
        Paragraph('PREPARED BY', section_title_style),
        Paragraph('APPROVED BY', section_title_style),
        Paragraph('RECEIVED BY', section_title_style)
    ])
    preparer_display = ""
    if preparer_name:
        preparer_display += f"<b>{preparer_name}</b>"
        if preparer_title:
            preparer_display += f"<br/>{preparer_title}"
    else:
        preparer_display = "_________________________"
    approver_display = ""
    if approver_name:
        approver_display += f"<b>{approver_name}</b>"
        if approver_title:
            approver_display += f"<br/>{approver_title}"
    else:
        approver_display = "_________________________"
    receiver_display = ""
    if receiver_name:
        receiver_display += f"<b>{receiver_name}</b>"
        if receiver_title:
            receiver_display += f"<br/>{receiver_title}"
    else:
        receiver_display = "_________________________"
    sig_data.append([
        Paragraph(preparer_display, signature_style),
        Paragraph(approver_display, signature_style),
        Paragraph(receiver_display, signature_style)
    ])
    sig_data.append([
        Paragraph('Date: ____________________', normal_style),
        Paragraph('Date: ____________________', normal_style),
        Paragraph('Date: ____________________', normal_style)
    ])
    sig_images = []
    for sig in [preparer, approver, receiver]:
        if sig and sig.signature_filename:
            try:
                sig_path = os.path.join(app.config['SIGNATURE_FOLDER'], sig.signature_filename)
                if os.path.exists(sig_path):
                    img = Image(sig_path, width=1.2 * inch, height=0.4 * inch)
                    sig_images.append(img)
                else:
                    sig_images.append(Paragraph('____________________', normal_style))
            except:
                sig_images.append(Paragraph('____________________', normal_style))
        else:
            sig_images.append(Paragraph('____________________', normal_style))
    sig_data.append(sig_images)
    sig_table = Table(sig_data, colWidths=sig_col_widths)
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10), ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8), ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#cccccc')),
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'), ('BOTTOMPADDING', (0, 1), (-1, 1), 6),
        ('TOPPADDING', (0, 1), (-1, 1), 6), ('ALIGN', (0, 2), (-1, 2), 'CENTER'),
        ('BOTTOMPADDING', (0, 2), (-1, 2), 4), ('TOPPADDING', (0, 2), (-1, 2), 4),
        ('LINEABOVE', (0, 2), (-1, 2), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN', (0, 3), (-1, 3), 'CENTER'), ('BOTTOMPADDING', (0, 3), (-1, 3), 4),
        ('TOPPADDING', (0, 3), (-1, 3), 4), ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    elements.append(sig_table)
    elements.append(Spacer(1, 8))
    footer_text = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M')} | This is a computer-generated voucher"
    elements.append(Paragraph(footer_text, normal_style))
    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()
    return send_file(BytesIO(pdf_data), mimetype='application/pdf', as_attachment=True,
                     download_name=f'Payment_Voucher_{payment.transaction_number}.pdf')


# ==================== INITIALIZE DATABASE ====================
init_db()

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 APP4 - Billing and Payment Platform")
    print("=" * 60)
    print("📊 Features: Payments, Invoices, VAT, Levy, Reports")
    print("📁 Base Path: " + (BASE_PATH if BASE_PATH else '/'))
    print("🌐 Running at: http://localhost:5000" + (BASE_PATH if BASE_PATH else ''))
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)