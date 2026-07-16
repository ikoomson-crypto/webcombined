# app4/app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, FloatField, SelectField, DateField, FieldList, FormField, HiddenField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, ValidationError
from datetime import datetime
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
import os
import re
import json
import traceback
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-app4-secret-key-change-in-production')

# ============ DATABASE CONFIGURATION ============
# Check if we're on Render (production) or local
if os.environ.get('DATABASE_URL_APP4'):
    # Use PostgreSQL on Render
    database_url = os.environ.get('DATABASE_URL_APP4')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print(f"✅ Using PostgreSQL database on Render for App4")
else:
    # Use SQLite locally
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'app4.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f"✅ Using SQLite database at: {db_path}")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False

# ============ FOLDER CONFIGURATION ============
base_dir = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'static/uploads/logos')
app.config['SIGNATURE_FOLDER'] = os.path.join(base_dir, 'static/uploads/signatures')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SIGNATURE_FOLDER'], exist_ok=True)

# Initialize database
db = SQLAlchemy(app)


# ==================== DATABASE INITIALIZATION FUNCTION ====================
def init_db():
    """Initialize database - create tables and default data"""
    with app.app_context():
        db.create_all()
        print(f"✅ Database tables created/verified")

        # Create default company if none exists
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


# ==================== FORMS ====================

class SignatureForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    title = StringField('Title/Position', validators=[Optional(), Length(max=100)])
    role = SelectField('Role', choices=[
        ('Preparer', 'Preparer'),
        ('Approver', 'Approver'),
        ('Receiver', 'Receiver')
    ], validators=[DataRequired()])
    signature_image = FileField('Signature Image', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')
    ])
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
        ('', '-- Select Currency --'),
        ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'),
        ('JPY', 'JPY - Japanese Yen'),
        ('CHF', 'CHF - Swiss Franc'),
        ('CAD', 'CAD - Canadian Dollar'),
        ('AUD', 'AUD - Australian Dollar'),
        ('CNY', 'CNY - Chinese Yuan'),
        ('INR', 'INR - Indian Rupee'),
        ('BRL', 'BRL - Brazilian Real'),
        ('ZAR', 'ZAR - South African Rand'),
        ('AED', 'AED - UAE Dirham'),
        ('NGN', 'NGN - Nigerian Naira'),
        ('KES', 'KES - Kenyan Shilling'),
        ('TZS', 'TZS - Tanzanian Shilling'),
        ('UGX', 'UGX - Ugandan Shilling'),
        ('ZMW', 'ZMW - Zambian Kwacha')
    ], validators=[DataRequired()], default='')
    exchange_rate = FloatField('Exchange Rate (1 USD = ?)', validators=[Optional(), NumberRange(min=0.01)], default=1.0)
    payment_date = DateField('Payment Date', format='%Y-%m-%d', validators=[Optional()])
    description = TextAreaField('Payment Description', validators=[Optional()])
    reference = StringField('Reference Number', validators=[Optional()])

    prepared_by_id = SelectField('Prepared By', coerce=int, validators=[Optional()])
    approved_by_id = SelectField('Approved By', coerce=int, validators=[Optional()])
    received_by_id = SelectField('Received By', coerce=int, validators=[Optional()])

    source_bank_id = SelectField('Source Bank', coerce=int, validators=[Optional()])

    line_items = FieldList(FormField(LineItemForm), min_entries=1)

    def __init__(self, *args, **kwargs):
        super(PaymentForm, self).__init__(*args, **kwargs)
        active_company = Company.query.filter_by(is_active=True).first()

        # Supplier choices - Add empty option at the top
        if active_company:
            suppliers = Supplier.query.filter_by(company_id=active_company.id).all()
            # Sort suppliers alphabetically
            suppliers = sorted(suppliers, key=lambda s: s.name.lower())
            # Add empty option first
            self.supplier_id.choices = [(0, '-- Select Supplier --')] + [(s.id, s.name) for s in suppliers]
        else:
            self.supplier_id.choices = [(0, '-- No suppliers available --')]

        # Signature choices
        default_choices = [(0, '-- Select --')]

        if active_company:
            signatures = AuthorizedSignature.query.filter_by(
                company_id=active_company.id,
                is_active=True
            ).all()

            if signatures:
                signature_choices = [(s.id, f"{s.name} ({s.role})") for s in signatures]
                self.prepared_by_id.choices = default_choices + signature_choices
                self.approved_by_id.choices = default_choices + signature_choices
                self.received_by_id.choices = default_choices + signature_choices
            else:
                self.prepared_by_id.choices = [(0, '-- No signatures available --')]
                self.approved_by_id.choices = [(0, '-- No signatures available --')]
                self.received_by_id.choices = [(0, '-- No signatures available --')]

            # Bank choices - Add empty option at the top
            banks = Bank.query.filter_by(
                company_id=active_company.id,
                is_active=True
            ).all()

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
        ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'),
        ('GHS', 'GHS - Ghana Cedi'),
        ('JPY', 'JPY - Japanese Yen'),
        ('CHF', 'CHF - Swiss Franc'),
        ('CAD', 'CAD - Canadian Dollar'),
        ('AUD', 'AUD - Australian Dollar'),
        ('CNY', 'CNY - Chinese Yuan'),
        ('INR', 'INR - Indian Rupee'),
        ('BRL', 'BRL - Brazilian Real'),
        ('ZAR', 'ZAR - South African Rand'),
        ('AED', 'AED - UAE Dirham'),
        ('NGN', 'NGN - Nigerian Naira'),
        ('KES', 'KES - Kenyan Shilling'),
        ('TZS', 'TZS - Tanzanian Shilling'),
        ('UGX', 'UGX - Ugandan Shilling'),
        ('ZMW', 'ZMW - Zambian Kwacha')
    ], validators=[DataRequired()])
    logo = FileField('Company Logo', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'svg'], 'Images only!')
    ])


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
    format = SelectField('Download Format', choices=[
        ('pdf', 'PDF'),
        ('excel', 'Excel')
    ], validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        super(ReportForm, self).__init__(*args, **kwargs)
        active_company = Company.query.filter_by(is_active=True).first()
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


# ==================== UTILITY FUNCTIONS ====================

def get_exchange_rate(currency):
    exchange_rates = {
        'USD': 1.0,
        'EUR': 0.92,
        'GBP': 0.79,
        'GHS': 15.0,
        'JPY': 149.0,
        'CHF': 0.88,
        'CAD': 1.36,
        'AUD': 1.53,
        'CNY': 7.25,
        'INR': 83.0,
        'BRL': 5.10,
        'ZAR': 18.50,
        'AED': 3.67,
        'NGN': 1500.0,
        'KES': 150.0,
        'TZS': 2500.0,
        'UGX': 3700.0,
        'ZMW': 26.0
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


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_active_company():
    return Company.query.filter_by(is_active=True).first()


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
                'address': '',
                'telephone': '',
                'bank_name': '',
                'account_number': '',
                'account_name': '',
                'swift_code': '',
                'bank_address': '',
                'email': '',
                'tax_id': ''
            }

            field_mappings = {
                'address': 'Address',
                'telephone': 'Telephone',
                'bank_name': 'Bank Name',
                'account_number': 'Account Number/IBAN',
                'account_name': 'Account Name',
                'swift_code': 'SWIFT Code',
                'bank_address': 'Bank Address',
                'email': 'Email (Optional)',
                'tax_id': 'Tax ID (Optional)'
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
                    'supplier_id': supplier_id,
                    'invoice_number': invoice_number,
                    'currency': currency,
                    'exchange_rate': exchange_rate,
                    'payment_date': payment_date,
                    'description': description,
                    'reference': reference,
                    'source_bank_id': source_bank_id,
                    'prepared_by_id': prepared_by_id,
                    'approved_by_id': approved_by_id,
                    'received_by_id': received_by_id,
                    'line_items': [],
                    'total_gross': 0,
                    'total_wht': 0,
                    'total_vat': 0,
                    'total_net': 0
                }

            calc = calculate_line_item_totals(quantity, unit_price, wht_rate, vat_rate)

            line_item = {
                'description': item_desc,
                'quantity': quantity,
                'unit_price': unit_price,
                'total_amount': calc['total'],
                'wht_rate': wht_rate,
                'vat_rate': vat_rate,
                'wht_amount': calc['wht_amount'],
                'vat_amount': calc['vat_amount'],
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
    """Generate Supplier Transactions Report - Sorted by Supplier Name (Case-Insensitive)"""
    query = Payment.query.filter(
        Payment.company_id == company_id,
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to
    )

    if supplier_id:
        query = query.filter(Payment.supplier_id == supplier_id)

    # Get all payments
    payments = query.all()

    # Sort by supplier name alphabetically (case-insensitive)
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
                    str(idx),
                    row['Transaction #'],
                    row['Date'],
                    row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:30] + '...' if len(row['Description']) > 30 else row['Description'],
                    f"{row['Gross Amount']:,.2f}",
                    f"{row['WHT Rate (%)']:.2f}%",
                    f"{row['WHT Amount']:,.2f}",
                    row['Currency']
                ])
        elif report_type == 'vat':
            col_headers = ['#', 'Transaction #', 'Date', 'Supplier', 'Invoice #', 'Description', 'Gross Amount',
                           'VAT Rate', 'VAT Amount', 'Currency']
            col_widths = [0.3 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch, 0.7 * inch, 1.2 * inch, 0.7 * inch,
                          0.6 * inch, 0.7 * inch, 0.5 * inch]
            data = []
            for idx, row in enumerate(report_data, 1):
                data.append([
                    str(idx),
                    row['Transaction #'],
                    row['Date'],
                    row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:30] + '...' if len(row['Description']) > 30 else row['Description'],
                    f"{row['Gross Amount']:,.2f}",
                    f"{row['VAT Rate (%)']:.2f}%",
                    f"{row['VAT Amount']:,.2f}",
                    row['Currency']
                ])
        else:
            col_headers = ['#', 'Transaction #', 'Date', 'Supplier', 'Invoice #', 'Description', 'Gross', 'WHT', 'VAT',
                           'Net', 'Currency']
            col_widths = [0.3 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch, 0.7 * inch, 1.0 * inch, 0.6 * inch,
                          0.6 * inch, 0.6 * inch, 0.6 * inch, 0.5 * inch]
            data = []
            for idx, row in enumerate(report_data, 1):
                data.append([
                    str(idx),
                    row['Transaction #'],
                    row['Date'],
                    row['Supplier'],
                    row['Invoice #'],
                    row['Description'][:25] + '...' if len(row['Description']) > 25 else row['Description'],
                    f"{row['Gross Amount']:,.2f}",
                    f"{row['WHT Amount']:,.2f}",
                    f"{row['VAT Amount']:,.2f}",
                    f"{row['Net Amount']:,.2f}",
                    row['Currency']
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


# ==================== ROUTES ====================

@app.route('/')
def index():
    active_company = get_active_company()
    supplier_count = payment_count = total_amount = 0

    if active_company:
        supplier_count = Supplier.query.filter_by(company_id=active_company.id).count()
        payment_count = Payment.query.filter_by(company_id=active_company.id).count()
        total_amount = db.session.query(db.func.sum(Payment.total_net_amount)).filter_by(
            company_id=active_company.id).scalar() or 0

    return render_template('index.html',
                           active_company=active_company,
                           supplier_count=supplier_count,
                           payment_count=payment_count,
                           total_amount=total_amount)


@app.route('/companies')
def companies():
    companies = Company.query.all()
    return render_template('companies.html', companies=companies)


@app.route('/add_company', methods=['GET', 'POST'])
def add_company():
    form = CompanyForm()
    if form.validate_on_submit():
        company = Company(
            name=form.name.data,
            base_currency=form.base_currency.data
        )

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
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'suppliers_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


@app.route('/download_template')
def download_template():
    excel_file = generate_supplier_template()
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='supplier_import_template.xlsx'
    )


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
            from datetime import timedelta
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

    return render_template('payments.html',
                           payments=payments,
                           company=active_company,
                           suppliers=suppliers,
                           currencies=currencies)


@app.route('/add_payment', methods=['GET', 'POST'])
def add_payment():
    active_company = get_active_company()
    if not active_company:
        flash('Please select a company first', 'warning')
        return redirect(url_for('companies'))

    form = PaymentForm()

    # Only add one empty line item - NO default date set
    if len(form.line_items) == 0:
        form.line_items.append_entry()

    if request.method == 'POST':
        print("=" * 60)
        print("POST REQUEST RECEIVED")
        print(f"Form data keys: {list(request.form.keys())}")
        print("=" * 60)

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
            # Generate unique transaction number
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
            print(f"Generated transaction number: {transaction_number}")

            # Parse payment date - if empty, use None (will default in model)
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

            total_gross = 0
            total_wht = 0
            total_vat = 0
            total_net = 0

            for item_data in line_items_data:
                print(f"Processing item: {item_data['description']}")
                calc = calculate_line_item_totals(
                    item_data['quantity'],
                    item_data['unit_price'],
                    item_data['wht_rate'],
                    item_data['vat_rate']
                )
                print(f"  Calculated: {calc}")

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

            print(
                f"TOTALS - Gross: {payment.total_gross_amount}, WHT: {payment.total_wht_amount}, VAT: {payment.total_vat_amount}, Net: {payment.total_net_amount}")

            db.session.add(payment)
            db.session.commit()
            db.session.refresh(payment)
            print(f"AFTER REFRESH - Net Amount: {payment.total_net_amount}")

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
                db.session.delete(payment)
                deleted_count += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} payment(s)'
        })
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
    db.session.delete(payment)
    db.session.commit()
    flash('Payment deleted successfully!', 'success')
    return redirect(url_for('payments'))


@app.route('/calculate_line_item', methods=['POST'])
def calculate_line_item():
    data = request.json
    quantity = float(data.get('quantity', 1))
    unit_price = float(data.get('unit_price', 0))
    wht_rate = float(data.get('wht_rate', 0))
    vat_rate = float(data.get('vat_rate', 0))

    result = calculate_line_item_totals(quantity, unit_price, wht_rate, vat_rate)
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
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='payment_import_template.xlsx'
        )
    except Exception as e:
        flash(f'Error generating template: {str(e)}', 'danger')
        return redirect(url_for('import_payments'))


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

    valid_report_types = ['wht', 'vat', 'supplier']
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
    else:
        report_title = 'Supplier Transactions Report'

    if request.method == 'GET':
        supplier_id = None
        if report_type == 'wht':
            report_data, total_amount, _ = generate_wht_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )
        elif report_type == 'vat':
            report_data, total_amount, _ = generate_vat_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )
        else:
            report_data, total_amount = generate_supplier_transactions_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )

    if request.method == 'POST' and form.validate_on_submit():
        supplier_id = form.supplier_id.data if form.supplier_id.data != 0 else None
        action = request.form.get('action', 'preview')

        if report_type == 'wht':
            report_data, total_amount, _ = generate_wht_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )
        elif report_type == 'vat':
            report_data, total_amount, _ = generate_vat_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )
        else:
            report_data, total_amount = generate_supplier_transactions_report(
                active_company.id, form.date_from.data, form.date_to.data, supplier_id
            )

        if action == 'download':
            if form.format.data == 'pdf':
                pdf_data = generate_report_pdf(
                    report_data,
                    report_title,
                    total_amount,
                    active_company.base_currency,
                    report_type
                )
                return send_file(
                    BytesIO(pdf_data),
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'{report_title}_{datetime.now().strftime("%Y%m%d")}.pdf'
                )
            else:
                excel_data = generate_report_excel(
                    report_data,
                    report_title,
                    total_amount,
                    active_company.base_currency
                )
                return send_file(
                    BytesIO(excel_data),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True,
                    download_name=f'{report_title}_{datetime.now().strftime("%Y%m%d")}.xlsx'
                )

    return render_template('report_view.html',
                           form=form,
                           report_data=report_data,
                           report_title=report_title,
                           total_amount=total_amount,
                           active_company=active_company,
                           now=datetime.now())


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
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=8,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=4,
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
    value_style = ParagraphStyle(
        'ValueStyle',
        parent=styles['Normal'],
        fontSize=8,
        fontName='Helvetica-Bold',
        spaceAfter=2,
        textColor=colors.black
    )
    section_title_style = ParagraphStyle(
        'SectionTitleStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold',
        textColor=colors.black,
        spaceAfter=4,
        alignment=TA_CENTER
    )
    signature_style = ParagraphStyle(
        'SignatureStyle',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica',
        textColor=colors.black,
        alignment=TA_CENTER,
        leading=14
    )

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
        f'<b>Date:</b> {payment.payment_date.strftime("%d-%m-%Y") if payment.payment_date else "N/A"}',
    ]

    supplier_details = [
        f'<b>Supplier:</b> {payment.supplier.name}',
    ]
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

    max_rows = max(len(trans_details), len(supplier_details), len(payment_details))

    while len(trans_details) < max_rows:
        trans_details.append('')
    while len(supplier_details) < max_rows:
        supplier_details.append('')
    while len(payment_details) < max_rows:
        payment_details.append('')

    for i in range(max_rows):
        col_data.append([
            Paragraph(trans_details[i], normal_style),
            Paragraph(supplier_details[i], normal_style),
            Paragraph(payment_details[i], normal_style)
        ])

    info_table = Table(col_data, colWidths=col_widths)
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
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
            Paragraph('S/N', normal_style),
            Paragraph('Description', normal_style),
            Paragraph('Qty', normal_style),
            Paragraph('Unit Price', normal_style),
            Paragraph('Total', normal_style),
            Paragraph('WHT Rate', normal_style),
            Paragraph('WHT Amount', normal_style),
            Paragraph('VAT Rate', normal_style),
            Paragraph('VAT Amount', normal_style),
            Paragraph('Net', normal_style)
        ])

        for idx, item in enumerate(payment.line_items, 1):
            line_data.append([
                Paragraph(str(idx), normal_style),
                Paragraph(item.description, normal_style),
                Paragraph(f"{item.quantity:,.2f}", normal_style),
                Paragraph(f"{item.unit_price:,.2f}", normal_style),
                Paragraph(f"{item.total_amount:,.2f}", normal_style),
                Paragraph(f"{item.withholding_tax_rate or 0:.2f}%", normal_style),
                Paragraph(f"{item.withholding_tax_amount or 0:,.2f}", normal_style),
                Paragraph(f"{item.vat_rate or 0:.2f}%", normal_style),
                Paragraph(f"{item.vat_amount or 0:,.2f}", normal_style),
                Paragraph(f"{item.net_amount or 0:,.2f}", normal_style)
            ])

        line_data.append([
            Paragraph('', normal_style),
            Paragraph('TOTALS', value_style),
            Paragraph('', normal_style),
            Paragraph('', normal_style),
            Paragraph(f"{gross_total:,.2f}", value_style),
            Paragraph('', normal_style),
            Paragraph(f"{wht_total:,.2f}", value_style),
            Paragraph('', normal_style),
            Paragraph(f"{vat_total:,.2f}", value_style),
            Paragraph(f"{net_total:,.2f}", value_style)
        ])

        line_table = Table(line_data,
                           colWidths=[0.35 * inch, 2.0 * inch, 0.5 * inch, 0.7 * inch, 0.7 * inch,
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
            ('SPAN', (0, -1), (1, -1)),
            ('SPAN', (2, -1), (3, -1)),
            ('SPAN', (5, -1), (5, -1)),
            ('SPAN', (7, -1), (7, -1)),
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
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (1, 2), 0.5, colors.HexColor('#dddddd')),
        ('BACKGROUND', (0, 0), (0, 2), colors.HexColor('#f8f9fa')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 6))

    net_data = [['NET PAYMENT AMOUNT:', f"{net_total:,.2f} {currency}"]]
    net_table = Table(net_data, colWidths=[2.8 * inch, 2.2 * inch])
    net_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica'),
        ('FONTSIZE', (0, 0), (1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (1, 0), 4),
        ('TOPPADDING', (0, 0), (1, 0), 4),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (1, 0), 10),
        ('RIGHTPADDING', (0, 0), (1, 0), 10),
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#f0f0f0')),
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
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#cccccc')),
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 6),
        ('TOPPADDING', (0, 1), (-1, 1), 6),
        ('ALIGN', (0, 2), (-1, 2), 'CENTER'),
        ('BOTTOMPADDING', (0, 2), (-1, 2), 4),
        ('TOPPADDING', (0, 2), (-1, 2), 4),
        ('LINEABOVE', (0, 2), (-1, 2), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN', (0, 3), (-1, 3), 'CENTER'),
        ('BOTTOMPADDING', (0, 3), (-1, 3), 4),
        ('TOPPADDING', (0, 3), (-1, 3), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    elements.append(sig_table)
    elements.append(Spacer(1, 8))

    footer_text = f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M')} | This is a computer-generated voucher"
    elements.append(Paragraph(footer_text, normal_style))

    doc.build(elements)

    pdf_data = buffer.getvalue()
    buffer.close()

    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Payment_Voucher_{payment.transaction_number}.pdf'
    )


# ==================== INITIALIZE DATABASE ====================
# This runs when the app starts
init_db()

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 APP4 - Payment System Application")
    print("=" * 60)
    if os.environ.get('DATABASE_URL_APP4'):
        print(f"📊 Database: PostgreSQL (Render)")
    else:
        print(f"📊 Database: SQLite at: {db_path}")
    print("🌐 Running at: http://localhost:5000/app4/")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)