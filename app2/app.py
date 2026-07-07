from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import pandas as pd
import os
from io import BytesIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///assets.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


def ensure_database_schema():
    """Auto-add missing columns to companies table"""
    try:
        inspector = db.inspect(db.engine)

        if 'companies' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('companies')]

            # Define ALL required columns with their definitions
            required_columns = {
                'base_currency': "VARCHAR(3) NOT NULL DEFAULT 'USD'",
                'code': "VARCHAR(20) NOT NULL DEFAULT 'DEFAULT'",
                'address': "VARCHAR(200)",
                'phone': "VARCHAR(50)",
                'email': "VARCHAR(100)",
                'tax_id': "VARCHAR(50)"
            }

            missing = [col for col in required_columns if col not in columns]

            if missing:
                print(f"Adding missing columns: {missing}")
                with db.engine.connect() as conn:
                    # Begin transaction
                    conn.execute(db.text('BEGIN'))

                    # Add each missing column
                    for col, col_def in required_columns.items():
                        if col not in columns:
                            conn.execute(db.text(f'ALTER TABLE companies ADD COLUMN {col} {col_def}'))

                    # Add unique constraint for code if it was missing
                    if 'code' in missing:
                        constraints = inspector.get_unique_constraints('companies')
                        if not any(c.get('column_names', []) == ['code'] for c in constraints):
                            conn.execute(
                                db.text('ALTER TABLE companies ADD CONSTRAINT companies_code_key UNIQUE (code)'))

                    conn.execute(db.text('COMMIT'))
                print("✓ Database schema updated successfully")

    except Exception as e:
        print(f"⚠️ Schema update warning: {e}")


# ===== MODELS =====
class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    base_currency = db.Column(db.String(3), nullable=False, default='USD')
    created_date = db.Column(db.Date, default=datetime.now().date)
    is_active = db.Column(db.Boolean, default=True)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'base_currency': self.base_currency,
            'created_date': self.created_date.strftime('%Y-%m-%d') if self.created_date else '',
            'is_active': self.is_active,
            'address': self.address or '',
            'phone': self.phone or '',
            'email': self.email or '',
            'tax_id': self.tax_id or ''
        }


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='user')
    department = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_date = db.Column(db.Date, default=datetime.now().date)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)

    company = db.relationship('Company', backref='users')

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'role': self.role,
            'department': self.department or '',
            'phone': self.phone or '',
            'is_active': self.is_active,
            'created_date': self.created_date.strftime('%Y-%m-%d') if self.created_date else '',
            'company_id': self.company_id
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'department': self.department or ''
        }


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_date = db.Column(db.Date, default=datetime.now().date)
    description = db.Column(db.String(200))
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)

    company = db.relationship('Company', backref='categories')

    __table_args__ = (
        db.UniqueConstraint('name', 'company_id', name='unique_category_per_company'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'created_date': self.created_date.strftime('%Y-%m-%d') if self.created_date else '',
            'description': self.description or '',
            'company_id': self.company_id
        }


class Asset(db.Model):
    __tablename__ = 'assets'
    id = db.Column(db.Integer, primary_key=True)
    asset_no = db.Column(db.String(50), nullable=False)
    asset_category = db.Column(db.String(100), nullable=False, default='Uncategorized')
    description = db.Column(db.String(200), nullable=False)
    user = db.Column(db.String(100), nullable=False)
    serial_no = db.Column(db.String(100))
    condition = db.Column(db.String(50), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False)
    depreciation_start_date = db.Column(db.Date, nullable=False)
    useful_life_yrs = db.Column(db.Float, nullable=False)
    disposal_date = db.Column(db.Date)
    initial_cost = db.Column(db.Float, nullable=False)
    other_cost = db.Column(db.Float, default=0.0)
    entity = db.Column(db.String(100), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)

    company = db.relationship('Company', backref='assets')

    __table_args__ = (
        db.UniqueConstraint('asset_no', 'company_id', name='unique_asset_per_company'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'asset_no': self.asset_no,
            'asset_category': self.asset_category,
            'description': self.description,
            'user': self.user,
            'serial_no': self.serial_no,
            'condition': self.condition,
            'purchase_date': self.purchase_date.strftime('%Y-%m-%d') if self.purchase_date else '',
            'depreciation_start_date': self.depreciation_start_date.strftime(
                '%Y-%m-%d') if self.depreciation_start_date else '',
            'useful_life_yrs': self.useful_life_yrs,
            'disposal_date': self.disposal_date.strftime('%Y-%m-%d') if self.disposal_date else '',
            'initial_cost': self.initial_cost,
            'other_cost': self.other_cost,
            'entity': self.entity,
            'currency': self.currency,
            'company_id': self.company_id
        }


class AssetAssignment(db.Model):
    __tablename__ = 'asset_assignments'
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    assigned_to = db.Column(db.String(100), nullable=False)
    assigned_by = db.Column(db.String(100), nullable=False)
    assigned_date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    expected_return_date = db.Column(db.Date)
    actual_return_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='Active')
    notes = db.Column(db.String(500))
    returned_condition = db.Column(db.String(50))
    return_notes = db.Column(db.String(500))

    asset = db.relationship('Asset', backref='assignments')

    def to_dict(self):
        return {
            'id': self.id,
            'asset_id': self.asset_id,
            'asset_no': self.asset.asset_no if self.asset else '',
            'asset_description': self.asset.description if self.asset else '',
            'assigned_to': self.assigned_to,
            'assigned_by': self.assigned_by,
            'assigned_date': self.assigned_date.strftime('%Y-%m-%d') if self.assigned_date else '',
            'expected_return_date': self.expected_return_date.strftime('%Y-%m-%d') if self.expected_return_date else '',
            'actual_return_date': self.actual_return_date.strftime('%Y-%m-%d') if self.actual_return_date else '',
            'status': self.status,
            'notes': self.notes or '',
            'returned_condition': self.returned_condition or '',
            'return_notes': self.return_notes or '',
            'is_overdue': self.status == 'Active' and self.expected_return_date and self.expected_return_date < datetime.now().date()
        }


class AssetReturnForm(db.Model):
    __tablename__ = 'asset_return_forms'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('asset_assignments.id'), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    returned_by = db.Column(db.String(100), nullable=False)
    returned_date = db.Column(db.Date, nullable=False, default=datetime.now().date)
    condition = db.Column(db.String(50), nullable=False)
    damage_description = db.Column(db.String(500))
    maintenance_required = db.Column(db.Boolean, default=False)
    maintenance_notes = db.Column(db.String(500))
    signature = db.Column(db.String(200))
    received_by = db.Column(db.String(100))
    notes = db.Column(db.String(500))
    attachment_path = db.Column(db.String(500))
    attachment_filename = db.Column(db.String(200))

    assignment = db.relationship('AssetAssignment', backref='return_form')
    asset = db.relationship('Asset', backref='return_forms')

    def to_dict(self):
        return {
            'id': self.id,
            'assignment_id': self.assignment_id,
            'asset_id': self.asset_id,
            'asset_no': self.asset.asset_no if self.asset else '',
            'asset_description': self.asset.description if self.asset else '',
            'returned_by': self.returned_by,
            'returned_date': self.returned_date.strftime('%Y-%m-%d') if self.returned_date else '',
            'condition': self.condition,
            'damage_description': self.damage_description or '',
            'maintenance_required': self.maintenance_required,
            'maintenance_notes': self.maintenance_notes or '',
            'signature': self.signature or '',
            'received_by': self.received_by or '',
            'notes': self.notes or '',
            'attachment_path': self.attachment_path or '',
            'attachment_filename': self.attachment_filename or ''
        }


def get_current_company():
    """Get the current company from session or app config"""
    # First check if there's a company_id in the session (for logged-in users)
    company_id = session.get('current_company_id')
    if company_id:
        company = Company.query.get(company_id)
        if company:
            return company

    # Fall back to the app config default
    company_id = app.config.get('CURRENT_COMPANY_ID')
    if company_id:
        company = Company.query.get(company_id)
        if company:
            return company

    # Last resort: get the default company from the database
    default = Company.query.filter_by(code='DEFAULT').first()
    if default:
        session['current_company_id'] = default.id
        return default
    return None


# ===== DATABASE INITIALIZATION =====
with app.app_context():
    print("Creating database tables...")
    db.create_all()
    print("✓ Tables created")

    print("Ensuring schema is up to date...")
    ensure_database_schema()

    # Create or update default company
    print("Setting up default company...")
    default_company = Company.query.filter_by(code='DEFAULT').first()
    if not default_company:
        default_company = Company(
            name='Default Company',
            code='DEFAULT',
            base_currency='USD',
            created_date=datetime.now().date(),
            is_active=True,
            address='',
            phone='',
            email='',
            tax_id=''
        )
        db.session.add(default_company)
        db.session.commit()
        print("✓ Added default company")
    else:
        # Ensure existing company has all fields populated
        if not default_company.base_currency:
            default_company.base_currency = 'USD'
        if not default_company.address:
            default_company.address = ''
        if not default_company.phone:
            default_company.phone = ''
        if not default_company.email:
            default_company.email = ''
        if not default_company.tax_id:
            default_company.tax_id = ''
        db.session.commit()
        print("✓ Default company updated")

    # Create admin user
    admin_user = User.query.filter_by(full_name='System Administrator', company_id=default_company.id).first()
    if not admin_user:
        admin_user = User(
            full_name='System Administrator',
            role='admin',
            department='IT',
            is_active=True,
            created_date=datetime.now().date(),
            company_id=default_company.id
        )
        db.session.add(admin_user)
        db.session.commit()
        print("✓ Created admin user")

    # Store the default company ID in app config for use outside request context
    app.config['CURRENT_COMPANY_ID'] = default_company.id
    print(f"✓ Default company set: {default_company.name}")


# ===== ROUTES =====
@app.route('/')
def index():
    company = get_current_company()
    return render_template('index.html', company=company)


@app.route('/api/companies')
def get_companies():
    companies = Company.query.all()
    return jsonify({'companies': [c.to_dict() for c in companies]})


@app.route('/api/companies', methods=['POST'])
def create_company():
    try:
        data = request.json
        name = data.get('name', '').strip()
        code = data.get('code', '').strip().upper()
        base_currency = data.get('base_currency', 'USD').strip().upper()
        address = data.get('address', '')
        phone = data.get('phone', '')
        email = data.get('email', '')
        tax_id = data.get('tax_id', '')

        if not name:
            return jsonify({'success': False, 'error': 'Company name is required'}), 400
        if not code:
            return jsonify({'success': False, 'error': 'Company code is required'}), 400

        existing = Company.query.filter_by(name=name).first()
        if existing:
            return jsonify({'success': False, 'error': 'Company name already exists'}), 400

        existing_code = Company.query.filter_by(code=code).first()
        if existing_code:
            return jsonify({'success': False, 'error': 'Company code already exists'}), 400

        company = Company(
            name=name,
            code=code,
            base_currency=base_currency,
            created_date=datetime.now().date(),
            is_active=True,
            address=address,
            phone=phone,
            email=email,
            tax_id=tax_id
        )
        db.session.add(company)
        db.session.commit()

        session['current_company_id'] = company.id

        return jsonify({
            'success': True,
            'message': f'Company "{name}" created successfully',
            'company': company.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/companies/<int:company_id>/switch', methods=['POST'])
def switch_company(company_id):
    try:
        company = Company.query.get_or_404(company_id)
        session['current_company_id'] = company.id
        return jsonify({
            'success': True,
            'message': f'Switched to {company.name}',
            'company': company.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/companies/<int:company_id>', methods=['PUT'])
def update_company(company_id):
    try:
        company = Company.query.get_or_404(company_id)
        data = request.json

        if company.code == 'DEFAULT':
            company.address = data.get('address', company.address)
            company.phone = data.get('phone', company.phone)
            company.email = data.get('email', company.email)
            company.tax_id = data.get('tax_id', company.tax_id)
        else:
            company.name = data.get('name', company.name)
            company.code = data.get('code', company.code).upper()
            company.base_currency = data.get('base_currency', company.base_currency).upper()
            company.address = data.get('address', company.address)
            company.phone = data.get('phone', company.phone)
            company.email = data.get('email', company.email)
            company.tax_id = data.get('tax_id', company.tax_id)
            company.is_active = data.get('is_active', company.is_active)

        db.session.commit()
        return jsonify({'success': True, 'company': company.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/companies/<int:company_id>', methods=['DELETE'])
def delete_company(company_id):
    try:
        company = Company.query.get_or_404(company_id)
        if company.code == 'DEFAULT':
            return jsonify({'success': False, 'error': 'Cannot delete the default company'}), 400

        asset_count = Asset.query.filter_by(company_id=company_id).count()
        if asset_count > 0:
            return jsonify({
                'success': False,
                'error': f'Cannot delete company with {asset_count} assets. Please reassign or delete assets first.'
            }), 400

        Category.query.filter_by(company_id=company_id).delete()
        User.query.filter_by(company_id=company_id).delete()

        if session.get('current_company_id') == company_id:
            default = Company.query.filter_by(code='DEFAULT').first()
            if default:
                session['current_company_id'] = default.id

        db.session.delete(company)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Company deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/current-company')
def get_current_company_api():
    company = get_current_company()
    if company:
        return jsonify({'success': True, 'company': company.to_dict()})
    return jsonify({'success': False, 'error': 'No company found'}), 404


@app.route('/api/users')
def get_users():
    company = get_current_company()
    if not company:
        return jsonify({'users': []})

    users = User.query.filter_by(company_id=company.id).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@app.route('/api/users/simple')
def get_users_simple():
    company = get_current_company()
    if not company:
        return jsonify({'users': []})

    users = User.query.filter_by(company_id=company.id, is_active=True).all()
    return jsonify({'users': [u.to_dict_simple() for u in users]})


@app.route('/api/users', methods=['POST'])
def create_user():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        data = request.json
        full_name = data.get('full_name', '').strip()
        role = data.get('role', 'user')
        department = data.get('department', '')
        phone = data.get('phone', '')

        if not full_name:
            return jsonify({'success': False, 'error': 'Full name is required'}), 400

        user = User(
            full_name=full_name,
            role=role,
            department=department,
            phone=phone,
            is_active=True,
            created_date=datetime.now().date(),
            company_id=company.id
        )
        db.session.add(user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'User "{full_name}" created successfully',
            'user': user.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        user = User.query.filter_by(id=user_id, company_id=company.id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        data = request.json
        user.full_name = data.get('full_name', user.full_name)
        user.role = data.get('role', user.role)
        user.department = data.get('department', user.department)
        user.phone = data.get('phone', user.phone)
        user.is_active = data.get('is_active', user.is_active)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'User "{user.full_name}" updated successfully',
            'user': user.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        user = User.query.filter_by(id=user_id, company_id=company.id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        admin_count = User.query.filter_by(company_id=company.id, role='admin', is_active=True).count()
        if user.role == 'admin' and admin_count <= 1:
            return jsonify({'success': False, 'error': 'Cannot delete the last admin user'}), 400

        db.session.delete(user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'User deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/users/<int:user_id>/toggle-status', methods=['POST'])
def toggle_user_status(user_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        user = User.query.filter_by(id=user_id, company_id=company.id).first()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        user.is_active = not user.is_active
        db.session.commit()

        status = 'activated' if user.is_active else 'deactivated'
        return jsonify({
            'success': True,
            'message': f'User "{user.full_name}" {status} successfully',
            'user': user.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assets')
def get_assets():
    company = get_current_company()
    if not company:
        return jsonify([])
    assets = Asset.query.filter_by(company_id=company.id).all()
    return jsonify([asset.to_dict() for asset in assets])


@app.route('/api/assets', methods=['POST'])
def add_asset():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        data = request.json
        asset = Asset(
            asset_no=data['asset_no'],
            asset_category=data.get('asset_category', 'Uncategorized'),
            description=data['description'],
            user=data['user'],
            serial_no=data.get('serial_no', ''),
            condition=data['condition'],
            purchase_date=datetime.strptime(data['purchase_date'], '%Y-%m-%d').date(),
            depreciation_start_date=datetime.strptime(data['depreciation_start_date'], '%Y-%m-%d').date(),
            useful_life_yrs=float(data['useful_life_yrs']),
            disposal_date=datetime.strptime(data['disposal_date'], '%Y-%m-%d').date() if data.get(
                'disposal_date') else None,
            initial_cost=float(data['initial_cost']),
            other_cost=float(data.get('other_cost', 0)),
            entity=data['entity'],
            currency=data['currency'],
            company_id=company.id
        )
        db.session.add(asset)
        db.session.commit()
        return jsonify({'success': True, 'asset': asset.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assets/<int:asset_id>', methods=['PUT'])
def update_asset(asset_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        asset = Asset.query.filter_by(id=asset_id, company_id=company.id).first_or_404()
        data = request.json

        asset.asset_no = data['asset_no']
        asset.asset_category = data.get('asset_category', 'Uncategorized')
        asset.description = data['description']
        asset.user = data['user']
        asset.serial_no = data.get('serial_no', '')
        asset.condition = data['condition']
        asset.purchase_date = datetime.strptime(data['purchase_date'], '%Y-%m-%d').date()
        asset.depreciation_start_date = datetime.strptime(data['depreciation_start_date'], '%Y-%m-%d').date()
        asset.useful_life_yrs = float(data['useful_life_yrs'])
        asset.disposal_date = datetime.strptime(data['disposal_date'], '%Y-%m-%d').date() if data.get(
            'disposal_date') else None
        asset.initial_cost = float(data['initial_cost'])
        asset.other_cost = float(data.get('other_cost', 0))
        asset.entity = data['entity']
        asset.currency = data['currency']

        db.session.commit()
        return jsonify({'success': True, 'asset': asset.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assets/<int:asset_id>', methods=['DELETE'])
def delete_asset(asset_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        asset = Asset.query.filter_by(id=asset_id, company_id=company.id).first_or_404()
        db.session.delete(asset)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/categories')
def get_categories():
    company = get_current_company()
    if not company:
        return jsonify({'categories': []})
    categories = Category.query.filter_by(company_id=company.id).order_by(Category.name).all()
    return jsonify({'categories': [c.name for c in categories]})


@app.route('/api/categories/all')
def get_all_categories():
    company = get_current_company()
    if not company:
        return jsonify({'categories': []})
    categories = Category.query.filter_by(company_id=company.id).order_by(Category.name).all()
    return jsonify({'categories': [c.to_dict() for c in categories]})


@app.route('/api/categories', methods=['POST'])
def add_category():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        data = request.json
        category_name = data.get('category', '').strip()

        if not category_name:
            return jsonify({'success': False, 'error': 'Category name is required'}), 400

        existing = Category.query.filter_by(name=category_name, company_id=company.id).first()
        if existing:
            return jsonify({'success': False, 'error': 'Category already exists'}), 400

        new_category = Category(
            name=category_name,
            created_date=datetime.now().date(),
            company_id=company.id
        )
        db.session.add(new_category)
        db.session.commit()

        return jsonify({'success': True, 'message': f'Category "{category_name}" created successfully',
                        'category': new_category.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/categories/<category_name>', methods=['DELETE'])
def delete_category(category_name):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        category = Category.query.filter_by(name=category_name, company_id=company.id).first()
        if not category:
            return jsonify({'success': False, 'error': 'Category not found'}), 404

        assets = Asset.query.filter_by(asset_category=category_name, company_id=company.id).all()
        for asset in assets:
            asset.asset_category = 'Uncategorized'

        db.session.delete(category)
        db.session.commit()

        return jsonify({'success': True,
                        'message': f'Category "{category_name}" deleted. {len(assets)} assets reassigned to "Uncategorized".'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assignments')
def get_assignments():
    company = get_current_company()
    if not company:
        return jsonify({'assignments': []})

    assignments = AssetAssignment.query.join(Asset).filter(Asset.company_id == company.id).all()
    return jsonify({'assignments': [a.to_dict() for a in assignments]})


@app.route('/api/assignments', methods=['POST'])
def create_assignment():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        data = request.json
        asset = Asset.query.filter_by(id=data['asset_id'], company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        if data.get('user_id'):
            user = User.query.filter_by(id=data['user_id'], company_id=company.id, is_active=True).first()
            if not user:
                return jsonify({'success': False, 'error': 'User not found or inactive'}), 400
            assigned_to = user.full_name
        else:
            assigned_to = data.get('assigned_to', '')

        if not assigned_to:
            return jsonify({'success': False, 'error': 'Please specify who to assign the asset to'}), 400

        # Check if asset is already assigned
        active_assignment = AssetAssignment.query.filter_by(asset_id=data['asset_id'], status='Active').first()
        if active_assignment:
            # If asset is already assigned, return it first (automatically)
            active_assignment.status = 'Returned'
            active_assignment.actual_return_date = datetime.now().date()
            active_assignment.returned_condition = 'Good'
            active_assignment.return_notes = 'Auto-returned for reassignment'

            # Also create a return form for the auto-return
            return_form = AssetReturnForm(
                assignment_id=active_assignment.id,
                asset_id=asset.id,
                returned_by=active_assignment.assigned_to,
                returned_date=datetime.now().date(),
                condition='Good',
                damage_description='Auto-returned for reassignment',
                maintenance_required=False,
                notes=f'Asset reassigned to {assigned_to}'
            )
            db.session.add(return_form)

        # Create new assignment
        assignment = AssetAssignment(
            asset_id=data['asset_id'],
            assigned_to=assigned_to,
            assigned_by=data.get('assigned_by', 'System'),
            assigned_date=datetime.strptime(data['assigned_date'], '%Y-%m-%d').date() if data.get(
                'assigned_date') else datetime.now().date(),
            expected_return_date=datetime.strptime(data['expected_return_date'], '%Y-%m-%d').date() if data.get(
                'expected_return_date') else None,
            notes=data.get('notes', '')
        )
        db.session.add(assignment)

        # CRITICAL: Update the asset's user field to the new user
        asset.user = assigned_to

        db.session.commit()

        return jsonify({'success': True, 'assignment': assignment.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assignments/<int:assignment_id>/return', methods=['POST'])
def return_asset(assignment_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        assignment = AssetAssignment.query.get_or_404(assignment_id)
        asset = Asset.query.filter_by(id=assignment.asset_id, company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        data = request.json

        assignment.actual_return_date = datetime.strptime(data['return_date'], '%Y-%m-%d').date() if data.get(
            'return_date') else datetime.now().date()
        assignment.status = 'Returned'
        assignment.returned_condition = data.get('condition', 'Good')
        assignment.return_notes = data.get('notes', '')

        return_form = AssetReturnForm(
            assignment_id=assignment.id,
            asset_id=asset.id,
            returned_by=data.get('returned_by', assignment.assigned_to),
            returned_date=datetime.strptime(data['return_date'], '%Y-%m-%d').date() if data.get(
                'return_date') else datetime.now().date(),
            condition=data.get('condition', 'Good'),
            damage_description=data.get('damage_description', ''),
            maintenance_required=data.get('maintenance_required', False),
            maintenance_notes=data.get('maintenance_notes', ''),
            signature=data.get('signature', ''),
            received_by=data.get('received_by', ''),
            notes=data.get('notes', '')
        )
        db.session.add(return_form)

        asset.user = 'Unassigned'
        db.session.commit()

        return jsonify({'success': True, 'assignment': assignment.to_dict(), 'return_form': return_form.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assignments/asset/<int:asset_id>/history')
def get_asset_assignment_history(asset_id):
    company = get_current_company()
    if not company:
        return jsonify({'assignments': []})

    assignments = AssetAssignment.query.filter_by(asset_id=asset_id).order_by(
        AssetAssignment.assigned_date.desc()).all()
    return jsonify({'assignments': [a.to_dict() for a in assignments]})


@app.route('/api/return-forms')
def get_return_forms():
    company = get_current_company()
    if not company:
        return jsonify({'return_forms': []})

    return_forms = AssetReturnForm.query.join(Asset).filter(Asset.company_id == company.id).order_by(
        AssetReturnForm.returned_date.desc()).all()
    return jsonify({'return_forms': [f.to_dict() for f in return_forms]})


@app.route('/api/return-forms/<int:form_id>/attachment', methods=['POST'])
def upload_return_form_attachment(form_id):
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        return_form = AssetReturnForm.query.get_or_404(form_id)
        asset = Asset.query.filter_by(id=return_form.asset_id, company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        upload_dir = os.path.join('uploads', 'return_forms')
        os.makedirs(upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"return_form_{form_id}_{timestamp}_{file.filename}"
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        return_form.attachment_path = filepath
        return_form.attachment_filename = file.filename
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'attachment_path': filepath,
            'attachment_filename': file.filename
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/return-forms/<int:form_id>/attachment')
def get_return_form_attachment(form_id):
    try:
        return_form = AssetReturnForm.query.get_or_404(form_id)

        if not return_form.attachment_path or not os.path.exists(return_form.attachment_path):
            return jsonify({'error': 'No attachment found'}), 404

        return send_file(
            return_form.attachment_path,
            as_attachment=True,
            download_name=return_form.attachment_filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/export/excel')
def export_excel():
    company = get_current_company()
    if not company:
        return jsonify({'error': 'No company selected'}), 400

    assets = Asset.query.filter_by(company_id=company.id).all()
    data = [asset.to_dict() for asset in assets]

    if not data:
        df = pd.DataFrame(columns=['ASSET NO.', 'ASSET CATEGORY', 'DESCRIPTION', 'USER', 'SERIAL NO.', 'CONDITION',
                                   'Purchase Date', 'Depreciation Start Date', 'Useful life (Yrs)',
                                   'DISPOSAL Date', 'INITIAL COST', 'OTHER COST', 'Entity', 'Currency'])
    else:
        df = pd.DataFrame(data)
        if 'id' in df.columns:
            df = df.drop('id', axis=1)
        if 'company_id' in df.columns:
            df = df.drop('company_id', axis=1)

        column_order = ['asset_no', 'asset_category', 'description', 'user', 'serial_no', 'condition',
                        'purchase_date', 'depreciation_start_date', 'useful_life_yrs',
                        'disposal_date', 'initial_cost', 'other_cost', 'entity', 'currency']

        df = df[column_order]
        df.columns = ['ASSET NO.', 'ASSET CATEGORY', 'DESCRIPTION', 'USER', 'SERIAL NO.', 'CONDITION',
                      'Purchase Date', 'Depreciation Start Date', 'Useful life (Yrs)',
                      'DISPOSAL Date', 'INITIAL COST', 'OTHER COST', 'Entity', 'Currency']

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Assets', index=False)

        worksheet = writer.sheets['Assets']
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

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'asset_register_{company.code}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


@app.route('/import/excel', methods=['POST'])
def import_excel():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({'success': False, 'error': 'Please upload an Excel file (.xlsx or .xls)'}), 400

        try:
            df = pd.read_excel(file, engine='openpyxl')
        except Exception as e1:
            try:
                file.seek(0)
                df = pd.read_excel(file)
            except Exception as e2:
                return jsonify({'success': False, 'error': f'Error reading Excel file: {str(e2)}'}), 400

        if df.empty:
            return jsonify({'success': False, 'error': 'The Excel file is empty'}), 400

        df.columns = df.columns.str.strip()

        required_columns = ['ASSET NO.', 'DESCRIPTION', 'USER', 'CONDITION', 'Purchase Date',
                            'Depreciation Start Date', 'Useful life (Yrs)', 'INITIAL COST', 'Entity', 'Currency']

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return jsonify({'success': False, 'error': f'Missing required columns: {", ".join(missing_columns)}'}), 400

        imported_count = 0
        skipped_count = 0
        errors = []

        existing_categories = {}
        for cat in Category.query.filter_by(company_id=company.id).all():
            existing_categories[cat.name.lower()] = cat.name

        for index, row in df.iterrows():
            try:
                if pd.isna(row.get('ASSET NO.')) or str(row.get('ASSET NO.')).strip() == '':
                    skipped_count += 1
                    continue

                asset_no = str(row['ASSET NO.']).strip()
                existing = Asset.query.filter_by(asset_no=asset_no, company_id=company.id).first()
                if existing:
                    errors.append(f"Row {index + 2}: Asset No. {asset_no} already exists")
                    skipped_count += 1
                    continue

                category = 'Uncategorized'
                if 'ASSET CATEGORY' in df.columns and pd.notna(row.get('ASSET CATEGORY')):
                    category_name = str(row['ASSET CATEGORY']).strip()
                    if category_name and category_name != 'Uncategorized':
                        existing_name = existing_categories.get(category_name.lower())
                        if existing_name:
                            category = existing_name
                        else:
                            new_category = Category(
                                name=category_name,
                                created_date=datetime.now().date(),
                                company_id=company.id
                            )
                            db.session.add(new_category)
                            db.session.flush()
                            existing_categories[category_name.lower()] = category_name
                            category = category_name

                try:
                    purchase_date = pd.to_datetime(row['Purchase Date']).date()
                except:
                    errors.append(f"Row {index + 2}: Invalid Purchase Date format")
                    skipped_count += 1
                    continue

                try:
                    depreciation_start_date = pd.to_datetime(row['Depreciation Start Date']).date()
                except:
                    errors.append(f"Row {index + 2}: Invalid Depreciation Start Date format")
                    skipped_count += 1
                    continue

                disposal_date = None
                if 'DISPOSAL Date' in df.columns and pd.notna(row.get('DISPOSAL Date')) and str(
                        row.get('DISPOSAL Date')).strip():
                    try:
                        disposal_date = pd.to_datetime(row['DISPOSAL Date']).date()
                    except:
                        errors.append(f"Row {index + 2}: Invalid Disposal Date format")
                        skipped_count += 1
                        continue

                other_cost = 0
                if 'OTHER COST' in df.columns and pd.notna(row.get('OTHER COST')):
                    try:
                        other_cost = float(row['OTHER COST'])
                    except:
                        other_cost = 0

                try:
                    useful_life = float(row['Useful life (Yrs)'])
                except:
                    errors.append(f"Row {index + 2}: Invalid Useful life value")
                    skipped_count += 1
                    continue

                try:
                    initial_cost = float(row['INITIAL COST'])
                except:
                    errors.append(f"Row {index + 2}: Invalid INITIAL COST value")
                    skipped_count += 1
                    continue

                asset = Asset(
                    asset_no=asset_no,
                    asset_category=category,
                    description=str(row['DESCRIPTION']).strip(),
                    user=str(row['USER']).strip(),
                    serial_no=str(row.get('SERIAL NO.', '')).strip() if 'SERIAL NO.' in df.columns and pd.notna(
                        row.get('SERIAL NO.')) else '',
                    condition=str(row['CONDITION']).strip(),
                    purchase_date=purchase_date,
                    depreciation_start_date=depreciation_start_date,
                    useful_life_yrs=useful_life,
                    disposal_date=disposal_date,
                    initial_cost=initial_cost,
                    other_cost=other_cost,
                    entity=str(row['Entity']).strip(),
                    currency=str(row['Currency']).strip() if 'Currency' in df.columns else company.base_currency,
                    company_id=company.id
                )
                db.session.add(asset)
                imported_count += 1

            except Exception as e:
                errors.append(f"Row {index + 2}: {str(e)}")
                skipped_count += 1
                continue

        db.session.commit()

        message = f'Successfully imported {imported_count} assets'
        if skipped_count > 0:
            message += f', skipped {skipped_count} rows'
        if errors:
            message += f'. First few errors: {"; ".join(errors[:3])}'

        return jsonify({'success': True, 'message': message, 'imported': imported_count, 'skipped': skipped_count,
                        'errors': errors[:5]})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/download/template/asset-import')
def download_asset_import_template():
    template_data = {
        'ASSET NO.': ['A001', 'A002', 'A003'],
        'ASSET CATEGORY': ['Electronics', 'Furniture', 'Vehicles'],
        'DESCRIPTION': ['Laptop Dell XPS', 'Office Chair', 'Toyota Camry'],
        'USER': ['Unassigned', 'Unassigned', 'Unassigned'],
        'SERIAL NO.': ['SN123456', 'CH789012', 'VIN987654'],
        'CONDITION': ['Good', 'Excellent', 'Fair'],
        'Purchase Date': ['2024-01-01', '2024-01-15', '2024-02-01'],
        'Depreciation Start Date': ['2024-01-01', '2024-01-15', '2024-02-01'],
        'Useful life (Yrs)': [3, 5, 8],
        'DISPOSAL Date': ['', '', ''],
        'INITIAL COST': [1200.00, 350.00, 25000.00],
        'OTHER COST': [50.00, 0.00, 1000.00],
        'Entity': ['IT Department', 'Facilities', 'Transport'],
        'Currency': ['USD', 'USD', 'USD']
    }

    df = pd.DataFrame(template_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Asset Template', index=False)

        instructions_df = pd.DataFrame({
            'Instructions': [
                'HOW TO USE THIS TEMPLATE:',
                '1. Do not modify the column headers',
                '2. Fill in your asset data starting from row 2',
                '3. ASSET NO. must be unique',
                '4. Date format must be YYYY-MM-DD (e.g., 2024-01-01)',
                '5. Leave DISPOSAL Date empty if asset is still active',
                '6. ASSET CATEGORY examples: Electronics, Furniture, Vehicles, etc.',
                '7. Required fields: ASSET NO., DESCRIPTION, USER, CONDITION,',
                '   Purchase Date, Depreciation Start Date, Useful life (Yrs),',
                '   INITIAL COST, Entity, Currency',
                '8. Save the file and use the Import Assets button to upload'
            ]
        })
        instructions_df.to_excel(writer, sheet_name='Instructions', index=False)

        for sheetname in writer.sheets:
            worksheet = writer.sheets[sheetname]
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

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='asset_import_template.xlsx'
    )


@app.route('/download/template/assignment')
def download_assignment_template():
    template_data = {
        'ASSET NO.': ['A001', 'A002'],
        'ASSET DESCRIPTION': ['Laptop Dell XPS', 'Office Chair'],
        'ASSIGNED TO': ['John Doe', 'Jane Smith'],
        'ASSIGNED BY': ['Admin', 'Admin'],
        'ASSIGNED DATE': ['2024-01-15', '2024-01-20'],
        'EXPECTED RETURN DATE': ['2024-06-15', '2024-06-20'],
        'NOTES': ['For project XYZ', 'For office renovation']
    }

    df = pd.DataFrame(template_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Assignment Template', index=False)

        instructions_df = pd.DataFrame({
            'Instructions': [
                'HOW TO USE THIS TEMPLATE:',
                '1. Do not modify the column headers',
                '2. Fill in your assignment data starting from row 2',
                '3. ASSET NO. must match an existing asset in the system',
                '4. ASSIGNED TO is the person receiving the asset',
                '5. ASSIGNED BY is who is assigning it (usually admin)',
                '6. Date format must be YYYY-MM-DD (e.g., 2024-01-15)',
                '7. Leave fields empty if not applicable',
                '8. Save the file and use the Import Assignments button to upload'
            ]
        })
        instructions_df.to_excel(writer, sheet_name='Instructions', index=False)

        for sheetname in writer.sheets:
            worksheet = writer.sheets[sheetname]
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

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='assignment_template.xlsx'
    )


@app.route('/download/template/return-form')
def download_return_form_template():
    template_data = {
        'ASSET NO.': ['A001', 'A002'],
        'ASSET DESCRIPTION': ['Laptop Dell XPS', 'Office Chair'],
        'RETURNED BY': ['John Doe', 'Jane Smith'],
        'RETURN DATE': ['2024-05-20', '2024-06-25'],
        'CONDITION': ['Good', 'Fair'],
        'DAMAGE DESCRIPTION': ['Minor scratch on screen', 'Wobbly armrest'],
        'MAINTENANCE REQUIRED': ['Yes', 'No'],
        'MAINTENANCE NOTES': ['Screen needs replacement', ''],
        'RECEIVED BY': ['Admin', 'Admin'],
        'SIGNATURE': ['John Doe', 'Jane Smith'],
        'NOTES': ['Returned early', 'Returned on time']
    }

    df = pd.DataFrame(template_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Return Form Template', index=False)

        instructions_df = pd.DataFrame({
            'Instructions': [
                'HOW TO USE THIS TEMPLATE:',
                '1. Do not modify the column headers',
                '2. Fill in your return form data starting from row 2',
                '3. ASSET NO. must match an existing asset in the system',
                '4. Condition options: New, Good, Fair, Poor, Damaged',
                '5. Date format must be YYYY-MM-DD (e.g., 2024-05-20)',
                '6. MAINTENANCE REQUIRED: Yes or No',
                '7. Leave fields empty if not applicable',
                '8. Save the file and use the Import Return Forms button to upload'
            ]
        })
        instructions_df.to_excel(writer, sheet_name='Instructions', index=False)

        for sheetname in writer.sheets:
            worksheet = writer.sheets[sheetname]
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

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='return_form_template.xlsx'
    )


@app.route('/download/template/supplier')
def download_supplier_template():
    template_data = {
        'SUPPLIER CODE': ['SUP001', 'SUP002'],
        'SUPPLIER NAME': ['Tech Supplies Ltd', 'Office Furniture Co'],
        'CONTACT PERSON': ['Sarah Johnson', 'Mike Peters'],
        'EMAIL': ['sarah@techsupplies.com', 'mike@officefurniture.com'],
        'PHONE': ['+1234567890', '+0987654321'],
        'ADDRESS': ['123 Tech Street, City', '456 Furniture Ave, City'],
        'TAX ID': ['TAX123456', 'TAX789012'],
        'PAYMENT TERMS': ['Net 30', 'Net 45'],
        'CATEGORY': ['Electronics', 'Furniture'],
        'NOTES': ['Preferred supplier for laptops', 'Good quality chairs']
    }

    df = pd.DataFrame(template_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Supplier Template', index=False)

        instructions_df = pd.DataFrame({
            'Instructions': [
                'HOW TO USE THIS TEMPLATE:',
                '1. Do not modify the column headers',
                '2. Fill in your supplier data starting from row 2',
                '3. SUPPLIER CODE must be unique',
                '4. SUPPLIER NAME is required',
                '5. CATEGORY examples: Electronics, Furniture, Vehicles, etc.',
                '6. Leave fields empty if not applicable',
                '7. Save the file and use the Import Suppliers button to upload'
            ]
        })
        instructions_df.to_excel(writer, sheet_name='Instructions', index=False)

        for sheetname in writer.sheets:
            worksheet = writer.sheets[sheetname]
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

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='supplier_template.xlsx'
    )


def calculate_asset_depreciation(asset):
    total_cost = asset.initial_cost + asset.other_cost
    annual_depreciation = total_cost / asset.useful_life_yrs if asset.useful_life_yrs > 0 else 0
    monthly_depreciation = annual_depreciation / 12

    if asset.disposal_date:
        end_date = asset.disposal_date
    else:
        end_date = datetime.now().date()

    if asset.disposal_date:
        months_diff = (asset.disposal_date.year - asset.depreciation_start_date.year) * 12 + (
                asset.disposal_date.month - asset.depreciation_start_date.month)
    else:
        months_diff = (datetime.now().date().year - asset.depreciation_start_date.year) * 12 + (
                datetime.now().date().month - asset.depreciation_start_date.month)

    total_months = asset.useful_life_yrs * 12
    months_diff = min(months_diff, total_months)

    accumulated_depreciation = monthly_depreciation * months_diff
    accumulated_depreciation = min(accumulated_depreciation, total_cost)
    net_book_value = total_cost - accumulated_depreciation

    yearly_breakdown = []
    current_date = asset.depreciation_start_date
    months_elapsed = 0

    for year in range(1, int(asset.useful_life_yrs) + 1):
        year_depreciation = 0
        year_start = current_date
        year_end = current_date.replace(year=current_date.year + 1)

        months_in_year = 12
        if asset.disposal_date and asset.disposal_date < year_end:
            months_in_year = (asset.disposal_date.year - current_date.year) * 12 + (
                    asset.disposal_date.month - current_date.month)
            months_in_year = max(0, months_in_year)

        year_depreciation = monthly_depreciation * months_in_year

        total_depreciated = sum(d['depreciation'] for d in yearly_breakdown) + year_depreciation
        if total_depreciated > total_cost:
            year_depreciation = total_cost - sum(d['depreciation'] for d in yearly_breakdown)

        months_elapsed += months_in_year
        accumulated = monthly_depreciation * months_elapsed

        yearly_breakdown.append({
            'asset_no': asset.asset_no,
            'description': asset.description,
            'year': year,
            'year_start': current_date.strftime('%Y-%m-%d'),
            'year_end': year_end.strftime('%Y-%m-%d'),
            'depreciation': round(year_depreciation, 2),
            'accumulated_depreciation': round(min(accumulated, total_cost), 2),
            'net_book_value': round(max(total_cost - accumulated, 0), 2)
        })

        current_date = year_end
        if asset.disposal_date and current_date > asset.disposal_date:
            break

    return {
        'asset': asset,
        'total_cost': total_cost,
        'annual_depreciation': round(annual_depreciation, 2),
        'monthly_depreciation': round(monthly_depreciation, 2),
        'accumulated_depreciation': round(accumulated_depreciation, 2),
        'net_book_value': round(net_book_value, 2),
        'depreciation_percentage': round((accumulated_depreciation / total_cost) * 100, 2) if total_cost > 0 else 0,
        'months_elapsed': months_diff,
        'total_months': total_months,
        'yearly_breakdown': yearly_breakdown,
        'is_active': not asset.disposal_date
    }


@app.route('/depreciation/schedule')
def depreciation_schedule():
    company = get_current_company()
    if not company:
        return render_template('error.html', message='No company selected')

    assets = Asset.query.filter_by(company_id=company.id).all()
    schedules = [calculate_asset_depreciation(asset) for asset in assets]
    return render_template('depreciation_schedule.html', schedules=schedules, company=company)


@app.route('/depreciation/schedule/<int:asset_id>')
def asset_depreciation_schedule(asset_id):
    company = get_current_company()
    if not company:
        return render_template('error.html', message='No company selected')

    asset = Asset.query.filter_by(id=asset_id, company_id=company.id).first_or_404()
    schedule = calculate_asset_depreciation(asset)
    return render_template('asset_depreciation.html', schedule=schedule, company=company)


@app.route('/depreciation/export/excel')
def export_depreciation_excel():
    company = get_current_company()
    if not company:
        return jsonify({'error': 'No company selected'}), 400

    assets = Asset.query.filter_by(company_id=company.id).all()
    all_schedules = []

    for asset in assets:
        schedule = calculate_asset_depreciation(asset)
        for breakdown in schedule['yearly_breakdown']:
            all_schedules.append({
                'Asset No': breakdown['asset_no'],
                'Description': breakdown['description'],
                'Year': breakdown['year'],
                'Year Start': breakdown['year_start'],
                'Year End': breakdown['year_end'],
                'Depreciation': breakdown['depreciation'],
                'Accumulated Depreciation': breakdown['accumulated_depreciation'],
                'Net Book Value': breakdown['net_book_value']
            })

    df = pd.DataFrame(all_schedules)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Depreciation Schedule', index=False)

        worksheet = writer.sheets['Depreciation Schedule']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 25)
            worksheet.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'depreciation_schedule_{company.code}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


def calculate_asset_movement(asset, start_date, end_date):
    total_cost = asset.initial_cost + asset.other_cost
    annual_depreciation = total_cost / asset.useful_life_yrs if asset.useful_life_yrs > 0 else 0
    monthly_depreciation = annual_depreciation / 12

    depreciation_start = asset.depreciation_start_date

    if asset.purchase_date <= end_date:
        if asset.purchase_date < start_date:
            cost_opening = total_cost
            cost_additions = 0
        else:
            cost_opening = 0
            cost_additions = total_cost
    else:
        cost_opening = 0
        cost_additions = 0

    if asset.disposal_date:
        if asset.disposal_date < start_date:
            cost_opening = 0
            cost_additions = 0
            cost_disposals = 0
            is_active_during_period = False
        elif asset.disposal_date <= end_date:
            cost_opening = total_cost if asset.purchase_date < start_date else 0
            cost_additions = total_cost if start_date <= asset.purchase_date <= end_date else 0
            cost_disposals = total_cost
            is_active_during_period = True
        else:
            cost_opening = total_cost if asset.purchase_date < start_date else 0
            cost_additions = total_cost if start_date <= asset.purchase_date <= end_date else 0
            cost_disposals = 0
            is_active_during_period = True
    else:
        cost_opening = total_cost if asset.purchase_date < start_date else 0
        cost_additions = total_cost if start_date <= asset.purchase_date <= end_date else 0
        cost_disposals = 0
        is_active_during_period = True

    cost_closing = cost_opening + cost_additions - cost_disposals

    if depreciation_start < start_date:
        months_to_start = (start_date.year - depreciation_start.year) * 12 + (
                start_date.month - depreciation_start.month)
        months_to_start = max(0, months_to_start)
        depn_opening = min(monthly_depreciation * months_to_start, total_cost)
    else:
        depn_opening = 0

    period_start = max(start_date, depreciation_start)
    period_end = min(end_date, asset.disposal_date if asset.disposal_date else end_date)

    if period_end >= period_start and is_active_during_period:
        months_in_period = (period_end.year - period_start.year) * 12 + (period_end.month - period_start.month)
        if period_end > period_start:
            months_in_period += 1
        months_in_period = max(0, months_in_period)
        depn_period = min(monthly_depreciation * months_in_period, total_cost - depn_opening)
    else:
        depn_period = 0

    if asset.disposal_date and start_date <= asset.disposal_date <= end_date:
        months_to_disposal = (asset.disposal_date.year - depreciation_start.year) * 12 + (
                asset.disposal_date.month - depreciation_start.month)
        months_to_disposal = max(0, months_to_disposal)
        depn_up_to_disposal = min(monthly_depreciation * months_to_disposal, total_cost)
        depn_disposals = max(0, depn_up_to_disposal - depn_opening)
    else:
        depn_disposals = 0

    depn_closing = depn_opening + depn_period - depn_disposals

    nbv_opening = cost_opening - depn_opening
    nbv_closing = cost_closing - depn_closing

    return {
        'asset_id': asset.id,
        'asset_no': asset.asset_no,
        'description': asset.description,
        'user': asset.user,
        'entity': asset.entity,
        'currency': asset.currency,
        'purchase_date': asset.purchase_date.strftime('%Y-%m-%d'),
        'disposal_date': asset.disposal_date.strftime('%Y-%m-%d') if asset.disposal_date else '',
        'cost_opening': round(cost_opening, 2),
        'cost_additions': round(cost_additions, 2),
        'cost_disposals': round(cost_disposals, 2),
        'cost_closing': round(cost_closing, 2),
        'depn_opening': round(depn_opening, 2),
        'depn_period': round(depn_period, 2),
        'depn_disposals': round(depn_disposals, 2),
        'depn_closing': round(depn_closing, 2),
        'nbv_opening': round(nbv_opening, 2),
        'nbv_closing': round(nbv_closing, 2)
    }


@app.route('/reports/asset-movement')
def asset_movement_report():
    company = get_current_company()
    if not company:
        return render_template('error.html', message='No company selected')

    entities = db.session.query(Asset.entity).filter_by(company_id=company.id).distinct().all()
    entities = [e[0] for e in entities if e[0]]

    categories = [c.name for c in Category.query.filter_by(company_id=company.id).order_by(Category.name).all() if
                  c.name != 'Uncategorized']

    return render_template('asset_movement_report.html',
                           entities=entities,
                           categories=categories,
                           company=company)


@app.route('/api/reports/asset-movement', methods=['POST'])
def api_asset_movement_report():
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        data = request.json
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        entity = data.get('entity', '')
        category = data.get('category', '')

        query = Asset.query.filter_by(company_id=company.id)
        if entity and entity != 'all':
            query = query.filter(Asset.entity == entity)
        if category and category != 'all':
            query = query.filter(Asset.asset_category == category)

        assets = query.all()
        categories_data = {}

        for asset in assets:
            asset_category = asset.asset_category if asset.asset_category else 'Uncategorized'
            movement_data = calculate_asset_movement(asset, start_date, end_date)

            if asset_category not in categories_data:
                categories_data[asset_category] = {
                    'category': asset_category,
                    'assets': [],
                    'totals': {
                        'cost_opening': 0, 'cost_additions': 0, 'cost_disposals': 0, 'cost_closing': 0,
                        'depn_opening': 0, 'depn_period': 0, 'depn_disposals': 0, 'depn_closing': 0,
                        'nbv_opening': 0, 'nbv_closing': 0
                    }
                }

            categories_data[asset_category]['assets'].append(movement_data)
            cat_totals = categories_data[asset_category]['totals']
            cat_totals['cost_opening'] += movement_data['cost_opening']
            cat_totals['cost_additions'] += movement_data['cost_additions']
            cat_totals['cost_disposals'] += movement_data['cost_disposals']
            cat_totals['cost_closing'] += movement_data['cost_closing']
            cat_totals['depn_opening'] += movement_data['depn_opening']
            cat_totals['depn_period'] += movement_data['depn_period']
            cat_totals['depn_disposals'] += movement_data['depn_disposals']
            cat_totals['depn_closing'] += movement_data['depn_closing']
            cat_totals['nbv_opening'] += movement_data['nbv_opening']
            cat_totals['nbv_closing'] += movement_data['nbv_closing']

        grand_totals = {
            'cost_opening': 0, 'cost_additions': 0, 'cost_disposals': 0, 'cost_closing': 0,
            'depn_opening': 0, 'depn_period': 0, 'depn_disposals': 0, 'depn_closing': 0,
            'nbv_opening': 0, 'nbv_closing': 0
        }

        for cat_data in categories_data.values():
            for key in grand_totals:
                grand_totals[key] += cat_data['totals'][key]

        return jsonify({
            'success': True,
            'categories': list(categories_data.values()),
            'grand_totals': grand_totals,
            'filters': {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'entity': entity if entity != 'all' else 'All Entities',
                'category': category if category != 'all' else 'All Categories'
            },
            'report_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'company': company.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ==================== USER ASSET REPORT ====================

@app.route('/reports/user-assets')
def user_asset_report():
    """Display user asset report page"""
    company = get_current_company()
    if not company:
        flash('No company selected. Please switch to a company.', 'warning')
        return redirect(url_for('index'))

    company_id = company.id

    # Get all users with their assigned assets for this company
    users = User.query.filter_by(company_id=company_id, is_active=True).all()

    user_assets = []
    for user in users:
        # Get assets assigned to this user
        assets = Asset.query.filter_by(
            company_id=company_id,
            user=user.full_name
        ).all()

        asset_list = []
        for asset in assets:
            # Find the active assignment for this asset
            active_assignment = AssetAssignment.query.filter_by(
                asset_id=asset.id,
                status='Active'
            ).first()

            asset_list.append({
                'asset_no': asset.asset_no,
                'description': asset.description,
                'category': asset.asset_category,
                'serial_no': asset.serial_no,
                'condition': asset.condition,
                'initial_cost': asset.initial_cost,
                'purchase_date': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
                'assigned_date': active_assignment.assigned_date.strftime('%Y-%m-%d') if active_assignment else ''
            })

        # Count active assignments for this user
        active_assignments = AssetAssignment.query.filter_by(
            assigned_to=user.full_name,
            status='Active'
        ).count()

        # Convert user to dict for JSON serialization
        user_dict = {
            'id': user.id,
            'full_name': user.full_name,
            'role': user.role,
            'department': user.department or '',
            'phone': user.phone or '',
            'is_active': user.is_active
        }

        user_assets.append({
            'user': user_dict,
            'assets': asset_list,
            'total_assets': len(assets),
            'total_value': sum(a.initial_cost + a.other_cost for a in assets),
            'active_assignments': active_assignments
        })

    return render_template(
        'user_asset_report.html',
        user_assets=user_assets,
        company=company,
        generated_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


@app.route('/api/reports/user-assets')
def api_user_asset_report():
    """API endpoint for user asset report data"""
    company = get_current_company()
    if not company:
        return jsonify({'success': False, 'error': 'No company selected'}), 400

    user_id = request.args.get('user_id')

    # Get all users for the company
    query = User.query.filter_by(company_id=company.id, is_active=True)
    if user_id and user_id != 'all':
        query = query.filter_by(id=int(user_id))

    users = query.all()

    report_data = []
    all_assignments = []

    for user in users:
        # Get ALL assignments for this user (including returned ones)
        user_assignments = AssetAssignment.query.filter_by(
            assigned_to=user.full_name
        ).order_by(AssetAssignment.assigned_date.desc()).all()

        # Add to all assignments for return status tracking
        all_assignments.extend(user_assignments)

        # Get unique asset IDs from assignments
        assigned_asset_ids = set([a.asset_id for a in user_assignments])

        # Get assets from assignments
        assets = []
        for asset_id in assigned_asset_ids:
            asset = Asset.query.filter_by(id=asset_id, company_id=company.id).first()
            if asset:
                assets.append(asset)

        # Calculate total value
        total_value = sum(a.initial_cost + a.other_cost for a in assets)

        # Convert assets to dict with assignment info
        asset_list = []
        for asset in assets:
            # Find all assignments for this asset and user
            asset_user_assignments = [a for a in user_assignments if a.asset_id == asset.id]

            # Get the most recent assignment for this asset and user
            latest_assignment = asset_user_assignments[0] if asset_user_assignments else None

            # Find if there's any active assignment for this asset (could be assigned to someone else now)
            active_assignment = AssetAssignment.query.filter_by(
                asset_id=asset.id,
                status='Active'
            ).first()

            # Find returned assignment for this user
            returned_assignment = None
            for a in asset_user_assignments:
                if a.status == 'Returned' or a.actual_return_date:
                    returned_assignment = a
                    break

            # Determine if this user currently has the asset
            is_current_user = active_assignment and active_assignment.assigned_to == user.full_name

            # Determine status for this user
            status_label = 'Not Assigned'
            if is_current_user:
                # User currently has the asset
                if active_assignment.expected_return_date:
                    expected_date = active_assignment.expected_return_date
                    if expected_date < datetime.now().date():
                        status_label = 'Overdue'
                    else:
                        status_label = 'Pending'
                else:
                    status_label = 'Active'
            elif returned_assignment:
                # User had the asset but returned it
                status_label = 'Returned'

            # Get the actual return date if returned
            actual_return_date = returned_assignment.actual_return_date.strftime(
                '%Y-%m-%d') if returned_assignment and returned_assignment.actual_return_date else ''

            asset_list.append({
                'id': asset.id,
                'asset_no': asset.asset_no,
                'description': asset.description,
                'category': asset.asset_category,
                'serial_no': asset.serial_no,
                'condition': asset.condition,
                'assigned_date': latest_assignment.assigned_date.strftime('%Y-%m-%d') if latest_assignment else '',
                'expected_return_date': active_assignment.expected_return_date.strftime(
                    '%Y-%m-%d') if is_current_user and active_assignment and active_assignment.expected_return_date else (
                    latest_assignment.expected_return_date.strftime(
                        '%Y-%m-%d') if latest_assignment and latest_assignment.expected_return_date else ''),
                'actual_return_date': actual_return_date,
                'status': status_label,
                'is_current_user': is_current_user
            })

        # Calculate active assignments for this user (where they are the current assignee)
        active_count = len([a for a in asset_list if a.get('is_current_user')])

        report_data.append({
            'user': {
                'id': user.id,
                'full_name': user.full_name,
                'role': user.role,
                'department': user.department or '',
                'phone': user.phone or ''
            },
            'assets': asset_list,
            'assignment_count': len(user_assignments),
            'total_value': total_value,
            'active_assignments': active_count
        })

    # Get all assignments for return status tracking
    assignments_data = []
    for assignment in all_assignments:
        assignments_data.append({
            'id': assignment.id,
            'asset_id': assignment.asset_id,
            'assigned_to': assignment.assigned_to,
            'assigned_date': assignment.assigned_date.strftime('%Y-%m-%d') if assignment.assigned_date else '',
            'expected_return_date': assignment.expected_return_date.strftime(
                '%Y-%m-%d') if assignment.expected_return_date else '',
            'actual_return_date': assignment.actual_return_date.strftime(
                '%Y-%m-%d') if assignment.actual_return_date else '',
            'status': assignment.status,
            'is_overdue': assignment.status == 'Active' and assignment.expected_return_date and assignment.expected_return_date < datetime.now().date()
        })

    return jsonify({
        'success': True,
        'data': report_data,
        'assignments': assignments_data,
        'company': company.to_dict(),
        'generated_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.route('/reports/user-assets/export/pdf')
def export_user_asset_pdf():
    """Export user asset report to PDF"""
    company = get_current_company()
    if not company:
        return jsonify({'error': 'No company selected'}), 400

    user_id = request.args.get('user_id')

    # Get all users for the company
    query = User.query.filter_by(company_id=company.id, is_active=True)
    if user_id and user_id != 'all':
        query = query.filter_by(id=int(user_id))

    users = query.all()

    # Build report data
    report_data = []
    total_all_assets = 0
    total_all_value = 0

    for user in users:
        assets = Asset.query.filter_by(
            company_id=company.id,
            user=user.full_name
        ).all()

        assignments = AssetAssignment.query.filter_by(
            assigned_to=user.full_name
        ).order_by(AssetAssignment.assigned_date.desc()).all()

        total_value = sum(a.initial_cost + a.other_cost for a in assets)
        total_all_assets += len(assets)
        total_all_value += total_value

        report_data.append({
            'user': user,
            'assets': assets,
            'assignment_count': len(assignments),
            'total_value': total_value,
            'active_assignments': len([a for a in assignments if a.status == 'Active'])
        })

    # Generate HTML for PDF
    html = render_template('user_asset_pdf.html',
                           report_data=report_data,
                           company=company,
                           generated_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                           user_id=user_id,
                           total_all_assets=total_all_assets,
                           total_all_value=total_all_value)

    return html


@app.route('/api/assets/unassigned')
def get_unassigned_assets():
    """Get all unassigned assets"""
    company = get_current_company()
    if not company:
        return jsonify([])
    assets = Asset.query.filter_by(company_id=company.id).filter(
        (Asset.user == None) | (Asset.user == '') | (Asset.user == 'Unassigned')
    ).all()
    return jsonify([a.to_dict() for a in assets])


@app.route('/api/assets/<int:asset_id>/full-history')
def get_asset_full_history(asset_id):
    """Get complete history of an asset with user details"""
    company = get_current_company()
    if not company:
        return jsonify({'success': False, 'error': 'No company selected'}), 400

    asset = Asset.query.filter_by(id=asset_id, company_id=company.id).first()
    if not asset:
        return jsonify({'success': False, 'error': 'Asset not found'}), 404

    # Get all assignments for this asset with user details
    assignments = AssetAssignment.query.filter_by(asset_id=asset_id).order_by(
        AssetAssignment.assigned_date.desc()
    ).all()

    history = []
    for ass in assignments:
        # Get user details if available
        user = User.query.filter_by(full_name=ass.assigned_to, company_id=company.id).first()
        history.append({
            'id': ass.id,
            'assigned_to': ass.assigned_to,
            'assigned_by': ass.assigned_by,
            'assigned_date': ass.assigned_date.strftime('%Y-%m-%d') if ass.assigned_date else '',
            'expected_return_date': ass.expected_return_date.strftime('%Y-%m-%d') if ass.expected_return_date else '',
            'actual_return_date': ass.actual_return_date.strftime('%Y-%m-%d') if ass.actual_return_date else '',
            'status': ass.status,
            'notes': ass.notes or '',
            'returned_condition': ass.returned_condition or '',
            'return_notes': ass.return_notes or '',
            'is_overdue': ass.status == 'Active' and ass.expected_return_date and ass.expected_return_date < datetime.now().date(),
            'user_details': user.to_dict() if user else None
        })

    return jsonify({
        'success': True,
        'asset': asset.to_dict(),
        'history': history
    })


@app.route('/api/return-forms/<int:form_id>', methods=['PUT'])
def update_return_form(form_id):
    """Update an existing return form"""
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        return_form = AssetReturnForm.query.get_or_404(form_id)
        asset = Asset.query.filter_by(id=return_form.asset_id, company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        data = request.json

        # Update return form
        return_form.returned_by = data.get('returned_by', return_form.returned_by)
        return_form.returned_date = datetime.strptime(data['returned_date'], '%Y-%m-%d').date() if data.get(
            'returned_date') else return_form.returned_date
        return_form.condition = data.get('condition', return_form.condition)
        return_form.damage_description = data.get('damage_description', '')
        return_form.maintenance_required = data.get('maintenance_required', False)
        return_form.maintenance_notes = data.get('maintenance_notes', '')
        return_form.signature = data.get('signature', '')
        return_form.received_by = data.get('received_by', '')
        return_form.notes = data.get('notes', '')

        # Also update the assignment's returned condition
        assignment = AssetAssignment.query.get(return_form.assignment_id)
        if assignment:
            assignment.returned_condition = data.get('condition', 'Good')
            assignment.return_notes = data.get('notes', '')
            if data.get('returned_date'):
                assignment.actual_return_date = datetime.strptime(data['returned_date'], '%Y-%m-%d').date()

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Return form updated successfully',
            'return_form': return_form.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/return-forms/<int:form_id>', methods=['DELETE'])
def delete_return_form(form_id):
    """Delete a return form and revert the asset to assigned status"""
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        return_form = AssetReturnForm.query.get_or_404(form_id)
        asset = Asset.query.filter_by(id=return_form.asset_id, company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        # Get the assignment
        assignment = AssetAssignment.query.get(return_form.assignment_id)

        # Delete the return form
        db.session.delete(return_form)

        # Update assignment status back to Active
        if assignment:
            assignment.status = 'Active'
            assignment.actual_return_date = None
            assignment.returned_condition = None
            assignment.return_notes = None
            # Update asset user back to the assigned user
            asset.user = assignment.assigned_to

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Return form deleted. Asset is now assigned again.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assignments/<int:assignment_id>', methods=['PUT'])
def update_assignment(assignment_id):
    """Update an existing assignment"""
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        assignment = AssetAssignment.query.get_or_404(assignment_id)
        asset = Asset.query.filter_by(id=assignment.asset_id, company_id=company.id).first()
        if not asset:
            return jsonify({'success': False, 'error': 'Asset not found'}), 404

        data = request.json
        user_id = data.get('user_id')

        if user_id:
            user = User.query.filter_by(id=user_id, company_id=company.id, is_active=True).first()
            if not user:
                return jsonify({'success': False, 'error': 'User not found or inactive'}), 400
            assignment.assigned_to = user.full_name

        if data.get('assigned_date'):
            assignment.assigned_date = datetime.strptime(data['assigned_date'], '%Y-%m-%d').date()

        if data.get('expected_return_date'):
            assignment.expected_return_date = datetime.strptime(data['expected_return_date'], '%Y-%m-%d').date()
        else:
            assignment.expected_return_date = None

        assignment.notes = data.get('notes', '')

        # Update the asset's user field
        if user_id:
            asset.user = assignment.assigned_to

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Assignment updated successfully',
            'assignment': assignment.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/assignments/<int:assignment_id>', methods=['DELETE'])
def delete_assignment(assignment_id):
    """Delete an assignment and unassign the asset"""
    try:
        company = get_current_company()
        if not company:
            return jsonify({'success': False, 'error': 'No company selected'}), 400

        assignment = AssetAssignment.query.get_or_404(assignment_id)
        asset = Asset.query.filter_by(id=assignment.asset_id, company_id=company.id).first()

        # Delete the assignment
        db.session.delete(assignment)

        # Update the asset user to Unassigned
        if asset:
            asset.user = 'Unassigned'

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Assignment deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/reports/asset-history/export/pdf')
def export_asset_history_pdf():
    """Export Asset History report to PDF"""
    company = get_current_company()
    if not company:
        return jsonify({'error': 'No company selected'}), 400

    search = request.args.get('search', '')

    # Get all assets for the company
    query = Asset.query.filter_by(company_id=company.id)
    if search:
        query = query.filter(
            db.or_(
                Asset.asset_no.ilike(f'%{search}%'),
                Asset.description.ilike(f'%{search}%'),
                Asset.user.ilike(f'%{search}%'),
                Asset.asset_category.ilike(f'%{search}%')
            )
        )

    assets = query.all()

    # Get all assignments for these assets
    asset_ids = [a.id for a in assets]
    assignments = AssetAssignment.query.filter(AssetAssignment.asset_id.in_(asset_ids)).order_by(
        AssetAssignment.assigned_date.desc()
    ).all()

    # Generate HTML for PDF
    html = render_template('asset_history_pdf.html',
                           assets=assets,
                           assignments=assignments,
                           company=company,
                           generated_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    return html


if __name__ == '__main__':
    print("=" * 60)
    print("ASSET REGISTER MANAGEMENT SYSTEM")
    print("=" * 60)
    print("✓ Flask Application Started")
    print("✓ Database:", os.environ.get('DATABASE_URL', 'SQLite (local)'))
    print("✓ Multi-Company Support Active (filtered by company_id)")
    print("✓ User Management System Active (Name, Role, Department, Phone)")
    print("✓ No default categories created - users create their own")
    print("\n🌐 Access the application at: http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)