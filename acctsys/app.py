# acctsys/app.py - Final version (no auto-creation of accounts)

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import uuid
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
import sqlite3

from config import config
from extensions import db

# acctsys/app.py – Update imports

from acctsys.models import User, Invoice, Expense, Category, AccountType, ChartOfAccount, GeneralLedger, Supplier, Customer, \
    JournalEntry, Purchase, PurchaseLine,InvoiceLine, PaymentVoucher, PaymentVoucherLine, SystemSetting
from acctsys.forms import (
    LoginForm,
    RegistrationForm,
    InvoiceForm,
    InvoiceEditForm,
    ExpenseForm,
    AccountTypeForm,
    AccountTypeEditForm,
    ChartOfAccountForm,
    ChartOfAccountEditForm,
    SupplierForm,
    SupplierEditForm,
    CustomerForm,
    CustomerEditForm,
    PurchaseForm,
    PurchaseEditForm,
    PaymentVoucherForm,
    PaymentVoucherEditForm
)

# Create Flask app
app = Flask(__name__)

# Apply configuration
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS

# PostgreSQL-specific settings
if hasattr(config, 'SQLALCHEMY_ENGINE_OPTIONS'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = config.SQLALCHEMY_ENGINE_OPTIONS

# Configuration for file uploads
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}

app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Helper function for file uploads
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# GL Posting Helper
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
    else:  # Credit-balance accounts (Liability, Equity, Revenue)
        if is_debit:
            gl_entry.balance -= amount
        else:
            gl_entry.balance += amount

    gl_entry.last_updated = datetime.utcnow()


# Helper to generate the next account code
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
        except:
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
        except:
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
        except:
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
        except:
            next_number = 1
    else:
        next_number = 1
    current_year = datetime.now().year
    return f"PO-{current_year}-{next_number:04d}"


# acctsys/app.py – Helper to get system settings

def get_system_setting(key):
    """Get a system setting by key"""
    setting = SystemSetting.query.filter_by(key=key).first()
    return setting.value if setting else None


def get_ar_account():
    """Get the configured Accounts Receivable account"""
    ar_account_id = get_system_setting('ar_account_id')
    if ar_account_id:
        return ChartOfAccount.query.get(ar_account_id)

    # Fallback: find any Asset account
    return ChartOfAccount.query.filter(
        ChartOfAccount.account_type.has(name='Asset'),
        ChartOfAccount.is_active == True
    ).order_by(ChartOfAccount.account_code).first()


def get_ap_account():
    """Get the configured Accounts Payable account"""
    ap_account_id = get_system_setting('ap_account_id')
    if ap_account_id:
        return ChartOfAccount.query.get(ap_account_id)

    # Fallback: find any Liability account
    return ChartOfAccount.query.filter(
        ChartOfAccount.account_type.has(name='Liability'),
        ChartOfAccount.is_active == True
    ).order_by(ChartOfAccount.account_code).first()


# Initialize database
db.init_app(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Helper function to check if columns exist
def check_columns_exist():
    try:
        db_path = config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            return False, False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart_of_account'")
        if not cursor.fetchone():
            conn.close()
            return False, False

        cursor.execute("PRAGMA table_info(chart_of_account)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()

        has_parent_id = 'parent_id' in columns
        has_is_main_account = 'is_main_account' in columns
        return has_parent_id, has_is_main_account
    except Exception as e:
        print(f"⚠️ Could not check columns: {e}")
        return False, False


def add_missing_columns():
    try:
        db_path = config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            return False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart_of_account'")
        if not cursor.fetchone():
            conn.close()
            return False

        cursor.execute("PRAGMA table_info(chart_of_account)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'parent_id' not in columns:
            try:
                cursor.execute("ALTER TABLE chart_of_account ADD COLUMN parent_id INTEGER REFERENCES chart_of_account(id)")
                print("✅ Added parent_id column")
            except sqlite3.OperationalError as e:
                print(f"⚠️ Could not add parent_id: {e}")

        if 'is_main_account' not in columns:
            try:
                cursor.execute("ALTER TABLE chart_of_account ADD COLUMN is_main_account BOOLEAN DEFAULT 0")
                print("✅ Added is_main_account column")
            except sqlite3.OperationalError as e:
                print(f"⚠️ Could not add is_main_account: {e}")

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Could not add columns: {e}")
        return False


# Create database tables and default data
with app.app_context():
    db.create_all()
    print("✅ Database tables created/verified")

    has_parent_id, has_is_main_account = check_columns_exist()
    if not has_parent_id or not has_is_main_account:
        print("⚠️ Missing columns detected. Adding them now...")
        if add_missing_columns():
            print("✅ Columns added successfully!")
        else:
            print("⚠️ Could not add columns automatically.")
            print("   Please run: python migrate_db.py")

    # Default categories
    if Category.query.count() == 0:
        default_categories = ['Sales', 'Services', 'Products', 'Consulting']
        for cat in default_categories:
            category = Category(name=cat)
            db.session.add(category)
        db.session.commit()
        print("✅ Default categories created")

    # Default Account Types
    asset_type = AccountType.query.filter_by(name='Asset').first()
    liability_type = AccountType.query.filter_by(name='Liability').first()
    expense_type = AccountType.query.filter_by(name='Expense').first()

    if not asset_type:
        asset_type = AccountType(name='Asset', normal_balance='Debit')
        db.session.add(asset_type)
    if not liability_type:
        liability_type = AccountType(name='Liability', normal_balance='Credit')
        db.session.add(liability_type)
    if not expense_type:
        expense_type = AccountType(name='Expense', normal_balance='Debit')
        db.session.add(expense_type)
    db.session.commit()
    print("✅ Default account types created")

    # Define account type ranges
    account_type_ranges = {
        'Asset': (1000, 1999),
        'Liability': (2000, 2999),
        'Equity': (3000, 3999),
        'Revenue': (4000, 4999),
        'Expense': (5000, 5999),
    }

    for name, (min_code, max_code) in account_type_ranges.items():
        at = AccountType.query.filter_by(name=name).first()
        if at:
            at.min_code = min_code
            at.max_code = max_code
            print(f"✅ Updated {name} range: {min_code}–{max_code}")
        else:
            normal_balance = 'Credit' if name in ['Liability', 'Equity', 'Revenue'] else 'Debit'
            at = AccountType(
                name=name,
                normal_balance=normal_balance,
                min_code=min_code,
                max_code=max_code
            )
            db.session.add(at)
            print(f"✅ Created {name} with range: {min_code}–{max_code}")
    db.session.commit()

    # Default Users
    if not User.query.filter_by(email='admin@example.com').first():
        admin_user = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123')
        )
        db.session.add(admin_user)
        db.session.commit()
        print("✅ Default admin user created! (admin/admin123)")
    else:
        print("✅ Default admin user already exists")

    if not User.query.filter_by(email='test@example.com').first():
        test_user = User(
            username='testuser',
            email='test@example.com',
            password_hash=generate_password_hash('Test123!')
        )
        db.session.add(test_user)
        db.session.commit()
        print("✅ Test user created! (testuser/Test123!)")
    else:
        print("✅ Test user already exists")

    print("=" * 60)
    print("✅ Database initialized successfully!")
    print(f"📊 Database: {config.SQLALCHEMY_DATABASE_URI}")
    print(f"👤 Users in database: {User.query.count()}")
    print(f"📁 Accounts in database: {ChartOfAccount.query.count()}")
    print("=" * 60)


# ========== ROUTES ==========

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

        hashed_password = generate_password_hash(form.password.data)
        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=hashed_password
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


# acctsys/app.py – Updated dashboard route

@app.route('/dashboard')
@login_required
def dashboard():
    # Get all invoices for this user
    invoices = Invoice.query.filter_by(user_id=current_user.id).all()

    # Calculate total invoice amount from lines
    total_invoices = 0
    for invoice in invoices:
        invoice_total = db.session.query(db.func.sum(InvoiceLine.total)).filter_by(
            invoice_id=invoice.id
        ).scalar() or 0
        total_invoices += invoice_total

    total_expenses = db.session.query(db.func.sum(Expense.amount)).filter_by(user_id=current_user.id).scalar() or 0
    net_income = total_invoices - total_expenses

    recent_invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.date.desc()).limit(5).all()
    recent_expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).limit(5).all()

    current_month = datetime.now().month
    current_year = datetime.now().year

    # Calculate monthly invoice total
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

    return render_template('dashboard.html',
                           total_invoices=total_invoices,
                           total_expenses=total_expenses,
                           net_income=net_income,
                           recent_invoices=recent_invoices,
                           recent_expenses=recent_expenses,
                           monthly_invoices=monthly_invoices,
                           monthly_expenses=monthly_expenses)

@app.route('/invoices')
@login_required
def invoices():
    invoices = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.date.desc()).all()
    return render_template('invoices.html', invoices=invoices)


# acctsys/app.py – Updated add_invoice route (uses settings)

@app.route('/add_invoice', methods=['GET', 'POST'])
@login_required
def add_invoice():
    form = InvoiceForm()

    # Populate customer choices
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(0, 'Select Customer')] + [(c.id, c.name) for c in customers]

    # Populate line account choices (Revenue accounts)
    revenue_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Revenue')
    ).order_by(ChartOfAccount.account_code).all()

    if not revenue_accounts:
        revenue_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()

    line_account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in revenue_accounts
    ]

    for line in form.lines:
        line.account_id.choices = line_account_choices

    # Auto-generate invoice number
    last_invoice = Invoice.query.filter_by(user_id=current_user.id).order_by(Invoice.id.desc()).first()
    if last_invoice:
        try:
            last_number = int(last_invoice.invoice_number.split('-')[-1])
            new_number = last_number + 1
        except:
            new_number = 1
    else:
        new_number = 1

    current_year = datetime.now().year
    form.invoice_number.data = f"INV-{current_year}-{new_number:04d}"

    # Add one line only on initial GET
    if request.method == 'GET':
        form.lines.append_entry()
        form.lines[-1].account_id.choices = line_account_choices

    # Handle AJAX request for customer data
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

            # Read line data from request.form (since lines are manual HTML inputs)
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

            # 1. Create the Invoice
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

            # 2. Create Invoice Lines
            for line in line_data:
                invoice_line = InvoiceLine(
                    invoice_id=invoice.id,
                    description=line['description'],
                    quantity=line['quantity'],
                    unit_price=line['unit_price'],
                    total=line['total'],
                    account_id=line['account_id']
                )
                db.session.add(invoice_line)

            # 3. ✅ GET AR Account from settings
            ar_account = get_ar_account()
            if not ar_account:
                db.session.rollback()
                flash('Please configure AR account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            from datetime import datetime as dt
            import uuid
            timestamp = dt.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"INV-{timestamp}-{unique_id}"

            # Debit: AR Account (total invoice amount)
            debit_journal = JournalEntry(
                entry_number=entry_number,
                date=invoice.date,
                description=f"Invoice {invoice.invoice_number} - {customer.name if customer else 'Customer'}",
                account_id=ar_account.id,
                debit=total_amount,
                credit=0,
                reference_type='Invoice',
                reference_id=invoice.id,
                user_id=current_user.id
            )
            db.session.add(debit_journal)

            # Credit: Split by each line item's account
            for line in line_data:
                credit_journal = JournalEntry(
                    entry_number=entry_number,
                    date=invoice.date,
                    description=f"Invoice {invoice.invoice_number} - {line['description']}",
                    account_id=line['account_id'],
                    debit=0,
                    credit=line['total'],
                    reference_type='Invoice',
                    reference_id=invoice.id,
                    user_id=current_user.id
                )
                db.session.add(credit_journal)
                post_to_general_ledger(line['account_id'], line['total'], is_debit=False)

            # Post AR to GL
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
        print(f"Form errors: {form.errors}")

    return render_template('add_invoice.html', form=form, revenue_accounts=revenue_accounts)

@app.route('/view_invoice/<int:id>')
@login_required
def view_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices'))
    return render_template('view_invoice.html', invoice=invoice)


@app.route('/download_invoice/<int:id>')
@login_required
def download_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices'))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=1
    )

    elements.append(Paragraph(f"Invoice #{invoice.invoice_number}", title_style))
    elements.append(Spacer(1, 20))

    data = [
        ['Customer:', invoice.customer_name],
        ['Date:', invoice.date.strftime('%Y-%m-%d')],
        ['Amount:', f"${invoice.amount:,.2f}"],
        ['Status:', invoice.status],
        ['Description:', invoice.description or 'N/A']
    ]

    table = Table(data, colWidths=[100, 300])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f'invoice_{invoice.invoice_number}.pdf',
                     mimetype='application/pdf')


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


@app.route('/chart_of_accounts')
@login_required
def chart_of_accounts():
    main_accounts = ChartOfAccount.query.filter_by(
        is_active=True,
        parent_id=None
    ).order_by(ChartOfAccount.account_code).all()
    return render_template('chart_of_accounts.html', accounts=main_accounts)


@app.route('/add_account_type', methods=['GET', 'POST'])
@login_required
def add_account_type():
    form = AccountTypeForm()
    if form.validate_on_submit():
        account_type = AccountType(
            name=form.name.data,
            description=form.description.data,
            normal_balance=form.normal_balance.data,
            min_code=form.min_code.data,
            max_code=form.max_code.data
        )
        db.session.add(account_type)
        db.session.commit()
        flash('Account type added successfully!', 'success')
        return redirect(url_for('account_types'))

    return render_template('add_account_type.html', form=form)


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


@app.route('/purchases')
@login_required
def purchases():
    purchases_list = Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc()).all()
    return render_template('purchases.html', purchases=purchases_list)


# acctsys/app.py – Updated add_purchase route (uses settings)

@app.route('/add_purchase', methods=['GET', 'POST'])
@login_required
def add_purchase():
    form = PurchaseForm()

    # Populate supplier choices
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    form.supplier_id.choices = [(0, 'Select Supplier')] + [
        (s.id, s.name) for s in suppliers
    ]

    # Populate account choices
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(
            AccountType.name.in_(['Asset', 'Expense'])
        )
    ).order_by(ChartOfAccount.account_code).all()

    if not accounts:
        accounts = ChartOfAccount.query.filter_by(
            is_active=True
        ).order_by(ChartOfAccount.account_code).all()

    # Populate line account choices
    account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in accounts
    ]

    for line in form.lines:
        line.account_id.choices = account_choices

    # Auto-generate purchase number
    form.purchase_number.data = generate_next_purchase_number()

    # Add one line only on initial GET
    if request.method == 'GET':
        form.lines.append_entry()
        form.lines[-1].account_id.choices = account_choices

    if form.validate_on_submit():
        try:
            supplier = Supplier.query.get(form.supplier_id.data)

            # Read line data from request.form
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

            # 1. Create the Purchase
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

            # 2. Create Purchase Lines
            for line in line_data:
                purchase_line = PurchaseLine(
                    purchase_id=purchase.id,
                    description=line['description'],
                    quantity=line['quantity'],
                    unit_price=line['unit_price'],
                    total=line['total'],
                    account_id=line['account_id']
                )
                db.session.add(purchase_line)

            # 3. Update Supplier Balance
            if supplier:
                supplier.current_balance += total_amount

            # 4. ✅ GET AP Account from settings
            ap_account = get_ap_account()
            if not ap_account:
                db.session.rollback()
                flash('Please configure AP account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            from datetime import datetime as dt
            import uuid
            timestamp = dt.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"PUR-{timestamp}-{unique_id}"

            # Credit: AP Account (total amount)
            credit_journal = JournalEntry(
                entry_number=entry_number,
                date=purchase.date,
                description=f"Purchase {purchase.purchase_number} - {supplier.name if supplier else ''}",
                account_id=ap_account.id,
                debit=0,
                credit=total_amount,
                reference_type='Purchase',
                reference_id=purchase.id,
                user_id=current_user.id
            )
            db.session.add(credit_journal)

            # Debit: Split by each line item's account
            for line in line_data:
                debit_journal = JournalEntry(
                    entry_number=entry_number,
                    date=purchase.date,
                    description=f"Purchase {purchase.purchase_number} - {line['description']}",
                    account_id=line['account_id'],
                    debit=line['total'],
                    credit=0,
                    reference_type='Purchase',
                    reference_id=purchase.id,
                    user_id=current_user.id
                )
                db.session.add(debit_journal)
                post_to_general_ledger(line['account_id'], line['total'], is_debit=True)

            # Post AP to GL
            post_to_general_ledger(ap_account.id, total_amount, is_debit=False)

            db.session.commit()
            flash(f'Purchase {purchase.purchase_number} added successfully with {len(line_data)} line(s)!', 'success')
            return redirect(url_for('purchases'))

        except Exception as e:
            db.session.rollback()
            print(f"Error adding purchase: {e}")
            flash(f'Error adding purchase: {str(e)}', 'danger')

    elif request.method == 'POST':
        print("Purchase form validation failed:")
        print(form.errors)

        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return render_template(
        'add_purchase.html',
        form=form,
        accounts=accounts
    )

@app.route('/trial_balance')
@login_required
def trial_balance():
    gl_entries = GeneralLedger.query.join(ChartOfAccount).filter(
        ChartOfAccount.is_active == True
    ).all()

    trial_balance_data = []
    total_debits = 0
    total_credits = 0

    for gl in gl_entries:
        account = gl.account
        account_type = AccountType.query.get(account.account_type_id)
        balance = gl.balance

        if account_type:
            if account_type.normal_balance == 'Credit':
                if balance > 0:
                    total_credits += balance
                    debit_amount = 0
                    credit_amount = balance
                else:
                    total_debits += abs(balance)
                    debit_amount = abs(balance)
                    credit_amount = 0
            else:
                if balance > 0:
                    total_debits += balance
                    debit_amount = balance
                    credit_amount = 0
                else:
                    total_credits += abs(balance)
                    debit_amount = 0
                    credit_amount = abs(balance)
        else:
            debit_amount = 0
            credit_amount = 0

        trial_balance_data.append({
            'account_code': account.account_code,
            'account_name': account.account_name,
            'account_type': account_type.name if account_type else 'N/A',
            'debit': debit_amount,
            'credit': credit_amount
        })

    return render_template('trial_balance.html',
                           trial_balance=trial_balance_data,
                           total_debits=total_debits,
                           total_credits=total_credits,
                           datetime=datetime)


@app.route('/journal_entries')
@login_required
def journal_entries():
    entries = JournalEntry.query.filter(
        JournalEntry.user_id == current_user.id,
        JournalEntry.reference_type == 'Manual Entry'
    ).order_by(JournalEntry.date.desc(), JournalEntry.entry_number.desc()).all()

    grouped_entries = {}
    for entry in entries:
        if entry.entry_number not in grouped_entries:
            grouped_entries[entry.entry_number] = []
        grouped_entries[entry.entry_number].append(entry)

    return render_template('journal_entries.html', grouped_entries=grouped_entries)


@app.route('/add_journal_entry', methods=['GET', 'POST'])
@login_required
def add_journal_entry():
    from datetime import datetime as dt
    import uuid

    accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()
    accounts_serializable = [{'id': a.id, 'account_code': a.account_code, 'account_name': a.account_name} for a in
                             accounts]

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
                return render_template('add_journal_entry.html', accounts=accounts, accounts_json=accounts_serializable,
                                       entry_count=entry_count, datetime=dt)

            timestamp = dt.now().strftime('%Y%m%d%H%M%S')
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

                debit_journal = JournalEntry(
                    entry_number=entry_number,
                    date=dt.strptime(entry_data['date'], '%Y-%m-%d').date(),
                    description=entry_data['description'],
                    account_id=entry_data['debit_account_id'],
                    debit=entry_data['amount'],
                    credit=0,
                    attachment_filename=attachment_filename,
                    attachment_original_name=attachment_original_name,
                    reference_type='Manual Entry',
                    user_id=current_user.id
                )
                db.session.add(debit_journal)

                credit_journal = JournalEntry(
                    entry_number=entry_number,
                    date=dt.strptime(entry_data['date'], '%Y-%m-%d').date(),
                    description=entry_data['description'],
                    account_id=entry_data['credit_account_id'],
                    debit=0,
                    credit=entry_data['amount'],
                    attachment_filename=attachment_filename,
                    attachment_original_name=attachment_original_name,
                    reference_type='Manual Entry',
                    user_id=current_user.id
                )
                db.session.add(credit_journal)

                post_to_general_ledger(entry_data['debit_account_id'], entry_data['amount'], is_debit=True)
                post_to_general_ledger(entry_data['credit_account_id'], entry_data['amount'], is_debit=False)

            db.session.commit()
            flash(f'Journal entry created successfully with {len(entries_data)} transaction(s)!', 'success')
            return redirect(url_for('journal_entries'))

        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}")
            flash(f'Error creating journal entry: {str(e)}', 'danger')
            return render_template('add_journal_entry.html', accounts=accounts, accounts_json=accounts_serializable,
                                   entry_count=entry_count, datetime=dt)

    return render_template('add_journal_entry.html', accounts=accounts, accounts_json=accounts_serializable,
                           entry_count=1, datetime=datetime)


@app.route('/view_journal_entry/<entry_number>')
@login_required
def view_journal_entry(entry_number):
    entries = JournalEntry.query.filter_by(entry_number=entry_number, user_id=current_user.id).order_by(
        JournalEntry.id).all()
    if not entries:
        flash('Journal entry not found', 'danger')
        return redirect(url_for('journal_entries'))

    total_debits = sum(e.debit for e in entries)
    total_credits = sum(e.credit for e in entries)

    return render_template('view_journal_entry.html', entries=entries, entry_number=entry_number,
                           total_debits=total_debits, total_credits=total_credits)


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


@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')


# Payment Voucher Routes
@app.route('/payment_vouchers')
@login_required
def payment_vouchers():
    vouchers = PaymentVoucher.query.filter_by(user_id=current_user.id).order_by(PaymentVoucher.date.desc()).all()
    return render_template('payment_vouchers.html', vouchers=vouchers)

# acctsys/app.py – Updated add_payment_voucher route with debugging

@app.route('/add_payment_voucher', methods=['GET', 'POST'])
@login_required
def add_payment_voucher():
    from datetime import datetime as dt
    import uuid

    form = PaymentVoucherForm()

    # Populate supplier choices
    suppliers = Supplier.query.filter_by(is_active=True).all()
    form.supplier_id.choices = [(0, 'Select Supplier')] + [(s.id, s.name) for s in suppliers]

    # Populate payment account choices (Asset accounts)
    payment_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Asset')
    ).order_by(ChartOfAccount.account_code).all()

    if not payment_accounts:
        payment_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()

    form.payment_account_id.choices = [(0, 'Select Payment Account')] + [(a.id, f"{a.account_code} - {a.account_name}") for a in payment_accounts]

    if request.method == 'POST':
        try:
            entry_count = int(request.form.get('entry_count', 1))
            lines = []
            total_gross = 0
            total_wht = 0
            total_vat = 0
            total_net = 0

            # Collect all line items from the form
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

            # Generate voucher number
            voucher_number = f"PV-{dt.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            # Handle file attachment
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

            # 1. Create the main voucher
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

            # Save each line item
            for line in lines:
                voucher_line = PaymentVoucherLine(
                    payment_voucher_id=voucher.id,
                    description=line['description'],
                    wht_rate=line['wht_rate'],
                    vat_rate=line['vat_rate'],
                    gross_amount=line['gross_amount'],
                    wht_amount=line['wht_amount'],
                    vat_amount=line['vat_amount'],
                    net_amount=line['net_amount']
                )
                db.session.add(voucher_line)

            # ✅ GET AP Account from settings
            ap_account = get_ap_account()
            if not ap_account:
                db.session.rollback()
                flash('Please configure AP account in System Settings.', 'danger')
                return redirect(url_for('settings'))

            # Get selected payment account (Cash/Bank)
            payment_account = ChartOfAccount.query.get(form.payment_account_id.data)
            if not payment_account:
                db.session.rollback()
                flash('Please select a valid payment account.', 'danger')
                return redirect(url_for('add_payment_voucher'))

            # Generate unique entry number
            timestamp = dt.now().strftime('%Y%m%d%H%M%S')
            unique_id = uuid.uuid4().hex[:8].upper()
            entry_number = f"PV-{timestamp}-{unique_id}"

            # Debit: AP Account
            debit_journal = JournalEntry(
                entry_number=entry_number,
                date=voucher.date,
                description=f"Payment Voucher {voucher.voucher_number} - {voucher.supplier.name}",
                account_id=ap_account.id,
                debit=voucher.net_amount,
                credit=0,
                reference_type='Payment Voucher',
                reference_id=voucher.id,
                user_id=current_user.id
            )
            db.session.add(debit_journal)

            # Credit: Payment Account (Cash/Bank)
            credit_journal = JournalEntry(
                entry_number=entry_number,
                date=voucher.date,
                description=f"Payment Voucher {voucher.voucher_number} - {voucher.supplier.name}",
                account_id=payment_account.id,
                debit=0,
                credit=voucher.net_amount,
                reference_type='Payment Voucher',
                reference_id=voucher.id,
                user_id=current_user.id
            )
            db.session.add(credit_journal)

            # ✅ 5. Post to General Ledger
            post_to_general_ledger(ap_account.id, voucher.net_amount, is_debit=True)
            post_to_general_ledger(payment_account.id, voucher.net_amount, is_debit=False)

            # ✅ 6. Reduce supplier balance
            supplier = Supplier.query.get(form.supplier_id.data)
            if supplier:
                supplier.current_balance -= voucher.net_amount

            db.session.commit()
            flash(f'Payment Voucher {voucher_number} created successfully! Journal entry and GL posted.', 'success')
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

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=15 * mm,
                            rightMargin=15 * mm)
    elements = []

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16,
                                 textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=20)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=12,
                                   textColor=colors.HexColor('#34495e'), alignment=0, spaceAfter=10, spaceBefore=15)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=9, spaceAfter=4)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Bold', spaceAfter=4)

    elements.append(Paragraph("PAYMENT VOUCHER", title_style))
    elements.append(Spacer(1, 5))

    header_data = [
        [Paragraph("<b>Voucher No:</b>", label_style), voucher.voucher_number, Paragraph("<b>Date:</b>", label_style),
         voucher.date.strftime('%d-%m-%Y')],
        [Paragraph("<b>Reference:</b>", label_style), voucher.reference_number or 'N/A',
         Paragraph("<b>Status:</b>", label_style), voucher.status],
    ]
    header_table = Table(header_data, colWidths=[35 * mm, 55 * mm, 30 * mm, 50 * mm])
    header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 15))

    info_data = [
        [Paragraph("<b>SUPPLIER INFORMATION</b>", label_style), Paragraph("<b>ACCOUNT INFORMATION</b>", label_style)],
        [f"Name: {voucher.supplier.name}",
         f"Payment Account: {voucher.payment_account.account_code} - {voucher.payment_account.account_name}"],
        [f"Email: {voucher.supplier.email or 'N/A'}", f"Debit Account (Auto): Accounts Payable - Trade"],
        [f"Phone: {voucher.supplier.phone or 'N/A'}", f"Currency: {voucher.currency} (Rate: {voucher.exchange_rate})"],
    ]
    info_table = Table(info_data, colWidths=[85 * mm, 85 * mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("PAYMENT LINE ITEMS", section_style))

    line_data = [['#', 'Description', 'WHT %', 'VAT %', 'Gross', 'WHT', 'VAT', 'Net']]
    for idx, line in enumerate(voucher.lines, 1):
        line_data.append([
            str(idx),
            line.description[:40] + '...' if len(line.description) > 40 else line.description,
            f"{line.wht_rate:.2f}%",
            f"{line.vat_rate:.2f}%",
            f"{voucher.currency} {line.gross_amount:,.2f}",
            f"({voucher.currency} {line.wht_amount:,.2f})",
            f"{voucher.currency} {line.vat_amount:,.2f}",
            f"{voucher.currency} {line.net_amount:,.2f}"
        ])

    line_data.append([
        '', Paragraph("<b>TOTAL</b>", normal_style), '', '',
        Paragraph(f"<b>{voucher.currency} {voucher.gross_amount:,.2f}</b>", normal_style),
        Paragraph(f"<b>({voucher.currency} {voucher.wht_amount:,.2f})</b>", normal_style),
        Paragraph(f"<b>{voucher.currency} {voucher.vat_amount:,.2f}</b>", normal_style),
        Paragraph(f"<b>{voucher.currency} {voucher.net_amount:,.2f}</b>", normal_style)
    ])

    line_table = Table(line_data, colWidths=[10 * mm, 55 * mm, 15 * mm, 15 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'), ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 8), ('ALIGN', (2, 1), (7, -2), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, len(line_data) - 1), (-1, len(line_data) - 1), colors.HexColor('#e8f4f8')),
        ('FONTNAME', (0, len(line_data) - 1), (-1, len(line_data) - 1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 10))

    summary_data = [
        ['Total Gross Amount:', f"{voucher.currency} {voucher.gross_amount:,.2f}"],
        ['Less: WHT Amount:', f"({voucher.currency} {voucher.wht_amount:,.2f})"],
        ['Add: VAT Amount:', f"{voucher.currency} {voucher.vat_amount:,.2f}"],
        ['NET PAYMENT AMOUNT:', f"{voucher.currency} {voucher.net_amount:,.2f}"]
    ]
    summary_table = Table(summary_data, colWidths=[100 * mm, 70 * mm])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#e8f4f8')),
        ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'), ('TEXTCOLOR', (0, 3), (-1, 3), colors.HexColor('#2c3e50')),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 15))

    def number_to_words(amount):
        return f"{amount:,.2f} only"

    elements.append(Paragraph(f"Amount in Words: {number_to_words(voucher.net_amount)}", normal_style))
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("APPROVALS", section_style))

    approval_data = [
        ['', '', '', ''],
        ['PREPARED BY', 'CHECKED BY', 'APPROVED BY', 'RECEIVED BY'],
        ['', '', '', ''],
        ['Name: _______________', 'Name: _______________', 'Name: _______________', 'Name: _______________'],
        ['Signature: __________', 'Signature: __________', 'Signature: __________', 'Signature: __________'],
        ['Date: _______________', 'Date: _______________', 'Date: _______________', 'Date: _______________'],
    ]

    approval_table = Table(approval_data, colWidths=[42.5 * mm, 42.5 * mm, 42.5 * mm, 42.5 * mm])
    approval_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#2c3e50')), ('TEXTCOLOR', (0, 1), (-1, 1), colors.white),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'), ('FONTSIZE', (0, 1), (-1, 1), 10),
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'), ('FONTSIZE', (0, 3), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(approval_table)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("This is a computer-generated document.",
                              ParagraphStyle('Footer', parent=normal_style, textColor=colors.grey, alignment=1,
                                             fontSize=8)))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f'payment_voucher_{voucher.voucher_number}.pdf',
                     mimetype='application/pdf')


# acctsys/app.py – Updated financial_data route

@app.route('/api/financial_data')
@login_required
def financial_data():
    report_type = request.args.get('type', 'monthly')
    year = request.args.get('year', datetime.now().year)

    if report_type == 'monthly':
        monthly_data = []
        for month in range(1, 13):
            # Get invoices for this month
            invoices = Invoice.query.filter(
                Invoice.user_id == current_user.id,
                db.extract('month', Invoice.date) == month,
                db.extract('year', Invoice.date) == year
            ).all()

            # Calculate invoice total from lines
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
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


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

        deleted_ids = []
        skipped_ids = []
        skipped_names = []
        error_messages = []

        for account in accounts_to_delete:
            try:
                journal_count = JournalEntry.query.filter_by(account_id=account.id).count()
                sub_account_count = ChartOfAccount.query.filter_by(parent_id=account.id).count()

                if journal_count > 0:
                    skipped_ids.append(account.id)
                    skipped_names.append(account.account_name)
                    error_messages.append(f"Account '{account.account_name}' has {journal_count} journal entries")
                    continue

                if sub_account_count > 0:
                    skipped_ids.append(account.id)
                    skipped_names.append(account.account_name)
                    error_messages.append(f"Account '{account.account_name}' has {sub_account_count} sub-account(s)")
                    continue

                db.session.delete(account)
                deleted_ids.append(account.id)

            except Exception as e:
                skipped_ids.append(account.id)
                skipped_names.append(account.account_name)
                error_messages.append(f"Account '{account.account_name}': {str(e)}")

        db.session.commit()

        message = f'Successfully deleted {len(deleted_ids)} account(s)'
        if skipped_ids:
            message += f'. {len(skipped_ids)} account(s) could not be deleted:'
            for error in error_messages:
                message += f'\n- {error}'

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'skipped_names': skipped_names,
            'error_messages': error_messages,
            'message': message
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
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

        return jsonify({
            'success': True,
            'message': f'Account "{account.account_name}" deleted successfully.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


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

        customers_to_delete = Customer.query.filter(
            Customer.id.in_(customer_ids)
        ).all()

        if not customers_to_delete:
            return jsonify({'success': False, 'message': 'No matching customers found'}), 404

        deleted_ids = []
        skipped_ids = []
        skipped_names = []
        error_messages = []

        for customer in customers_to_delete:
            try:
                invoice_count = Invoice.query.filter_by(customer_name=customer.name).count()

                if invoice_count > 0:
                    skipped_ids.append(customer.id)
                    skipped_names.append(customer.name)
                    error_messages.append(f"Customer '{customer.name}' has {invoice_count} invoice(s)")
                    continue

                db.session.delete(customer)
                deleted_ids.append(customer.id)

            except Exception as e:
                skipped_ids.append(customer.id)
                skipped_names.append(customer.name)
                error_messages.append(f"Customer '{customer.name}': {str(e)}")

        db.session.commit()

        message = f'Successfully deleted {len(deleted_ids)} customer(s)'
        if skipped_ids:
            message += f'. {len(skipped_ids)} customer(s) could not be deleted:'
            for error in error_messages:
                message += f'\n- {error}'

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'skipped_names': skipped_names,
            'error_messages': error_messages,
            'message': message
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_customer/<int:customer_id>', methods=['POST'])
@login_required
def delete_customer(customer_id):
    try:
        customer = Customer.query.get_or_404(customer_id)
        invoice_count = Invoice.query.filter_by(customer_name=customer.name).count()

        if invoice_count > 0:
            return jsonify({
                'success': False,
                'message': f'Customer "{customer.name}" has {invoice_count} invoice(s) and cannot be deleted.'
            }), 400

        db.session.delete(customer)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Customer "{customer.name}" deleted successfully.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


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

        suppliers_to_delete = Supplier.query.filter(
            Supplier.id.in_(supplier_ids)
        ).all()

        if not suppliers_to_delete:
            return jsonify({'success': False, 'message': 'No matching suppliers found'}), 404

        deleted_ids = []
        skipped_ids = []
        skipped_names = []
        error_messages = []

        for supplier in suppliers_to_delete:
            try:
                purchase_count = Purchase.query.filter_by(supplier_id=supplier.id).count()
                payment_voucher_count = PaymentVoucher.query.filter_by(supplier_id=supplier.id).count()

                if purchase_count > 0:
                    skipped_ids.append(supplier.id)
                    skipped_names.append(supplier.name)
                    error_messages.append(f"Supplier '{supplier.name}' has {purchase_count} purchase(s)")
                    continue

                if payment_voucher_count > 0:
                    skipped_ids.append(supplier.id)
                    skipped_names.append(supplier.name)
                    error_messages.append(f"Supplier '{supplier.name}' has {payment_voucher_count} payment voucher(s)")
                    continue

                db.session.delete(supplier)
                deleted_ids.append(supplier.id)

            except Exception as e:
                skipped_ids.append(supplier.id)
                skipped_names.append(supplier.name)
                error_messages.append(f"Supplier '{supplier.name}': {str(e)}")

        db.session.commit()

        message = f'Successfully deleted {len(deleted_ids)} supplier(s)'
        if skipped_ids:
            message += f'. {len(skipped_ids)} supplier(s) could not be deleted:'
            for error in error_messages:
                message += f'\n- {error}'

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'skipped_names': skipped_names,
            'error_messages': error_messages,
            'message': message
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/delete_supplier/<int:supplier_id>', methods=['POST'])
@login_required
def delete_supplier(supplier_id):
    try:
        supplier = Supplier.query.get_or_404(supplier_id)
        purchase_count = Purchase.query.filter_by(supplier_id=supplier.id).count()
        payment_voucher_count = PaymentVoucher.query.filter_by(supplier_id=supplier.id).count()

        if purchase_count > 0:
            return jsonify({
                'success': False,
                'message': f'Supplier "{supplier.name}" has {purchase_count} purchase(s) and cannot be deleted.'
            }), 400

        if payment_voucher_count > 0:
            return jsonify({
                'success': False,
                'message': f'Supplier "{supplier.name}" has {payment_voucher_count} payment voucher(s) and cannot be deleted.'
            }), 400

        db.session.delete(supplier)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Supplier "{supplier.name}" deleted successfully.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


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
        revenue_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()

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

        old_amount = invoice.amount
        old_account_id = invoice.account_id

        invoice.invoice_number = form.invoice_number.data
        invoice.customer_id = form.customer_id.data
        invoice.customer_name = customer.name if customer else ''
        invoice.amount = form.amount.data
        invoice.date = form.date.data
        invoice.status = form.status.data
        invoice.description = form.description.data
        invoice.account_id = form.account_id.data

        journal_entry_number = f"INV-{invoice.id}"
        journal_entries = JournalEntry.query.filter_by(
            entry_number=journal_entry_number,
            user_id=current_user.id
        ).all()

        if journal_entries:
            ar_account = ChartOfAccount.query.filter_by(account_code='1200').first()
            old_revenue_account = ChartOfAccount.query.get(old_account_id)

            if ar_account and old_revenue_account:
                for je in journal_entries:
                    if je.debit > 0:
                        ar_account.balance -= old_amount
                    elif je.credit > 0:
                        old_revenue_account.balance += old_amount

            for je in journal_entries:
                db.session.delete(je)

        ar_account = ChartOfAccount.query.filter_by(account_code='1200').first()
        if not ar_account:
            flash('Accounts Receivable account (1200) not found. Please create it first.', 'danger')
            return redirect(url_for('chart_of_accounts'))

        journal_entry_number = f"INV-{invoice.id}"

        debit_journal = JournalEntry(
            entry_number=journal_entry_number,
            date=invoice.date,
            description=f"Invoice {invoice.invoice_number} - {customer.name if customer else 'Customer'}",
            account_id=ar_account.id,
            debit=invoice.amount,
            credit=0,
            reference_type='Invoice',
            reference_id=invoice.id,
            user_id=current_user.id
        )
        db.session.add(debit_journal)

        credit_journal = JournalEntry(
            entry_number=journal_entry_number,
            date=invoice.date,
            description=f"Invoice {invoice.invoice_number} - {customer.name if customer else 'Customer'}",
            account_id=account.id,
            debit=0,
            credit=invoice.amount,
            reference_type='Invoice',
            reference_id=invoice.id,
            user_id=current_user.id
        )
        db.session.add(credit_journal)

        ar_account.balance += invoice.amount
        account.balance -= invoice.amount

        db.session.commit()
        flash(f'Invoice {invoice.invoice_number} updated successfully! Journal entry updated.', 'success')
        return redirect(url_for('invoices'))

    return render_template('edit_invoice.html', form=form, invoice=invoice)


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
            'message': f'Successfully updated {updated_count} invoice(s).' + (' Errors: ' + '; '.join(errors) if errors else '')
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
        deleted_invoice_numbers = []
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
                deleted_invoice_numbers.append(invoice.invoice_number)

            except Exception as e:
                print(f"Error deleting invoice {invoice.id}: {e}")
                continue

        db.session.commit()

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'deleted_invoice_numbers': deleted_invoice_numbers,
            'reversed_gl_count': reversed_gl_count,
            'message': f'Successfully deleted {len(deleted_ids)} invoice(s) and reversed {reversed_gl_count} GL posting(s).'
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


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

        deleted_ids = []
        skipped_ids = []
        skipped_names = []
        error_messages = []

        for account_type in account_types_to_delete:
            try:
                account_count = ChartOfAccount.query.filter_by(account_type_id=account_type.id).count()

                if account_count > 0:
                    skipped_ids.append(account_type.id)
                    skipped_names.append(account_type.name)
                    error_messages.append(f"Account Type '{account_type.name}' is used by {account_count} account(s)")
                    continue

                db.session.delete(account_type)
                deleted_ids.append(account_type.id)

            except Exception as e:
                skipped_ids.append(account_type.id)
                skipped_names.append(account_type.name)
                error_messages.append(f"Account Type '{account_type.name}': {str(e)}")

        db.session.commit()

        message = f'Successfully deleted {len(deleted_ids)} account type(s)'
        if skipped_ids:
            message += f'. {len(skipped_ids)} account type(s) could not be deleted:'
            for error in error_messages:
                message += f'\n- {error}'

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_count': len(skipped_ids),
            'skipped_ids': skipped_ids,
            'skipped_names': skipped_names,
            'error_messages': error_messages,
            'message': message
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# acctsys/app.py – Updated edit_purchase route

@app.route('/edit_purchase/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    if purchase.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('purchases'))

    form = PurchaseEditForm(obj=purchase)
    form.original_purchase_number = purchase.purchase_number

    # Populate supplier choices
    form.supplier_id.choices = [(0, 'Select Supplier')] + [(s.id, s.name) for s in
                                                           Supplier.query.filter_by(is_active=True).all()]

    # Populate account choices (for line items)
    accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(AccountType.name.in_(['Asset', 'Expense']))
    ).order_by(ChartOfAccount.account_code).all()

    if not accounts:
        accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()

    # Populate line account choices
    account_choices = [(0, 'Select Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in accounts
    ]

    for line in form.lines:
        line.account_id.choices = account_choices

    # ❌ REMOVE: form.account_id.choices = [...]

    if form.validate_on_submit():
        # Update purchase details
        purchase.purchase_number = form.purchase_number.data
        purchase.supplier_id = form.supplier_id.data
        purchase.invoice_number = form.invoice_number.data
        purchase.date = form.date.data
        purchase.due_date = form.due_date.data
        purchase.status = form.status.data

        # Read line data from request.form
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

        # Calculate total
        total_amount = sum(line['total'] for line in line_data)
        purchase.amount = total_amount

        # Delete existing lines
        PurchaseLine.query.filter_by(purchase_id=purchase.id).delete()

        # Create new lines
        for line in line_data:
            purchase_line = PurchaseLine(
                purchase_id=purchase.id,
                description=line['description'],
                quantity=line['quantity'],
                unit_price=line['unit_price'],
                total=line['total'],
                account_id=line['account_id']
            )
            db.session.add(purchase_line)

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

        deleted_ids = []
        reversed_gl_count = 0

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
            'message': f'Successfully deleted {len(deleted_ids)} purchase(s) and reversed {reversed_gl_count} GL posting(s).'
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/get_sub_accounts/<int:parent_id>')
@login_required
def get_sub_accounts(parent_id):
    sub_accounts = ChartOfAccount.query.filter_by(
        parent_id=parent_id,
        is_active=True
    ).order_by(ChartOfAccount.account_code).all()

    data = []
    for acc in sub_accounts:
        data.append({
            'id': acc.id,
            'account_code': acc.account_code,
            'account_name': acc.account_name,
            'account_type_name': acc.account_type.name if acc.account_type else 'N/A',
            'parent_name': acc.parent.account_name if acc.parent else None,
            'parent_code': acc.parent.account_code if acc.parent else None,
            'balance': acc.balance,
            'is_active': acc.is_active,
            'is_main_account': acc.is_main_account
        })

    return jsonify({'sub_accounts': data})


# acctsys/app.py – Updated add_account route

@app.route('/add_account', methods=['GET', 'POST'])
@login_required
def add_account():
    form = ChartOfAccountForm()
    form.account_type_id.choices = [(t.id, t.name) for t in AccountType.query.all()]

    all_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()
    form.parent_id.choices = [(0, 'None - This is a Main Account')] + [
        (a.id, f"{a.account_code} - {a.account_name}") for a in all_accounts
    ]

    if form.validate_on_submit():
        # ✅ Auto-generate account code if field is empty
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
                journal = JournalEntry(
                    entry_number=f"OPEN-{account.account_code}",
                    date=datetime.now().date(),
                    description=f"Opening balance for {account.account_name}",
                    account_id=account.id,
                    debit=form.opening_balance.data if account_type.normal_balance == 'Debit' else 0,
                    credit=form.opening_balance.data if account_type.normal_balance == 'Credit' else 0,
                    reference_type='Opening Balance',
                    user_id=current_user.id
                )
                db.session.add(journal)
                db.session.commit()

        flash(f'Account "{account.account_name}" added successfully! Code: {account.account_code}', 'success')
        return redirect(url_for('chart_of_accounts'))

    return render_template('add_account.html', form=form)

@app.route('/get_next_account_code/<int:account_type_id>')
@login_required
def get_next_account_code(account_type_id):
    next_code = generate_next_account_code(account_type_id)
    if next_code:
        return jsonify({'success': True, 'next_code': next_code})
    return jsonify({'success': False})


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

    payment_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(AccountType.name == 'Asset')
    ).order_by(ChartOfAccount.account_code).all()

    if not payment_accounts:
        payment_accounts = ChartOfAccount.query.filter_by(is_active=True).order_by(ChartOfAccount.account_code).all()

    form.payment_account_id.choices = [(0, 'Select Payment Account')] + [(a.id, f"{a.account_code} - {a.account_name}") for a in payment_accounts]

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

        deleted_ids = []
        reversed_gl_count = 0

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
            'message': f'Successfully deleted {len(deleted_ids)} payment voucher(s) and reversed {reversed_gl_count} GL posting(s).'
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


@app.route('/account_types')
@login_required
def account_types():
    account_types = AccountType.query.all()
    return render_template('account_types.html', account_types=account_types)


# acctsys/app.py – Updated settings route

@app.route('/settings')
@login_required
def settings():
    # Get asset accounts (for AR)
    asset_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Asset')
    ).order_by(ChartOfAccount.account_code).all()

    # Get liability accounts (for AP)
    liability_accounts = ChartOfAccount.query.filter(
        ChartOfAccount.is_active == True,
        ChartOfAccount.account_type.has(name='Liability')
    ).order_by(ChartOfAccount.account_code).all()

    # Get current settings
    ar_setting = SystemSetting.query.filter_by(key='ar_account_id').first()
    ap_setting = SystemSetting.query.filter_by(key='ap_account_id').first()

    settings = {
        'ar_account_id': ar_setting.value if ar_setting else None,
        'ap_account_id': ap_setting.value if ap_setting else None
    }

    return render_template('settings.html',
                           asset_accounts=asset_accounts,
                           liability_accounts=liability_accounts,
                           settings=settings,
                           csrf_token=generate_csrf())  # ✅ Add this

@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    ar_account_id = request.form.get('ar_account_id')
    ap_account_id = request.form.get('ap_account_id')

    # Save AR account setting
    ar_setting = SystemSetting.query.filter_by(key='ar_account_id').first()
    if ar_setting:
        ar_setting.value = int(ar_account_id)
    else:
        ar_setting = SystemSetting(
            key='ar_account_id',
            value=int(ar_account_id),
            description='Accounts Receivable account for invoices'
        )
        db.session.add(ar_setting)

    # Save AP account setting
    ap_setting = SystemSetting.query.filter_by(key='ap_account_id').first()
    if ap_setting:
        ap_setting.value = int(ap_account_id)
    else:
        ap_setting = SystemSetting(
            key='ap_account_id',
            value=int(ap_account_id),
            description='Accounts Payable account for purchases and payment vouchers'
        )
        db.session.add(ap_setting)

    db.session.commit()
    flash('Settings saved successfully!', 'success')
    return redirect(url_for('settings'))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))