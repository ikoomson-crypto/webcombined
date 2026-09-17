# acctsys/models.py – Complete with correct relationships

from flask_login import UserMixin
from datetime import datetime
from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    invoices = db.relationship('Invoice', back_populates='user', lazy=True)
    expenses = db.relationship('Expense', back_populates='user', lazy=True)
    journal_entries = db.relationship('JournalEntry', back_populates='user', lazy=True)
    purchases = db.relationship('Purchase', back_populates='user', lazy=True)
    payment_vouchers = db.relationship('PaymentVoucher', back_populates='user', lazy=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    expenses = db.relationship('Expense', back_populates='category', lazy=True)


class AccountType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    normal_balance = db.Column(db.String(10))
    min_code = db.Column(db.Integer, nullable=True)
    max_code = db.Column(db.Integer, nullable=True)

    accounts = db.relationship('ChartOfAccount', back_populates='account_type', lazy=True)


class ChartOfAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_code = db.Column(db.String(20), unique=True, nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    account_type_id = db.Column(db.Integer, db.ForeignKey('account_type.id'), nullable=False)
    description = db.Column(db.String(200))
    balance = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=True)
    is_main_account = db.Column(db.Boolean, default=False)

    # Relationships
    parent = db.relationship('ChartOfAccount', remote_side=[id], back_populates='sub_accounts', lazy=True)
    sub_accounts = db.relationship('ChartOfAccount', back_populates='parent', lazy=True)
    account_type = db.relationship('AccountType', back_populates='accounts', lazy=True)
    journal_entries = db.relationship('JournalEntry', back_populates='account', lazy=True)


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    tax_id = db.Column(db.String(50))
    payment_terms = db.Column(db.String(50), default='Net 30')
    opening_balance = db.Column(db.Float, default=0.0)
    current_balance = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    purchases = db.relationship('Purchase', back_populates='supplier', lazy=True)
    payment_vouchers = db.relationship('PaymentVoucher', back_populates='supplier', lazy=True)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    tax_id = db.Column(db.String(50))
    credit_limit = db.Column(db.Float, default=0.0)
    opening_balance = db.Column(db.Float, default=0.0)
    current_balance = db.Column(db.Float, default=0.0)
    payment_terms = db.Column(db.String(50), default='Net 30')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class JournalEntry(db.Model):
    __tablename__ = 'journal_entry'
    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)
    account_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=False)
    debit = db.Column(db.Float, default=0.0)
    credit = db.Column(db.Float, default=0.0)
    reference_type = db.Column(db.String(50))
    reference_id = db.Column(db.Integer)
    attachment_filename = db.Column(db.String(255))
    attachment_original_name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    account = db.relationship('ChartOfAccount', back_populates='journal_entries', lazy=True)
    user = db.relationship('User', back_populates='journal_entries', lazy=True)


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_number = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    invoice_number = db.Column(db.String(50))
    amount = db.Column(db.Float, nullable=False, default=0.0)
    date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='Pending')
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    supplier = db.relationship('Supplier', back_populates='purchases', lazy=True)
    user = db.relationship('User', back_populates='purchases', lazy=True)


class PurchaseLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=False)

    # Relationships
    purchase = db.relationship('Purchase', backref='lines', lazy=True)
    account = db.relationship('ChartOfAccount', backref='purchase_lines', lazy=True)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', back_populates='invoices', lazy=True)
    customer = db.relationship('Customer', backref='invoices', lazy=True)
    # ❌ REMOVED: account = db.relationship('ChartOfAccount', backref='invoices', lazy=True)


class InvoiceLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=False)

    # Relationships
    invoice = db.relationship('Invoice', backref='lines', lazy=True)
    account = db.relationship('ChartOfAccount', backref='invoice_lines', lazy=True)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    payment_method = db.Column(db.String(50))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    category = db.relationship('Category', back_populates='expenses', lazy=True)
    user = db.relationship('User', back_populates='expenses', lazy=True)


class PaymentVoucher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    voucher_number = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    currency = db.Column(db.String(3), default='USD')
    exchange_rate = db.Column(db.Float, default=1.0)
    date = db.Column(db.Date, nullable=False)
    payment_account_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=False)
    gross_amount = db.Column(db.Float, nullable=False)
    wht_amount = db.Column(db.Float, default=0.0)
    vat_amount = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='Pending')
    reference_number = db.Column(db.String(100))
    attachment_filename = db.Column(db.String(255))
    attachment_original_name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    supplier = db.relationship('Supplier', back_populates='payment_vouchers', lazy=True)
    payment_account = db.relationship('ChartOfAccount', foreign_keys=[payment_account_id], backref='payment_vouchers_credit', lazy=True)
    user = db.relationship('User', back_populates='payment_vouchers', lazy=True)


class PaymentVoucherLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_voucher_id = db.Column(db.Integer, db.ForeignKey('payment_voucher.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    wht_rate = db.Column(db.Float, default=0.0)
    vat_rate = db.Column(db.Float, default=0.0)
    gross_amount = db.Column(db.Float, nullable=False)
    wht_amount = db.Column(db.Float, default=0.0)
    vat_amount = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, default=0.0)

    payment_voucher = db.relationship('PaymentVoucher', backref='lines', lazy=True)


class GeneralLedger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('chart_of_account.id'), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship('ChartOfAccount', backref='general_ledger', lazy=True)

# acctsys/models.py – Updated SystemSetting model

class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Integer, nullable=True)              # ChartOfAccount id
    value_string = db.Column(db.String(255), nullable=True)   # ✅ widened from 100 → 255
    value_text = db.Column(db.Text, nullable=True)            # ✅ NEW: long text (address, notes)
    description = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
