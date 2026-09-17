# acctsys/app.py - Final version (with base currency + company profile)

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file, Response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import uuid
import sqlite3
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter




from config import config
from extensions import db

from acctsys.models import (
    User, Invoice, Expense, Category, AccountType, ChartOfAccount,
    GeneralLedger, Supplier, Customer, JournalEntry, Purchase, PurchaseLine,
    InvoiceLine, PaymentVoucher, PaymentVoucherLine, SystemSetting
)
from acctsys.forms import (
    LoginForm, RegistrationForm, InvoiceForm, InvoiceEditForm, ExpenseForm,
    AccountTypeForm, AccountTypeEditForm, ChartOfAccountForm, ChartOfAccountEditForm,
    SupplierForm, SupplierEditForm, CustomerForm, CustomerEditForm,
    PurchaseForm, PurchaseEditForm, PaymentVoucherForm, PaymentVoucherEditForm
)


# ============================================================
# ✅ CONSTANTS — defined BEFORE anything uses them
# ============================================================

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}

SUPPORTED_CURRENCIES = [
    ('USD', 'USD - US Dollar'),
    ('EUR', 'EUR - Euro'),
    ('GBP', 'GBP - British Pound'),
    ('GHS', 'GHS - Ghana Cedi'),
    ('NGN', 'NGN - Nigerian Naira'),
    ('ZAR', 'ZAR - South African Rand'),
    ('KES', 'KES - Kenyan Shilling'),
    ('XOF', 'XOF - West African CFA Franc'),
]

DEFAULT_BASE_CURRENCY = 'USD'
DEFAULT_COMPANY_NAME = 'Accounting Pro'

COMPANY_SETTING_KEYS = [
    'company_name',
    'company_address',
    'company_phone',
    'company_email',
    'company_tax_id',
    'company_website',
    'company_logo',
]

# ============================================================
# ✅ PDF FONT REGISTRATION (for ₵, ₦, €, £, etc.)
# ============================================================

_UNICODE_FONTS_REGISTERED = False


def register_unicode_fonts():
    """
    Register Unicode-capable fonts with ReportLab so that symbols
    like ₵ (Ghana Cedi), ₦ (Naira), € (Euro), £ (Pound) render correctly.
    Falls back to Helvetica if no Unicode font can be found.
    """
    global _UNICODE_FONTS_REGISTERED
    if _UNICODE_FONTS_REGISTERED:
        return

    # Candidate paths — we look in several common locations
    candidates_regular = [
        # Bundled with reportlab (rare, but some installs ship it)
        os.path.join(os.path.dirname(__import__('reportlab').__file__),
                     'fonts', 'DejaVuSans.ttf'),
        # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans.ttf',
        # macOS (Homebrew)
        '/opt/homebrew/share/fonts/DejaVuSans.ttf',
        '/usr/local/share/fonts/DejaVuSans.ttf',
        # macOS (system)
        '/Library/Fonts/DejaVuSans.ttf',
        # Windows — try Arial, Segoe UI, Calibri (all support ₵)
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf'),
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'segoeui.ttf'),
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibri.ttf'),
        # Project-local fallback (if you drop DejaVuSans.ttf in ./acctsys/fonts/)
        os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf'),
    ]

    candidates_bold = [
        os.path.join(os.path.dirname(__import__('reportlab').__file__),
                     'fonts', 'DejaVuSans-Bold.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
        '/opt/homebrew/share/fonts/DejaVuSans-Bold.ttf',
        '/usr/local/share/fonts/DejaVuSans-Bold.ttf',
        '/Library/Fonts/DejaVuSans-Bold.ttf',
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arialbd.ttf'),
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'segoeuib.ttf'),
        os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'calibrib.ttf'),
        os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans-Bold.ttf'),
    ]

    regular_path = next((p for p in candidates_regular if os.path.exists(p)), None)
    bold_path = next((p for p in candidates_bold if os.path.exists(p)), None)

    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont('AppFont', regular_path))
            print(f"✅ Registered Unicode PDF font: {regular_path}")
        else:
            print("⚠️ No Unicode font found for regular text. "
                  "Currency symbols like ₵ may render as ■.")
            # Fallback: still register something so we don't crash
            pdfmetrics.registerFont(TTFont('AppFont', 'Helvetica'))

        if bold_path:
            pdfmetrics.registerFont(TTFont('AppFont-Bold', bold_path))
        else:
            # Use regular for bold as fallback
            pdfmetrics.registerFont(
                TTFont('AppFont-Bold', bold_path or regular_path or 'Helvetica-Bold')
            )

        _UNICODE_FONTS_REGISTERED = True
    except Exception as e:
        print(f"⚠️ Could not register Unicode font: {e}")
        # Ensure at least the standard fonts are available
        try:
            pdfmetrics.registerFont(TTFont('AppFont', 'Helvetica'))
            pdfmetrics.registerFont(TTFont('AppFont-Bold', 'Helvetica-Bold'))
        except Exception:
            pass


def get_pdf_font(bold=False):
    """Return the font name to use in PDF styles."""
    register_unicode_fonts()
    return 'AppFont-Bold' if bold else 'AppFont'


# acctsys/app.py – Excel export helper


# ============================================================
# ✅ EXCEL EXPORT HELPERS
# ============================================================

# Common styles reused across sheets
EXCEL_TITLE_FONT      = Font(name='Calibri', size=16, bold=True, color='2C3E50')
EXCEL_SUBTITLE_FONT   = Font(name='Calibri', size=11, italic=True, color='555555')
EXCEL_HEADER_FONT     = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
EXCEL_SECTION_FONT    = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
EXCEL_TOTAL_FONT      = Font(name='Calibri', size=11, bold=True)
EXCEL_NORMAL_FONT     = Font(name='Calibri', size=10)

EXCEL_HEADER_FILL     = PatternFill('solid', fgColor='34495E')
EXCEL_SECTION_FILL    = PatternFill('solid', fgColor='3498DB')
EXCEL_SECTION_FILL_2  = PatternFill('solid', fgColor='E74C3C')
EXCEL_SECTION_FILL_3  = PatternFill('solid', fgColor='8E44AD')
EXCEL_TOTAL_FILL      = PatternFill('solid', fgColor='D6EAF8')
EXCEL_TOTAL_FILL_RED  = PatternFill('solid', fgColor='FADBD8')
EXCEL_TOTAL_FILL_GRN  = PatternFill('solid', fgColor='D5F5E3')

EXCEL_THIN_BORDER = Border(
    left=Side(style='thin', color='CCCCCC'),
    right=Side(style='thin', color='CCCCCC'),
    top=Side(style='thin', color='CCCCCC'),
    bottom=Side(style='thin', color='CCCCCC'),
)

EXCEL_ALIGN_LEFT   = Alignment(horizontal='left', vertical='center')
EXCEL_ALIGN_RIGHT  = Alignment(horizontal='right', vertical='center')
EXCEL_ALIGN_CENTER = Alignment(horizontal='center', vertical='center')


def _apply_border(ws, row_start, row_end, col_start, col_end):
    """Apply thin border to a rectangular range."""
    for row in range(row_start, row_end + 1):
        for col in range(col_start, col_end + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = EXCEL_THIN_BORDER


def _autosize_columns(ws, min_width=10, max_width=45):
    """Auto-size columns based on content."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                val = str(cell.value) if cell.value is not None else ''
                max_len = max(max_len, len(val))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(
            max(min_width, max_len + 2), max_width
        )


def _write_company_header(ws, company, base_currency, symbol):
    """Write the standard company header on a worksheet."""
    ws['A1'] = company['name']
    ws['A1'].font = EXCEL_TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5)

    row = 2
    if company.get('address'):
        ws.cell(row=row, column=1, value=company['address'].replace('\n', ', ')).font = EXCEL_SUBTITLE_FONT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1

    contact = []
    if company.get('phone'):   contact.append(f"Tel: {company['phone']}")
    if company.get('email'):   contact.append(f"Email: {company['email']}")
    if company.get('website'): contact.append(f"Web: {company['website']}")
    if contact:
        ws.cell(row=row, column=1, value=" • ".join(contact)).font = EXCEL_SUBTITLE_FONT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1

    if company.get('tax_id'):
        ws.cell(row=row, column=1, value=f"Tax ID / VAT: {company['tax_id']}").font = EXCEL_SUBTITLE_FONT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1

    return row  # next free row


def _write_sheet_title(ws, row, title, period_text):
    """Write a centered title + period line, return next free row."""
    ws.cell(row=row, column=1, value=title).font = Font(name='Calibri', size=14, bold=True, color='2C3E50')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
    row += 1

    ws.cell(row=row, column=1, value=period_text).font = EXCEL_SUBTITLE_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
    return row + 2  # add spacing


# ============================================================
# ✅ FLASK APP INITIALIZATION
# ============================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS

if hasattr(config, 'SQLALCHEMY_ENGINE_OPTIONS'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = config.SQLALCHEMY_ENGINE_OPTIONS

app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ============================================================
# ✅ CORE HELPERS
# ============================================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_system_setting(key):
    """Get a system setting value (integer) by key."""
    setting = SystemSetting.query.filter_by(key=key).first()
    return setting.value if setting else None


def get_base_currency():
    """Get the configured base currency. Falls back to USD."""
    setting = SystemSetting.query.filter_by(key='base_currency').first()
    if setting and setting.value_string:
        return setting.value_string
    return DEFAULT_BASE_CURRENCY


def get_base_currency_symbol():
    """Get the symbol for the base currency."""
    symbols = {
        'USD': '$', 'EUR': '€', 'GBP': '£', 'GHS': '₵',
        'NGN': '₦', 'ZAR': 'R', 'KES': 'KSh', 'XOF': 'CFA',
    }
    code = get_base_currency()
    return symbols.get(code, code + ' ')


def get_company_setting(key, default=''):
    """Fetch a company profile setting by key."""
    setting = SystemSetting.query.filter_by(key=key).first()
    if not setting:
        return default

    if setting.value_string:
        return setting.value_string
    if setting.value_text:
        return setting.value_text
    if setting.value is not None:
        return setting.value
    return default


def get_company_profile():
    """Return the full company profile as a dict."""
    return {
        'name':    get_company_setting('company_name', DEFAULT_COMPANY_NAME),
        'address': get_company_setting('company_address', ''),
        'phone':   get_company_setting('company_phone', ''),
        'email':   get_company_setting('company_email', ''),
        'tax_id':  get_company_setting('company_tax_id', ''),
        'website': get_company_setting('company_website', ''),
        'logo':    get_company_setting('company_logo', ''),
    }


def set_company_setting(key, value):
    """Upsert a company profile setting. Uses value_string or value_text based on length."""
    if value is None:
        value = ''

    setting = SystemSetting.query.filter_by(key=key).first()
    is_long = key in ('company_address',) or len(str(value)) > 200

    if setting:
        if is_long:
            setting.value_text = value
            setting.value_string = None
        else:
            setting.value_string = value
            setting.value_text = None
    else:
        setting = SystemSetting(
            key=key,
            value=None,
            value_string=None if is_long else value,
            value_text=value if is_long else None,
            description=f'Company profile: {key}'
        )
        db.session.add(setting)


def post_to_general_ledger(account_id, amount, is_debit=True):
    """
    Post a transaction to the General Ledger.
    is_debit=True → increase balance (for Debit accounts) or decrease (for Credit accounts)
    is_debit=False → decrease balance (for Debit accounts) or increase (for Credit accounts)
    """
    gl_entry = GeneralLedger.query.filter_by(account_id=account_id).first()
    if not gl_entry:
        gl_entry = GeneralLedger(account_id=account_id, balance=0.0)
        db.session.add(gl_entry)

    account = ChartOfAccount.query.get(account_id)
    if not account:
        return

    account_type = AccountType.query.get(account.account_type_id)
    if not account_type:
        return

    if account_type.normal_balance == 'Debit':
        if is_debit:
            gl_entry.balance += amount
        else:
            gl_entry.balance -= amount
    else:  # Credit-balance accounts
        if is_debit:
            gl_entry.balance -= amount
        else:
            gl_entry.balance += amount

    gl_entry.last_updated = datetime.utcnow()


def generate_next_account_code(account_type_id):
    account_type = AccountType.query.get(account_type_id)
    if not account_type or not account_type.min_code or not account_type.max_code:
        return None

    highest = ChartOfAccount.query.filter(
        ChartOfAccount.account_type_id == account_type_id,
        ChartOfAccount.account_code >= str(account_type.min_code),
        ChartOfAccount.account_code <= str(account_type.max_code)
    ).order_by(ChartOfAccount.account_code.desc()).first()

    if highest:
        try:
            next_code = int(highest.account_code) + 1
        except Exception:
            next_code = account_type.min_code
    else:
        next_code = account_type.min_code

    if next_code > account_type.max_code:
        return None

    return str(next_code)


def generate_next_customer_code():
    last_customer = Customer.query.order_by(Customer.id.desc()).first()
    if last_customer:
        try:
            last_number = int(last_customer.customer_code.split('-')[-1])
            next_number = last_number + 1
        except Exception:
            next_number = 1
    else:
        next_number = 1
    return f"CUST-{next_number:04d}"


def generate_next_supplier_code():
    last_supplier = Supplier.query.order_by(Supplier.id.desc()).first()
    if last_supplier:
        try:
            last_number = int(last_supplier.supplier_code.split('-')[-1])
            next_number = last_number + 1
        except Exception:
            next_number = 1
    else:
        next_number = 1
    return f"SUP-{next_number:04d}"


def generate_next_purchase_number():
    last_purchase = Purchase.query.order_by(Purchase.id.desc()).first()
    if last_purchase:
        try:
            last_number = int(last_purchase.purchase_number.split('-')[-1])
            next_number = last_number + 1
        except Exception:
            next_number = 1
    else:
        next_number = 1
    current_year = datetime.now().year
    return f"PO-{current_year}-{next_number:04d}"


def get_ar_account():
    """Get the configured Accounts Receivable account."""
    ar_account_id = get_system_setting('ar_account_id')
    if ar_account_id:
        return ChartOfAccount.query.get(ar_account_id)

    # Fallback: any active debit-normal account
    return ChartOfAccount.query.join(AccountType).filter(
        AccountType.normal_balance == 'Debit',
        ChartOfAccount.is_active == True
    ).order_by(ChartOfAccount.account_code).first()


def get_ap_account():
    """Get the configured Accounts Payable account."""
    ap_account_id = get_system_setting('ap_account_id')
    if ap_account_id:
        return ChartOfAccount.query.get(ap_account_id)

    # Fallback: any active credit-normal account
    return ChartOfAccount.query.join(AccountType).filter(
        AccountType.normal_balance == 'Credit',
        ChartOfAccount.is_active == True
    ).order_by(ChartOfAccount.account_code).first()


# ============================================================
# ✅ CONTEXT PROCESSOR — inject globals into all templates
# ============================================================

@app.context_processor
def inject_globals():
    return dict(
        base_currency=get_base_currency(),
        base_currency_symbol=get_base_currency_symbol(),
        supported_currencies=SUPPORTED_CURRENCIES,
        company=get_company_profile(),
        datetime=datetime,
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ============================================================
# ✅ DATABASE MIGRATION HELPERS
# ============================================================

def _resolve_sqlite_path():
    """Resolve the actual SQLite file path (handles Flask instance folder)."""
    db_uri = config.SQLALCHEMY_DATABASE_URI
    if not db_uri.startswith('sqlite'):
        return None

    rel = db_uri.replace('sqlite:///', '').replace('sqlite://', '')
    if not os.path.isabs(rel):
        # Flask-SQLAlchemy puts relative sqlite paths in the instance folder
        return os.path.join(app.instance_path, os.path.basename(rel))
    return rel


def ensure_system_setting_columns():
    """SQLite-friendly migration: ensure SystemSetting has value_string and value_text."""
    db_path = _resolve_sqlite_path()
    if not db_path:
        return

    # Also check the "legacy" path in case the DB is in the project root
    candidates = [db_path]
    legacy = config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    if os.path.isabs(legacy) and legacy != db_path:
        candidates.append(legacy)
    elif not os.path.isabs(legacy):
        # also check cwd
        candidates.append(os.path.join(os.getcwd(), legacy))

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='system_setting'"
            )
            if not cursor.fetchone():
                conn.close()
                continue

            cursor.execute("PRAGMA table_info(system_setting)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'value_string' not in columns:
                cursor.execute(
                    "ALTER TABLE system_setting ADD COLUMN value_string VARCHAR(255)"
                )
                print(f"✅ Added value_string to system_setting ({path})")

            if 'value_text' not in columns:
                cursor.execute(
                    "ALTER TABLE system_setting ADD COLUMN value_text TEXT"
                )
                print(f"✅ Added value_text to system_setting ({path})")

            conn.commit()
            conn.close()
            return
        except Exception as e:
            print(f"⚠️  Migration failed for {path}: {e}")


def check_columns_exist():
    """Check if chart_of_account has parent_id and is_main_account."""
    try:
        db_path = config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            return False, False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chart_of_account'"
        )
        if not cursor.fetchone():
            conn.close()
            return False, False

        cursor.execute("PRAGMA table_info(chart_of_account)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()

        return ('parent_id' in columns, 'is_main_account' in columns)
    except Exception as e:
        print(f"⚠️ Could not check columns: {e}")
        return False, False


def add_missing_columns():
    """Add parent_id and is_main_account to chart_of_account if missing."""
    try:
        db_path = config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            return False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chart_of_account'"
        )
        if not cursor.fetchone():
            conn.close()
            return False

        cursor.execute("PRAGMA table_info(chart_of_account)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'parent_id' not in columns:
            try:
                cursor.execute(
                    "ALTER TABLE chart_of_account ADD COLUMN parent_id INTEGER REFERENCES chart_of_account(id)"
                )
                print("✅ Added parent_id column")
            except sqlite3.OperationalError as e:
                print(f"⚠️ Could not add parent_id: {e}")

        if 'is_main_account' not in columns:
            try:
                cursor.execute(
                    "ALTER TABLE chart_of_account ADD COLUMN is_main_account BOOLEAN DEFAULT 0"
                )
                print("✅ Added is_main_account column")
            except sqlite3.OperationalError as e:
                print(f"⚠️ Could not add is_main_account: {e}")

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Could not add columns: {e}")
        return False


# ============================================================
# ✅ STARTUP: create tables, migrate, seed defaults
# ============================================================

with app.app_context():
    db.create_all()
    print("✅ Database tables created/verified")

    # ✅ Register PDF fonts so ₵, ₦, €, £ render correctly
    register_unicode_fonts()

    # --- Migrations ---
    ensure_system_setting_columns()

    has_parent_id, has_is_main_account = check_columns_exist()
    if not has_parent_id or not has_is_main_account:
        print("⚠️ Missing chart_of_account columns detected. Adding them now...")
        if add_missing_columns():
            print("✅ Columns added successfully!")
        else:
            print("⚠️ Could not add columns automatically.")

    # --- Base currency ---
    if not SystemSetting.query.filter_by(key='base_currency').first():
        db.session.add(SystemSetting(
            key='base_currency',
            value=None,
            value_string=DEFAULT_BASE_CURRENCY,
            description='System base currency for reporting'
        ))
        db.session.commit()
        print(f"✅ Base currency initialized: {DEFAULT_BASE_CURRENCY}")
    else:
        print("✅ Base currency already configured")

    # --- Company profile defaults ---
    company_defaults = {
        'company_name': DEFAULT_COMPANY_NAME,
        'company_address': '',
        'company_phone': '',
        'company_email': '',
        'company_tax_id': '',
        'company_website': '',
        'company_logo': '',
    }
    for key, default_value in company_defaults.items():
        if not SystemSetting.query.filter_by(key=key).first():
            set_company_setting(key, default_value)
    db.session.commit()
    print("✅ Company profile settings initialized")

    # --- Default categories ---
    if Category.query.count() == 0:
        for cat in ['Sales', 'Services', 'Products', 'Consulting']:
            db.session.add(Category(name=cat))
        db.session.commit()
        print("✅ Default categories created")

    # --- Default users ---
    if not User.query.filter_by(email='admin@example.com').first():
        db.session.add(User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123')
        ))
        db.session.commit()
        print("✅ Default admin user created! (admin@example.com / admin123)")
    else:
        print("✅ Default admin user already exists")

    if not User.query.filter_by(email='test@example.com').first():
        db.session.add(User(
            username='testuser',
            email='test@example.com',
            password_hash=generate_password_hash('Test123!')
        ))
        db.session.commit()
        print("✅ Test user created! (test@example.com / Test123!)")

    print("=" * 60)
    print("✅ Database initialized successfully!")
    print(f"📊 Database: {config.SQLALCHEMY_DATABASE_URI}")
    print(f"👤 Users in database: {User.query.count()}")
    print(f"📁 Accounts in database: {ChartOfAccount.query.count()}")
    print("=" * 60)


# ============================================================
# ✅ ROUTES — AUTH
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered. Please use a different email.', 'danger')
            return render_template('register.html', form=form)

        if User.query.filter_by(username=form.username.data).first():
            flash('Username already taken. Please choose a different username.', 'danger')
            return render_template('register.html', form=form)

        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data)
        )
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')

    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ============================================================
# ✅ ROUTES — DASHBOARD
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    invoices = Invoice.query.filter_by(user_id=current_user.id).all()

    total_invoices = 0
    for invoice in invoices:
        invoice_total = db.session.query(db.func.sum(InvoiceLine.total)).filter_by(
            invoice_id=invoice.id
        ).scalar() or 0
        total_invoices += invoice_total

    total_expenses = db.session.query(db.func.sum(Expense.amount)).filter_by(
        user_id=current_user.id
    ).scalar() or 0

    net_income = total_invoices - total_expenses

    recent_invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(
        Invoice.date.desc()
    ).limit(5).all()

    recent_expenses = Expense.query.filter_by(user_id=current_user.id).order_by(
        Expense.date.desc()
    ).limit(5).all()

    current_month = datetime.now().month
    current_year = datetime.now().year

    monthly_invoices = 0
    for invoice in invoices:
        if invoice.date.month == current_month and invoice.date.year == current_year:
            invoice_total = db.session.query(db.func.sum(InvoiceLine.total)).filter_by(
                invoice_id=invoice.id
            ).scalar() or 0
            monthly_invoices += invoice_total

    monthly_expenses = db.session.query(db.func.sum(Expense.amount)).filter(
        Expense.user_id == current_user.id,
        db.extract('month', Expense.date) == current_month,
        db.extract('year', Expense.date) == current_year
    ).scalar() or 0

    return render_template(
        'dashboard.html',
        total_invoices=total_invoices,
        total_expenses=total_expenses,
        net_income=net_income,
        recent_invoices=recent_invoices,
        recent_expenses=recent_expenses,
        monthly_invoices=monthly_invoices,
        monthly_expenses=monthly_expenses,
    )


# ============================================================
# ✅ ROUTES — INVOICES
# ============================================================

@app.route('/invoices')
@login_required
def invoices():
    invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(
        Invoice.date.desc()
    ).all()
    return render_template('invoices.html', invoices=invoices)


@app.route('/add_invoice', methods=['GET', 'POST'])
@login_required
def add_invoice():
    form = InvoiceForm()

    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(0, 'Select Customer')] + [(c.id, c.name) for c in customers]

    revenue_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Revenue')
    ).order_by(ChartOfAccount.account_code).all()

    if not revenue_accounts:
        revenue_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    line_account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in revenue_accounts
    ]

    for line in form.lines:
        line.account_id.choices = line_account_choices

    last_invoice = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.id.desc()).first()
    if last_invoice:
        try:
            last_number = int(last_invoice.invoice_number.split('-')[-1])
            new_number = last_number + 1
        except Exception:
            new_number = 1
    else:
        new_number = 1

    current_year = datetime.now().year
    form.invoice_number.data = f"INV-{current_year}-{new_number:04d}"

    if request.method == 'GET':
        form.lines.append_entry()
        form.lines[-1].account_id.choices = line_account_choices

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        customer_id = request.args.get('customer_id')
        if customer_id and customer_id != '0':
            customer = Customer.query.get(int(customer_id))
            if customer:
                return jsonify({
                    'customer_name': customer.name,
                    'payment_terms': customer.payment_terms
                })
        return jsonify({'customer_name': '', 'payment_terms': ''})

    if form.validate_on_submit():
        try:
            customer = Customer.query.get(form.customer_id.data)

            line_data = []
            index = 0
            while True:
                description_key = f'lines-{index}-description'
                if description_key not in request.form:
                    break

                description = request.form.get(description_key, '')
                quantity = request.form.get(f'lines-{index}-quantity', '1')
                unit_price = request.form.get(f'lines-{index}-unit_price', '0')
                account_id = request.form.get(f'lines-{index}-account_id', '')

                if description and float(unit_price) > 0:
                    line_data.append({
                        'description': description,
                        'quantity': float(quantity),
                        'unit_price': float(unit_price),
                        'account_id': int(account_id) if account_id else None,
                        'total': float(quantity) * float(unit_price)
                    })

                index += 1

            total_amount = sum(line['total'] for line in line_data)

            invoice = Invoice(
                invoice_number=form.invoice_number.data,
                customer_id=form.customer_id.data,
                customer_name=customer.name if customer else '',
                date=form.date.data,
                status=form.status.data,
                description=form.description.data,
                user_id=current_user.id
            )
            db.session.add(invoice)
            db.session.flush()

            for line in line_data:
                db.session.add(InvoiceLine(
                    invoice_id=invoice.id,
                    description=line['description'],
                    quantity=line['quantity'],
                    unit_price=line['unit_price'],
                    total=line['total'],
                    account_id=line['account_id']
                ))

            ar_account = get_ar_account()
            if not ar_account:
                db.session.rollback()
                flash('Please configure AR account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"INV-{timestamp}-{unique_id}"

            db.session.add(JournalEntry(
                entry_number=entry_number,
                date=invoice.date,
                description=f"Invoice {invoice.invoice_number} - {customer.name if customer else 'Customer'}",
                account_id=ar_account.id,
                debit=total_amount,
                credit=0,
                reference_type='Invoice',
                reference_id=invoice.id,
                user_id=current_user.id
            ))

            for line in line_data:
                db.session.add(JournalEntry(
                    entry_number=entry_number,
                    date=invoice.date,
                    description=f"Invoice {invoice.invoice_number} - {line['description']}",
                    account_id=line['account_id'],
                    debit=0,
                    credit=line['total'],
                    reference_type='Invoice',
                    reference_id=invoice.id,
                    user_id=current_user.id
                ))
                post_to_general_ledger(line['account_id'], line['total'], is_debit=False)

            post_to_general_ledger(ar_account.id, total_amount, is_debit=True)

            db.session.commit()
            flash(f'Invoice {invoice.invoice_number} added successfully with {len(line_data)} line(s)!', 'success')
            return redirect(url_for('invoices'))

        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}")
            flash(f'Error adding invoice: {str(e)}', 'danger')
            return render_template('add_invoice.html', form=form, revenue_accounts=revenue_accounts)
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return render_template('add_invoice.html', form=form, revenue_accounts=revenue_accounts)


@app.route('/view_invoice/<int:id>')
@login_required
def view_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices'))
    return render_template('view_invoice.html', invoice=invoice)


@app.route('/edit_invoice/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices'))

    form = InvoiceEditForm(obj=invoice)
    form.original_invoice_number = invoice.invoice_number

    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(0, 'Select Customer')] + [(c.id, c.name) for c in customers]

    revenue_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Revenue')
    ).order_by(ChartOfAccount.account_code).all()

    if not revenue_accounts:
        revenue_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    form.account_id.choices = [(a.id, f"{a.account_code} - {a.account_name}") for a in revenue_accounts]

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        customer_id = request.args.get('customer_id')
        if customer_id and customer_id != '0':
            customer = Customer.query.get(int(customer_id))
            if customer:
                return jsonify({
                    'customer_name': customer.name,
                    'payment_terms': customer.payment_terms
                })
        return jsonify({'customer_name': '', 'payment_terms': ''})

    if form.validate_on_submit():
        customer = Customer.query.get(form.customer_id.data)
        account = ChartOfAccount.query.get(form.account_id.data)

        invoice.invoice_number = form.invoice_number.data
        invoice.customer_id = form.customer_id.data
        invoice.customer_name = customer.name if customer else ''
        invoice.amount = form.amount.data
        invoice.date = form.date.data
        invoice.status = form.status.data
        invoice.description = form.description.data
        invoice.account_id = form.account_id.data

        db.session.commit()
        flash(f'Invoice {invoice.invoice_number} updated successfully!', 'success')
        return redirect(url_for('invoices'))

    return render_template('edit_invoice.html', form=form, invoice=invoice)


# acctsys/app.py

@app.route('/download_invoice/<int:id>')
@login_required
def download_invoice(id):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO

    invoice = Invoice.query.get_or_404(id)
    if invoice.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices'))

    # ========== ENSURE UNICODE FONTS ARE REGISTERED ==========
    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # ========== COMPANY + CURRENCY CONTEXT ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    # ========== CALCULATE INVOICE TOTAL ==========
    invoice_total = sum(line.total for line in invoice.lines) if invoice.lines else 0.0

    # ========== PDF SETUP ==========
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Invoice {invoice.invoice_number}",
        author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    # ========== STYLES (all using AppFont for Unicode support) ==========
    company_name_style = ParagraphStyle(
        'CompanyName', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=4,
        fontName=FONT_BOLD,
    )
    company_sub_style = ParagraphStyle(
        'CompanySub', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1,
        spaceAfter=2, leading=12,
        fontName=FONT,
    )
    title_style = ParagraphStyle(
        'InvoiceTitle', parent=styles['Heading1'], fontSize=22,
        textColor=colors.HexColor('#3498db'), alignment=1,
        spaceBefore=6, spaceAfter=14,
        fontName=FONT_BOLD,
    )
    label_style = ParagraphStyle(
        'Label', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#333333'), spaceAfter=2,
        fontName=FONT_BOLD,
    )
    value_style = ParagraphStyle(
        'Value', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#222222'), spaceAfter=2,
        fontName=FONT,
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Heading2'], fontSize=12,
        textColor=colors.HexColor('#34495e'),
        spaceBefore=12, spaceAfter=8,
        fontName=FONT_BOLD,
    )
    total_label_style = ParagraphStyle(
        'TotalLabel', parent=styles['Normal'], fontSize=12,
        alignment=2, textColor=colors.HexColor('#2c3e50'),
        fontName=FONT_BOLD,
    )
    total_value_style = ParagraphStyle(
        'TotalValue', parent=styles['Normal'], fontSize=14,
        alignment=2, textColor=colors.HexColor('#3498db'),
        fontName=FONT_BOLD,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1,
        fontName=FONT,
    )

    # ========== COMPANY HEADER ==========
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_name_style))

    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), company_sub_style))

    contact_parts = []
    if company['phone']:
        contact_parts.append(f"Tel: {company['phone']}")
    if company['email']:
        contact_parts.append(f"Email: {company['email']}")
    if company['website']:
        contact_parts.append(f"Web: {company['website']}")
    if contact_parts:
        elements.append(Paragraph(" • ".join(contact_parts), company_sub_style))

    if company['tax_id']:
        elements.append(Paragraph(f"Tax ID / VAT: {company['tax_id']}", company_sub_style))

    elements.append(Spacer(1, 12))

    # Divider
    divider = Table([['']], colWidths=[180 * mm], rowHeights=[1])
    divider.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#3498db')),
    ]))
    elements.append(divider)
    elements.append(Spacer(1, 8))

    # ========== INVOICE TITLE ==========
    elements.append(Paragraph(f"INVOICE #{invoice.invoice_number}", title_style))

    # ========== CUSTOMER + INVOICE DETAILS ==========
    customer_block = [
        [Paragraph("<b>BILL TO</b>", label_style)],
        [Paragraph(invoice.customer_name or 'N/A', value_style)],
    ]
    if invoice.customer:
        if invoice.customer.contact_person:
            customer_block.append([Paragraph(f"Attn: {invoice.customer.contact_person}", value_style)])
        if invoice.customer.address:
            customer_block.append([Paragraph(invoice.customer.address.replace('\n', ', '), value_style)])
        if invoice.customer.email:
            customer_block.append([Paragraph(f"Email: {invoice.customer.email}", value_style)])
        if invoice.customer.phone:
            customer_block.append([Paragraph(f"Phone: {invoice.customer.phone}", value_style)])
        if invoice.customer.tax_id:
            customer_block.append([Paragraph(f"Tax ID: {invoice.customer.tax_id}", value_style)])

    invoice_block = [
        [Paragraph("<b>INVOICE DETAILS</b>", label_style)],
        [Paragraph(f"Invoice Date: {invoice.date.strftime('%d %b %Y')}", value_style)],
        [Paragraph(f"Status: {invoice.status}", value_style)],
        [Paragraph(f"Payment Terms: {invoice.customer.payment_terms if invoice.customer else 'N/A'}", value_style)],
        [Paragraph(f"Currency: {base_currency} ({symbol})", value_style)],
    ]
    if invoice.description:
        invoice_block.append([Paragraph(f"Reference: {invoice.description[:80]}", value_style)])

    customer_table = Table(customer_block, colWidths=[85 * mm])
    customer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTNAME', (0, 0), (-1, -1), FONT),
    ]))

    invoice_table = Table(invoice_block, colWidths=[85 * mm])
    invoice_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTNAME', (0, 0), (-1, -1), FONT),
    ]))

    details_row = Table([[customer_table, invoice_table]], colWidths=[90 * mm, 90 * mm])
    details_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(details_row)
    elements.append(Spacer(1, 16))

    # ========== LINE ITEMS ==========
    elements.append(Paragraph("Line Items", section_style))

    line_data = [['#', 'Description', 'Account', 'Qty', 'Unit Price', 'Total']]
    for idx, line in enumerate(invoice.lines, 1):
        account_label = f"{line.account.account_code}" if line.account else '—'
        line_data.append([
            str(idx),
            line.description or '',
            account_label,
            f"{line.quantity:g}",
            f"{symbol}{line.unit_price:,.2f}",
            f"{symbol}{line.total:,.2f}",
        ])

    if len(line_data) == 1:
        line_data.append(['', 'No line items', '', '', '', ''])

    line_table = Table(
        line_data,
        colWidths=[10 * mm, 70 * mm, 22 * mm, 15 * mm, 28 * mm, 35 * mm],
        repeatRows=1,
    )
    line_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        # Body
        ('FONTNAME', (0, 1), (-1, -1), FONT),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (3, 1), (5, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 10))

    # ========== TOTAL ==========
    total_table = Table(
        [[
            Paragraph("Grand Total:", total_label_style),
            Paragraph(f"{symbol}{invoice_total:,.2f} {base_currency}", total_value_style),
        ]],
        colWidths=[110 * mm, 70 * mm],
    )
    total_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f8ff')),
        ('BOX', (0, 0), (-1, 0), 0.5, colors.HexColor('#3498db')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (-1, -1), FONT_BOLD),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 20))

    # ========== NOTES ==========
    if invoice.description:
        elements.append(Paragraph("Notes", section_style))
        elements.append(Paragraph(invoice.description, value_style))
        elements.append(Spacer(1, 12))

    # ========== FOOTER ==========
    footer_parts = []
    if company['email']:
        footer_parts.append(f"For questions, contact {company['email']}")
    if company['phone']:
        footer_parts.append(f"Tel: {company['phone']}")
    if footer_parts:
        elements.append(Paragraph(" • ".join(footer_parts), footer_style))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"This is a computer-generated invoice. All amounts in {base_currency} ({symbol}).",
        footer_style,
    ))

    # ========== BUILD ==========
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'invoice_{invoice.invoice_number}.pdf',
        mimetype='application/pdf',
    )

@app.route('/update_invoices', methods=['POST'])
@login_required
def update_invoices():
    try:
        data = request.get_json()
        invoices_data = data.get('invoices', [])
        if not invoices_data:
            return jsonify({'success': False, 'message': 'No invoice data provided'}), 400

        updated_count = 0
        errors = []

        for inv_data in invoices_data:
            try:
                invoice = Invoice.query.get(int(inv_data['id']))
                if not invoice or invoice.user_id != current_user.id:
                    errors.append(f"Invoice ID {inv_data['id']} not found or access denied")
                    continue

                invoice.amount = float(inv_data.get('amount', invoice.amount))
                invoice.status = inv_data.get('status', invoice.status)
                invoice.date = datetime.strptime(inv_data['date'], '%Y-%m-%d').date() if inv_data.get('date') else invoice.date
                invoice.description = inv_data.get('description', invoice.description)
                updated_count += 1
            except Exception as e:
                errors.append(f"Invoice {inv_data.get('id')}: {str(e)}")

        db.session.commit()
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'errors': errors,
            'message': f'Successfully updated {updated_count} invoice(s).'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_invoices', methods=['POST'])
@login_required
def delete_invoices():
    try:
        data = request.get_json()
        invoice_ids = data.get('invoice_ids', [])
        if not invoice_ids:
            return jsonify({'success': False, 'message': 'No invoices selected'}), 400

        invoices_to_delete = Invoice.query.filter(
            Invoice.id.in_(invoice_ids),
            Invoice.user_id == current_user.id
        ).all()

        if not invoices_to_delete:
            return jsonify({'success': False, 'message': 'No matching invoices found'}), 404

        deleted_ids = []
        reversed_gl_count = 0

        for invoice in invoices_to_delete:
            try:
                journal_entries = JournalEntry.query.filter_by(
                    reference_type='Invoice',
                    reference_id=invoice.id,
                    user_id=current_user.id
                ).all()

                for je in journal_entries:
                    if je.debit > 0:
                        post_to_general_ledger(je.account_id, je.debit, is_debit=False)
                        reversed_gl_count += 1
                    if je.credit > 0:
                        post_to_general_ledger(je.account_id, je.credit, is_debit=True)
                        reversed_gl_count += 1

                for je in journal_entries:
                    db.session.delete(je)

                db.session.delete(invoice)
                deleted_ids.append(invoice.id)
            except Exception as e:
                print(f"Error deleting invoice {invoice.id}: {e}")
                continue

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'reversed_gl_count': reversed_gl_count,
            'message': f'Successfully deleted {len(deleted_ids)} invoice(s).'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ============================================================
# ✅ ROUTES — EXPENSES
# ============================================================

@app.route('/expenses')
@login_required
def expenses():
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    return render_template('expenses.html', expenses=expenses)


@app.route('/add_expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    form = ExpenseForm()
    categories = Category.query.all()
    form.category.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        expense = Expense(
            description=form.description.data,
            amount=form.amount.data,
            date=form.date.data,
            payment_method=form.payment_method.data,
            category_id=form.category.data,
            user_id=current_user.id
        )
        db.session.add(expense)
        db.session.commit()
        flash('Expense added successfully!', 'success')
        return redirect(url_for('expenses'))

    return render_template('add_expense.html', form=form)


# ============================================================
# ✅ ROUTES — CHART OF ACCOUNTS
# ============================================================

@app.route('/chart_of_accounts')
@login_required
def chart_of_accounts():
    main_accounts = ChartOfAccount.query.filter_by(
        is_active=True, parent_id=None
    ).order_by(ChartOfAccount.account_code).all()
    return render_template('chart_of_accounts.html', accounts=main_accounts)


@app.route('/add_account', methods=['GET', 'POST'])
@login_required
def add_account():
    form = ChartOfAccountForm()

    form.account_type_id.choices = [(0, '— Select Account Type —')] + [
        (t.id, t.name) for t in AccountType.query.order_by(AccountType.name).all()
    ]

    all_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
        ChartOfAccount.account_code
    ).all()
    form.parent_id.choices = [(0, 'None - This is a Main Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in all_accounts
    ]

    if form.validate_on_submit():
        if not form.account_type_id.data or form.account_type_id.data == 0:
            flash('Please select an Account Type.', 'danger')
            return render_template('add_account.html', form=form)

        if not form.account_code.data or not form.account_code.data.strip():
            generated_code = generate_next_account_code(form.account_type_id.data)
            if generated_code:
                form.account_code.data = generated_code
            else:
                flash('Could not generate account code. Range may be full or not defined.', 'danger')
                return render_template('add_account.html', form=form)

        account = ChartOfAccount(
            account_code=form.account_code.data.strip(),
            account_name=form.account_name.data,
            account_type_id=form.account_type_id.data,
            description=form.description.data,
            balance=form.opening_balance.data,
            parent_id=form.parent_id.data if form.parent_id.data != 0 else None,
            is_main_account=form.is_main_account.data or form.parent_id.data == 0
        )
        db.session.add(account)
        db.session.commit()

        if form.opening_balance.data != 0:
            account_type = AccountType.query.get(form.account_type_id.data)
            if account_type:
                db.session.add(JournalEntry(
                    entry_number=f"OPEN-{account.account_code}",
                    date=datetime.now().date(),
                    description=f"Opening balance for {account.account_name}",
                    account_id=account.id,
                    debit=form.opening_balance.data if account_type.normal_balance == 'Debit' else 0,
                    credit=form.opening_balance.data if account_type.normal_balance == 'Credit' else 0,
                    reference_type='Opening Balance',
                    user_id=current_user.id
                ))
                db.session.commit()

        flash(f'Account "{account.account_name}" added successfully! Code: {account.account_code}', 'success')
        return redirect(url_for('chart_of_accounts'))

    return render_template('add_account.html', form=form)


@app.route('/edit_account/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_account(id):
    account = ChartOfAccount.query.get_or_404(id)
    form = ChartOfAccountEditForm(obj=account)
    form.original_code = account.account_code

    form.account_type_id.choices = [(t.id, t.name) for t in AccountType.query.all()]

    all_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.id != account.id
    ).order_by(ChartOfAccount.account_code).all()

    form.parent_id.choices = [(0, 'None - This is a Main Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in all_accounts
    ]

    if form.validate_on_submit():
        account.account_code = form.account_code.data
        account.account_name = form.account_name.data
        account.account_type_id = form.account_type_id.data
        account.description = form.description.data
        account.balance = form.balance.data
        account.parent_id = form.parent_id.data if form.parent_id.data != 0 else None
        account.is_main_account = form.is_main_account.data or form.parent_id.data == 0
        account.is_active = form.is_active.data

        db.session.commit()
        flash(f'Account "{account.account_name}" updated successfully!', 'success')
        return redirect(url_for('chart_of_accounts'))

    return render_template('edit_account.html', form=form, account=account)


@app.route('/delete_accounts', methods=['POST'])
@login_required
def delete_accounts():
    try:
        data = request.get_json()
        account_ids = data.get('account_ids', [])
        if not account_ids:
            return jsonify({'success': False, 'message': 'No accounts selected'}), 400

        accounts_to_delete = ChartOfAccount.query.filter(
            ChartOfAccount.id.in_(account_ids)
        ).all()

        if not accounts_to_delete:
            return jsonify({'success': False, 'message': 'No matching accounts found'}), 404

        deleted_ids, skipped_ids, skipped_names, error_messages = [], [], [], []

        for account in accounts_to_delete:
            try:
                journal_count = JournalEntry.query.filter_by(account_id=account.id).count()
                sub_count = ChartOfAccount.query.filter_by(parent_id=account.id).count()

                if journal_count > 0:
                    skipped_ids.append(account.id)
                    skipped_names.append(account.account_name)
                    error_messages.append(f"Account '{account.account_name}' has {journal_count} journal entries")
                    continue

                if sub_count > 0:
                    skipped_ids.append(account.id)
                    skipped_names.append(account.account_name)
                    error_messages.append(f"Account '{account.account_name}' has {sub_count} sub-account(s)")
                    continue

                db.session.delete(account)
                deleted_ids.append(account.id)
            except Exception as e:
                skipped_ids.append(account.id)
                error_messages.append(f"Account '{account.account_name}': {str(e)}")

        db.session.commit()

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'skipped_names': skipped_names,
            'error_messages': error_messages,
            'message': f'Successfully deleted {len(deleted_ids)} account(s)'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    try:
        account = ChartOfAccount.query.get_or_404(account_id)
        journal_count = JournalEntry.query.filter_by(account_id=account.id).count()

        if journal_count > 0:
            return jsonify({
                'success': False,
                'message': f'Account "{account.account_name}" has {journal_count} journal entries and cannot be deleted.'
            }), 400

        db.session.delete(account)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Account "{account.account_name}" deleted successfully.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/get_sub_accounts/<int:parent_id>')
@login_required
def get_sub_accounts(parent_id):
    sub_accounts = ChartOfAccount.query.filter_by(
        parent_id=parent_id, is_active=True
    ).order_by(ChartOfAccount.account_code).all()

    data = [{
        'id': acc.id,
        'account_code': acc.account_code,
        'account_name': acc.account_name,
        'account_type_name': acc.account_type.name if acc.account_type else 'N/A',
        'parent_name': acc.parent.account_name if acc.parent else None,
        'parent_code': acc.parent.account_code if acc.parent else None,
        'balance': acc.balance,
        'is_active': acc.is_active,
        'is_main_account': acc.is_main_account
    } for acc in sub_accounts]

    return jsonify({'sub_accounts': data})


@app.route('/get_next_account_code/<int:account_type_id>')
@login_required
def get_next_account_code(account_type_id):
    next_code = generate_next_account_code(account_type_id)
    if next_code:
        return jsonify({'success': True, 'next_code': next_code})
    return jsonify({'success': False})


# ============================================================
# ✅ ROUTES — ACCOUNT TYPES
# ============================================================

@app.route('/account_types')
@login_required
def account_types():
    account_types = AccountType.query.all()
    return render_template('account_types.html', account_types=account_types)


@app.route('/add_account_type', methods=['GET', 'POST'])
@login_required
def add_account_type():
    form = AccountTypeForm()
    if form.validate_on_submit():
        db.session.add(AccountType(
            name=form.name.data,
            description=form.description.data,
            normal_balance=form.normal_balance.data,
            min_code=form.min_code.data,
            max_code=form.max_code.data
        ))
        db.session.commit()
        flash('Account type added successfully!', 'success')
        return redirect(url_for('account_types'))

    return render_template('add_account_type.html', form=form)


@app.route('/edit_account_type/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_account_type(id):
    account_type = AccountType.query.get_or_404(id)
    form = AccountTypeEditForm(obj=account_type)
    form.original_name = account_type.name

    if form.validate_on_submit():
        account_type.name = form.name.data
        account_type.description = form.description.data
        account_type.normal_balance = form.normal_balance.data
        account_type.min_code = form.min_code.data
        account_type.max_code = form.max_code.data

        db.session.commit()
        flash(f'Account Type "{account_type.name}" updated successfully!', 'success')
        return redirect(url_for('account_types'))

    return render_template('edit_account_type.html', form=form, account_type=account_type)


@app.route('/delete_account_types', methods=['POST'])
@login_required
def delete_account_types():
    try:
        data = request.get_json()
        account_type_ids = data.get('account_type_ids', [])
        if not account_type_ids:
            return jsonify({'success': False, 'message': 'No account types selected'}), 400

        account_types_to_delete = AccountType.query.filter(
            AccountType.id.in_(account_type_ids)
        ).all()

        if not account_types_to_delete:
            return jsonify({'success': False, 'message': 'No matching account types found'}), 404

        deleted_ids, skipped_ids, error_messages = [], [], []

        for account_type in account_types_to_delete:
            try:
                count = ChartOfAccount.query.filter_by(account_type_id=account_type.id).count()
                if count > 0:
                    skipped_ids.append(account_type.id)
                    error_messages.append(f"Account Type '{account_type.name}' is used by {count} account(s)")
                    continue

                db.session.delete(account_type)
                deleted_ids.append(account_type.id)
            except Exception as e:
                skipped_ids.append(account_type.id)
                error_messages.append(f"Account Type '{account_type.name}': {str(e)}")

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'error_messages': error_messages,
            'message': f'Successfully deleted {len(deleted_ids)} account type(s)'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ============================================================
# ✅ ROUTES — SUPPLIERS
# ============================================================

@app.route('/suppliers')
@login_required
def suppliers():
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template('suppliers.html', suppliers=suppliers_list)


@app.route('/add_supplier', methods=['GET', 'POST'])
@login_required
def add_supplier():
    form = SupplierForm()
    if form.validate_on_submit():
        supplier_code = generate_next_supplier_code()
        supplier = Supplier(
            supplier_code=supplier_code,
            name=form.name.data,
            contact_person=form.contact_person.data,
            email=form.email.data,
            phone=form.phone.data,
            address=form.address.data,
            tax_id=form.tax_id.data,
            payment_terms=form.payment_terms.data,
            opening_balance=form.opening_balance.data,
            current_balance=form.opening_balance.data
        )
        db.session.add(supplier)
        db.session.commit()
        flash(f'Supplier "{supplier.name}" added successfully! Code: {supplier_code}', 'success')
        return redirect(url_for('suppliers'))

    return render_template('add_supplier.html', form=form)


@app.route('/view_supplier/<int:id>')
@login_required
def view_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    purchases = Purchase.query.filter_by(supplier_id=id).order_by(Purchase.date.desc()).all()
    return render_template('view_supplier.html', supplier=supplier, purchases=purchases)


@app.route('/edit_supplier/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    form = SupplierEditForm(obj=supplier)

    if form.validate_on_submit():
        supplier.name = form.name.data
        supplier.contact_person = form.contact_person.data
        supplier.email = form.email.data
        supplier.phone = form.phone.data
        supplier.address = form.address.data
        supplier.tax_id = form.tax_id.data
        supplier.payment_terms = form.payment_terms.data
        supplier.opening_balance = form.opening_balance.data
        supplier.current_balance = form.current_balance.data
        supplier.is_active = form.is_active.data

        db.session.commit()
        flash(f'Supplier "{supplier.name}" updated successfully!', 'success')
        return redirect(url_for('suppliers'))

    return render_template('edit_supplier.html', form=form, supplier=supplier)


@app.route('/delete_suppliers', methods=['POST'])
@login_required
def delete_suppliers():
    try:
        data = request.get_json()
        supplier_ids = data.get('supplier_ids', [])
        if not supplier_ids:
            return jsonify({'success': False, 'message': 'No suppliers selected'}), 400

        suppliers_to_delete = Supplier.query.filter(Supplier.id.in_(supplier_ids)).all()
        if not suppliers_to_delete:
            return jsonify({'success': False, 'message': 'No matching suppliers found'}), 404

        deleted_ids, skipped_ids, error_messages = [], [], []

        for supplier in suppliers_to_delete:
            try:
                pc = Purchase.query.filter_by(supplier_id=supplier.id).count()
                vc = PaymentVoucher.query.filter_by(supplier_id=supplier.id).count()

                if pc > 0:
                    skipped_ids.append(supplier.id)
                    error_messages.append(f"Supplier '{supplier.name}' has {pc} purchase(s)")
                    continue
                if vc > 0:
                    skipped_ids.append(supplier.id)
                    error_messages.append(f"Supplier '{supplier.name}' has {vc} payment voucher(s)")
                    continue

                db.session.delete(supplier)
                deleted_ids.append(supplier.id)
            except Exception as e:
                skipped_ids.append(supplier.id)
                error_messages.append(f"Supplier '{supplier.name}': {str(e)}")

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'error_messages': error_messages,
            'message': f'Successfully deleted {len(deleted_ids)} supplier(s)'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_supplier/<int:supplier_id>', methods=['POST'])
@login_required
def delete_supplier(supplier_id):
    try:
        supplier = Supplier.query.get_or_404(supplier_id)
        pc = Purchase.query.filter_by(supplier_id=supplier.id).count()
        vc = PaymentVoucher.query.filter_by(supplier_id=supplier.id).count()

        if pc > 0:
            return jsonify({'success': False, 'message': f'Supplier has {pc} purchase(s).'}), 400
        if vc > 0:
            return jsonify({'success': False, 'message': f'Supplier has {vc} voucher(s).'}), 400

        db.session.delete(supplier)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Supplier "{supplier.name}" deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# ✅ ROUTES — CUSTOMERS
# ============================================================

@app.route('/customers')
@login_required
def customers():
    customers_list = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return render_template('customers.html', customers=customers_list)


@app.route('/add_customer', methods=['GET', 'POST'])
@login_required
def add_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer_code = generate_next_customer_code()
        customer = Customer(
            customer_code=customer_code,
            name=form.name.data,
            contact_person=form.contact_person.data,
            email=form.email.data,
            phone=form.phone.data,
            address=form.address.data,
            tax_id=form.tax_id.data,
            credit_limit=form.credit_limit.data,
            opening_balance=form.opening_balance.data,
            current_balance=form.opening_balance.data,
            payment_terms=form.payment_terms.data
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Customer "{customer.name}" added successfully! Code: {customer_code}', 'success')
        return redirect(url_for('customers'))

    return render_template('add_customer.html', form=form)


@app.route('/view_customer/<int:id>')
@login_required
def view_customer(id):
    customer = Customer.query.get_or_404(id)
    invoices = Invoice.query.filter_by(customer_name=customer.name).order_by(Invoice.date.desc()).all()
    return render_template('view_customer.html', customer=customer, invoices=invoices)


@app.route('/edit_customer/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    form = CustomerEditForm(obj=customer)

    if form.validate_on_submit():
        customer.name = form.name.data
        customer.contact_person = form.contact_person.data
        customer.email = form.email.data
        customer.phone = form.phone.data
        customer.address = form.address.data
        customer.tax_id = form.tax_id.data
        customer.credit_limit = form.credit_limit.data
        customer.opening_balance = form.opening_balance.data
        customer.current_balance = form.current_balance.data
        customer.payment_terms = form.payment_terms.data
        customer.is_active = form.is_active.data

        db.session.commit()
        flash(f'Customer "{customer.name}" updated successfully!', 'success')
        return redirect(url_for('customers'))

    return render_template('edit_customer.html', form=form, customer=customer)


@app.route('/delete_customers', methods=['POST'])
@login_required
def delete_customers():
    try:
        data = request.get_json()
        customer_ids = data.get('customer_ids', [])
        if not customer_ids:
            return jsonify({'success': False, 'message': 'No customers selected'}), 400

        customers_to_delete = Customer.query.filter(Customer.id.in_(customer_ids)).all()
        if not customers_to_delete:
            return jsonify({'success': False, 'message': 'No matching customers found'}), 404

        deleted_ids, skipped_ids, error_messages = [], [], []

        for customer in customers_to_delete:
            try:
                ic = Invoice.query.filter_by(customer_name=customer.name).count()
                if ic > 0:
                    skipped_ids.append(customer.id)
                    error_messages.append(f"Customer '{customer.name}' has {ic} invoice(s)")
                    continue

                db.session.delete(customer)
                deleted_ids.append(customer.id)
            except Exception as e:
                skipped_ids.append(customer.id)
                error_messages.append(f"Customer '{customer.name}': {str(e)}")

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'error_messages': error_messages,
            'message': f'Successfully deleted {len(deleted_ids)} customer(s)'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_customer/<int:customer_id>', methods=['POST'])
@login_required
def delete_customer(customer_id):
    try:
        customer = Customer.query.get_or_404(customer_id)
        ic = Invoice.query.filter_by(customer_name=customer.name).count()
        if ic > 0:
            return jsonify({'success': False, 'message': f'Customer has {ic} invoice(s).'}), 400

        db.session.delete(customer)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Customer "{customer.name}" deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# ✅ ROUTES — PURCHASES
# ============================================================

@app.route('/purchases')
@login_required
def purchases():
    purchases_list = Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc()).all()
    return render_template('purchases.html', purchases=purchases_list)


@app.route('/add_purchase', methods=['GET', 'POST'])
@login_required
def add_purchase():
    form = PurchaseForm()

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    form.supplier_id.choices = [(0, 'Select Supplier')] + [(s.id, s.name) for s in suppliers]

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(AccountType.name.in_(['Asset', 'Expense']))
    ).order_by(ChartOfAccount.account_code).all()

    if not accounts:
        accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in accounts
    ]

    for line in form.lines:
        line.account_id.choices = account_choices

    form.purchase_number.data = generate_next_purchase_number()

    if request.method == 'GET':
        form.lines.append_entry()
        form.lines[-1].account_id.choices = account_choices

    if form.validate_on_submit():
        try:
            supplier = Supplier.query.get(form.supplier_id.data)

            line_data = []
            index = 0
            while True:
                description_key = f'lines-{index}-description'
                if description_key not in request.form:
                    break

                description = request.form.get(description_key, '')
                quantity = request.form.get(f'lines-{index}-quantity', '1')
                unit_price = request.form.get(f'lines-{index}-unit_price', '0')
                account_id = request.form.get(f'lines-{index}-account_id', '')

                if description and float(unit_price) > 0:
                    line_data.append({
                        'description': description,
                        'quantity': float(quantity),
                        'unit_price': float(unit_price),
                        'account_id': int(account_id) if account_id else None,
                        'total': float(quantity) * float(unit_price)
                    })

                index += 1

            total_amount = sum(line['total'] for line in line_data)

            purchase = Purchase(
                purchase_number=form.purchase_number.data,
                supplier_id=form.supplier_id.data,
                invoice_number=form.invoice_number.data,
                amount=total_amount,
                date=form.date.data,
                due_date=form.due_date.data,
                status=form.status.data,
                user_id=current_user.id
            )
            db.session.add(purchase)
            db.session.flush()

            for line in line_data:
                db.session.add(PurchaseLine(
                    purchase_id=purchase.id,
                    description=line['description'],
                    quantity=line['quantity'],
                    unit_price=line['unit_price'],
                    total=line['total'],
                    account_id=line['account_id']
                ))

            if supplier:
                supplier.current_balance += total_amount

            ap_account = get_ap_account()
            if not ap_account:
                db.session.rollback()
                flash('Please configure AP account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"PUR-{timestamp}-{unique_id}"

            db.session.add(JournalEntry(
                entry_number=entry_number,
                date=purchase.date,
                description=f"Purchase {purchase.purchase_number} - {supplier.name if supplier else ''}",
                account_id=ap_account.id,
                debit=0,
                credit=total_amount,
                reference_type='Purchase',
                reference_id=purchase.id,
                user_id=current_user.id
            ))

            for line in line_data:
                db.session.add(JournalEntry(
                    entry_number=entry_number,
                    date=purchase.date,
                    description=f"Purchase {purchase.purchase_number} - {line['description']}",
                    account_id=line['account_id'],
                    debit=line['total'],
                    credit=0,
                    reference_type='Purchase',
                    reference_id=purchase.id,
                    user_id=current_user.id
                ))
                post_to_general_ledger(line['account_id'], line['total'], is_debit=True)

            post_to_general_ledger(ap_account.id, total_amount, is_debit=False)

            db.session.commit()
            flash(f'Purchase {purchase.purchase_number} added successfully!', 'success')
            return redirect(url_for('purchases'))

        except Exception as e:
            db.session.rollback()
            print(f"Error adding purchase: {e}")
            flash(f'Error adding purchase: {str(e)}', 'danger')

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return render_template('add_purchase.html', form=form, accounts=accounts)


@app.route('/edit_purchase/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    if purchase.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('purchases'))

    form = PurchaseEditForm(obj=purchase)
    form.original_purchase_number = purchase.purchase_number

    form.supplier_id.choices = [(0, 'Select Supplier')] + [
        (s.id, s.name) for s in Supplier.query.filter_by(is_active=True).all()
    ]

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(AccountType.name.in_(['Asset', 'Expense']))
    ).order_by(ChartOfAccount.account_code).all()

    if not accounts:
        accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in accounts
    ]

    for line in form.lines:
        line.account_id.choices = account_choices

    if form.validate_on_submit():
        purchase.purchase_number = form.purchase_number.data
        purchase.supplier_id = form.supplier_id.data
        purchase.invoice_number = form.invoice_number.data
        purchase.date = form.date.data
        purchase.due_date = form.due_date.data
        purchase.status = form.status.data

        line_data = []
        index = 0
        while True:
            description_key = f'lines-{index}-description'
            if description_key not in request.form:
                break

            description = request.form.get(description_key, '')
            quantity = request.form.get(f'lines-{index}-quantity', '1')
            unit_price = request.form.get(f'lines-{index}-unit_price', '0')
            account_id = request.form.get(f'lines-{index}-account_id', '')

            if description and float(unit_price) > 0:
                line_data.append({
                    'description': description,
                    'quantity': float(quantity),
                    'unit_price': float(unit_price),
                    'account_id': int(account_id) if account_id else None,
                    'total': float(quantity) * float(unit_price)
                })

            index += 1

        purchase.amount = sum(line['total'] for line in line_data)

        PurchaseLine.query.filter_by(purchase_id=purchase.id).delete()

        for line in line_data:
            db.session.add(PurchaseLine(
                purchase_id=purchase.id,
                description=line['description'],
                quantity=line['quantity'],
                unit_price=line['unit_price'],
                total=line['total'],
                account_id=line['account_id']
            ))

        db.session.commit()
        flash(f'Purchase {purchase.purchase_number} updated successfully!', 'success')
        return redirect(url_for('purchases'))

    return render_template('edit_purchase.html', form=form, purchase=purchase, accounts=accounts)


@app.route('/delete_purchases', methods=['POST'])
@login_required
def delete_purchases():
    try:
        data = request.get_json()
        purchase_ids = data.get('purchase_ids', [])
        if not purchase_ids:
            return jsonify({'success': False, 'message': 'No purchases selected'}), 400

        purchases_to_delete = Purchase.query.filter(
            Purchase.id.in_(purchase_ids),
            Purchase.user_id == current_user.id
        ).all()

        if not purchases_to_delete:
            return jsonify({'success': False, 'message': 'No matching purchases found'}), 404

        deleted_ids, reversed_gl_count = [], 0

        for purchase in purchases_to_delete:
            try:
                journal_entries = JournalEntry.query.filter_by(
                    reference_type='Purchase',
                    reference_id=purchase.id,
                    user_id=current_user.id
                ).all()

                for je in journal_entries:
                    if je.debit > 0:
                        post_to_general_ledger(je.account_id, je.debit, is_debit=False)
                        reversed_gl_count += 1
                    if je.credit > 0:
                        post_to_general_ledger(je.account_id, je.credit, is_debit=True)
                        reversed_gl_count += 1

                for je in journal_entries:
                    db.session.delete(je)

                supplier = Supplier.query.get(purchase.supplier_id)
                if supplier:
                    supplier.current_balance -= purchase.amount

                db.session.delete(purchase)
                deleted_ids.append(purchase.id)
            except Exception as e:
                print(f"Error deleting purchase {purchase.id}: {e}")
                continue

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'reversed_gl_count': reversed_gl_count,
            'message': f'Successfully deleted {len(deleted_ids)} purchase(s).'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ============================================================
# ✅ ROUTES — TRIAL BALANCE & JOURNAL
# ============================================================

# acctsys/app.py – Trial Balance with date range support

@app.route('/trial_balance')
@login_required
def trial_balance():
    from datetime import date

    # ========== PARSE QUERY PARAMETERS ==========
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    mode = request.args.get('mode', 'as_of')  # 'as_of' or 'period'

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # ========== QUERY JOURNAL ENTRIES BASED ON MODE ==========
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)

    if mode == 'period':
        # Period mode: entries WITHIN the range
        if start_date:
            query = query.filter(JournalEntry.date >= start_date)
        if end_date:
            query = query.filter(JournalEntry.date <= end_date)
    else:
        # As-of mode: entries UP TO end_date (cumulative)
        # If only start_date given, treat it as the cut-off too
        cut_off = end_date or start_date
        if cut_off:
            query = query.filter(JournalEntry.date <= cut_off)

    entries = query.all()

    # ========== AGGREGATE DEBITS / CREDITS BY ACCOUNT ==========
    account_totals = {}   # account_id -> {'debit': x, 'credit': y}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    # ========== FETCH ACCOUNTS ==========
    account_ids = list(account_totals.keys())
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(account_ids),
        ChartOfAccount.is_active == True,
    ).order_by(ChartOfAccount.account_code).all() if account_ids else []

    # ========== BUILD TRIAL BALANCE ROWS ==========
    trial_balance_data = []
    total_debits = 0.0
    total_credits = 0.0

    for account in accounts:
        totals = account_totals.get(account.id)
        if not totals:
            continue

        account_type = AccountType.query.get(account.account_type_id)
        if not account_type:
            continue

        debit = totals['debit']
        credit = totals['credit']

        # Compute the net signed balance based on normal balance
        if account_type.normal_balance == 'Debit':
            balance = debit - credit
        else:
            balance = credit - debit

        # Split the balance into its debit-side or credit-side column
        if account_type.normal_balance == 'Debit':
            if balance > 0:
                debit_amount = balance
                credit_amount = 0.0
            elif balance < 0:
                debit_amount = 0.0
                credit_amount = abs(balance)
            else:
                debit_amount = 0.0
                credit_amount = 0.0
        else:
            if balance > 0:
                debit_amount = 0.0
                credit_amount = balance
            elif balance < 0:
                debit_amount = abs(balance)
                credit_amount = 0.0
            else:
                debit_amount = 0.0
                credit_amount = 0.0

        total_debits += debit_amount
        total_credits += credit_amount

        trial_balance_data.append({
            'account_code': account.account_code,
            'account_name': account.account_name,
            'account_type': account_type.name,
            'debit': debit_amount,
            'credit': credit_amount,
            'raw_debit': debit,      # for debugging / detail view
            'raw_credit': credit,
        })

    # ========== DETERMINE PERIOD LABEL ==========
    if mode == 'period':
        if start_date and end_date:
            period_label = (
                f"For the period "
                f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
            )
        elif start_date:
            period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
        elif end_date:
            period_label = f"Up to {end_date.strftime('%d %b %Y')}"
        else:
            period_label = "All periods"
    else:  # as_of
        cut_off = end_date or start_date
        if cut_off:
            period_label = f"As of {cut_off.strftime('%d %b %Y')}"
        else:
            period_label = f"As of {date.today().strftime('%d %b %Y')}"

    return render_template(
        'trial_balance.html',
        trial_balance=trial_balance_data,
        total_debits=total_debits,
        total_credits=total_credits,
        start_date=start_date,
        end_date=end_date,
        mode=mode,
        period_label=period_label,
        datetime=datetime,
    )

# acctsys/app.py – Trial Balance Excel export

@app.route('/trial_balance/excel')
@login_required
def trial_balance_excel():
    from datetime import date

    # ========== PARSE PARAMETERS ==========
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    mode = request.args.get('mode', 'as_of')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # ========== QUERY ENTRIES ==========
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if mode == 'period':
        if start_date:
            query = query.filter(JournalEntry.date >= start_date)
        if end_date:
            query = query.filter(JournalEntry.date <= end_date)
    else:
        cut_off = end_date or start_date
        if cut_off:
            query = query.filter(JournalEntry.date <= cut_off)

    entries = query.all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    account_ids = list(account_totals.keys())
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(account_ids),
        ChartOfAccount.is_active == True,
    ).order_by(ChartOfAccount.account_code).all() if account_ids else []

    rows = []
    total_debits = total_credits = 0.0
    for account in accounts:
        totals = account_totals.get(account.id)
        if not totals:
            continue
        at = AccountType.query.get(account.account_type_id)
        if not at:
            continue
        debit = totals['debit']
        credit = totals['credit']
        balance = (debit - credit) if at.normal_balance == 'Debit' else (credit - debit)
        if at.normal_balance == 'Debit':
            d_amt = balance if balance > 0 else 0.0
            c_amt = abs(balance) if balance < 0 else 0.0
        else:
            d_amt = abs(balance) if balance < 0 else 0.0
            c_amt = balance if balance > 0 else 0.0
        total_debits += d_amt
        total_credits += c_amt
        rows.append({
            'code': account.account_code,
            'name': account.account_name,
            'type': at.name,
            'debit': d_amt,
            'credit': c_amt,
        })

    # ========== PERIOD LABEL ==========
    if mode == 'period':
        if start_date and end_date:
            period_label = (f"For the period {start_date.strftime('%d %b %Y')} – "
                            f"{end_date.strftime('%d %b %Y')}")
        elif start_date:
            period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
        elif end_date:
            period_label = f"Up to {end_date.strftime('%d %b %Y')}"
        else:
            period_label = "All periods"
    else:
        cut_off = end_date or start_date
        period_label = f"As of {cut_off.strftime('%d %b %Y')}" if cut_off \
                       else f"As of {date.today().strftime('%d %b %Y')}"

    # ========== BUILD WORKBOOK ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trial Balance"

    row = _write_company_header(ws, company, base_currency, symbol)
    row = _write_sheet_title(ws, row, "TRIAL BALANCE",
                             f"{period_label}  •  All amounts in {base_currency} ({symbol})")

    # Header row
    headers = ['Code', 'Account Name', 'Type',
               f'Debit ({base_currency})', f'Credit ({base_currency})']
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = EXCEL_HEADER_FONT
        cell.fill = EXCEL_HEADER_FILL
        cell.alignment = EXCEL_ALIGN_CENTER
    header_row = row
    row += 1

    first_data_row = row
    for r in rows:
        ws.cell(row=row, column=1, value=r['code']).font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
        ws.cell(row=row, column=2, value=r['name']).font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=3, value=r['type']).font = EXCEL_NORMAL_FONT
        c4 = ws.cell(row=row, column=4, value=r['debit'] if r['debit'] > 0 else None)
        c4.number_format = f'"{symbol}"#,##0.00'
        c4.font = EXCEL_NORMAL_FONT
        c4.alignment = EXCEL_ALIGN_RIGHT
        c5 = ws.cell(row=row, column=5, value=r['credit'] if r['credit'] > 0 else None)
        c5.number_format = f'"{symbol}"#,##0.00'
        c5.font = EXCEL_NORMAL_FONT
        c5.alignment = EXCEL_ALIGN_RIGHT
        row += 1

    if not rows:
        ws.cell(row=row, column=1, value="No activity in this period").font = EXCEL_NORMAL_FONT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
        row += 1

    last_data_row = row - 1

    # Total row
    ws.cell(row=row, column=1, value="").fill = EXCEL_TOTAL_FILL
    ws.cell(row=row, column=2, value="TOTAL").font = EXCEL_TOTAL_FONT
    ws.cell(row=row, column=2).alignment = EXCEL_ALIGN_RIGHT
    ws.cell(row=row, column=2).fill = EXCEL_TOTAL_FILL

    c4 = ws.cell(row=row, column=4, value=f"=SUM(D{first_data_row}:D{last_data_row})")
    c4.number_format = f'"{symbol}"#,##0.00'
    c4.font = EXCEL_TOTAL_FONT
    c4.alignment = EXCEL_ALIGN_RIGHT
    c4.fill = EXCEL_TOTAL_FILL

    c5 = ws.cell(row=row, column=5, value=f"=SUM(E{first_data_row}:E{last_data_row})")
    c5.number_format = f'"{symbol}"#,##0.00'
    c5.font = EXCEL_TOTAL_FONT
    c5.alignment = EXCEL_ALIGN_RIGHT
    c5.fill = EXCEL_TOTAL_FILL
    total_row = row
    row += 1

    # Balance check
    diff = total_debits - total_credits
    if abs(diff) < 0.01:
        msg = "✓ Trial balance is in balance (Debits = Credits)"
        fill = EXCEL_TOTAL_FILL_GRN
    else:
        msg = f"⚠ Out of balance by {symbol}{abs(diff):,.2f}"
        fill = EXCEL_TOTAL_FILL_RED

    c = ws.cell(row=row, column=1, value=msg)
    c.font = EXCEL_TOTAL_FONT
    c.alignment = EXCEL_ALIGN_CENTER
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    for col in range(1, 6):
        ws.cell(row=row, column=col).fill = fill

    # Apply borders to the table body
    _apply_border(ws, header_row, total_row, 1, 5)

    # Footer
    row += 2
    ws.cell(row=row, column=1,
            value=f"This is a computer-generated Trial Balance. All amounts in {base_currency}."
            ).font = Font(name='Calibri', size=8, italic=True, color='888888')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)

    _autosize_columns(ws)

    # ========== SEND ==========
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    suffix = ""
    if start_date: suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date:   suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buf,
        as_attachment=True,
        download_name=f'trial_balance{suffix}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

# acctsys/app.py – General Ledger Report

@app.route('/general_ledger')
@login_required
def general_ledger():
    """
    General Ledger detail report.
    Shows all journal entries for accounts within a date range,
    grouped by account with running balance.
    """
    from datetime import date

    # ========== PARSE PARAMETERS ==========
    account_id = request.args.get('account_id', type=int)
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # ========== FETCH ALL ACCOUNTS (for the filter dropdown) ==========
    all_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
        ChartOfAccount.account_code
    ).all()

    # ========== BUILD QUERY ==========
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)

    if account_id:
        query = query.filter(JournalEntry.account_id == account_id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)

    entries = query.order_by(
        JournalEntry.account_id,
        JournalEntry.date,
        JournalEntry.id,
    ).all()

    # ========== GROUP BY ACCOUNT ==========
    grouped = {}  # account_id -> {'account': obj, 'entries': [...], 'opening': x, 'total_debit': x, 'total_credit': x, 'closing': x}

    # Step 1: compute opening balance per account (before start_date)
    opening_balances = {}
    if start_date and account_id:
        opening_entries = JournalEntry.query.filter(
            JournalEntry.user_id == current_user.id,
            JournalEntry.account_id == account_id,
            JournalEntry.date < start_date,
        ).all()
        for e in opening_entries:
            opening_balances.setdefault(e.account_id, 0.0)
            # Signed balance based on normal balance
            acct = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(acct.account_type_id) if acct else None
            if at and at.normal_balance == 'Debit':
                opening_balances[e.account_id] += (e.debit or 0) - (e.credit or 0)
            else:
                opening_balances[e.account_id] += (e.credit or 0) - (e.debit or 0)

    # Step 2: build the grouped structure
    for e in entries:
        if e.account_id not in grouped:
            account = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(account.account_type_id) if account else None
            grouped[e.account_id] = {
                'account': account,
                'account_type': at,
                'entries': [],
                'opening': opening_balances.get(e.account_id, 0.0),
                'total_debit': 0.0,
                'total_credit': 0.0,
                'running_balance': opening_balances.get(e.account_id, 0.0),
            }
        grouped[e.account_id]['entries'].append(e)
        grouped[e.account_id]['total_debit'] += e.debit or 0.0
        grouped[e.account_id]['total_credit'] += e.credit or 0.0

    # Step 3: compute running balance per entry
    for account_id_, data in grouped.items():
        at = data['account_type']
        running = data['opening']
        is_debit_normal = at and at.normal_balance == 'Debit'

        for entry in data['entries']:
            debit = entry.debit or 0.0
            credit = entry.credit or 0.0
            if is_debit_normal:
                running += debit - credit
            else:
                running += credit - debit
            entry._running_balance = running  # attach dynamically

        # Closing balance
        data['closing'] = running

    # Sort groups by account code
    grouped_sorted = dict(sorted(
        grouped.items(),
        key=lambda kv: kv[1]['account'].account_code if kv[1]['account'] else '',
    ))

    # ========== GRAND TOTALS ==========
    grand_total_debit = sum(d['total_debit'] for d in grouped.values())
    grand_total_credit = sum(d['total_credit'] for d in grouped.values())

    # ========== PERIOD LABEL ==========
    if start_date and end_date:
        period_label = (
            f"From {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
        )
    elif start_date:
        period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
    elif end_date:
        period_label = f"Up to {end_date.strftime('%d %b %Y')}"
    else:
        period_label = "All activity"

    # ========== SINGLE-ACCOUNT MODE LABEL ==========
    selected_account = None
    if account_id:
        selected_account = ChartOfAccount.query.get(account_id)

    return render_template(
        'general_ledger.html',
        grouped=grouped_sorted,
        all_accounts=all_accounts,
        account_id=account_id,
        selected_account=selected_account,
        start_date=start_date,
        end_date=end_date,
        period_label=period_label,
        grand_total_debit=grand_total_debit,
        grand_total_credit=grand_total_credit,
    )

# acctsys/app.py – General Ledger PDF

@app.route('/general_ledger/pdf')
@login_required
def general_ledger_pdf():
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO

    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # --- same query logic as HTML view ---
    account_id = request.args.get('account_id', type=int)
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if account_id:
        query = query.filter(JournalEntry.account_id == account_id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)
    entries = query.order_by(
        JournalEntry.account_id, JournalEntry.date, JournalEntry.id
    ).all()

    grouped = {}
    opening_balances = {}
    if start_date and account_id:
        for e in JournalEntry.query.filter(
            JournalEntry.user_id == current_user.id,
            JournalEntry.account_id == account_id,
            JournalEntry.date < start_date,
        ).all():
            acct = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(acct.account_type_id) if acct else None
            opening_balances.setdefault(e.account_id, 0.0)
            if at and at.normal_balance == 'Debit':
                opening_balances[e.account_id] += (e.debit or 0) - (e.credit or 0)
            else:
                opening_balances[e.account_id] += (e.credit or 0) - (e.debit or 0)

    for e in entries:
        if e.account_id not in grouped:
            account = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(account.account_type_id) if account else None
            grouped[e.account_id] = {
                'account': account,
                'account_type': at,
                'entries': [],
                'opening': opening_balances.get(e.account_id, 0.0),
                'total_debit': 0.0,
                'total_credit': 0.0,
            }
        grouped[e.account_id]['entries'].append(e)
        grouped[e.account_id]['total_debit'] += e.debit or 0.0
        grouped[e.account_id]['total_credit'] += e.credit or 0.0

    for account_id_, data in grouped.items():
        at = data['account_type']
        running = data['opening']
        is_debit_normal = at and at.normal_balance == 'Debit'
        for entry in data['entries']:
            d, c = entry.debit or 0.0, entry.credit or 0.0
            running += (d - c) if is_debit_normal else (c - d)
            entry._running_balance = running
        data['closing'] = running

    grouped_sorted = dict(sorted(
        grouped.items(),
        key=lambda kv: kv[1]['account'].account_code if kv[1]['account'] else '',
    ))

    # --- labels ---
    if start_date and end_date:
        period_label = f"From {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
    elif start_date:
        period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
    elif end_date:
        period_label = f"Up to {end_date.strftime('%d %b %Y')}"
    else:
        period_label = "All activity"

    selected_account = ChartOfAccount.query.get(account_id) if account_id else None
    if selected_account:
        period_label = f"Account: {selected_account.account_code} - {selected_account.account_name}  •  {period_label}"

    # --- company + currency ---
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=12 * mm, bottomMargin=12 * mm,
        leftMargin=12 * mm, rightMargin=12 * mm,
        title="General Ledger", author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    company_style = ParagraphStyle(
        'CN', parent=styles['Heading1'], fontSize=16,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=3,
        fontName=FONT_BOLD,
    )
    sub_style = ParagraphStyle(
        'CS', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1,
        spaceAfter=2, leading=11, fontName=FONT,
    )
    title_style = ParagraphStyle(
        'T', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#34495e'), alignment=1,
        spaceBefore=4, spaceAfter=4, fontName=FONT_BOLD,
    )
    period_style = ParagraphStyle(
        'P', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#7f8c8d'), alignment=1,
        spaceAfter=12, fontName=FONT,
    )
    acct_header_style = ParagraphStyle(
        'AH', parent=styles['Heading2'], fontSize=11,
        textColor=colors.white, backColor=colors.HexColor('#34495e'),
        alignment=0, spaceBefore=8, spaceAfter=4, leftIndent=6,
        fontName=FONT_BOLD,
    )
    footer_style = ParagraphStyle(
        'F', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1, fontName=FONT,
    )

    # Header
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_style))
    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), sub_style))
    contact = []
    if company['phone']: contact.append(f"Tel: {company['phone']}")
    if company['email']: contact.append(f"Email: {company['email']}")
    if contact:
        elements.append(Paragraph(" • ".join(contact), sub_style))

    elements.append(Spacer(1, 6))
    elements.append(Paragraph("GENERAL LEDGER", title_style))
    elements.append(Paragraph(
        f"{period_label}  •  All amounts in {base_currency} ({symbol})",
        period_style,
    ))

    # Loop through each account group
    for account_id_, data in grouped_sorted.items():
        account = data['account']
        if not account:
            continue

        # Account header
        header_text = (
            f"{account.account_code} - {account.account_name}  "
            f"({data['account_type'].name if data['account_type'] else 'N/A'})"
        )
        elements.append(Paragraph(f"<b>{header_text}</b>", acct_header_style))

        # Table data
        table_data = [['Date', 'Entry #', 'Description',
                       f'Debit ({base_currency})', f'Credit ({base_currency})',
                       f'Balance ({base_currency})']]

        # Opening balance row
        if data['opening'] != 0 or start_date:
            table_data.append([
                '', '', Paragraph("<i>Opening Balance</i>", styles['Normal']),
                '', '', f"{symbol}{data['opening']:,.2f}",
            ])

        for entry in data['entries']:
            desc = entry.description or ''
            if len(desc) > 60:
                desc = desc[:57] + '...'
            table_data.append([
                entry.date.strftime('%d %b %Y'),
                entry.entry_number[:20] if entry.entry_number else '',
                desc,
                f"{symbol}{entry.debit:,.2f}" if entry.debit else '-',
                f"{symbol}{entry.credit:,.2f}" if entry.credit else '-',
                f"{symbol}{entry._running_balance:,.2f}",
            ])

        # Totals row
        table_data.append([
            '', '',
            Paragraph("<b>TOTAL</b>", styles['Normal']),
            Paragraph(f"<b>{symbol}{data['total_debit']:,.2f}</b>", styles['Normal']),
            Paragraph(f"<b>{symbol}{data['total_credit']:,.2f}</b>", styles['Normal']),
            Paragraph(f"<b>{symbol}{data['closing']:,.2f}</b>", styles['Normal']),
        ])

        t = Table(
            table_data,
            colWidths=[26 * mm, 32 * mm, 90 * mm, 32 * mm, 32 * mm, 32 * mm],
            repeatRows=1,
        )
        t.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

            # Body
            ('FONTNAME', (0, 1), (-1, -2), FONT),
            ('FONTSIZE', (0, 1), (-1, -2), 8),
            ('ALIGN', (0, 1), (1, -2), 'CENTER'),
            ('ALIGN', (3, 1), (5, -2), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

            # Totals row
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#d6eaf8')),
            ('FONTNAME', (0, -1), (-1, -1), FONT_BOLD),
            ('ALIGN', (3, -1), (5, -1), 'RIGHT'),

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 8))

    if not grouped_sorted:
        elements.append(Paragraph("No transactions found for this period.", styles['Normal']))

    # Footer
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        f"This is a computer-generated General Ledger report. All amounts in {base_currency}.",
        footer_style,
    ))

    doc.build(elements)
    buffer.seek(0)

    suffix = ""
    if start_date: suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date: suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'general_ledger{suffix}.pdf',
        mimetype='application/pdf',
    )

# acctsys/app.py – General Ledger Excel

@app.route('/general_ledger/excel')
@login_required
def general_ledger_excel():
    from datetime import date

    account_id = request.args.get('account_id', type=int)
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if account_id:
        query = query.filter(JournalEntry.account_id == account_id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)
    entries = query.order_by(
        JournalEntry.account_id, JournalEntry.date, JournalEntry.id
    ).all()

    grouped = {}
    opening_balances = {}
    if start_date and account_id:
        for e in JournalEntry.query.filter(
            JournalEntry.user_id == current_user.id,
            JournalEntry.account_id == account_id,
            JournalEntry.date < start_date,
        ).all():
            acct = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(acct.account_type_id) if acct else None
            opening_balances.setdefault(e.account_id, 0.0)
            if at and at.normal_balance == 'Debit':
                opening_balances[e.account_id] += (e.debit or 0) - (e.credit or 0)
            else:
                opening_balances[e.account_id] += (e.credit or 0) - (e.debit or 0)

    for e in entries:
        if e.account_id not in grouped:
            account = ChartOfAccount.query.get(e.account_id)
            at = AccountType.query.get(account.account_type_id) if account else None
            grouped[e.account_id] = {
                'account': account,
                'account_type': at,
                'entries': [],
                'opening': opening_balances.get(e.account_id, 0.0),
                'total_debit': 0.0,
                'total_credit': 0.0,
            }
        grouped[e.account_id]['entries'].append(e)
        grouped[e.account_id]['total_debit'] += e.debit or 0.0
        grouped[e.account_id]['total_credit'] += e.credit or 0.0

    for account_id_, data in grouped.items():
        at = data['account_type']
        running = data['opening']
        is_debit_normal = at and at.normal_balance == 'Debit'
        for entry in data['entries']:
            d, c = entry.debit or 0.0, entry.credit or 0.0
            running += (d - c) if is_debit_normal else (c - d)
            entry._running_balance = running
        data['closing'] = running

    grouped_sorted = dict(sorted(
        grouped.items(),
        key=lambda kv: kv[1]['account'].account_code if kv[1]['account'] else '',
    ))

    # Labels
    if start_date and end_date:
        period_label = f"From {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
    elif start_date:
        period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
    elif end_date:
        period_label = f"Up to {end_date.strftime('%d %b %Y')}"
    else:
        period_label = "All activity"

    selected_account = ChartOfAccount.query.get(account_id) if account_id else None
    if selected_account:
        period_label = f"Account: {selected_account.account_code} - {selected_account.account_name}  •  {period_label}"

    # Company + currency
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "General Ledger"

    row = _write_company_header(ws, company, base_currency, symbol)
    row = _write_sheet_title(
        ws, row, "GENERAL LEDGER",
        f"{period_label}  •  All amounts in {base_currency} ({symbol})",
    )

    for account_id_, data in grouped_sorted.items():
        account = data['account']
        if not account:
            continue

        # Account header
        header_text = (
            f"{account.account_code} - {account.account_name}  "
            f"({data['account_type'].name if data['account_type'] else 'N/A'})"
        )
        ws.cell(row=row, column=1, value=header_text).font = EXCEL_SECTION_FONT
        for c in range(1, 7):
            ws.cell(row=row, column=c).fill = EXCEL_HEADER_FILL
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        row += 1

        # Column headers
        headers = ['Date', 'Entry #', 'Description',
                   f'Debit ({base_currency})',
                   f'Credit ({base_currency})',
                   f'Balance ({base_currency})']
        for c, h in enumerate(headers, start=1):
            cell = ws.cell(row=row, column=c, value=h)
            cell.font = EXCEL_HEADER_FONT
            cell.fill = EXCEL_SECTION_FILL
            cell.alignment = EXCEL_ALIGN_CENTER
        header_row = row
        row += 1

        first_data = row

        # Opening balance row
        if data['opening'] != 0 or start_date:
            ws.cell(row=row, column=3, value="Opening Balance").font = Font(
                name='Calibri', size=10, italic=True)
            c6 = ws.cell(row=row, column=6, value=data['opening'])
            c6.number_format = f'"{symbol}"#,##0.00'
            c6.font = Font(name='Calibri', size=10, italic=True)
            c6.alignment = EXCEL_ALIGN_RIGHT
            row += 1

        for entry in data['entries']:
            ws.cell(row=row, column=1, value=entry.date.strftime('%d %b %Y')).font = EXCEL_NORMAL_FONT
            ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
            ws.cell(row=row, column=2, value=entry.entry_number).font = EXCEL_NORMAL_FONT
            ws.cell(row=row, column=3, value=entry.description or '').font = EXCEL_NORMAL_FONT

            c4 = ws.cell(row=row, column=4, value=entry.debit or None)
            c4.number_format = f'"{symbol}"#,##0.00'
            c4.font = EXCEL_NORMAL_FONT
            c4.alignment = EXCEL_ALIGN_RIGHT

            c5 = ws.cell(row=row, column=5, value=entry.credit or None)
            c5.number_format = f'"{symbol}"#,##0.00'
            c5.font = EXCEL_NORMAL_FONT
            c5.alignment = EXCEL_ALIGN_RIGHT

            c6 = ws.cell(row=row, column=6, value=entry._running_balance)
            c6.number_format = f'"{symbol}"#,##0.00'
            c6.font = EXCEL_NORMAL_FONT
            c6.alignment = EXCEL_ALIGN_RIGHT
            row += 1

        last_data = row - 1

        # Totals row
        ws.cell(row=row, column=3, value="TOTAL").font = EXCEL_TOTAL_FONT
        ws.cell(row=row, column=3).alignment = EXCEL_ALIGN_RIGHT
        for c in range(1, 7):
            ws.cell(row=row, column=c).fill = EXCEL_TOTAL_FILL

        c4 = ws.cell(row=row, column=4, value=f"=SUM(D{first_data}:D{last_data})")
        c4.number_format = f'"{symbol}"#,##0.00'
        c4.font = EXCEL_TOTAL_FONT
        c4.alignment = EXCEL_ALIGN_RIGHT

        c5 = ws.cell(row=row, column=5, value=f"=SUM(E{first_data}:E{last_data})")
        c5.number_format = f'"{symbol}"#,##0.00'
        c5.font = EXCEL_TOTAL_FONT
        c5.alignment = EXCEL_ALIGN_RIGHT

        c6 = ws.cell(row=row, column=6, value=data['closing'])
        c6.number_format = f'"{symbol}"#,##0.00'
        c6.font = EXCEL_TOTAL_FONT
        c6.alignment = EXCEL_ALIGN_RIGHT

        total_row = row
        _apply_border(ws, header_row, total_row, 1, 6)
        row += 2

    if not grouped_sorted:
        ws.cell(row=row, column=1, value="No transactions found for this period.").font = EXCEL_NORMAL_FONT

    # Footer
    row += 2
    ws.cell(row=row, column=1,
            value=f"This is a computer-generated General Ledger report. All amounts in {base_currency}."
            ).font = Font(name='Calibri', size=8, italic=True, color='888888')

    _autosize_columns(ws, max_width=60)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    suffix = ""
    if start_date: suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date: suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buf,
        as_attachment=True,
        download_name=f'general_ledger{suffix}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )



@app.route('/journal_entries')
@login_required
def journal_entries():
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.reference_type == 'Manual Entry'
    ).order_by(JournalEntry.date.desc(), JournalEntry.entry_number.desc()).all()

    grouped_entries = {}
    for entry in entries:
        grouped_entries.setdefault(entry.entry_number, []).append(entry)

    return render_template('journal_entries.html', grouped_entries=grouped_entries)


@app.route('/add_journal_entry', methods=['GET', 'POST'])
@login_required
def add_journal_entry():
    accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
        ChartOfAccount.account_code
    ).all()
    accounts_serializable = [
        {'id': a.id, 'account_code': a.account_code, 'account_name': a.account_name}
        for a in accounts
    ]

    if request.method == 'POST':
        try:
            entry_count = int(request.form.get('entry_count', 1))
            entries_data = []
            total_amount = 0

            for i in range(entry_count):
                date = request.form.get(f'entries-{i}-date')
                description = request.form.get(f'entries-{i}-description')
                debit_account_id = request.form.get(f'entries-{i}-debit_account')
                credit_account_id = request.form.get(f'entries-{i}-credit_account')
                amount = float(request.form.get(f'entries-{i}-amount', 0) or 0)

                if debit_account_id and credit_account_id and amount > 0:
                    entries_data.append({
                        'date': date,
                        'description': description,
                        'debit_account_id': int(debit_account_id),
                        'credit_account_id': int(credit_account_id),
                        'amount': amount,
                        'index': i
                    })
                    total_amount += amount

            if total_amount == 0:
                flash('At least one entry must have an amount greater than 0', 'danger')
                return render_template(
                    'add_journal_entry.html',
                    accounts=accounts, accounts_json=accounts_serializable,
                    entry_count=entry_count, datetime=datetime
                )

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"JE-{timestamp}-{unique_id}"

            for entry_data in entries_data:
                attachment_filename = None
                attachment_original_name = None
                file_field = f'entries-{entry_data["index"]}-attachment'
                if file_field in request.files:
                    file = request.files[file_field]
                    if file and file.filename and allowed_file(file.filename):
                        original_filename = secure_filename(file.filename)
                        attachment_filename = f"{uuid.uuid4().hex}_{original_filename}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], attachment_filename)
                        file.save(file_path)
                        attachment_original_name = original_filename

                entry_date = datetime.strptime(entry_data['date'], '%Y-%m-%d').date()

                db.session.add(JournalEntry(
                    entry_number=entry_number,
                    date=entry_date,
                    description=entry_data['description'],
                    account_id=entry_data['debit_account_id'],
                    debit=entry_data['amount'],
                    credit=0,
                    attachment_filename=attachment_filename,
                    attachment_original_name=attachment_original_name,
                    reference_type='Manual Entry',
                    user_id=current_user.id
                ))

                db.session.add(JournalEntry(
                    entry_number=entry_number,
                    date=entry_date,
                    description=entry_data['description'],
                    account_id=entry_data['credit_account_id'],
                    debit=0,
                    credit=entry_data['amount'],
                    attachment_filename=attachment_filename,
                    attachment_original_name=attachment_original_name,
                    reference_type='Manual Entry',
                    user_id=current_user.id
                ))

                post_to_general_ledger(entry_data['debit_account_id'], entry_data['amount'], is_debit=True)
                post_to_general_ledger(entry_data['credit_account_id'], entry_data['amount'], is_debit=False)

            db.session.commit()
            flash(f'Journal entry created successfully with {len(entries_data)} transaction(s)!', 'success')
            return redirect(url_for('journal_entries'))

        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}")
            flash(f'Error creating journal entry: {str(e)}', 'danger')
            return render_template(
                'add_journal_entry.html',
                accounts=accounts, accounts_json=accounts_serializable,
                entry_count=entry_count, datetime=datetime
            )

    return render_template(
        'add_journal_entry.html',
        accounts=accounts, accounts_json=accounts_serializable,
        entry_count=1, datetime=datetime
    )


@app.route('/view_journal_entry/<entry_number>')
@login_required
def view_journal_entry(entry_number):
    entries = JournalEntry.query.filter_by(
        entry_number=entry_number, user_id=current_user.id
    ).order_by(JournalEntry.id).all()

    if not entries:
        flash('Journal entry not found', 'danger')
        return redirect(url_for('journal_entries'))

    total_debits = sum(e.debit for e in entries)
    total_credits = sum(e.credit for e in entries)

    return render_template(
        'view_journal_entry.html',
        entries=entries, entry_number=entry_number,
        total_debits=total_debits, total_credits=total_credits
    )


@app.route('/download_attachment/<int:entry_id>')
@login_required
def download_attachment(entry_id):
    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id:
        flash('Access denied', 'danger')
        return redirect(url_for('journal_entries'))

    if entry.attachment_filename:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], entry.attachment_filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=entry.attachment_original_name)
        else:
            flash('File not found', 'danger')
    else:
        flash('No attachment found', 'warning')

    return redirect(url_for('journal_entries'))


@app.route('/delete_journal_entries', methods=['POST'])
@login_required
def delete_journal_entries():
    try:
        data = request.get_json()
        entry_numbers = data.get('entry_numbers', [])
        if not entry_numbers:
            return jsonify({'success': False, 'message': 'No entries selected'}), 400

        deleted_count = 0
        for entry_number in entry_numbers:
            entries = JournalEntry.query.filter_by(
                entry_number=entry_number,
                user_id=current_user.id
            ).all()

            for entry in entries:
                if entry.debit > 0:
                    post_to_general_ledger(entry.account_id, entry.debit, is_debit=False)
                if entry.credit > 0:
                    post_to_general_ledger(entry.account_id, entry.credit, is_debit=True)

            for entry in entries:
                db.session.delete(entry)
                deleted_count += 1

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} journal entries and reversed GL.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ============================================================
# ✅ ROUTES — REPORTS
# ============================================================

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')


@app.route('/api/financial_data')
@login_required
def financial_data():
    report_type = request.args.get('type', 'monthly')
    year = request.args.get('year', datetime.now().year)

    if report_type == 'monthly':
        monthly_data = []
        for month in range(1, 13):
            invoices = Invoice.query.filter(
                Invoice.user_id == current_user.id,
                db.extract('month', Invoice.date) == month,
                db.extract('year', Invoice.date) == year
            ).all()

            invoice_total = 0
            for invoice in invoices:
                invoice_amount = db.session.query(db.func.sum(InvoiceLine.total)).filter_by(
                    invoice_id=invoice.id
                ).scalar() or 0
                invoice_total += invoice_amount

            expense_total = db.session.query(db.func.sum(Expense.amount)).filter(
                Expense.user_id == current_user.id,
                db.extract('month', Expense.date) == month,
                db.extract('year', Expense.date) == year
            ).scalar() or 0

            monthly_data.append({
                'month': datetime(year, month, 1).strftime('%B'),
                'invoices': float(invoice_total),
                'expenses': float(expense_total),
                'profit': float(invoice_total - expense_total)
            })

        return jsonify(monthly_data)

    return jsonify({'error': 'Invalid report type'}), 400

# ============================================================
# ✅ ROUTES — PAYMENT VOUCHERS
# ============================================================

@app.route('/payment_vouchers')
@login_required
def payment_vouchers():
    vouchers = PaymentVoucher.query.filter_by(user_id=current_user.id).order_by(
        PaymentVoucher.date.desc()
    ).all()
    return render_template('payment_vouchers.html', vouchers=vouchers)


@app.route('/add_payment_voucher', methods=['GET', 'POST'])
@login_required
def add_payment_voucher():
    form = PaymentVoucherForm()

    suppliers = Supplier.query.filter_by(is_active=True).all()
    form.supplier_id.choices = [(0, 'Select Supplier')] + [(s.id, s.name) for s in suppliers]

    payment_accounts = ChartOfAccount.query.join(AccountType).filter(
        ChartOfAccount.is_active == True,
        AccountType.normal_balance == 'Debit'
    ).order_by(ChartOfAccount.account_code).all()

    if not payment_accounts:
        payment_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    form.payment_account_id.choices = [(0, 'Select Payment Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in payment_accounts
    ]

    if request.method == 'POST':
        try:
            entry_count = int(request.form.get('entry_count', 1))
            lines = []
            total_gross = total_wht = total_vat = total_net = 0

            for i in range(entry_count):
                description = request.form.get(f'entries-{i}-description', '').strip()
                wht_rate = float(request.form.get(f'entries-{i}-wht_rate', 0) or 0)
                vat_rate = float(request.form.get(f'entries-{i}-vat_rate', 0) or 0)
                gross_amount = float(request.form.get(f'entries-{i}-gross_amount', 0) or 0)

                if gross_amount > 0:
                    wht_amount = gross_amount * (wht_rate / 100)
                    vat_amount = gross_amount * (vat_rate / 100)
                    net_amount = gross_amount - wht_amount + vat_amount

                    lines.append({
                        'description': description if description else f"Item {i + 1}",
                        'wht_rate': wht_rate,
                        'vat_rate': vat_rate,
                        'gross_amount': gross_amount,
                        'wht_amount': wht_amount,
                        'vat_amount': vat_amount,
                        'net_amount': net_amount
                    })

                    total_gross += gross_amount
                    total_wht += wht_amount
                    total_vat += vat_amount
                    total_net += net_amount

            if total_gross == 0:
                flash('At least one entry with a gross amount is required', 'danger')
                return render_template('add_payment_voucher.html', form=form)

            voucher_number = f"PV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            attachment_filename = None
            attachment_original_name = None
            if form.attachment.data:
                file = form.attachment.data
                if file and allowed_file(file.filename):
                    original_filename = secure_filename(file.filename)
                    attachment_filename = f"{uuid.uuid4().hex}_{original_filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], attachment_filename)
                    file.save(file_path)
                    attachment_original_name = original_filename

            voucher = PaymentVoucher(
                voucher_number=voucher_number,
                supplier_id=form.supplier_id.data,
                currency=form.currency.data,
                exchange_rate=form.exchange_rate.data,
                date=form.date.data,
                payment_account_id=form.payment_account_id.data,
                gross_amount=total_gross,
                wht_amount=total_wht,
                vat_amount=total_vat,
                net_amount=total_net,
                reference_number=form.reference_number.data,
                attachment_filename=attachment_filename,
                attachment_original_name=attachment_original_name,
                user_id=current_user.id
            )
            db.session.add(voucher)
            db.session.flush()

            for line in lines:
                db.session.add(PaymentVoucherLine(
                    payment_voucher_id=voucher.id,
                    description=line['description'],
                    wht_rate=line['wht_rate'],
                    vat_rate=line['vat_rate'],
                    gross_amount=line['gross_amount'],
                    wht_amount=line['wht_amount'],
                    vat_amount=line['vat_amount'],
                    net_amount=line['net_amount']
                ))

            ap_account = get_ap_account()
            if not ap_account:
                db.session.rollback()
                flash('Please configure AP account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            payment_account = ChartOfAccount.query.get(form.payment_account_id.data)
            if not payment_account:
                db.session.rollback()
                flash('Please select a valid payment account.', 'danger')
                return redirect(url_for('add_payment_voucher'))

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"PV-{timestamp}-{unique_id}"

            db.session.add(JournalEntry(
                entry_number=entry_number,
                date=voucher.date,
                description=f"Payment Voucher {voucher.voucher_number} - {voucher.supplier.name}",
                account_id=ap_account.id,
                debit=voucher.net_amount,
                credit=0,
                reference_type='Payment Voucher',
                reference_id=voucher.id,
                user_id=current_user.id
            ))

            db.session.add(JournalEntry(
                entry_number=entry_number,
                date=voucher.date,
                description=f"Payment Voucher {voucher.voucher_number} - {voucher.supplier.name}",
                account_id=payment_account.id,
                debit=0,
                credit=voucher.net_amount,
                reference_type='Payment Voucher',
                reference_id=voucher.id,
                user_id=current_user.id
            ))

            post_to_general_ledger(ap_account.id, voucher.net_amount, is_debit=True)
            post_to_general_ledger(payment_account.id, voucher.net_amount, is_debit=False)

            supplier = Supplier.query.get(form.supplier_id.data)
            if supplier:
                supplier.current_balance -= voucher.net_amount

            db.session.commit()
            flash(f'Payment Voucher {voucher_number} created successfully!', 'success')
            return redirect(url_for('payment_vouchers'))

        except Exception as e:
            db.session.rollback()
            print(f"❌ ERROR creating payment voucher: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error creating payment voucher: {str(e)}', 'danger')
            return render_template('add_payment_voucher.html', form=form)

    return render_template('add_payment_voucher.html', form=form)


@app.route('/view_payment_voucher/<int:id>')
@login_required
def view_payment_voucher(id):
    voucher = PaymentVoucher.query.get_or_404(id)
    if voucher.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('payment_vouchers'))
    return render_template('view_payment_voucher.html', voucher=voucher)


@app.route('/download_voucher_attachment/<int:id>')
@login_required
def download_voucher_attachment(id):
    voucher = PaymentVoucher.query.get_or_404(id)
    if voucher.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('payment_vouchers'))

    if voucher.attachment_filename:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], voucher.attachment_filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=voucher.attachment_original_name)
        else:
            flash('File not found', 'danger')
    else:
        flash('No attachment found', 'warning')

    return redirect(url_for('payment_vouchers'))


@app.route('/edit_payment_voucher/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_payment_voucher(id):
    voucher = PaymentVoucher.query.get_or_404(id)
    if voucher.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('payment_vouchers'))

    form = PaymentVoucherEditForm(obj=voucher)

    suppliers = Supplier.query.filter_by(is_active=True).all()
    form.supplier_id.choices = [(0, 'Select Supplier')] + [(s.id, s.name) for s in suppliers]

    payment_accounts = ChartOfAccount.query.join(AccountType).filter(
        ChartOfAccount.is_active == True,
        AccountType.normal_balance == 'Debit'
    ).order_by(ChartOfAccount.account_code).all()

    if not payment_accounts:
        payment_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(
            ChartOfAccount.account_code
        ).all()

    form.payment_account_id.choices = [(0, 'Select Payment Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in payment_accounts
    ]

    if form.validate_on_submit():
        voucher.supplier_id = form.supplier_id.data
        voucher.currency = form.currency.data
        voucher.exchange_rate = form.exchange_rate.data
        voucher.date = form.date.data
        voucher.description = form.description.data
        voucher.payment_account_id = form.payment_account_id.data
        voucher.gross_amount = form.gross_amount.data
        voucher.reference_number = form.reference_number.data

        if form.wht_rate.data > 0:
            voucher.wht_amount = form.gross_amount.data * (form.wht_rate.data / 100)
        if form.vat_rate.data > 0:
            voucher.vat_amount = form.gross_amount.data * (form.vat_rate.data / 100)
        voucher.net_amount = form.gross_amount.data - voucher.wht_amount + voucher.vat_amount

        db.session.commit()
        flash(f'Payment Voucher {voucher.voucher_number} updated successfully!', 'success')
        return redirect(url_for('payment_vouchers'))

    return render_template('edit_payment_voucher.html', form=form, voucher=voucher)


# acctsys/app.py

@app.route('/print_payment_voucher/<int:id>')
@login_required
def print_payment_voucher(id):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO

    voucher = PaymentVoucher.query.get_or_404(id)
    if voucher.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('payment_vouchers'))

    # ========== ENSURE UNICODE FONTS ARE REGISTERED ==========
    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # ========== COMPANY + CURRENCY CONTEXT ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    base_symbol = get_base_currency_symbol()

    # Voucher currency (may differ from base)
    voucher_currency = voucher.currency or base_currency
    voucher_symbol = {
        'USD': '$', 'EUR': '€', 'GBP': '£', 'GHS': '₵',
        'NGN': '₦', 'ZAR': 'R', 'KES': 'KSh', 'XOF': 'CFA',
    }.get(voucher_currency, voucher_currency + ' ')

    # Exchange rate & base equivalents
    rate = voucher.exchange_rate or 1.0
    base_gross = voucher.gross_amount * rate
    base_wht = voucher.wht_amount * rate
    base_vat = voucher.vat_amount * rate
    base_net = voucher.net_amount * rate
    is_foreign = (voucher_currency != base_currency)

    # ========== PDF SETUP ==========
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Payment Voucher {voucher.voucher_number}",
        author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    # ========== STYLES ==========
    company_name_style = ParagraphStyle(
        'CompanyName', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=4,
        fontName=FONT_BOLD,
    )
    company_sub_style = ParagraphStyle(
        'CompanySub', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1,
        spaceAfter=2, leading=12,
        fontName=FONT,
    )
    title_style = ParagraphStyle(
        'VoucherTitle', parent=styles['Heading1'], fontSize=22,
        textColor=colors.HexColor('#8e44ad'), alignment=1,
        spaceBefore=6, spaceAfter=14,
        fontName=FONT_BOLD,
    )
    label_style = ParagraphStyle(
        'Label', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#333333'), spaceAfter=2,
        fontName=FONT_BOLD,
    )
    value_style = ParagraphStyle(
        'Value', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#222222'), spaceAfter=2,
        fontName=FONT,
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Heading2'], fontSize=12,
        textColor=colors.HexColor('#34495e'),
        spaceBefore=12, spaceAfter=8,
        fontName=FONT_BOLD,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1,
        fontName=FONT,
    )

    # ========== COMPANY HEADER ==========
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_name_style))

    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), company_sub_style))

    contact_parts = []
    if company['phone']:
        contact_parts.append(f"Tel: {company['phone']}")
    if company['email']:
        contact_parts.append(f"Email: {company['email']}")
    if company['website']:
        contact_parts.append(f"Web: {company['website']}")
    if contact_parts:
        elements.append(Paragraph(" • ".join(contact_parts), company_sub_style))

    if company['tax_id']:
        elements.append(Paragraph(f"Tax ID / VAT: {company['tax_id']}", company_sub_style))

    elements.append(Spacer(1, 12))

    # Divider
    divider = Table([['']], colWidths=[180 * mm], rowHeights=[1])
    divider.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#8e44ad')),
    ]))
    elements.append(divider)
    elements.append(Spacer(1, 8))

    # ========== TITLE ==========
    elements.append(Paragraph("PAYMENT VOUCHER", title_style))

    # ========== HEADER INFO TABLE ==========
    header_data = [
        [
            Paragraph("<b>Voucher No:</b>", label_style),
            voucher.voucher_number,
            Paragraph("<b>Date:</b>", label_style),
            voucher.date.strftime('%d %b %Y'),
        ],
        [
            Paragraph("<b>Reference:</b>", label_style),
            voucher.reference_number or 'N/A',
            Paragraph("<b>Status:</b>", label_style),
            voucher.status,
        ],
        [
            Paragraph("<b>Base Currency:</b>", label_style),
            f"{base_currency} ({base_symbol})",
            Paragraph("<b>Voucher Currency:</b>", label_style),
            f"{voucher_currency} ({voucher_symbol})",
        ],
    ]
    header_table = Table(header_data, colWidths=[35 * mm, 55 * mm, 35 * mm, 55 * mm])
    header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 12))

    # ========== SUPPLIER + ACCOUNT INFO ==========
    supplier_block = [
        [Paragraph("<b>PAY TO (SUPPLIER)</b>", label_style)],
        [Paragraph(voucher.supplier.name if voucher.supplier else 'N/A', value_style)],
    ]
    if voucher.supplier:
        if voucher.supplier.contact_person:
            supplier_block.append([Paragraph(f"Attn: {voucher.supplier.contact_person}", value_style)])
        if voucher.supplier.address:
            supplier_block.append([Paragraph(voucher.supplier.address.replace('\n', ', '), value_style)])
        if voucher.supplier.email:
            supplier_block.append([Paragraph(f"Email: {voucher.supplier.email}", value_style)])
        if voucher.supplier.phone:
            supplier_block.append([Paragraph(f"Phone: {voucher.supplier.phone}", value_style)])
        if voucher.supplier.tax_id:
            supplier_block.append([Paragraph(f"Tax ID: {voucher.supplier.tax_id}", value_style)])

    account_block = [[Paragraph("<b>ACCOUNT INFORMATION</b>", label_style)]]
    if voucher.payment_account:
        account_block.append([Paragraph(
            f"Payment Account: {voucher.payment_account.account_code} - "
            f"{voucher.payment_account.account_name}", value_style)])
    account_block.append([Paragraph("Debit Account: Accounts Payable - Trade", value_style)])
    if is_foreign:
        account_block.append([Paragraph(
            f"Exchange Rate: 1 {voucher_currency} = {rate:g} {base_currency}", value_style)])
    else:
        account_block.append([Paragraph("No currency conversion applied", value_style)])

    supplier_table = Table(supplier_block, colWidths=[85 * mm])
    supplier_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTNAME', (0, 0), (-1, -1), FONT),
    ]))

    account_table = Table(account_block, colWidths=[85 * mm])
    account_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('FONTNAME', (0, 0), (-1, -1), FONT),
    ]))

    info_row = Table([[supplier_table, account_table]], colWidths=[90 * mm, 90 * mm])
    info_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(info_row)
    elements.append(Spacer(1, 16))

    # ========== LINE ITEMS ==========
    elements.append(Paragraph(f"Payment Line Items (in {voucher_currency})", section_style))

    line_data = [['#', 'Description', 'WHT %', 'VAT %', 'Gross', 'WHT', 'VAT', 'Net']]
    for idx, line in enumerate(voucher.lines, 1):
        desc = line.description or ''
        if len(desc) > 40:
            desc = desc[:37] + '...'
        line_data.append([
            str(idx),
            desc,
            f"{line.wht_rate:.2f}%",
            f"{line.vat_rate:.2f}%",
            f"{voucher_symbol}{line.gross_amount:,.2f}",
            f"({voucher_symbol}{line.wht_amount:,.2f})",
            f"{voucher_symbol}{line.vat_amount:,.2f}",
            f"{voucher_symbol}{line.net_amount:,.2f}",
        ])

    if len(line_data) == 1:
        line_data.append(['', 'No line items', '', '', '', '', '', ''])

    # Totals row
    line_data.append([
        '',
        Paragraph("<b>TOTAL</b>", value_style),
        '', '',
        Paragraph(f"<b>{voucher_symbol}{voucher.gross_amount:,.2f}</b>", value_style),
        Paragraph(f"<b>({voucher_symbol}{voucher.wht_amount:,.2f})</b>", value_style),
        Paragraph(f"<b>{voucher_symbol}{voucher.vat_amount:,.2f}</b>", value_style),
        Paragraph(f"<b>{voucher_symbol}{voucher.net_amount:,.2f}</b>", value_style),
    ])

    line_table = Table(
        line_data,
        colWidths=[10 * mm, 52 * mm, 15 * mm, 15 * mm, 25 * mm, 25 * mm, 24 * mm, 24 * mm],
        repeatRows=1,
    )
    line_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        # Body
        ('FONTNAME', (0, 1), (-1, -2), FONT),
        ('FONTSIZE', (0, 1), (-1, -2), 8),
        ('ALIGN', (0, 1), (0, -2), 'CENTER'),
        ('ALIGN', (2, 1), (7, -2), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Totals row
        ('BACKGROUND', (0, len(line_data) - 1), (-1, len(line_data) - 1), colors.HexColor('#f4ecf7')),
        ('FONTNAME', (0, len(line_data) - 1), (-1, len(line_data) - 1), FONT_BOLD),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 12))

    # ========== SUMMARY (Voucher Currency) ==========
    elements.append(Paragraph(f"Summary (in {voucher_currency})", section_style))

    summary_data = [
        ['Total Gross Amount:', f"{voucher_symbol}{voucher.gross_amount:,.2f}"],
        ['Less: WHT Amount:', f"({voucher_symbol}{voucher.wht_amount:,.2f})"],
        ['Add: VAT Amount:', f"{voucher_symbol}{voucher.vat_amount:,.2f}"],
        ['NET PAYMENT AMOUNT:', f"{voucher_symbol}{voucher.net_amount:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[110 * mm, 70 * mm])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#f4ecf7')),
        ('FONTNAME', (0, 3), (-1, 3), FONT_BOLD),
        ('TEXTCOLOR', (0, 3), (-1, 3), colors.HexColor('#6c3483')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    # ========== BASE CURRENCY EQUIVALENT (only if foreign) ==========
    if is_foreign:
        elements.append(Paragraph(f"Base Currency Equivalent ({base_currency})", section_style))

        base_data = [
            ['Exchange Rate Applied:', f"1 {voucher_currency} = {rate:g} {base_currency}"],
            ['Gross Amount:', f"{base_symbol}{base_gross:,.2f}"],
            ['Less: WHT Amount:', f"({base_symbol}{base_wht:,.2f})"],
            ['Add: VAT Amount:', f"{base_symbol}{base_vat:,.2f}"],
            ['NET PAYMENT (Base):', f"{base_symbol}{base_net:,.2f}"],
        ]
        base_table = Table(base_data, colWidths=[110 * mm, 70 * mm])
        base_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor('#fff3cd')),
            ('FONTNAME', (0, 4), (-1, 4), FONT_BOLD),
            ('TEXTCOLOR', (0, 4), (-1, 4), colors.HexColor('#856404')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ]))
        elements.append(base_table)
        elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph(
            f"<i>Voucher currency matches base currency ({base_currency}). No conversion applied.</i>",
            footer_style,
        ))
        elements.append(Spacer(1, 8))

    # ========== AMOUNT IN WORDS ==========
    def amount_in_words(amount):
        return f"{amount:,.2f} only"

    words_style = ParagraphStyle(
        'Words', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#333333'), spaceAfter=3,
        fontName=FONT,
    )
    elements.append(Paragraph(
        f"<b>Amount in Words (Voucher Currency):</b> "
        f"{amount_in_words(voucher.net_amount)} {voucher_currency}",
        words_style,
    ))

    if is_foreign:
        elements.append(Paragraph(
            f"<b>Amount in Words (Base Currency):</b> "
            f"{amount_in_words(base_net)} {base_currency}",
            words_style,
        ))

    elements.append(Spacer(1, 16))

    # ========== APPROVALS ==========
    elements.append(Paragraph("Approvals", section_style))

    approval_data = [
        ['', '', '', ''],
        ['PREPARED BY', 'CHECKED BY', 'APPROVED BY', 'RECEIVED BY'],
        ['', '', '', ''],
        ['Name: ________________', 'Name: ________________', 'Name: ________________', 'Name: ________________'],
        ['Signature: ____________', 'Signature: ____________', 'Signature: ____________', 'Signature: ____________'],
        ['Date: ________________', 'Date: ________________', 'Date: ________________', 'Date: ________________'],
    ]
    approval_table = Table(approval_data, colWidths=[42.5 * mm, 42.5 * mm, 42.5 * mm, 42.5 * mm])
    approval_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 1), (-1, 1), colors.white),
        ('FONTNAME', (0, 1), (-1, 1), FONT_BOLD),
        ('FONTSIZE', (0, 1), (-1, 1), 9),
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
        ('FONTSIZE', (0, 3), (-1, -1), 8),
        ('FONTNAME', (0, 3), (-1, -1), FONT),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
    ]))
    elements.append(approval_table)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph(
        f"This is a computer-generated payment voucher. Base Currency: {base_currency}.",
        footer_style,
    ))

    # ========== BUILD ==========
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'payment_voucher_{voucher.voucher_number}.pdf',
        mimetype='application/pdf',
    )

@app.route('/delete_payment_vouchers', methods=['POST'])
@login_required
def delete_payment_vouchers():
    try:
        data = request.get_json()
        voucher_ids = data.get('voucher_ids', [])
        if not voucher_ids:
            return jsonify({'success': False, 'message': 'No payment vouchers selected'}), 400

        vouchers_to_delete = PaymentVoucher.query.filter(
            PaymentVoucher.id.in_(voucher_ids),
            PaymentVoucher.user_id == current_user.id
        ).all()

        if not vouchers_to_delete:
            return jsonify({'success': False, 'message': 'No matching payment vouchers found'}), 404

        deleted_ids, reversed_gl_count = [], 0

        for voucher in vouchers_to_delete:
            try:
                journal_entries = JournalEntry.query.filter_by(
                    reference_type='Payment Voucher',
                    reference_id=voucher.id,
                    user_id=current_user.id
                ).all()

                for je in journal_entries:
                    if je.debit > 0:
                        post_to_general_ledger(je.account_id, je.debit, is_debit=False)
                        reversed_gl_count += 1
                    if je.credit > 0:
                        post_to_general_ledger(je.account_id, je.credit, is_debit=True)
                        reversed_gl_count += 1

                for je in journal_entries:
                    db.session.delete(je)

                supplier = Supplier.query.get(voucher.supplier_id)
                if supplier:
                    supplier.current_balance += voucher.net_amount

                PaymentVoucherLine.query.filter_by(payment_voucher_id=voucher.id).delete()
                db.session.delete(voucher)
                deleted_ids.append(voucher.id)
            except Exception as e:
                print(f"Error deleting payment voucher {voucher.id}: {e}")
                continue

        db.session.commit()
        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'reversed_gl_count': reversed_gl_count,
            'message': f'Successfully deleted {len(deleted_ids)} payment voucher(s).'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ============================================================
# ✅ ROUTES — SETTINGS
# ============================================================

@app.route('/settings')
@login_required
def settings():
    # AR: debit-normal accounts
    asset_accounts = ChartOfAccount.query.join(AccountType).filter(
        ChartOfAccount.is_active == True,
        AccountType.normal_balance == 'Debit'
    ).order_by(ChartOfAccount.account_code).all()

    # AP: credit-normal accounts
    liability_accounts = ChartOfAccount.query.join(AccountType).filter(
        ChartOfAccount.is_active == True,
        AccountType.normal_balance == 'Credit'
    ).order_by(ChartOfAccount.account_code).all()

    ar_setting = SystemSetting.query.filter_by(key='ar_account_id').first()
    ap_setting = SystemSetting.query.filter_by(key='ap_account_id').first()
    currency_setting = SystemSetting.query.filter_by(key='base_currency').first()

    settings = {
        'ar_account_id': ar_setting.value if ar_setting else None,
        'ap_account_id': ap_setting.value if ap_setting else None,
        'base_currency': currency_setting.value_string if currency_setting else DEFAULT_BASE_CURRENCY,
    }

    return render_template(
        'settings.html',
        asset_accounts=asset_accounts,
        liability_accounts=liability_accounts,
        settings=settings,
        company=get_company_profile(),
        supported_currencies=SUPPORTED_CURRENCIES,
        csrf_token=generate_csrf()
    )


@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    # Base currency
    base_currency = request.form.get('base_currency', DEFAULT_BASE_CURRENCY).strip().upper()
    valid_codes = [code for code, _ in SUPPORTED_CURRENCIES]
    if base_currency not in valid_codes:
        flash(f'Invalid currency code: {base_currency}', 'danger')
        return redirect(url_for('settings'))

    currency_setting = SystemSetting.query.filter_by(key='base_currency').first()
    if currency_setting:
        currency_setting.value_string = base_currency
    else:
        db.session.add(SystemSetting(
            key='base_currency', value='base_currency',
            value_string=base_currency,
            description='System base currency for reporting'
        ))

    # AR / AP
    ar_account_id = request.form.get('ar_account_id')
    ap_account_id = request.form.get('ap_account_id')

    if ar_account_id:
        s = SystemSetting.query.filter_by(key='ar_account_id').first()
        if s:
            s.value = int(ar_account_id)
        else:
            db.session.add(SystemSetting(
                key='ar_account_id', value=int(ar_account_id),
                description='Accounts Receivable account for invoices'
            ))

    if ap_account_id:
        s = SystemSetting.query.filter_by(key='ap_account_id').first()
        if s:
            s.value = int(ap_account_id)
        else:
            db.session.add(SystemSetting(
                key='ap_account_id', value=int(ap_account_id),
                description='Accounts Payable account for purchases and payment vouchers'
            ))

    # Company profile
    set_company_setting('company_name',    request.form.get('company_name', '').strip())
    set_company_setting('company_address', request.form.get('company_address', '').strip())
    set_company_setting('company_phone',   request.form.get('company_phone', '').strip())
    set_company_setting('company_email',   request.form.get('company_email', '').strip())
    set_company_setting('company_tax_id',  request.form.get('company_tax_id', '').strip())
    set_company_setting('company_website', request.form.get('company_website', '').strip())

    # Logo
    if 'company_logo_file' in request.files:
        file = request.files['company_logo_file']
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext in {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}:
                filename = f"company_logo_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                set_company_setting('company_logo', filename)
            else:
                flash('Logo must be PNG, JPG, JPEG, GIF, SVG or WEBP.', 'warning')

    db.session.commit()
    flash('Settings saved successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/company_logo')
def company_logo():
    filename = get_company_setting('company_logo', '')
    if not filename:
        transparent_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return Response(transparent_png, mimetype='image/png')

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        flash('Logo file not found.', 'warning')
        return redirect(url_for('settings'))

    return send_file(filepath)

# acctsys/app.py – Profit & Loss (Income Statement)

@app.route('/profit_and_loss')
@login_required
def profit_and_loss():
    """
    Profit & Loss report.
    Revenue - Expenses = Net Profit/Loss.
    Driven by GeneralLedger balances grouped by AccountType.
    """
    from datetime import date

    # Optional date range
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # Query all journal entries (optionally date-filtered)
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)
    entries = query.all()

    # Aggregate by account
    account_totals = {}   # account_id -> {'debit': x, 'credit': y}
    for e in entries:
        if e.account_id not in account_totals:
            account_totals[e.account_id] = {'debit': 0.0, 'credit': 0.0}
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    # Fetch all account + type info in one go
    account_ids = list(account_totals.keys())
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(account_ids)
    ).all() if account_ids else []

    accounts_by_id = {a.id: a for a in accounts}

    revenue_lines = []
    expense_lines = []
    total_revenue = 0.0
    total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue

        at = account.account_type
        debit = totals['debit']
        credit = totals['credit']

        # For credit-normal accounts (Revenue), balance = credit - debit
        # For debit-normal accounts (Expense), balance = debit - credit
        if at.normal_balance == 'Credit':
            balance = credit - debit
        else:
            balance = debit - credit

        if balance == 0:
            continue

        if at.name.lower() in ('revenue', 'income', 'sales'):
            revenue_lines.append({
                'account_code': account.account_code,
                'account_name': account.account_name,
                'account_type': at.name,
                'amount': balance,
            })
            total_revenue += balance
        elif at.name.lower() in ('expense', 'expenses', 'cost of sales', 'cogs'):
            expense_lines.append({
                'account_code': account.account_code,
                'account_name': account.account_name,
                'account_type': at.name,
                'amount': balance,
            })
            total_expenses += balance
        # Other types (Asset, Liability, Equity) are ignored in P&L

    # Sort by account code
    revenue_lines.sort(key=lambda x: x['account_code'])
    expense_lines.sort(key=lambda x: x['account_code'])

    net_profit = total_revenue - total_expenses
    is_profit = net_profit >= 0

    return render_template(
        'profit_and_loss.html',
        revenue_lines=revenue_lines,
        expense_lines=expense_lines,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        net_profit=net_profit,
        is_profit=is_profit,
        start_date=start_date,
        end_date=end_date,
    )

# acctsys/app.py – Profit & Loss Excel export

@app.route('/profit_and_loss/excel')
@login_required
def profit_and_loss_excel():
    # Parse date range (same logic as HTML/PDF)
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)
    entries = query.all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(account_totals.keys()))
    ).all() if account_totals else []
    accounts_by_id = {a.id: a for a in accounts}

    revenue_lines, expense_lines = [], []
    total_revenue = total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue
        at = account.account_type
        balance = (totals['credit'] - totals['debit']) if at.normal_balance == 'Credit' \
                  else (totals['debit'] - totals['credit'])
        if balance == 0:
            continue
        row = {'code': account.account_code, 'name': account.account_name, 'amount': balance}
        nl = at.name.lower()
        if nl in ('revenue', 'income', 'sales'):
            revenue_lines.append(row)
            total_revenue += balance
        elif nl in ('expense', 'expenses', 'cost of sales', 'cogs'):
            expense_lines.append(row)
            total_expenses += balance

    revenue_lines.sort(key=lambda x: x['code'])
    expense_lines.sort(key=lambda x: x['code'])
    net_profit = total_revenue - total_expenses

    # ========== BUILD WORKBOOK ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Profit and Loss"

    row = _write_company_header(ws, company, base_currency, symbol)

    period_text = f"All amounts in {base_currency} ({symbol})"
    if start_date or end_date:
        period_text = (
            f"Period: {start_date.strftime('%d %b %Y') if start_date else '...'} "
            f"to {end_date.strftime('%d %b %Y') if end_date else '...'}  •  {period_text}"
        )
    row = _write_sheet_title(ws, row, "PROFIT & LOSS STATEMENT", period_text)

    # ---------- REVENUE ----------
    ws.cell(row=row, column=1, value="REVENUE").font = EXCEL_SECTION_FONT
    for c in range(1, 4):
        ws.cell(row=row, column=c).fill = EXCEL_SECTION_FILL
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    row += 1

    # Header
    for c, h in enumerate(['Code', 'Account', f'Amount ({base_currency})'], start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = EXCEL_HEADER_FONT
        cell.fill = EXCEL_HEADER_FILL
        cell.alignment = EXCEL_ALIGN_CENTER
    rev_header_row = row
    row += 1

    rev_first_data = row
    for line in revenue_lines:
        ws.cell(row=row, column=1, value=line['code']).font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
        ws.cell(row=row, column=2, value=line['name']).font = EXCEL_NORMAL_FONT
        c3 = ws.cell(row=row, column=3, value=line['amount'])
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_NORMAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        row += 1
    if not revenue_lines:
        ws.cell(row=row, column=1, value="—").font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=2, value="No revenue recorded").font = EXCEL_NORMAL_FONT
        c3 = ws.cell(row=row, column=3, value=0)
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_NORMAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        row += 1
    rev_last_data = row - 1

    # Total Revenue
    ws.cell(row=row, column=2, value="Total Revenue").font = EXCEL_TOTAL_FONT
    ws.cell(row=row, column=2).alignment = EXCEL_ALIGN_RIGHT
    ws.cell(row=row, column=2).fill = EXCEL_TOTAL_FILL
    ws.cell(row=row, column=1).fill = EXCEL_TOTAL_FILL
    c3 = ws.cell(row=row, column=3, value=f"=SUM(C{rev_first_data}:C{rev_last_data})")
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = EXCEL_TOTAL_FONT
    c3.alignment = EXCEL_ALIGN_RIGHT
    c3.fill = EXCEL_TOTAL_FILL
    rev_total_row = row
    row += 2

    # ---------- EXPENSES ----------
    ws.cell(row=row, column=1, value="EXPENSES").font = EXCEL_SECTION_FONT
    for c in range(1, 4):
        ws.cell(row=row, column=c).fill = EXCEL_SECTION_FILL_2
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    row += 1

    for c, h in enumerate(['Code', 'Account', f'Amount ({base_currency})'], start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = EXCEL_HEADER_FONT
        cell.fill = EXCEL_HEADER_FILL
        cell.alignment = EXCEL_ALIGN_CENTER
    exp_header_row = row
    row += 1

    exp_first_data = row
    for line in expense_lines:
        ws.cell(row=row, column=1, value=line['code']).font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
        ws.cell(row=row, column=2, value=line['name']).font = EXCEL_NORMAL_FONT
        c3 = ws.cell(row=row, column=3, value=line['amount'])
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_NORMAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        row += 1
    if not expense_lines:
        ws.cell(row=row, column=1, value="—").font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=2, value="No expenses recorded").font = EXCEL_NORMAL_FONT
        c3 = ws.cell(row=row, column=3, value=0)
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_NORMAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        row += 1
    exp_last_data = row - 1

    # Total Expenses
    ws.cell(row=row, column=2, value="Total Expenses").font = EXCEL_TOTAL_FONT
    ws.cell(row=row, column=2).alignment = EXCEL_ALIGN_RIGHT
    ws.cell(row=row, column=2).fill = EXCEL_TOTAL_FILL_RED
    ws.cell(row=row, column=1).fill = EXCEL_TOTAL_FILL_RED
    c3 = ws.cell(row=row, column=3, value=f"=SUM(C{exp_first_data}:C{exp_last_data})")
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = EXCEL_TOTAL_FONT
    c3.alignment = EXCEL_ALIGN_RIGHT
    c3.fill = EXCEL_TOTAL_FILL_RED
    exp_total_row = row
    row += 2

    # ---------- NET PROFIT / LOSS ----------
    net_label = "NET PROFIT" if net_profit >= 0 else "NET LOSS"
    fill = EXCEL_TOTAL_FILL_GRN if net_profit >= 0 else EXCEL_TOTAL_FILL_RED

    c1 = ws.cell(row=row, column=1, value=net_label)
    c1.font = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
    c1.alignment = EXCEL_ALIGN_LEFT
    c1.fill = PatternFill('solid', fgColor='27AE60' if net_profit >= 0 else 'C0392B')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)

    c3 = ws.cell(row=row, column=3, value=f"=C{rev_total_row}-C{exp_total_row}")
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
    c3.alignment = EXCEL_ALIGN_RIGHT
    c3.fill = PatternFill('solid', fgColor='27AE60' if net_profit >= 0 else 'C0392B')
    net_row = row
    row += 2

    # Footer
    ws.cell(row=row, column=1,
            value=f"This is a computer-generated Profit & Loss statement. All amounts in {base_currency}."
            ).font = Font(name='Calibri', size=8, italic=True, color='888888')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)

    # Borders for tables
    _apply_border(ws, rev_header_row, rev_total_row, 1, 3)
    _apply_border(ws, exp_header_row, exp_total_row, 1, 3)

    _autosize_columns(ws)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    suffix = ""
    if start_date: suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date:   suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buf,
        as_attachment=True,
        download_name=f'profit_and_loss{suffix}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

# acctsys/app.py

@app.route('/profit_and_loss/pdf')
@login_required
def profit_and_loss_pdf():
    """Generate Profit & Loss statement as PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO
    from datetime import date

    # ========== ENSURE UNICODE FONTS ARE REGISTERED ==========
    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # ========== PARSE DATE RANGE ==========
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # ========== QUERY JOURNAL ENTRIES ==========
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if start_date:
        query = query.filter(JournalEntry.date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.date <= end_date)
    entries = query.all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(account_totals.keys()))
    ).all() if account_totals else []
    accounts_by_id = {a.id: a for a in accounts}

    revenue_lines, expense_lines = [], []
    total_revenue = total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue
        at = account.account_type
        balance = (totals['credit'] - totals['debit']) if at.normal_balance == 'Credit' \
                  else (totals['debit'] - totals['credit'])
        if balance == 0:
            continue
        row = {
            'code': account.account_code,
            'name': account.account_name,
            'amount': balance,
        }
        name_lower = at.name.lower()
        if name_lower in ('revenue', 'income', 'sales'):
            revenue_lines.append(row)
            total_revenue += balance
        elif name_lower in ('expense', 'expenses', 'cost of sales', 'cogs'):
            expense_lines.append(row)
            total_expenses += balance

    revenue_lines.sort(key=lambda x: x['code'])
    expense_lines.sort(key=lambda x: x['code'])
    net_profit = total_revenue - total_expenses

    # ========== COMPANY + CURRENCY ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    # ========== PDF SETUP ==========
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title="Profit & Loss Statement",
        author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    # ========== STYLES ==========
    company_name_style = ParagraphStyle(
        'CompanyName', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=4,
        fontName=FONT_BOLD,
    )
    company_sub_style = ParagraphStyle(
        'CompanySub', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1,
        spaceAfter=2, leading=12,
        fontName=FONT,
    )
    title_style = ParagraphStyle(
        'Title', parent=styles['Heading1'], fontSize=20,
        textColor=colors.HexColor('#27ae60'), alignment=1,
        spaceBefore=6, spaceAfter=6,
        fontName=FONT_BOLD,
    )
    period_style = ParagraphStyle(
        'Period', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#7f8c8d'), alignment=1, spaceAfter=14,
        fontName=FONT,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1,
        fontName=FONT,
    )

    # ========== HEADER ==========
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_name_style))

    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), company_sub_style))

    contact_parts = []
    if company['phone']:
        contact_parts.append(f"Tel: {company['phone']}")
    if company['email']:
        contact_parts.append(f"Email: {company['email']}")
    if contact_parts:
        elements.append(Paragraph(" • ".join(contact_parts), company_sub_style))

    elements.append(Spacer(1, 8))
    elements.append(Paragraph("PROFIT &amp; LOSS STATEMENT", title_style))

    period_text = f"All amounts in {base_currency} ({symbol})"
    if start_date or end_date:
        period_text = (
            f"Period: {start_date.strftime('%d %b %Y') if start_date else '...'} "
            f"to {end_date.strftime('%d %b %Y') if end_date else '...'}  •  {period_text}"
        )
    elements.append(Paragraph(period_text, period_style))

    # ========== REVENUE SECTION ==========
    rev_head_style = ParagraphStyle(
        'SecHeadRev', parent=styles['Heading2'], fontSize=12,
        textColor=colors.white, backColor=colors.HexColor('#3498db'),
        alignment=0, spaceBefore=8, spaceAfter=6, leftIndent=4,
        fontName=FONT_BOLD,
    )
    elements.append(Paragraph("<b>REVENUE</b>", rev_head_style))

    rev_data = [['Code', 'Account', 'Amount']]
    for line in revenue_lines:
        rev_data.append([line['code'], line['name'], f"{symbol}{line['amount']:,.2f}"])
    if len(rev_data) == 1:
        rev_data.append(['—', 'No revenue recorded', f"{symbol}0.00"])

    total_label_para = Paragraph("<b>Total Revenue</b>", ParagraphStyle(
        'TL', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9,
    ))
    total_value_para = Paragraph(f"<b>{symbol}{total_revenue:,.2f}</b>", ParagraphStyle(
        'TV', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, alignment=2,
    ))
    rev_data.append(['', total_label_para, total_value_para])

    rev_table = Table(rev_data, colWidths=[25 * mm, 105 * mm, 50 * mm], repeatRows=1)
    rev_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -2), FONT),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, len(rev_data) - 1), (-1, len(rev_data) - 1), colors.HexColor('#d6eaf8')),
        ('FONTNAME', (0, len(rev_data) - 1), (-1, len(rev_data) - 1), FONT_BOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(rev_table)
    elements.append(Spacer(1, 14))

    # ========== EXPENSES SECTION ==========
    exp_head_style = ParagraphStyle(
        'SecHeadExp', parent=styles['Heading2'], fontSize=12,
        textColor=colors.white, backColor=colors.HexColor('#e74c3c'),
        alignment=0, spaceBefore=8, spaceAfter=6, leftIndent=4,
        fontName=FONT_BOLD,
    )
    elements.append(Paragraph("<b>EXPENSES</b>", exp_head_style))

    exp_data = [['Code', 'Account', 'Amount']]
    for line in expense_lines:
        exp_data.append([line['code'], line['name'], f"{symbol}{line['amount']:,.2f}"])
    if len(exp_data) == 1:
        exp_data.append(['—', 'No expenses recorded', f"{symbol}0.00"])

    exp_total_label = Paragraph("<b>Total Expenses</b>", ParagraphStyle(
        'TL2', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9,
    ))
    exp_total_value = Paragraph(f"<b>{symbol}{total_expenses:,.2f}</b>", ParagraphStyle(
        'TV2', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, alignment=2,
    ))
    exp_data.append(['', exp_total_label, exp_total_value])

    exp_table = Table(exp_data, colWidths=[25 * mm, 105 * mm, 50 * mm], repeatRows=1)
    exp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -2), FONT),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, len(exp_data) - 1), (-1, len(exp_data) - 1), colors.HexColor('#fadbd8')),
        ('FONTNAME', (0, len(exp_data) - 1), (-1, len(exp_data) - 1), FONT_BOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(exp_table)
    elements.append(Spacer(1, 16))

    # ========== NET PROFIT / LOSS ==========
    net_color = colors.HexColor('#27ae60') if net_profit >= 0 else colors.HexColor('#c0392b')
    net_label = "NET PROFIT" if net_profit >= 0 else "NET LOSS"

    net_label_para = Paragraph(
        f"<b>{net_label}</b>",
        ParagraphStyle('NetL', parent=styles['Normal'], fontSize=13,
                       fontName=FONT_BOLD, textColor=colors.white),
    )
    net_value_para = Paragraph(
        f"<b>{symbol}{abs(net_profit):,.2f} {base_currency}</b>",
        ParagraphStyle('NetR', parent=styles['Normal'], fontSize=13,
                       fontName=FONT_BOLD, textColor=colors.white, alignment=2),
    )
    net_table = Table([[net_label_para, net_value_para]], colWidths=[100 * mm, 80 * mm])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), net_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 20))

    # ========== FOOTER ==========
    elements.append(Paragraph(
        f"This is a computer-generated Profit &amp; Loss statement. "
        f"All amounts in {base_currency}.",
        footer_style,
    ))

    # ========== BUILD ==========
    doc.build(elements)
    buffer.seek(0)

    fname_suffix = ""
    if start_date:
        fname_suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date:
        fname_suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'profit_and_loss{fname_suffix}.pdf',
        mimetype='application/pdf',
    )

# acctsys/app.py – Balance Sheet

@app.route('/balance_sheet')
@login_required
def balance_sheet():
    """
    Balance Sheet as of a given date.
    Assets = Liabilities + Equity (+ Retained Earnings)
    """
    from datetime import date

    as_of_str = request.args.get('as_of_date')
    try:
        as_of_date = datetime.strptime(as_of_str, '%Y-%m-%d').date() if as_of_str else date.today()
    except ValueError:
        as_of_date = date.today()

    # Query all journal entries up to as_of_date
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.date <= as_of_date
    ).all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    account_ids = list(account_totals.keys())
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(account_ids)
    ).all() if account_ids else []
    accounts_by_id = {a.id: a for a in accounts}

    asset_lines = []
    liability_lines = []
    equity_lines = []

    total_assets = total_liabilities = total_equity = 0.0
    total_revenue = total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue

        at = account.account_type
        debit = totals['debit']
        credit = totals['credit']

        # Compute signed balance based on normal balance
        if at.normal_balance == 'Debit':
            balance = debit - credit       # positive = asset-style
        else:
            balance = credit - debit       # positive = liability/equity/revenue-style

        if balance == 0:
            continue

        name_lower = at.name.lower()

        if name_lower in ('asset', 'current asset', 'non-current asset',
                          'fixed asset', 'current assets', 'non-current assets'):
            asset_lines.append({
                'code': account.account_code,
                'name': account.account_name,
                'type': at.name,
                'amount': balance,
            })
            total_assets += balance
        elif name_lower in ('liability', 'current liability', 'non-current liability',
                            'current liabilities', 'non-current liabilities',
                            'payable', 'accounts payable'):
            liability_lines.append({
                'code': account.account_code,
                'name': account.account_name,
                'type': at.name,
                'amount': balance,
            })
            total_liabilities += balance
        elif name_lower in ('equity', "owner's equity", 'capital', 'retained earnings'):
            equity_lines.append({
                'code': account.account_code,
                'name': account.account_name,
                'type': at.name,
                'amount': balance,
            })
            total_equity += balance
        elif name_lower in ('revenue', 'income', 'sales'):
            total_revenue += balance
        elif name_lower in ('expense', 'expenses', 'cost of sales', 'cogs'):
            total_expenses += balance

    # Retained earnings = cumulative net profit (revenue - expenses) up to as_of_date
    retained_earnings = total_revenue - total_expenses
    total_equity_with_re = total_equity + retained_earnings

    # Balance check
    total_liabilities_and_equity = total_liabilities + total_equity_with_re
    difference = total_assets - total_liabilities_and_equity
    is_balanced = abs(difference) < 0.01

    asset_lines.sort(key=lambda x: x['code'])
    liability_lines.sort(key=lambda x: x['code'])
    equity_lines.sort(key=lambda x: x['code'])

    return render_template(
        'balance_sheet.html',
        asset_lines=asset_lines,
        liability_lines=liability_lines,
        equity_lines=equity_lines,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity_with_re,
        retained_earnings=retained_earnings,
        total_liabilities_and_equity=total_liabilities_and_equity,
        difference=difference,
        is_balanced=is_balanced,
        as_of_date=as_of_date,
    )



# acctsys/app.py

@app.route('/balance_sheet/pdf')
@login_required
def balance_sheet_pdf():
    """Generate Balance Sheet as PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO
    from datetime import date

    # ========== ENSURE UNICODE FONTS ARE REGISTERED ==========
    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # ========== PARSE AS-OF DATE ==========
    as_of_str = request.args.get('as_of_date')
    try:
        as_of_date = datetime.strptime(as_of_str, '%Y-%m-%d').date() if as_of_str else date.today()
    except ValueError:
        as_of_date = date.today()

    # ========== QUERY ENTRIES UP TO AS-OF DATE ==========
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.date <= as_of_date,
    ).all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(account_totals.keys()))
    ).all() if account_totals else []
    accounts_by_id = {a.id: a for a in accounts}

    asset_lines, liability_lines, equity_lines = [], [], []
    total_assets = total_liabilities = total_equity = 0.0
    total_revenue = total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue
        at = account.account_type
        balance = (totals['debit'] - totals['credit']) if at.normal_balance == 'Debit' \
                  else (totals['credit'] - totals['debit'])
        if balance == 0:
            continue

        row = {'code': account.account_code, 'name': account.account_name, 'amount': balance}
        nl = at.name.lower()

        if nl in ('asset', 'current asset', 'non-current asset', 'fixed asset',
                  'current assets', 'non-current assets'):
            asset_lines.append(row)
            total_assets += balance
        elif nl in ('liability', 'current liability', 'non-current liability',
                    'current liabilities', 'non-current liabilities',
                    'payable', 'accounts payable'):
            liability_lines.append(row)
            total_liabilities += balance
        elif nl in ('equity', "owner's equity", 'capital', 'retained earnings'):
            equity_lines.append(row)
            total_equity += balance
        elif nl in ('revenue', 'income', 'sales'):
            total_revenue += balance
        elif nl in ('expense', 'expenses', 'cost of sales', 'cogs'):
            total_expenses += balance

    retained_earnings = total_revenue - total_expenses
    total_equity_with_re = total_equity + retained_earnings
    total_liab_eq = total_liabilities + total_equity_with_re

    asset_lines.sort(key=lambda x: x['code'])
    liability_lines.sort(key=lambda x: x['code'])
    equity_lines.sort(key=lambda x: x['code'])

    # ========== COMPANY + CURRENCY ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    # ========== PDF SETUP ==========
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title="Balance Sheet",
        author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    # ========== STYLES ==========
    company_name_style = ParagraphStyle(
        'CompanyName', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=4,
        fontName=FONT_BOLD,
    )
    company_sub_style = ParagraphStyle(
        'CompanySub', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1,
        spaceAfter=2, leading=12,
        fontName=FONT,
    )
    title_style = ParagraphStyle(
        'Title', parent=styles['Heading1'], fontSize=20,
        textColor=colors.HexColor('#2980b9'), alignment=1,
        spaceBefore=6, spaceAfter=6,
        fontName=FONT_BOLD,
    )
    period_style = ParagraphStyle(
        'Period', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#7f8c8d'), alignment=1, spaceAfter=14,
        fontName=FONT,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1,
        fontName=FONT,
    )

    # ========== HEADER ==========
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_name_style))

    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), company_sub_style))

    contact_parts = []
    if company['phone']:
        contact_parts.append(f"Tel: {company['phone']}")
    if company['email']:
        contact_parts.append(f"Email: {company['email']}")
    if contact_parts:
        elements.append(Paragraph(" • ".join(contact_parts), company_sub_style))

    elements.append(Spacer(1, 8))
    elements.append(Paragraph("BALANCE SHEET", title_style))
    elements.append(Paragraph(
        f"As of {as_of_date.strftime('%d %b %Y')}  •  "
        f"All amounts in {base_currency} ({symbol})",
        period_style,
    ))

    # ========== HELPER: BUILD A SECTION ==========
    def build_section(title, lines, total_label, total_value, head_color_hex):
        head = ParagraphStyle(
            f'SH_{title}', parent=styles['Heading2'], fontSize=12,
            textColor=colors.white, backColor=colors.HexColor(head_color_hex),
            alignment=0, spaceBefore=8, spaceAfter=6, leftIndent=4,
            fontName=FONT_BOLD,
        )
        elements.append(Paragraph(f"<b>{title}</b>", head))

        data = [['Code', 'Account', 'Amount']]
        for line in lines:
            data.append([line['code'], line['name'], f"{symbol}{line['amount']:,.2f}"])
        if len(data) == 1:
            data.append(['—', 'None', f"{symbol}0.00"])

        total_label_para = Paragraph(
            f"<b>{total_label}</b>",
            ParagraphStyle('TL', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9),
        )
        total_value_para = Paragraph(
            f"<b>{symbol}{total_value:,.2f}</b>",
            ParagraphStyle('TV', parent=styles['Normal'], fontName=FONT_BOLD,
                           fontSize=9, alignment=2),
        )
        data.append(['', total_label_para, total_value_para])

        t = Table(data, colWidths=[25 * mm, 105 * mm, 50 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (0, 1), (-1, -2), FONT),
            ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
            ('BACKGROUND', (0, len(data) - 1), (-1, len(data) - 1), colors.HexColor('#eaf2f8')),
            ('FONTNAME', (0, len(data) - 1), (-1, len(data) - 1), FONT_BOLD),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 12))

    # ========== ASSETS ==========
    build_section("ASSETS", asset_lines, "Total Assets", total_assets, '#2980b9')

    # ========== LIABILITIES ==========
    build_section("LIABILITIES", liability_lines, "Total Liabilities",
                  total_liabilities, '#c0392b')

    # ========== EQUITY (with retained earnings) ==========
    eq_head = ParagraphStyle(
        'SH_EQ', parent=styles['Heading2'], fontSize=12,
        textColor=colors.white, backColor=colors.HexColor('#8e44ad'),
        alignment=0, spaceBefore=8, spaceAfter=6, leftIndent=4,
        fontName=FONT_BOLD,
    )
    elements.append(Paragraph("<b>EQUITY</b>", eq_head))

    eq_data = [['Code', 'Account', 'Amount']]
    for line in equity_lines:
        eq_data.append([line['code'], line['name'], f"{symbol}{line['amount']:,.2f}"])
    if not equity_lines:
        eq_data.append(['—', 'No equity accounts', f"{symbol}0.00"])

    # Add retained earnings as a separate row
    eq_data.append([
        '—',
        'Retained Earnings (cumulative net profit)',
        f"{symbol}{retained_earnings:,.2f}",
    ])

    eq_total_label = Paragraph(
        "<b>Total Equity</b>",
        ParagraphStyle('EQ_TL', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9),
    )
    eq_total_value = Paragraph(
        f"<b>{symbol}{total_equity_with_re:,.2f}</b>",
        ParagraphStyle('EQ_TV', parent=styles['Normal'], fontName=FONT_BOLD,
                       fontSize=9, alignment=2),
    )
    eq_data.append(['', eq_total_label, eq_total_value])

    eq_table = Table(eq_data, colWidths=[25 * mm, 105 * mm, 50 * mm], repeatRows=1)
    eq_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -2), FONT),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, len(eq_data) - 1), (-1, len(eq_data) - 1), colors.HexColor('#f4ecf7')),
        ('FONTNAME', (0, len(eq_data) - 1), (-1, len(eq_data) - 1), FONT_BOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(eq_table)
    elements.append(Spacer(1, 16))

    # ========== TOTAL LIABILITIES + EQUITY ==========
    total_l_label = Paragraph(
        "<b>TOTAL LIABILITIES + EQUITY</b>",
        ParagraphStyle('TL_LE', parent=styles['Normal'], fontSize=13,
                       fontName=FONT_BOLD, textColor=colors.white),
    )
    total_l_value = Paragraph(
        f"<b>{symbol}{total_liab_eq:,.2f} {base_currency}</b>",
        ParagraphStyle('TV_LE', parent=styles['Normal'], fontSize=13,
                       fontName=FONT_BOLD, textColor=colors.white, alignment=2),
    )
    total_table = Table([[total_l_label, total_l_value]], colWidths=[100 * mm, 80 * mm])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(total_table)

    elements.append(Spacer(1, 10))

    # ========== BALANCE CHECK ==========
    diff = total_assets - total_liab_eq
    if abs(diff) < 0.01:
        msg = f"✓ Balance Sheet is balanced (Assets = Liabilities + Equity)"
        msg_color = colors.HexColor('#27ae60')
    else:
        msg = f"⚠ Out of balance by {symbol}{abs(diff):,.2f}"
        msg_color = colors.HexColor('#c0392b')

    elements.append(Paragraph(msg, ParagraphStyle(
        'Bal', parent=styles['Normal'], fontSize=10,
        textColor=msg_color, alignment=1, fontName=FONT_BOLD,
    )))

    elements.append(Spacer(1, 16))
    elements.append(Paragraph(
        f"This is a computer-generated Balance Sheet. All amounts in {base_currency}.",
        footer_style,
    ))

    # ========== BUILD ==========
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'balance_sheet_{as_of_date.strftime("%Y%m%d")}.pdf',
        mimetype='application/pdf',
    )

# acctsys/app.py – PDF export of Trial Balance

# acctsys/app.py – Balance Sheet Excel export

@app.route('/balance_sheet/excel')
@login_required
def balance_sheet_excel():
    from datetime import date

    as_of_str = request.args.get('as_of_date')
    try:
        as_of_date = datetime.strptime(as_of_str, '%Y-%m-%d').date() if as_of_str else date.today()
    except ValueError:
        as_of_date = date.today()

    entries = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.date <= as_of_date,
    ).all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(list(account_totals.keys()))
    ).all() if account_totals else []
    accounts_by_id = {a.id: a for a in accounts}

    asset_lines, liability_lines, equity_lines = [], [], []
    total_assets = total_liabilities = total_equity = 0.0
    total_revenue = total_expenses = 0.0

    for account_id, totals in account_totals.items():
        account = accounts_by_id.get(account_id)
        if not account or not account.account_type:
            continue
        at = account.account_type
        balance = (totals['debit'] - totals['credit']) if at.normal_balance == 'Debit' \
                  else (totals['credit'] - totals['debit'])
        if balance == 0:
            continue
        row = {'code': account.account_code, 'name': account.account_name, 'amount': balance}
        nl = at.name.lower()
        if nl in ('asset', 'current asset', 'non-current asset', 'fixed asset',
                  'current assets', 'non-current assets'):
            asset_lines.append(row); total_assets += balance
        elif nl in ('liability', 'current liability', 'non-current liability',
                    'current liabilities', 'non-current liabilities',
                    'payable', 'accounts payable'):
            liability_lines.append(row); total_liabilities += balance
        elif nl in ('equity', "owner's equity", 'capital', 'retained earnings'):
            equity_lines.append(row); total_equity += balance
        elif nl in ('revenue', 'income', 'sales'):
            total_revenue += balance
        elif nl in ('expense', 'expenses', 'cost of sales', 'cogs'):
            total_expenses += balance

    retained_earnings = total_revenue - total_expenses
    total_equity_with_re = total_equity + retained_earnings
    total_liab_eq = total_liabilities + total_equity_with_re

    asset_lines.sort(key=lambda x: x['code'])
    liability_lines.sort(key=lambda x: x['code'])
    equity_lines.sort(key=lambda x: x['code'])

    # ========== BUILD WORKBOOK ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Balance Sheet"

    row = _write_company_header(ws, company, base_currency, symbol)
    row = _write_sheet_title(
        ws, row, "BALANCE SHEET",
        f"As of {as_of_date.strftime('%d %b %Y')}  •  All amounts in {base_currency} ({symbol})"
    )

    def write_section(title, lines, total_label, total_value, header_fill, total_fill):
        nonlocal row
        # Section header
        ws.cell(row=row, column=1, value=title).font = EXCEL_SECTION_FONT
        for c in range(1, 4):
            ws.cell(row=row, column=c).fill = header_fill
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        row += 1

        # Column headers
        for c, h in enumerate(['Code', 'Account', f'Amount ({base_currency})'], start=1):
            cell = ws.cell(row=row, column=c, value=h)
            cell.font = EXCEL_HEADER_FONT
            cell.fill = EXCEL_HEADER_FILL
            cell.alignment = EXCEL_ALIGN_CENTER
        header_row = row
        row += 1

        first_data_row = row
        for line in lines:
            ws.cell(row=row, column=1, value=line['code']).font = EXCEL_NORMAL_FONT
            ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
            ws.cell(row=row, column=2, value=line['name']).font = EXCEL_NORMAL_FONT
            c3 = ws.cell(row=row, column=3, value=line['amount'])
            c3.number_format = f'"{symbol}"#,##0.00'
            c3.font = EXCEL_NORMAL_FONT
            c3.alignment = EXCEL_ALIGN_RIGHT
            row += 1

        if not lines:
            ws.cell(row=row, column=1, value="—").font = EXCEL_NORMAL_FONT
            ws.cell(row=row, column=2, value="None").font = EXCEL_NORMAL_FONT
            c3 = ws.cell(row=row, column=3, value=0)
            c3.number_format = f'"{symbol}"#,##0.00'
            c3.font = EXCEL_NORMAL_FONT
            c3.alignment = EXCEL_ALIGN_RIGHT
            row += 1

        last_data_row = row - 1

        # Total row
        ws.cell(row=row, column=1).fill = total_fill
        ws.cell(row=row, column=2, value=total_label).font = EXCEL_TOTAL_FONT
        ws.cell(row=row, column=2).alignment = EXCEL_ALIGN_RIGHT
        ws.cell(row=row, column=2).fill = total_fill
        c3 = ws.cell(row=row, column=3, value=f"=SUM(C{first_data_row}:C{last_data_row})")
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_TOTAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        c3.fill = total_fill
        total_row = row
        row += 2

        _apply_border(ws, header_row, total_row, 1, 3)
        return total_row

    asset_total_row = write_section("ASSETS", asset_lines, "Total Assets",
                                    total_assets, EXCEL_SECTION_FILL, EXCEL_TOTAL_FILL)
    liab_total_row = write_section("LIABILITIES", liability_lines, "Total Liabilities",
                                   total_liabilities, EXCEL_SECTION_FILL_2, EXCEL_TOTAL_FILL_RED)

    # Equity section (custom because of retained earnings row)
    ws.cell(row=row, column=1, value="EQUITY").font = EXCEL_SECTION_FONT
    for c in range(1, 4):
        ws.cell(row=row, column=c).fill = EXCEL_SECTION_FILL_3
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    row += 1

    for c, h in enumerate(['Code', 'Account', f'Amount ({base_currency})'], start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = EXCEL_HEADER_FONT
        cell.fill = EXCEL_HEADER_FILL
        cell.alignment = EXCEL_ALIGN_CENTER
    eq_header_row = row
    row += 1

    eq_first_data = row
    for line in equity_lines:
        ws.cell(row=row, column=1, value=line['code']).font = EXCEL_NORMAL_FONT
        ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
        ws.cell(row=row, column=2, value=line['name']).font = EXCEL_NORMAL_FONT
        c3 = ws.cell(row=row, column=3, value=line['amount'])
        c3.number_format = f'"{symbol}"#,##0.00'
        c3.font = EXCEL_NORMAL_FONT
        c3.alignment = EXCEL_ALIGN_RIGHT
        row += 1

    # Retained earnings row
    ws.cell(row=row, column=1, value="—").font = EXCEL_NORMAL_FONT
    ws.cell(row=row, column=1).alignment = EXCEL_ALIGN_CENTER
    ws.cell(row=row, column=2,
            value="Retained Earnings (cumulative net profit)").font = EXCEL_NORMAL_FONT
    c3 = ws.cell(row=row, column=3, value=retained_earnings)
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = EXCEL_NORMAL_FONT
    c3.alignment = EXCEL_ALIGN_RIGHT
    row += 1
    eq_last_data = row - 1

    # Total Equity
    ws.cell(row=row, column=1).fill = EXCEL_TOTAL_FILL
    ws.cell(row=row, column=2, value="Total Equity").font = EXCEL_TOTAL_FONT
    ws.cell(row=row, column=2).alignment = EXCEL_ALIGN_RIGHT
    ws.cell(row=row, column=2).fill = EXCEL_TOTAL_FILL
    c3 = ws.cell(row=row, column=3, value=f"=SUM(C{eq_first_data}:C{eq_last_data})")
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = EXCEL_TOTAL_FONT
    c3.alignment = EXCEL_ALIGN_RIGHT
    c3.fill = EXCEL_TOTAL_FILL
    eq_total_row = row
    row += 2

    _apply_border(ws, eq_header_row, eq_total_row, 1, 3)

    # Total Liabilities + Equity
    c1 = ws.cell(row=row, column=1, value="TOTAL LIABILITIES + EQUITY")
    c1.font = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
    c1.alignment = EXCEL_ALIGN_LEFT
    c1.fill = PatternFill('solid', fgColor='34495E')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)

    c3 = ws.cell(row=row, column=3, value=f"=C{liab_total_row}+C{eq_total_row}")
    c3.number_format = f'"{symbol}"#,##0.00'
    c3.font = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
    c3.alignment = EXCEL_ALIGN_RIGHT
    c3.fill = PatternFill('solid', fgColor='34495E')
    liab_eq_row = row
    row += 2

    # Balance check
    diff = total_assets - total_liab_eq
    if abs(diff) < 0.01:
        msg = "✓ Balance Sheet is balanced (Assets = Liabilities + Equity)"
        fill = EXCEL_TOTAL_FILL_GRN
    else:
        msg = f"⚠ Out of balance by {symbol}{abs(diff):,.2f}"
        fill = EXCEL_TOTAL_FILL_RED

    c = ws.cell(row=row, column=1, value=msg)
    c.font = EXCEL_TOTAL_FONT
    c.alignment = EXCEL_ALIGN_CENTER
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    for col in range(1, 4):
        ws.cell(row=row, column=col).fill = fill
    row += 2

    # Footer
    ws.cell(row=row, column=1,
            value=f"This is a computer-generated Balance Sheet. All amounts in {base_currency}."
            ).font = Font(name='Calibri', size=8, italic=True, color='888888')
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)

    _autosize_columns(ws)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f'balance_sheet_{as_of_date.strftime("%Y%m%d")}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

@app.route('/trial_balance/pdf')
@login_required
def trial_balance_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from io import BytesIO
    from datetime import date

    register_unicode_fonts()
    FONT = get_pdf_font(bold=False)
    FONT_BOLD = get_pdf_font(bold=True)

    # ========== PARSE PARAMETERS (same logic as HTML view) ==========
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    mode = request.args.get('mode', 'as_of')

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    start_date = parse_date(start_str)
    end_date = parse_date(end_str)

    # ========== QUERY ENTRIES ==========
    query = JournalEntry.query.filter(JournalEntry.user_id == current_user.id)
    if mode == 'period':
        if start_date:
            query = query.filter(JournalEntry.date >= start_date)
        if end_date:
            query = query.filter(JournalEntry.date <= end_date)
    else:
        cut_off = end_date or start_date
        if cut_off:
            query = query.filter(JournalEntry.date <= cut_off)

    entries = query.all()

    account_totals = {}
    for e in entries:
        account_totals.setdefault(e.account_id, {'debit': 0.0, 'credit': 0.0})
        account_totals[e.account_id]['debit'] += e.debit or 0.0
        account_totals[e.account_id]['credit'] += e.credit or 0.0

    account_ids = list(account_totals.keys())
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.id.in_(account_ids),
        ChartOfAccount.is_active == True,
    ).order_by(ChartOfAccount.account_code).all() if account_ids else []

    trial_balance_data = []
    total_debits = total_credits = 0.0

    for account in accounts:
        totals = account_totals.get(account.id)
        if not totals:
            continue
        at = AccountType.query.get(account.account_type_id)
        if not at:
            continue
        debit = totals['debit']
        credit = totals['credit']
        balance = (debit - credit) if at.normal_balance == 'Debit' else (credit - debit)

        if at.normal_balance == 'Debit':
            d_amt = balance if balance > 0 else 0.0
            c_amt = abs(balance) if balance < 0 else 0.0
        else:
            d_amt = abs(balance) if balance < 0 else 0.0
            c_amt = balance if balance > 0 else 0.0

        total_debits += d_amt
        total_credits += c_amt
        trial_balance_data.append({
            'code': account.account_code,
            'name': account.account_name,
            'type': at.name,
            'debit': d_amt,
            'credit': c_amt,
        })

    # ========== PERIOD LABEL ==========
    if mode == 'period':
        if start_date and end_date:
            period_label = (
                f"For the period {start_date.strftime('%d %b %Y')} – "
                f"{end_date.strftime('%d %b %Y')}"
            )
        elif start_date:
            period_label = f"From {start_date.strftime('%d %b %Y')} onwards"
        elif end_date:
            period_label = f"Up to {end_date.strftime('%d %b %Y')}"
        else:
            period_label = "All periods"
    else:
        cut_off = end_date or start_date
        period_label = f"As of {cut_off.strftime('%d %b %Y')}" if cut_off \
                       else f"As of {date.today().strftime('%d %b %Y')}"

    # ========== COMPANY + CURRENCY ==========
    company = get_company_profile()
    base_currency = get_base_currency()
    symbol = get_base_currency_symbol()

    # ========== PDF SETUP ==========
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title="Trial Balance", author=company['name'],
    )
    elements = []
    styles = getSampleStyleSheet()

    company_name_style = ParagraphStyle(
        'CN', parent=styles['Heading1'], fontSize=18,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=4,
        fontName=FONT_BOLD,
    )
    company_sub_style = ParagraphStyle(
        'CS', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#555555'), alignment=1, spaceAfter=2, leading=12,
        fontName=FONT,
    )
    title_style = ParagraphStyle(
        'T', parent=styles['Heading1'], fontSize=20,
        textColor=colors.HexColor('#2c3e50'), alignment=1, spaceBefore=6, spaceAfter=6,
        fontName=FONT_BOLD,
    )
    period_style = ParagraphStyle(
        'P', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#7f8c8d'), alignment=1, spaceAfter=14,
        fontName=FONT,
    )
    footer_style = ParagraphStyle(
        'F', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1, fontName=FONT,
    )

    # Header
    elements.append(Paragraph(f"<b>{company['name']}</b>", company_name_style))
    if company['address']:
        elements.append(Paragraph(company['address'].replace('\n', ', '), company_sub_style))
    contact_parts = []
    if company['phone']: contact_parts.append(f"Tel: {company['phone']}")
    if company['email']: contact_parts.append(f"Email: {company['email']}")
    if contact_parts:
        elements.append(Paragraph(" • ".join(contact_parts), company_sub_style))

    elements.append(Spacer(1, 8))
    elements.append(Paragraph("TRIAL BALANCE", title_style))
    elements.append(Paragraph(
        f"{period_label}  •  All amounts in {base_currency} ({symbol})",
        period_style,
    ))

    # Table data
    data = [['Code', 'Account Name', 'Type',
             f'Debit ({base_currency})', f'Credit ({base_currency})']]
    for row in trial_balance_data:
        data.append([
            row['code'],
            row['name'],
            row['type'],
            f"{symbol}{row['debit']:,.2f}" if row['debit'] > 0 else '-',
            f"{symbol}{row['credit']:,.2f}" if row['credit'] > 0 else '-',
        ])
    if len(data) == 1:
        data.append(['—', 'No activity in this period', '', '', ''])

    total_label = Paragraph("<b>TOTAL</b>", ParagraphStyle(
        'TL', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, alignment=2,
    ))
    total_debit_para = Paragraph(
        f"<b>{symbol}{total_debits:,.2f}</b>",
        ParagraphStyle('TD', parent=styles['Normal'], fontName=FONT_BOLD,
                       fontSize=9, alignment=2),
    )
    total_credit_para = Paragraph(
        f"<b>{symbol}{total_credits:,.2f}</b>",
        ParagraphStyle('TC', parent=styles['Normal'], fontName=FONT_BOLD,
                       fontSize=9, alignment=2),
    )
    data.append(['', total_label, '', total_debit_para, total_credit_para])

    t = Table(
        data,
        colWidths=[22 * mm, 58 * mm, 25 * mm, 37 * mm, 38 * mm],
        repeatRows=1,
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTNAME', (0, 1), (-1, -2), FONT),
        ('FONTSIZE', (0, 1), (-1, -2), 9),
        ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, len(data) - 1), (-1, len(data) - 1), colors.HexColor('#d6eaf8')),
        ('FONTNAME', (0, len(data) - 1), (-1, len(data) - 1), FONT_BOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 12))

    # Balance check
    diff = total_debits - total_credits
    if abs(diff) < 0.01:
        msg = "✓ Trial balance is in balance (Debits = Credits)"
        msg_color = colors.HexColor('#27ae60')
    else:
        msg = f"⚠ Out of balance by {symbol}{abs(diff):,.2f}"
        msg_color = colors.HexColor('#c0392b')

    elements.append(Paragraph(msg, ParagraphStyle(
        'Bal', parent=styles['Normal'], fontSize=10,
        textColor=msg_color, alignment=1, fontName=FONT_BOLD,
    )))

    elements.append(Spacer(1, 16))
    elements.append(Paragraph(
        f"This is a computer-generated Trial Balance. All amounts in {base_currency}.",
        footer_style,
    ))

    doc.build(elements)
    buffer.seek(0)

    suffix = ""
    if start_date: suffix += f"_{start_date.strftime('%Y%m%d')}"
    if end_date:   suffix += f"_{end_date.strftime('%Y%m%d')}"

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'trial_balance{suffix}.pdf',
        mimetype='application/pdf',
    )

# ============================================================
# ✅ MAIN
# ============================================================

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))