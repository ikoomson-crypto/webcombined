from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import pandas as pd
import os
import json
from werkzeug.utils import secure_filename
import uuid
from pathlib import Path
import tempfile
import re
from dateutil.relativedelta import relativedelta
from flask_migrate import Migrate

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# ============ DATABASE CONFIGURATION ============
# Check if we're on Render (production) or local
if os.environ.get('DATABASE_URL'):
    # Use PostgreSQL on Render
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print(f"Using PostgreSQL database on Render")
else:
    # Use SQLite locally
    def get_database_path():
        # Store database in the project folder
        project_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        db_file = project_dir / 'payment_system.db'
        return str(db_file.absolute())

    database_path = get_database_path()
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{database_path}'
    print(f"Using SQLite database at: {database_path}")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ============ FOLDER CONFIGURATION ============
base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
app.config['UPLOAD_FOLDER'] = str(base_dir / 'uploads')
app.config['EXPORT_FOLDER'] = str(base_dir / 'exports')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)


# ============ MIGRATIONS (Optional) ============
# Uncomment if using Flask-Migrate
# from flask_migrate import Migrate
# migrate = Migrate(app, db)

# ============ HELPER FUNCTIONS ============
def format_currency(amount):
    """Format amount with comma separators"""
    if amount is None:
        return '0.00'
    return f"{amount:,.2f}"


def parse_currency(amount_str):
    """Parse currency string with commas back to float"""
    if not amount_str:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(amount_str))
    return float(cleaned) if cleaned else 0.0


def parse_date(date_value):
    """Parse date from various formats"""
    if pd.isna(date_value) or date_value is None:
        return None

    if isinstance(date_value, (datetime, pd.Timestamp)):
        return date_value.date() if hasattr(date_value, 'date') else date_value

    if isinstance(date_value, str):
        date_formats = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%b %d, %Y', '%B %d, %Y']
        for fmt in date_formats:
            try:
                return datetime.strptime(date_value.strip(), fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromordinal(int(float(date_value)) - 693594).date()
        except:
            pass

    return None


def get_active_company_id():
    """Get the ID of the currently active company"""
    company = Company.query.filter_by(is_active=True).first()
    return company.id if company else None


# ============ MODELS ============
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    telephone = db.Column(db.String(20))
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    account_name = db.Column(db.String(100))
    swift_code = db.Column(db.String(20))
    bank_address = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    currency = db.Column(db.String(10), default='GHS')


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    telephone = db.Column(db.String(20))
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    account_name = db.Column(db.String(100))
    swift_code = db.Column(db.String(20))
    bank_address = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref='suppliers')


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    telephone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref='customers')


class SupplierPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    payment_description = db.Column(db.String(200))
    invoice_ref = db.Column(db.String(50))
    amount = db.Column(db.Float)
    type = db.Column(db.String(20))
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20))
    invoice_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    supplier = db.relationship('Supplier', backref='payments')
    company = db.relationship('Company', backref='supplier_payments')


class CustomerPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    service_description = db.Column(db.String(200))
    invoice_ref = db.Column(db.String(50))
    amount = db.Column(db.Float)
    type = db.Column(db.String(20))
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20))
    invoice_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='payments')
    company = db.relationship('Company', backref='customer_payments')


class MonthlyLiquidity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    month = db.Column(db.String(20))
    year = db.Column(db.Integer)
    opening_balance = db.Column(db.Float, default=0)
    total_inflows = db.Column(db.Float, default=0)
    total_outflows = db.Column(db.Float, default=0)
    closing_balance = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref='liquidity')


# ============ SAFE TABLE CREATION ============
with app.app_context():
    from sqlalchemy import inspect

    inspector = inspect(db.engine)


    # Function to check if table exists (works for both SQLite and PostgreSQL)
    def table_exists(table_name):
        if db.engine.dialect.name == 'postgresql':
            try:
                result = db.session.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :table_name)",
                    {'table_name': table_name}
                )
                return result.scalar()
            except Exception as e:
                print(f"Error checking table {table_name}: {e}")
                return False
        else:
            return inspector.has_table(table_name)


    # Only create tables if they don't exist
    if not table_exists('company'):
        print("Creating tables...")
        db.create_all()
        print("Tables created successfully!")

        # Create default companies
        company_a = Company(
            name='Company A',
            address='123 Main Street, Accra, Ghana',
            telephone='+233 20 123 4567',
            bank_name='Ghana Commercial Bank',
            account_number='1234567890',
            account_name='Company A Ltd',
            swift_code='GCBKGHAX',
            bank_address='Accra, Ghana',
            is_active=True,
            currency='GHS'
        )
        company_b = Company(
            name='Company B',
            address='456 Independence Ave, Accra, Ghana',
            telephone='+233 24 987 6543',
            bank_name='Stanbic Bank',
            account_number='0987654321',
            account_name='Company B Ltd',
            swift_code='SBICGHAX',
            bank_address='Accra, Ghana',
            is_active=False,
            currency='GHS'
        )
        db.session.add(company_a)
        db.session.add(company_b)
        db.session.commit()
        print("Default companies created!")
    else:
        print("Tables already exist - skipping creation")

        # Check if companies exist, if not create them
        if Company.query.count() == 0:
            print("Creating default companies...")
            company_a = Company(
                name='Company A',
                address='123 Main Street, Accra, Ghana',
                telephone='+233 20 123 4567',
                bank_name='Ghana Commercial Bank',
                account_number='1234567890',
                account_name='Company A Ltd',
                swift_code='GCBKGHAX',
                bank_address='Accra, Ghana',
                is_active=True,
                currency='GHS'
            )
            company_b = Company(
                name='Company B',
                address='456 Independence Ave, Accra, Ghana',
                telephone='+233 24 987 6543',
                bank_name='Stanbic Bank',
                account_number='0987654321',
                account_name='Company B Ltd',
                swift_code='SBICGHAX',
                bank_address='Accra, Ghana',
                is_active=False,
                currency='GHS'
            )
            db.session.add(company_a)
            db.session.add(company_b)
            db.session.commit()
            print("Default companies created!")


# ============ ROUTES ============
@app.route('/')
def index():
    return render_template('index.html')


# ============ COMPANY ROUTES ============
@app.route('/api/companies', methods=['GET'])
def get_companies():
    companies = Company.query.all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'address': c.address,
        'telephone': c.telephone,
        'bank_name': c.bank_name,
        'account_number': c.account_number,
        'account_name': c.account_name,
        'swift_code': c.swift_code,
        'bank_address': c.bank_address,
        'is_active': c.is_active,
        'currency': c.currency
    } for c in companies])


@app.route('/api/companies', methods=['POST'])
def create_company():
    data = request.json

    existing = Company.query.filter_by(name=data['name']).first()
    if existing:
        return jsonify({'error': 'Company with this name already exists'}), 400

    company = Company(
        name=data['name'],
        address=data.get('address', ''),
        telephone=data.get('telephone', ''),
        bank_name=data.get('bank_name', ''),
        account_number=data.get('account_number', ''),
        account_name=data.get('account_name', ''),
        swift_code=data.get('swift_code', ''),
        bank_address=data.get('bank_address', ''),
        is_active=data.get('is_active', False),
        currency=data.get('currency', 'GHS')
    )

    db.session.add(company)
    db.session.commit()

    return jsonify({
        'id': company.id,
        'message': 'Company created successfully'
    })


@app.route('/api/companies/<int:company_id>', methods=['GET'])
def get_company(company_id):
    company = Company.query.get_or_404(company_id)
    return jsonify({
        'id': company.id,
        'name': company.name,
        'address': company.address,
        'telephone': company.telephone,
        'bank_name': company.bank_name,
        'account_number': company.account_number,
        'account_name': company.account_name,
        'swift_code': company.swift_code,
        'bank_address': company.bank_address,
        'is_active': company.is_active,
        'currency': company.currency
    })


@app.route('/api/companies/<int:company_id>', methods=['PUT'])
def update_company(company_id):
    data = request.json
    company = Company.query.get_or_404(company_id)

    if data.get('is_active'):
        Company.query.update({Company.is_active: False})

    company.name = data.get('name', company.name)
    company.address = data.get('address', company.address)
    company.telephone = data.get('telephone', company.telephone)
    company.bank_name = data.get('bank_name', company.bank_name)
    company.account_number = data.get('account_number', company.account_number)
    company.account_name = data.get('account_name', company.account_name)
    company.swift_code = data.get('swift_code', company.swift_code)
    company.bank_address = data.get('bank_address', company.bank_address)
    company.is_active = data.get('is_active', company.is_active)
    company.currency = data.get('currency', company.currency)

    db.session.commit()
    return jsonify({'message': 'Company updated successfully'})


@app.route('/api/companies/<int:company_id>', methods=['DELETE'])
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)

    if Company.query.count() <= 1:
        return jsonify({'error': 'Cannot delete the only company'}), 400

    if company.is_active:
        return jsonify({'error': 'Cannot delete the active company. Please switch to another company first.'}), 400

    db.session.delete(company)
    db.session.commit()

    return jsonify({'message': 'Company deleted successfully'})


@app.route('/api/active-company')
def get_active_company():
    company = Company.query.filter_by(is_active=True).first()
    if company:
        return jsonify({
            'id': company.id,
            'name': company.name,
            'address': company.address,
            'telephone': company.telephone,
            'bank_name': company.bank_name,
            'account_number': company.account_number,
            'account_name': company.account_name,
            'swift_code': company.swift_code,
            'bank_address': company.bank_address,
            'currency': company.currency
        })
    return jsonify({'error': 'No active company found'}), 404


# ============ SUPPLIER ROUTES ============
@app.route('/api/suppliers', methods=['GET', 'POST'])
def handle_suppliers():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    if request.method == 'GET':
        suppliers = Supplier.query.filter_by(company_id=company_id).all()
        return jsonify([{
            'id': s.id,
            'name': s.name,
            'address': s.address,
            'telephone': s.telephone,
            'bank_name': s.bank_name,
            'account_number': s.account_number,
            'account_name': s.account_name,
            'swift_code': s.swift_code,
            'bank_address': s.bank_address
        } for s in suppliers])

    elif request.method == 'POST':
        data = request.json
        supplier = Supplier(
            company_id=company_id,
            name=data['name'],
            address=data.get('address', ''),
            telephone=data.get('telephone', ''),
            bank_name=data.get('bank_name', ''),
            account_number=data.get('account_number', ''),
            account_name=data.get('account_name', ''),
            swift_code=data.get('swift_code', ''),
            bank_address=data.get('bank_address', '')
        )
        db.session.add(supplier)
        db.session.commit()
        return jsonify({'id': supplier.id, 'message': 'Supplier added successfully'})


@app.route('/api/suppliers/<int:supplier_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_supplier(supplier_id):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    supplier = Supplier.query.filter_by(id=supplier_id, company_id=company_id).first_or_404()

    if request.method == 'GET':
        return jsonify({
            'id': supplier.id,
            'name': supplier.name,
            'address': supplier.address,
            'telephone': supplier.telephone,
            'bank_name': supplier.bank_name,
            'account_number': supplier.account_number,
            'account_name': supplier.account_name,
            'swift_code': supplier.swift_code,
            'bank_address': supplier.bank_address
        })

    elif request.method == 'PUT':
        data = request.json
        supplier.name = data.get('name', supplier.name)
        supplier.address = data.get('address', supplier.address)
        supplier.telephone = data.get('telephone', supplier.telephone)
        supplier.bank_name = data.get('bank_name', supplier.bank_name)
        supplier.account_number = data.get('account_number', supplier.account_number)
        supplier.account_name = data.get('account_name', supplier.account_name)
        supplier.swift_code = data.get('swift_code', supplier.swift_code)
        supplier.bank_address = data.get('bank_address', supplier.bank_address)
        db.session.commit()
        return jsonify({'message': 'Supplier updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(supplier)
        db.session.commit()
        return jsonify({'message': 'Supplier deleted successfully'})


# ============ MULTIPLE DELETE FOR SUPPLIERS ============
@app.route('/api/suppliers/delete-multiple', methods=['POST'])
def delete_multiple_suppliers():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    data = request.json
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No IDs provided'}), 400

    try:
        deleted_count = Supplier.query.filter(Supplier.id.in_(ids), Supplier.company_id == company_id).delete(
            synchronize_session=False)
        db.session.commit()
        return jsonify({
            'message': f'Successfully deleted {deleted_count} supplier(s)',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============ CUSTOMER ROUTES ============
@app.route('/api/customers', methods=['GET', 'POST'])
def handle_customers():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    if request.method == 'GET':
        customers = Customer.query.filter_by(company_id=company_id).all()
        return jsonify([{
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'telephone': c.telephone
        } for c in customers])

    elif request.method == 'POST':
        data = request.json
        customer = Customer(
            company_id=company_id,
            name=data['name'],
            address=data.get('address', ''),
            telephone=data.get('telephone', '')
        )
        db.session.add(customer)
        db.session.commit()
        return jsonify({'id': customer.id, 'message': 'Customer added successfully'})


@app.route('/api/customers/<int:customer_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_customer(customer_id):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    customer = Customer.query.filter_by(id=customer_id, company_id=company_id).first_or_404()

    if request.method == 'GET':
        return jsonify({
            'id': customer.id,
            'name': customer.name,
            'address': customer.address,
            'telephone': customer.telephone
        })

    elif request.method == 'PUT':
        data = request.json
        customer.name = data.get('name', customer.name)
        customer.address = data.get('address', customer.address)
        customer.telephone = data.get('telephone', customer.telephone)
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})


# ============ SUPPLIER PAYMENT ROUTES ============
@app.route('/api/supplier-payments', methods=['GET', 'POST'])
def handle_supplier_payments():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    if request.method == 'GET':
        payments = SupplierPayment.query.filter_by(company_id=company_id).all()
        return jsonify([{
            'id': p.id,
            'supplier_id': p.supplier_id,
            'supplier_name': p.supplier.name if p.supplier else '',
            'payment_description': p.payment_description,
            'invoice_ref': p.invoice_ref,
            'amount': p.amount,
            'amount_formatted': format_currency(p.amount),
            'type': p.type,
            'due_date': p.due_date.isoformat() if p.due_date else None,
            'status': p.status,
            'invoice_date': p.invoice_date.isoformat() if p.invoice_date else None
        } for p in payments])

    elif request.method == 'POST':
        data = request.json
        print(f"Received POST data: {data}")  # Debug log

        # Validate required fields
        if not data.get('supplier_id'):
            return jsonify({'error': 'Supplier is required'}), 400
        if not data.get('amount'):
            return jsonify({'error': 'Amount is required'}), 400

        amount = parse_currency(data.get('amount', 0))
        if amount <= 0:
            return jsonify({'error': 'Amount must be greater than 0'}), 400

        try:
            payment = SupplierPayment(
                company_id=company_id,
                supplier_id=int(data['supplier_id']),
                payment_description=data.get('payment_description', ''),
                invoice_ref=data.get('invoice_ref', ''),
                amount=amount,
                type=data.get('type', 'Cash'),
                due_date=datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get('due_date') else None,
                status=data.get('status', 'Pending'),
                invoice_date=datetime.strptime(data['invoice_date'], '%Y-%m-%d').date() if data.get(
                    'invoice_date') else None
            )
            db.session.add(payment)
            db.session.commit()
            print(f"Payment created with ID: {payment.id}")  # Debug log
            return jsonify({'id': payment.id, 'message': 'Payment added successfully'})
        except Exception as e:
            db.session.rollback()
            print(f"Error creating payment: {str(e)}")  # Debug log
            return jsonify({'error': str(e)}), 400


@app.route('/api/supplier-payments/<int:payment_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_supplier_payment(payment_id):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    payment = SupplierPayment.query.filter_by(id=payment_id, company_id=company_id).first_or_404()

    if request.method == 'GET':
        return jsonify({
            'id': payment.id,
            'supplier_id': payment.supplier_id,
            'supplier_name': payment.supplier.name if payment.supplier else '',
            'payment_description': payment.payment_description,
            'invoice_ref': payment.invoice_ref,
            'amount': payment.amount,
            'type': payment.type,
            'due_date': payment.due_date.isoformat() if payment.due_date else None,
            'status': payment.status,
            'invoice_date': payment.invoice_date.isoformat() if payment.invoice_date else None
        })

    elif request.method == 'PUT':
        data = request.json
        payment.supplier_id = data.get('supplier_id', payment.supplier_id)
        payment.payment_description = data.get('payment_description', payment.payment_description)
        payment.invoice_ref = data.get('invoice_ref', payment.invoice_ref)
        payment.amount = parse_currency(data.get('amount', payment.amount))
        payment.type = data.get('type', payment.type)
        payment.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get(
            'due_date') else payment.due_date
        payment.status = data.get('status', payment.status)
        payment.invoice_date = datetime.strptime(data['invoice_date'], '%Y-%m-%d').date() if data.get(
            'invoice_date') else payment.invoice_date
        db.session.commit()
        return jsonify({'message': 'Payment updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(payment)
        db.session.commit()
        return jsonify({'message': 'Payment deleted successfully'})

# ============ CASHFLOW REPORT EXPORT ROUTES ============
@app.route('/api/reports/cashflow/export/excel', methods=['POST'])
def export_cashflow_excel():
    try:
        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        data = request.json
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        opening_balance = float(data.get('opening_balance', 0))

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = datetime(datetime.now().year, 1, 1).date()

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        # Get the cashflow data
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.company_id == company_id,
            db.or_(
                db.and_(
                    SupplierPayment.due_date >= start_date,
                    SupplierPayment.due_date <= end_date
                ),
                db.and_(
                    SupplierPayment.invoice_date >= start_date,
                    SupplierPayment.invoice_date <= end_date
                )
            )
        ).all()

        customer_payments = CustomerPayment.query.filter(
            CustomerPayment.company_id == company_id,
            db.or_(
                db.and_(
                    CustomerPayment.due_date >= start_date,
                    CustomerPayment.due_date <= end_date
                ),
                db.and_(
                    CustomerPayment.invoice_date >= start_date,
                    CustomerPayment.invoice_date <= end_date
                )
            )
        ).all()

        # Build monthly data
        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        year = start_date.year

        monthly_data = {}
        for month_key in month_order:
            month_num = month_order.index(month_key) + 1
            monthly_data[month_key] = {
                'month': month_key,
                'full_month': datetime(year, month_num, 1).strftime('%B'),
                'year': year,
                'month_index': month_num,
                'opening_balance': 0,
                'inflows': 0,
                'outflows': 0,
                'net': 0,
                'closing_balance': 0,
                'inflow_items': [],
                'outflow_items': []
            }

        for payment in supplier_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['outflows'] += payment.amount
                    description = payment.payment_description or 'Supplier Payment'
                    monthly_data[month_key]['outflow_items'].append({
                        'description': description,
                        'supplier': payment.supplier.name if payment.supplier else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })

        for payment in customer_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['inflows'] += payment.amount
                    description = payment.service_description or 'Customer Payment'
                    monthly_data[month_key]['inflow_items'].append({
                        'description': description,
                        'customer': payment.customer.name if payment.customer else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })

        # Calculate running balances
        running_balance = opening_balance
        chronological_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        active_months = []
        for month_key in chronological_months:
            month_num = chronological_months.index(month_key) + 1
            month_date = datetime(year, month_num, 1).date()
            if month_date >= start_date.replace(day=1) and month_date <= end_date:
                active_months.append(month_key)

        for month_key in active_months:
            monthly_data[month_key]['opening_balance'] = running_balance
            monthly_data[month_key]['net'] = monthly_data[month_key]['inflows'] - monthly_data[month_key]['outflows']
            running_balance += monthly_data[month_key]['net']
            monthly_data[month_key]['closing_balance'] = running_balance

        company = Company.query.get(company_id)
        currency = company.currency if company else 'GHS'

        # Create Excel file
        filename = f'cashflow_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
        os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # ========== SHEET 1: SUMMARY ==========
            total_inflows = sum(m['inflows'] for m in monthly_data.values())
            total_outflows = sum(m['outflows'] for m in monthly_data.values())
            total_net = sum(m['net'] for m in monthly_data.values())

            summary_data = {
                'Metric': ['Start Date', 'End Date', 'Opening Balance', 'Total Inflows', 'Total Outflows',
                           'Net Cashflow', 'Closing Balance'],
                'Value': [
                    start_date_str,
                    end_date_str,
                    opening_balance,
                    total_inflows,
                    total_outflows,
                    total_net,
                    running_balance
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

            # ========== SHEET 2: HORIZONTAL CASHFLOW REPORT ==========
            # Build the horizontal report - THIS IS THE FIXED PART
            report_data = []

            # Get all unique inflow and outflow descriptions
            all_inflow_descs = set()
            for month in active_months:
                for item in monthly_data[month]['inflow_items']:
                    all_inflow_descs.add(item['description'])
            all_inflow_descs = sorted(all_inflow_descs)

            all_outflow_descs = set()
            for month in active_months:
                for item in monthly_data[month]['outflow_items']:
                    all_outflow_descs.add(item['description'])
            all_outflow_descs = sorted(all_outflow_descs)

            # Build the horizontal data structure
            # Each row will be a dictionary with 'Category' and each month as keys

            # 1. Opening Balance
            row = {'Category': 'OPENING BALANCE'}
            for month in active_months:
                row[month] = monthly_data[month]['opening_balance']
            row['Total'] = opening_balance
            report_data.append(row)

            # 2. Inflows Header
            row = {'Category': 'INFLOWS'}
            for month in active_months:
                row[month] = monthly_data[month]['inflows']
            row['Total'] = total_inflows
            report_data.append(row)

            # 3. Inflow Details - Each description as a row (indented)
            for desc in all_inflow_descs:
                row = {'Category': f'  {desc}'}
                desc_total = 0
                for month in active_months:
                    items = monthly_data[month]['inflow_items']
                    item = next((i for i in items if i['description'] == desc), None)
                    amount = item['amount'] if item else 0
                    row[month] = amount
                    desc_total += amount
                row['Total'] = desc_total
                report_data.append(row)

            # 4. Outflows Header
            row = {'Category': 'OUTFLOWS'}
            for month in active_months:
                row[month] = monthly_data[month]['outflows']
            row['Total'] = total_outflows
            report_data.append(row)

            # 5. Outflow Details - Each description as a row (indented)
            for desc in all_outflow_descs:
                row = {'Category': f'  {desc}'}
                desc_total = 0
                for month in active_months:
                    items = monthly_data[month]['outflow_items']
                    item = next((i for i in items if i['description'] == desc), None)
                    amount = item['amount'] if item else 0
                    row[month] = amount
                    desc_total += amount
                row['Total'] = desc_total
                report_data.append(row)

            # 6. Net
            row = {'Category': 'NET'}
            for month in active_months:
                row[month] = monthly_data[month]['net']
            row['Total'] = total_net
            report_data.append(row)

            # 7. Closing Balance
            row = {'Category': 'CLOSING BALANCE'}
            for month in active_months:
                row[month] = monthly_data[month]['closing_balance']
            row['Total'] = running_balance
            report_data.append(row)

            # Create DataFrame for horizontal report
            df_horizontal = pd.DataFrame(report_data)

            # Write to Excel
            df_horizontal.to_excel(writer, sheet_name='Cashflow Report', index=False)

            # ========== SHEET 3: INFLOW DETAILS WITH STATUS ==========
            inflow_rows = []
            for month in active_months:
                for item in monthly_data[month]['inflow_items']:
                    inflow_rows.append({
                        'Month': month,
                        'Customer': item.get('customer', ''),
                        'Description': item.get('description', ''),
                        'Amount': item.get('amount', 0),
                        'Date': item.get('date', ''),
                        'Status': item.get('status', '')
                    })
            if inflow_rows:
                inflow_df = pd.DataFrame(inflow_rows)
                inflow_df.to_excel(writer, sheet_name='Inflow Details', index=False)

            # ========== SHEET 4: OUTFLOW DETAILS WITH STATUS ==========
            outflow_rows = []
            for month in active_months:
                for item in monthly_data[month]['outflow_items']:
                    outflow_rows.append({
                        'Month': month,
                        'Supplier': item.get('supplier', ''),
                        'Description': item.get('description', ''),
                        'Amount': item.get('amount', 0),
                        'Date': item.get('date', ''),
                        'Status': item.get('status', '')
                    })
            if outflow_rows:
                outflow_df = pd.DataFrame(outflow_rows)
                outflow_df.to_excel(writer, sheet_name='Outflow Details', index=False)

            # Format Excel sheets - Auto-adjust column widths
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 30)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        print(f"Excel export error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
@app.route('/api/reports/cashflow/export/pdf', methods=['POST'])
def export_cashflow_pdf():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        data = request.json
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        opening_balance = float(data.get('opening_balance', 0))

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = datetime(datetime.now().year, 1, 1).date()

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        # Get the cashflow data
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.company_id == company_id,
            db.or_(
                db.and_(
                    SupplierPayment.due_date >= start_date,
                    SupplierPayment.due_date <= end_date
                ),
                db.and_(
                    SupplierPayment.invoice_date >= start_date,
                    SupplierPayment.invoice_date <= end_date
                )
            )
        ).all()

        customer_payments = CustomerPayment.query.filter(
            CustomerPayment.company_id == company_id,
            db.or_(
                db.and_(
                    CustomerPayment.due_date >= start_date,
                    CustomerPayment.due_date <= end_date
                ),
                db.and_(
                    CustomerPayment.invoice_date >= start_date,
                    CustomerPayment.invoice_date <= end_date
                )
            )
        ).all()

        # Build monthly data
        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        year = start_date.year

        monthly_data = {}
        for month_key in month_order:
            month_num = month_order.index(month_key) + 1
            monthly_data[month_key] = {
                'month': month_key,
                'full_month': datetime(year, month_num, 1).strftime('%B'),
                'year': year,
                'month_index': month_num,
                'opening_balance': 0,
                'inflows': 0,
                'outflows': 0,
                'net': 0,
                'closing_balance': 0,
                'inflow_items': [],
                'outflow_items': []
            }

        for payment in supplier_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['outflows'] += payment.amount
                    description = payment.payment_description or 'Supplier Payment'
                    monthly_data[month_key]['outflow_items'].append({
                        'description': description,
                        'supplier': payment.supplier.name if payment.supplier else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })

        for payment in customer_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['inflows'] += payment.amount
                    description = payment.service_description or 'Customer Payment'
                    monthly_data[month_key]['inflow_items'].append({
                        'description': description,
                        'customer': payment.customer.name if payment.customer else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })

        # Calculate running balances
        running_balance = opening_balance
        chronological_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        active_months = []
        for month_key in chronological_months:
            month_num = chronological_months.index(month_key) + 1
            month_date = datetime(year, month_num, 1).date()
            if month_date >= start_date.replace(day=1) and month_date <= end_date:
                active_months.append(month_key)

        for month_key in active_months:
            monthly_data[month_key]['opening_balance'] = running_balance
            monthly_data[month_key]['net'] = monthly_data[month_key]['inflows'] - monthly_data[month_key]['outflows']
            running_balance += monthly_data[month_key]['net']
            monthly_data[month_key]['closing_balance'] = running_balance

        company = Company.query.get(company_id)
        currency = company.currency if company else 'GHS'

        # Generate PDF
        filename = f'cashflow_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
        os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

        doc = SimpleDocTemplate(filepath, pagesize=landscape(letter))
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=20
        )
        elements.append(Paragraph(f"Cashflow Report", title_style))
        elements.append(Paragraph(f"Company: {company.name}", styles['Normal']))
        elements.append(Paragraph(f"Period: {start_date_str} to {end_date_str}", styles['Normal']))
        elements.append(Paragraph(f"Currency: {currency}", styles['Normal']))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 12))

        # ========== SUMMARY TABLE ==========
        total_inflows = sum(m['inflows'] for m in monthly_data.values())
        total_outflows = sum(m['outflows'] for m in monthly_data.values())
        total_net = sum(m['net'] for m in monthly_data.values())

        summary_data = [
            ['Metric', 'Amount'],
            ['Opening Balance', f"{currency} {format_currency(opening_balance)}"],
            ['Total Inflows', f"{currency} {format_currency(total_inflows)}"],
            ['Total Outflows', f"{currency} {format_currency(total_outflows)}"],
            ['Net Cashflow', f"{currency} {format_currency(total_net)}"],
            ['Closing Balance', f"{currency} {format_currency(running_balance)}"]
        ]

        summary_table = Table(summary_data, colWidths=[2.5 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # ========== HORIZONTAL CASHFLOW TABLE ==========
        elements.append(Paragraph("Cashflow Report - Monthly Breakdown", styles['Heading2']))
        elements.append(Spacer(1, 10))

        # Build table data
        table_data = []

        # Header row with months
        header = ['Category / Description']
        for month in active_months:
            header.append(month)
        header.append('Total')
        table_data.append(header)

        # Opening Balance
        row = ['OPENING BALANCE']
        for month in active_months:
            row.append(f"{currency} {format_currency(monthly_data[month]['opening_balance'])}")
        row.append(f"{currency} {format_currency(opening_balance)}")
        table_data.append(row)

        # Inflows Header
        row = ['INFLOWS']
        for month in active_months:
            row.append(f"{currency} {format_currency(monthly_data[month]['inflows'])}")
        row.append(f"{currency} {format_currency(total_inflows)}")
        table_data.append(row)

        # Inflow Details
        all_inflow_descs = set()
        for month in active_months:
            for item in monthly_data[month]['inflow_items']:
                all_inflow_descs.add(item['description'])
        all_inflow_descs = sorted(all_inflow_descs)

        for desc in all_inflow_descs:
            row = [f'  {desc}']
            desc_total = 0
            for month in active_months:
                items = monthly_data[month]['inflow_items']
                item = next((i for i in items if i['description'] == desc), None)
                if item:
                    amount = item['amount']
                    desc_total += amount
                    customer = item.get('customer', '')
                    status = item.get('status', '')
                    row.append(f"{currency} {format_currency(amount)}")
                else:
                    row.append('-')
            row.append(f"{currency} {format_currency(desc_total)}")
            table_data.append(row)

        # Outflows Header
        row = ['OUTFLOWS']
        for month in active_months:
            row.append(f"{currency} {format_currency(monthly_data[month]['outflows'])}")
        row.append(f"{currency} {format_currency(total_outflows)}")
        table_data.append(row)

        # Outflow Details
        all_outflow_descs = set()
        for month in active_months:
            for item in monthly_data[month]['outflow_items']:
                all_outflow_descs.add(item['description'])
        all_outflow_descs = sorted(all_outflow_descs)

        for desc in all_outflow_descs:
            row = [f'  {desc}']
            desc_total = 0
            for month in active_months:
                items = monthly_data[month]['outflow_items']
                item = next((i for i in items if i['description'] == desc), None)
                if item:
                    amount = item['amount']
                    desc_total += amount
                    supplier = item.get('supplier', '')
                    status = item.get('status', '')
                    row.append(f"{currency} {format_currency(amount)}")
                else:
                    row.append('-')
            row.append(f"{currency} {format_currency(desc_total)}")
            table_data.append(row)

        # Net
        row = ['NET']
        for month in active_months:
            net = monthly_data[month]['net']
            row.append(f"{currency} {format_currency(net)}")
        row.append(f"{currency} {format_currency(total_net)}")
        table_data.append(row)

        # Closing Balance
        row = ['CLOSING BALANCE']
        for month in active_months:
            row.append(f"{currency} {format_currency(monthly_data[month]['closing_balance'])}")
        row.append(f"{currency} {format_currency(running_balance)}")
        table_data.append(row)

        # Create table with appropriate column widths
        col_width = 0.8 * inch
        col_widths = [1.5 * inch]
        for _ in active_months:
            col_widths.append(col_width)
        col_widths.append(0.8 * inch)

        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),

            # Opening Balance - Light Blue
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e3f2fd')),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),

            # Inflows Header - Green
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#c8e6c9')),
            ('FONTNAME', (0, 2), (-1, 2), 'Helvetica-Bold'),

            # Inflow Details - Light Green
            ('BACKGROUND', (0, 3), (-1, 3 + len(all_inflow_descs) - 1), colors.HexColor('#f1f8e9')),

            # Outflows Header - Red
            ('BACKGROUND', (0, 4 + len(all_inflow_descs)), (-1, 4 + len(all_inflow_descs)), colors.HexColor('#ffcdd2')),
            ('FONTNAME', (0, 4 + len(all_inflow_descs)), (-1, 4 + len(all_inflow_descs)), 'Helvetica-Bold'),

            # Outflow Details - Light Red
            ('BACKGROUND', (0, 5 + len(all_inflow_descs)), (-1, -3), colors.HexColor('#fbe9e7')),

            # Net - Blue
            ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#bbdefb')),
            ('FONTNAME', (0, -2), (-1, -2), 'Helvetica-Bold'),

            # Closing Balance - Light Blue
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e3f2fd')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),

            # Font size for all cells
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))

        elements.append(table)

        # Footer
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(
            f"Report generated on {datetime.now().strftime('%d/%m/%Y %H:%M')} | {company.name}",
            styles['Normal']
        ))

        # Build PDF
        doc.build(elements)

        return send_file(filepath, as_attachment=True, download_name=filename)

    except ImportError as e:
        print(f"ReportLab not installed: {str(e)}")
        return jsonify({'error': 'PDF library not installed. Please run: pip install reportlab'}), 500
    except Exception as e:
        print(f"PDF export error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400

# ============ MULTIPLE DELETE FOR SUPPLIER PAYMENTS ============
@app.route('/api/supplier-payments/delete-multiple', methods=['POST'])
def delete_multiple_supplier_payments():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    data = request.json
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No IDs provided'}), 400

    try:
        deleted_count = SupplierPayment.query.filter(
            SupplierPayment.id.in_(ids),
            SupplierPayment.company_id == company_id
        ).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({
            'message': f'Successfully deleted {deleted_count} supplier payment(s)',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============ CUSTOMER PAYMENT ROUTES ============
@app.route('/api/customer-payments', methods=['GET', 'POST'])
def handle_customer_payments():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    if request.method == 'GET':
        payments = CustomerPayment.query.filter_by(company_id=company_id).all()
        return jsonify([{
            'id': p.id,
            'customer_id': p.customer_id,
            'customer_name': p.customer.name if p.customer else '',
            'service_description': p.service_description,
            'invoice_ref': p.invoice_ref,
            'amount': p.amount,
            'amount_formatted': format_currency(p.amount),
            'type': p.type,
            'due_date': p.due_date.isoformat() if p.due_date else None,
            'status': p.status,
            'invoice_date': p.invoice_date.isoformat() if p.invoice_date else None
        } for p in payments])

    elif request.method == 'POST':
        data = request.json
        amount = parse_currency(data.get('amount', 0))

        payment = CustomerPayment(
            company_id=company_id,
            customer_id=data['customer_id'],
            service_description=data.get('service_description', ''),
            invoice_ref=data.get('invoice_ref', ''),
            amount=amount,
            type=data.get('type', ''),
            due_date=datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get('due_date') else None,
            status=data.get('status', 'Pending'),
            invoice_date=datetime.strptime(data['invoice_date'], '%Y-%m-%d').date() if data.get(
                'invoice_date') else None
        )
        db.session.add(payment)
        db.session.commit()
        return jsonify({'id': payment.id, 'message': 'Payment added successfully'})


@app.route('/api/customer-payments/<int:payment_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_customer_payment(payment_id):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    payment = CustomerPayment.query.filter_by(id=payment_id, company_id=company_id).first_or_404()

    if request.method == 'GET':
        return jsonify({
            'id': payment.id,
            'customer_id': payment.customer_id,
            'customer_name': payment.customer.name if payment.customer else '',
            'service_description': payment.service_description,
            'invoice_ref': payment.invoice_ref,
            'amount': payment.amount,
            'type': payment.type,
            'due_date': payment.due_date.isoformat() if payment.due_date else None,
            'status': payment.status,
            'invoice_date': payment.invoice_date.isoformat() if payment.invoice_date else None
        })

    elif request.method == 'PUT':
        data = request.json
        payment.customer_id = data.get('customer_id', payment.customer_id)
        payment.service_description = data.get('service_description', payment.service_description)
        payment.invoice_ref = data.get('invoice_ref', payment.invoice_ref)
        payment.amount = parse_currency(data.get('amount', payment.amount))
        payment.type = data.get('type', payment.type)
        payment.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get(
            'due_date') else payment.due_date
        payment.status = data.get('status', payment.status)
        payment.invoice_date = datetime.strptime(data['invoice_date'], '%Y-%m-%d').date() if data.get(
            'invoice_date') else payment.invoice_date
        db.session.commit()
        return jsonify({'message': 'Payment updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(payment)
        db.session.commit()
        return jsonify({'message': 'Payment deleted successfully'})


# ============ MULTIPLE DELETE FOR CUSTOMER PAYMENTS ============
@app.route('/api/customer-payments/delete-multiple', methods=['POST'])
def delete_multiple_customer_payments():
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    data = request.json
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No IDs provided'}), 400

    try:
        deleted_count = CustomerPayment.query.filter(
            CustomerPayment.id.in_(ids),
            CustomerPayment.company_id == company_id
        ).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({
            'message': f'Successfully deleted {deleted_count} customer payment(s)',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============ IMPORT ROUTES ============
@app.route('/api/import/<entity>', methods=['POST'])
def import_data(entity):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        # Read the Excel file
        df = pd.read_excel(file)
        print(f"Importing {entity} - Found {len(df)} rows")
        print(f"Columns: {df.columns.tolist()}")

        imported_count = 0
        errors = []

        if entity == 'suppliers':
            for index, row in df.iterrows():
                try:
                    # Check for required fields
                    if pd.isna(row.get('Name')) or not row.get('Name'):
                        errors.append(f"Row {index + 2}: Missing supplier name")
                        continue

                    supplier = Supplier(
                        company_id=company_id,
                        name=str(row['Name']).strip(),
                        address=str(row.get('Address', '')) if pd.notna(row.get('Address')) else '',
                        telephone=str(row.get('Telephone', '')) if pd.notna(row.get('Telephone')) else '',
                        bank_name=str(row.get('Bank Name', '')) if pd.notna(row.get('Bank Name')) else '',
                        account_number=str(row.get('Account Number', '')) if pd.notna(
                            row.get('Account Number')) else '',
                        account_name=str(row.get('Account Name', '')) if pd.notna(row.get('Account Name')) else '',
                        swift_code=str(row.get('SWIFT Code', '')) if pd.notna(row.get('SWIFT Code')) else '',
                        bank_address=str(row.get('Bank Address', '')) if pd.notna(row.get('Bank Address')) else ''
                    )
                    db.session.add(supplier)
                    imported_count += 1
                    print(f"Row {index + 2}: Imported supplier {supplier.name}")

                except Exception as e:
                    errors.append(f"Row {index + 2}: {str(e)}")
                    print(f"Error in row {index + 2}: {str(e)}")

            db.session.commit()

            result_message = f'Successfully imported {imported_count} supplier(s)'
            if errors:
                result_message += f' | Errors: {len(errors)} rows failed'
                print(f"Import errors: {errors}")

            return jsonify({
                'message': result_message,
                'imported': imported_count,
                'errors': errors
            })

        elif entity == 'customers':
            for index, row in df.iterrows():
                try:
                    if pd.isna(row.get('Name')) or not row.get('Name'):
                        errors.append(f"Row {index + 2}: Missing customer name")
                        continue

                    customer = Customer(
                        company_id=company_id,
                        name=str(row['Name']).strip(),
                        address=str(row.get('Address', '')) if pd.notna(row.get('Address')) else '',
                        telephone=str(row.get('Telephone', '')) if pd.notna(row.get('Telephone')) else ''
                    )
                    db.session.add(customer)
                    imported_count += 1
                    print(f"Row {index + 2}: Imported customer {customer.name}")

                except Exception as e:
                    errors.append(f"Row {index + 2}: {str(e)}")
                    print(f"Error in row {index + 2}: {str(e)}")

            db.session.commit()

            result_message = f'Successfully imported {imported_count} customer(s)'
            if errors:
                result_message += f' | Errors: {len(errors)} rows failed'
                print(f"Import errors: {errors}")

            return jsonify({
                'message': result_message,
                'imported': imported_count,
                'errors': errors
            })

        elif entity == 'supplier-payments':
            for index, row in df.iterrows():
                try:
                    # Get supplier name
                    supplier_name = row.get('Supplier', '')
                    if pd.isna(supplier_name) or not supplier_name:
                        errors.append(f"Row {index + 2}: Missing supplier name")
                        continue

                    # Find supplier in the current company
                    supplier = Supplier.query.filter_by(
                        name=str(supplier_name).strip(),
                        company_id=company_id
                    ).first()

                    if not supplier:
                        errors.append(f"Row {index + 2}: Supplier '{supplier_name}' not found in this company")
                        continue

                    # Parse amount
                    amount = parse_currency(row.get('Amount', 0))
                    if amount == 0 and row.get('Amount') is not None:
                        amount = float(row.get('Amount', 0))

                    # Parse dates
                    due_date = parse_date(row.get('Due Date'))
                    invoice_date = parse_date(row.get('Invoice Date'))

                    # If no dates provided, use today
                    if not due_date and not invoice_date:
                        today = datetime.now().date()
                        due_date = today
                        invoice_date = today
                        print(f"Row {index + 2}: No dates provided, using today's date")

                    payment = SupplierPayment(
                        company_id=company_id,
                        supplier_id=supplier.id,
                        payment_description=str(row.get('Payment Description', '')) if pd.notna(
                            row.get('Payment Description')) else '',
                        invoice_ref=str(row.get('Invoice Ref', '')) if pd.notna(row.get('Invoice Ref')) else '',
                        amount=amount,
                        type=str(row.get('Type', 'Cash')) if pd.notna(row.get('Type')) else 'Cash',
                        due_date=due_date,
                        status=str(row.get('Status', 'Pending')) if pd.notna(row.get('Status')) else 'Pending',
                        invoice_date=invoice_date
                    )
                    db.session.add(payment)
                    imported_count += 1
                    print(f"Row {index + 2}: Imported payment for {supplier_name} - Amount: {amount}")

                except Exception as e:
                    errors.append(f"Row {index + 2}: {str(e)}")
                    print(f"Error in row {index + 2}: {str(e)}")

            db.session.commit()

            result_message = f'Successfully imported {imported_count} supplier payment(s)'
            if errors:
                result_message += f' | Errors: {len(errors)} rows failed'
                print(f"Import errors: {errors}")

            return jsonify({
                'message': result_message,
                'imported': imported_count,
                'errors': errors
            })

        elif entity == 'customer-payments':
            for index, row in df.iterrows():
                try:
                    customer_name = row.get('Customer', '')
                    if pd.isna(customer_name) or not customer_name:
                        errors.append(f"Row {index + 2}: Missing customer name")
                        continue

                    customer = Customer.query.filter_by(
                        name=str(customer_name).strip(),
                        company_id=company_id
                    ).first()

                    if not customer:
                        errors.append(f"Row {index + 2}: Customer '{customer_name}' not found in this company")
                        continue

                    amount = parse_currency(row.get('Amount', 0))
                    if amount == 0 and row.get('Amount') is not None:
                        amount = float(row.get('Amount', 0))

                    due_date = parse_date(row.get('Due Date'))
                    invoice_date = parse_date(row.get('Invoice Date'))

                    if not due_date and not invoice_date:
                        today = datetime.now().date()
                        due_date = today
                        invoice_date = today
                        print(f"Row {index + 2}: No dates provided, using today's date")

                    payment = CustomerPayment(
                        company_id=company_id,
                        customer_id=customer.id,
                        service_description=str(row.get('Service Description', '')) if pd.notna(
                            row.get('Service Description')) else '',
                        invoice_ref=str(row.get('Invoice Ref', '')) if pd.notna(row.get('Invoice Ref')) else '',
                        amount=amount,
                        type=str(row.get('Type', 'Cash')) if pd.notna(row.get('Type')) else 'Cash',
                        due_date=due_date,
                        status=str(row.get('Status', 'Pending')) if pd.notna(row.get('Status')) else 'Pending',
                        invoice_date=invoice_date
                    )
                    db.session.add(payment)
                    imported_count += 1
                    print(f"Row {index + 2}: Imported payment for {customer_name} - Amount: {amount}")

                except Exception as e:
                    errors.append(f"Row {index + 2}: {str(e)}")
                    print(f"Error in row {index + 2}: {str(e)}")

            db.session.commit()

            result_message = f'Successfully imported {imported_count} customer payment(s)'
            if errors:
                result_message += f' | Errors: {len(errors)} rows failed'
                print(f"Import errors: {errors}")

            return jsonify({
                'message': result_message,
                'imported': imported_count,
                'errors': errors
            })

        else:
            return jsonify({'error': f'Invalid entity: {entity}'}), 400

    except Exception as e:
        db.session.rollback()
        print(f"Import error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


# ============ EXPORT ROUTES ============
@app.route('/api/export/<entity>')
def export_data(entity):
    company_id = get_active_company_id()
    if not company_id:
        return jsonify({'error': 'No active company'}), 400

    try:
        # Create exports folder if it doesn't exist
        os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

        filename = f'{entity}_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)

        if entity == 'suppliers':
            suppliers = Supplier.query.filter_by(company_id=company_id).all()
            data = [{
                'Name': s.name,
                'Address': s.address,
                'Telephone': s.telephone,
                'Bank Name': s.bank_name,
                'Account Number': s.account_number,
                'Account Name': s.account_name,
                'SWIFT Code': s.swift_code,
                'Bank Address': s.bank_address
            } for s in suppliers]
            df = pd.DataFrame(data)
            print(f"Exporting {len(suppliers)} suppliers")

        elif entity == 'customers':
            customers = Customer.query.filter_by(company_id=company_id).all()
            data = [{
                'Name': c.name,
                'Address': c.address,
                'Telephone': c.telephone
            } for c in customers]
            df = pd.DataFrame(data)
            print(f"Exporting {len(customers)} customers")

        elif entity == 'supplier-payments':
            payments = SupplierPayment.query.filter_by(company_id=company_id).all()
            data = [{
                'Supplier': p.supplier.name if p.supplier else '',
                'Payment Description': p.payment_description,
                'Invoice Ref': p.invoice_ref,
                'Amount': p.amount,
                'Type': p.type,
                'Due Date': p.due_date.isoformat() if p.due_date else '',
                'Status': p.status,
                'Invoice Date': p.invoice_date.isoformat() if p.invoice_date else ''
            } for p in payments]
            df = pd.DataFrame(data)
            print(f"Exporting {len(payments)} supplier payments")

        elif entity == 'customer-payments':
            payments = CustomerPayment.query.filter_by(company_id=company_id).all()
            data = [{
                'Customer': p.customer.name if p.customer else '',
                'Service Description': p.service_description,
                'Invoice Ref': p.invoice_ref,
                'Amount': p.amount,
                'Type': p.type,
                'Due Date': p.due_date.isoformat() if p.due_date else '',
                'Status': p.status,
                'Invoice Date': p.invoice_date.isoformat() if p.invoice_date else ''
            } for p in payments]
            df = pd.DataFrame(data)
            print(f"Exporting {len(payments)} customer payments")

        else:
            return jsonify({'error': f'Invalid entity: {entity}'}), 400

        # Check if data is empty
        if df.empty:
            print(f"No data to export for {entity}")
            # Create empty dataframe with headers
            if entity == 'suppliers':
                df = pd.DataFrame(
                    columns=['Name', 'Address', 'Telephone', 'Bank Name', 'Account Number', 'Account Name',
                             'SWIFT Code', 'Bank Address'])
            elif entity == 'customers':
                df = pd.DataFrame(columns=['Name', 'Address', 'Telephone'])
            elif entity == 'supplier-payments':
                df = pd.DataFrame(
                    columns=['Supplier', 'Payment Description', 'Invoice Ref', 'Amount', 'Type', 'Due Date', 'Status',
                             'Invoice Date'])
            elif entity == 'customer-payments':
                df = pd.DataFrame(
                    columns=['Customer', 'Service Description', 'Invoice Ref', 'Amount', 'Type', 'Due Date', 'Status',
                             'Invoice Date'])

        # Ensure all columns are included even if empty
        df.to_excel(filepath, index=False)
        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        print(f"Export error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


@app.route('/api/download-template/<entity>')
def download_template(entity):
    try:
        filename = f'{entity}_template.xlsx'
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)

        if entity == 'suppliers':
            columns = ['Name', 'Address', 'Telephone', 'Bank Name', 'Account Number', 'Account Name', 'SWIFT Code',
                       'Bank Address']
        elif entity == 'customers':
            columns = ['Name', 'Address', 'Telephone']
        elif entity == 'supplier-payments':
            columns = ['Supplier', 'Payment Description', 'Invoice Ref', 'Amount', 'Type', 'Due Date', 'Status',
                       'Invoice Date']
        elif entity == 'customer-payments':
            columns = ['Customer', 'Service Description', 'Invoice Ref', 'Amount', 'Type', 'Due Date', 'Status',
                       'Invoice Date']
        else:
            return jsonify({'error': 'Invalid entity'}), 400

        df = pd.DataFrame(columns=columns)
        df.to_excel(filepath, index=False)
        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ============ CASHFLOW REPORT ROUTE ============
@app.route('/api/reports/cashflow', methods=['GET'])
def get_cashflow_report():
    try:
        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        opening_balance = float(request.args.get('opening_balance', 0))

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = datetime(datetime.now().year, 1, 1).date()

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        print(f"\n{'=' * 60}")
        print(f"CASHFLOW REPORT - {start_date} to {end_date}")
        print(f"{'=' * 60}")
        print(f"Opening Balance: {opening_balance}")

        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.company_id == company_id,
            db.or_(
                db.and_(
                    SupplierPayment.due_date >= start_date,
                    SupplierPayment.due_date <= end_date
                ),
                db.and_(
                    SupplierPayment.invoice_date >= start_date,
                    SupplierPayment.invoice_date <= end_date
                )
            )
        ).all()

        customer_payments = CustomerPayment.query.filter(
            CustomerPayment.company_id == company_id,
            db.or_(
                db.and_(
                    CustomerPayment.due_date >= start_date,
                    CustomerPayment.due_date <= end_date
                ),
                db.and_(
                    CustomerPayment.invoice_date >= start_date,
                    CustomerPayment.invoice_date <= end_date
                )
            )
        ).all()

        print(f"Supplier Payments found: {len(supplier_payments)}")
        print(f"Customer Payments found: {len(customer_payments)}")

        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        year = start_date.year

        monthly_data = {}
        for month_key in month_order:
            month_num = month_order.index(month_key) + 1
            monthly_data[month_key] = {
                'month': month_key,
                'full_month': datetime(year, month_num, 1).strftime('%B'),
                'year': year,
                'month_index': month_num,
                'opening_balance': 0,
                'inflows': 0,
                'outflows': 0,
                'net': 0,
                'closing_balance': 0,
                'inflow_items': [],
                'outflow_items': []
            }

        for payment in supplier_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['outflows'] += payment.amount
                    description = payment.payment_description or 'Supplier Payment'
                    monthly_data[month_key]['outflow_items'].append({
                        'description': description,
                        'supplier': payment.supplier.name if payment.supplier else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })
                    print(
                        f"  OUTFLOW: {description} - {payment.amount} on {date_to_use.strftime('%Y-%m-%d')} -> {month_key}")

        for payment in customer_payments:
            date_to_use = payment.due_date if payment.due_date else payment.invoice_date
            if date_to_use:
                month_key = date_to_use.strftime('%b')
                if month_key in monthly_data:
                    monthly_data[month_key]['inflows'] += payment.amount
                    description = payment.service_description or 'Customer Payment'
                    monthly_data[month_key]['inflow_items'].append({
                        'description': description,
                        'customer': payment.customer.name if payment.customer else 'Unknown',
                        'amount': payment.amount,
                        'date': date_to_use.isoformat(),
                        'status': payment.status or 'Pending'
                    })
                    print(
                        f"  INFLOW: {description} - {payment.amount} on {date_to_use.strftime('%Y-%m-%d')} -> {month_key}")

        running_balance = opening_balance
        chronological_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        active_months = []
        for month_key in chronological_months:
            month_num = chronological_months.index(month_key) + 1
            month_date = datetime(year, month_num, 1).date()
            if month_date >= start_date.replace(day=1) and month_date <= end_date:
                active_months.append(month_key)

        for month_key in active_months:
            monthly_data[month_key]['opening_balance'] = running_balance
            monthly_data[month_key]['net'] = monthly_data[month_key]['inflows'] - monthly_data[month_key]['outflows']
            running_balance += monthly_data[month_key]['net']
            monthly_data[month_key]['closing_balance'] = running_balance

        result = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'opening_balance': opening_balance,
            'closing_balance': running_balance,
            'total_inflows': sum(m['inflows'] for m in monthly_data.values()),
            'total_outflows': sum(m['outflows'] for m in monthly_data.values()),
            'total_net': sum(m['net'] for m in monthly_data.values()),
            'months': active_months,
            'monthly_data': monthly_data,
            'row_data': {
                'opening_balances': [monthly_data[m]['opening_balance'] for m in active_months],
                'inflows': [monthly_data[m]['inflows'] for m in active_months],
                'outflows': [monthly_data[m]['outflows'] for m in active_months],
                'net': [monthly_data[m]['net'] for m in active_months],
                'closing_balances': [monthly_data[m]['closing_balance'] for m in active_months]
            }
        }

        print(f"\n{'=' * 60}")
        print("CASHFLOW SUMMARY:")
        print(f"{'=' * 60}")
        print(f"Opening Balance: {opening_balance}")
        print(f"Total Inflows: {result['total_inflows']}")
        print(f"Total Outflows: {result['total_outflows']}")
        print(f"Total Net: {result['total_net']}")
        print(f"Closing Balance: {result['closing_balance']}")
        print(f"Months in report: {active_months}")
        print(f"{'=' * 60}\n")

        return jsonify(result)

    except Exception as e:
        print(f"Error in cashflow report: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


# ============ DASHBOARD ROUTE ============
@app.route('/api/dashboard/stats')
def get_dashboard_stats():
    try:
        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        # Get counts
        total_suppliers = Supplier.query.filter_by(company_id=company_id).count()
        total_customers = Customer.query.filter_by(company_id=company_id).count()
        total_supplier_payments = SupplierPayment.query.filter_by(company_id=company_id).count()
        total_customer_payments = CustomerPayment.query.filter_by(company_id=company_id).count()

        # Get total amounts
        total_supplier_amount = db.session.query(db.func.sum(SupplierPayment.amount)).filter_by(
            company_id=company_id).scalar() or 0
        total_customer_amount = db.session.query(db.func.sum(CustomerPayment.amount)).filter_by(
            company_id=company_id).scalar() or 0

        # Get recent payments
        recent_supplier_payments = SupplierPayment.query.filter_by(company_id=company_id).order_by(
            SupplierPayment.created_at.desc()).limit(5).all()
        recent_customer_payments = CustomerPayment.query.filter_by(company_id=company_id).order_by(
            CustomerPayment.created_at.desc()).limit(5).all()

        # Get payment status breakdown
        supplier_status = db.session.query(
            SupplierPayment.status,
            db.func.count(SupplierPayment.id),
            db.func.sum(SupplierPayment.amount)
        ).filter_by(company_id=company_id).group_by(SupplierPayment.status).all()

        customer_status = db.session.query(
            CustomerPayment.status,
            db.func.count(CustomerPayment.id),
            db.func.sum(CustomerPayment.amount)
        ).filter_by(company_id=company_id).group_by(CustomerPayment.status).all()

        # Get current month's payments
        current_month = datetime.now().month
        current_year = datetime.now().year

        current_month_supplier = SupplierPayment.query.filter(
            SupplierPayment.company_id == company_id,
            db.extract('month', SupplierPayment.due_date) == current_month,
            db.extract('year', SupplierPayment.due_date) == current_year
        ).all()

        current_month_customer = CustomerPayment.query.filter(
            CustomerPayment.company_id == company_id,
            db.extract('month', CustomerPayment.due_date) == current_month,
            db.extract('year', CustomerPayment.due_date) == current_year
        ).all()

        current_month_total = sum(p.amount for p in current_month_supplier) + sum(
            p.amount for p in current_month_customer)

        return jsonify({
            'total_suppliers': total_suppliers,
            'total_customers': total_customers,
            'total_supplier_payments': total_supplier_payments,
            'total_customer_payments': total_customer_payments,
            'total_supplier_amount': total_supplier_amount,
            'total_customer_amount': total_customer_amount,
            'current_month_total': current_month_total,
            'recent_supplier_payments': [{
                'id': p.id,
                'supplier_name': p.supplier.name if p.supplier else '',
                'payment_description': p.payment_description,
                'amount': p.amount,
                'status': p.status,
                'due_date': p.due_date.isoformat() if p.due_date else None
            } for p in recent_supplier_payments],
            'recent_customer_payments': [{
                'id': p.id,
                'customer_name': p.customer.name if p.customer else '',
                'service_description': p.service_description,
                'amount': p.amount,
                'status': p.status,
                'due_date': p.due_date.isoformat() if p.due_date else None
            } for p in recent_customer_payments],
            'supplier_status': [{'status': s[0], 'count': s[1], 'total': s[2]} for s in supplier_status],
            'customer_status': [{'status': s[0], 'count': s[1], 'total': s[2]} for s in customer_status]
        })
    except Exception as e:
        print(f"Error in dashboard stats: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ============ SUPPLIER PAYMENT REPORT ROUTE ============
@app.route('/api/reports/supplier-payments', methods=['GET'])
def get_supplier_payment_report():
    try:
        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        # Get filter parameters
        supplier_id = request.args.get('supplier_id')
        status = request.args.get('status')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        # Build query
        query = SupplierPayment.query.filter_by(company_id=company_id)

        # Filter by supplier
        if supplier_id and supplier_id != 'all':
            query = query.filter(SupplierPayment.supplier_id == int(supplier_id))

        # Filter by status
        if status and status != 'all':
            query = query.filter(SupplierPayment.status == status)

        # Filter by date range
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(
                db.or_(
                    SupplierPayment.due_date >= start_date,
                    SupplierPayment.invoice_date >= start_date
                )
            )

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(
                db.or_(
                    SupplierPayment.due_date <= end_date,
                    SupplierPayment.invoice_date <= end_date
                )
            )

        # Get results
        payments = query.all()

        # Get all suppliers for dropdown (only for active company)
        suppliers = Supplier.query.filter_by(company_id=company_id).all()

        # Format response
        result = {
            'suppliers': [{'id': s.id, 'name': s.name} for s in suppliers],
            'payments': [{
                'id': p.id,
                'supplier_name': p.supplier.name if p.supplier else '',
                'payment_description': p.payment_description,
                'invoice_ref': p.invoice_ref,
                'amount': p.amount,
                'amount_formatted': format_currency(p.amount),
                'type': p.type,
                'due_date': p.due_date.isoformat() if p.due_date else None,
                'status': p.status,
                'invoice_date': p.invoice_date.isoformat() if p.invoice_date else None
            } for p in payments],
            'filters': {
                'supplier_id': supplier_id,
                'status': status,
                'start_date': start_date_str,
                'end_date': end_date_str
            }
        }

        print(f"Supplier Payment Report - Found {len(payments)} payments")
        return jsonify(result)

    except Exception as e:
        print(f"Error in supplier payment report: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


# ============ DATABASE INFO ROUTE ============
@app.route('/api/db-info')
def db_info():
    return jsonify({
        'database_path': database_path,
        'database_exists': os.path.exists(database_path),
        'upload_folder': app.config['UPLOAD_FOLDER'],
        'export_folder': app.config['EXPORT_FOLDER']
    })

# ============ PAYMENT SCHEDULE ROUTES ============
@app.route('/api/payment-schedule', methods=['GET'])
def get_payment_schedule():
    try:
        company_id = get_active_company_id()
        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        # Get filter parameters
        supplier_id = request.args.get('supplier_id')
        status = request.args.get('status', 'Pending')  # Default to Pending
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        payment_type = request.args.get('type')  # 'supplier' or 'customer'

        # Build supplier payments query - only Pending by default
        supplier_query = SupplierPayment.query.filter_by(company_id=company_id)
        customer_query = CustomerPayment.query.filter_by(company_id=company_id)

        # Filter by supplier
        if supplier_id and supplier_id != 'all':
            supplier_query = supplier_query.filter(SupplierPayment.supplier_id == int(supplier_id))

        # Filter by status - default to Pending
        if status and status != 'all':
            supplier_query = supplier_query.filter(SupplierPayment.status == status)
            customer_query = customer_query.filter(CustomerPayment.status == status)
        else:
            # Default: Only show Pending payments
            supplier_query = supplier_query.filter(SupplierPayment.status == 'Pending')
            customer_query = customer_query.filter(CustomerPayment.status == 'Pending')

        # Filter by date range
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            supplier_query = supplier_query.filter(
                db.or_(
                    SupplierPayment.due_date >= start_date,
                    SupplierPayment.invoice_date >= start_date
                )
            )
            customer_query = customer_query.filter(
                db.or_(
                    CustomerPayment.due_date >= start_date,
                    CustomerPayment.invoice_date >= start_date
                )
            )

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            supplier_query = supplier_query.filter(
                db.or_(
                    SupplierPayment.due_date <= end_date,
                    SupplierPayment.invoice_date <= end_date
                )
            )
            customer_query = customer_query.filter(
                db.or_(
                    CustomerPayment.due_date <= end_date,
                    CustomerPayment.invoice_date <= end_date
                )
            )

        # Get results
        supplier_payments = supplier_query.all()
        customer_payments = customer_query.all()

        # Format supplier payments
        formatted_supplier = [{
            'id': p.id,
            'type': 'supplier',
            'entity_name': p.supplier.name if p.supplier else '',
            'description': p.payment_description,
            'invoice_ref': p.invoice_ref,
            'amount': p.amount,
            'due_date': p.due_date.isoformat() if p.due_date else None,
            'status': p.status,
            'payment_type': 'Outflow'
        } for p in supplier_payments]

        # Format customer payments
        formatted_customer = [{
            'id': p.id,
            'type': 'customer',
            'entity_name': p.customer.name if p.customer else '',
            'description': p.service_description,
            'invoice_ref': p.invoice_ref,
            'amount': p.amount,
            'due_date': p.due_date.isoformat() if p.due_date else None,
            'status': p.status,
            'payment_type': 'Inflow'
        } for p in customer_payments]

        # Combine and sort by due date
        all_payments = formatted_supplier + formatted_customer
        all_payments.sort(key=lambda x: x['due_date'] if x['due_date'] else '9999-12-31')

        # Get suppliers for dropdown
        suppliers = Supplier.query.filter_by(company_id=company_id).all()

        return jsonify({
            'payments': all_payments,
            'suppliers': [{'id': s.id, 'name': s.name} for s in suppliers],
            'filters': {
                'supplier_id': supplier_id,
                'status': status,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'type': payment_type
            },
            'summary': {
                'total_supplier': len(formatted_supplier),
                'total_customer': len(formatted_customer),
                'total_amount': sum(p['amount'] for p in all_payments),
                'total_supplier_amount': sum(p['amount'] for p in formatted_supplier),
                'total_customer_amount': sum(p['amount'] for p in formatted_customer)
            }
        })

    except Exception as e:
        print(f"Error in payment schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


@app.route('/api/payment-schedule/export-pdf', methods=['POST'])
def export_payment_schedule_pdf():
    try:
        # Import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        data = request.json
        payment_ids = data.get('payment_ids', [])
        company_id = get_active_company_id()

        if not company_id:
            return jsonify({'error': 'No active company'}), 400

        if not payment_ids:
            return jsonify({'error': 'No payments selected'}), 400

        # Get the selected payments
        payments = []

        # Get supplier payments
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.id.in_(payment_ids),
            SupplierPayment.company_id == company_id
        ).all()

        # Get customer payments
        customer_payments = CustomerPayment.query.filter(
            CustomerPayment.id.in_(payment_ids),
            CustomerPayment.company_id == company_id
        ).all()

        # Format supplier payments
        for p in supplier_payments:
            payments.append({
                'id': p.id,
                'type': 'Supplier',
                'entity_name': p.supplier.name if p.supplier else '',
                'description': p.payment_description,
                'invoice_ref': p.invoice_ref,
                'amount': p.amount,
                'status': p.status,
            })

        # Format customer payments
        for p in customer_payments:
            payments.append({
                'id': p.id,
                'type': 'Customer',
                'entity_name': p.customer.name if p.customer else '',
                'description': p.service_description,
                'invoice_ref': p.invoice_ref,
                'amount': p.amount,
                'status': p.status,
            })

        # Sort by entity name
        payments.sort(key=lambda x: x['entity_name'])

        # Get company info
        company = db.session.get(Company, company_id)

        # Calculate total
        total_amount = sum(p['amount'] for p in payments)

        # Generate PDF
        filename = f'payment_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)

        doc = SimpleDocTemplate(filepath, pagesize=landscape(letter))
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=20
        )
        elements.append(Paragraph(f"Payment Schedule Report", title_style))
        elements.append(Paragraph(f"Company: {company.name}", styles['Normal']))
        elements.append(Paragraph(f"Date Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 12))

        # Payment table - without Due Date and Status columns
        table_data = [
            ['#', 'Type', 'Entity', 'Description', 'Invoice', 'Amount']
        ]

        for idx, p in enumerate(payments, 1):
            amount_str = f"{company.currency} {format_currency(p['amount'])}"

            table_data.append([
                str(idx),
                p['type'],
                p['entity_name'][:25] if p['entity_name'] else '-',
                p['description'][:30] if p['description'] else '-',
                p['invoice_ref'] or '-',
                amount_str
            ])

        # Add total row
        table_data.append([
            '', '', '', '', 'TOTAL',
            f"{company.currency} {format_currency(total_amount)}"
        ])

        # Create table - adjusted column widths
        table = Table(table_data, colWidths=[0.5 * inch, 0.8 * inch, 2 * inch, 2.5 * inch, 1.2 * inch, 1.2 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.lightgrey]),
            # Total row styling
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 10),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#2c3e50')),
            ('ALIGN', (5, -1), (5, -1), 'RIGHT'),
        ]))
        elements.append(table)

        # Build PDF
        doc.build(elements)

        return send_file(filepath, as_attachment=True, download_name=filename)

    except ImportError as e:
        print(f"ReportLab not installed: {str(e)}")
        return jsonify({'error': 'PDF library not installed. Please run: pip install reportlab'}), 500
    except Exception as e:
        print(f"PDF export error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print(f"PAYMENT SCHEDULE SYSTEM")
    print("=" * 60)
    print(f"Database Location: {database_path}")
    print(f"Upload Folder: {app.config['UPLOAD_FOLDER']}")
    print(f"Export Folder: {app.config['EXPORT_FOLDER']}")
    print("=" * 60)
    print("Server running at: http://localhost:5000")
    print("=" * 60 + "\n")

    app.run(debug=True, port=5000)