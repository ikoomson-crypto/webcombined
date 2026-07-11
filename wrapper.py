from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os
import re
import sqlite3

from extensions import db, migrate

from app1.app import app as app1
from app2.app import app as app2
from app3.app import app as app3


# ========== AUTH MODELS ==========
class User(db.Model):
    __tablename__ = 'auth_users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relationship to app access
    app_access = db.relationship('UserAppAccess', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_app_access(self, app_name):
        """Check if user has access to a specific app"""
        if self.is_admin:
            return True
        return self.app_access.filter_by(app_name=app_name, has_access=True).first() is not None

    def get_accessible_apps(self):
        """Get list of apps user has access to"""
        if self.is_admin:
            return ['app1', 'app2', 'app3']
        return [access.app_name for access in self.app_access.filter_by(has_access=True).all()]

    def has_any_app_access(self):
        """Check if user has access to at least one app"""
        if self.is_admin:
            return True
        return self.app_access.filter_by(has_access=True).count() > 0

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'last_login': self.last_login.strftime('%Y-%m-%d %H:%M:%S') if self.last_login else '',
            'apps': self.get_accessible_apps()
        }


class UserAppAccess(db.Model):
    __tablename__ = 'user_app_access'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('auth_users.id'), nullable=False)
    app_name = db.Column(db.String(50), nullable=False)
    has_access = db.Column(db.Boolean, default=True)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'app_name', name='unique_user_app'),
    )


# ========== DATABASE MIGRATION HELPER ==========
def migrate_database():
    """Add missing columns to existing database"""
    db_path = os.path.join(os.path.dirname(__file__), 'auth.db')

    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(auth_users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_approved' not in columns:
            print("🔧 Adding is_approved column to auth_users...")
            cursor.execute("ALTER TABLE auth_users ADD COLUMN is_approved BOOLEAN DEFAULT 1")
            conn.commit()
            print("✅ is_approved column added successfully!")

        conn.close()
    except Exception as e:
        print(f"⚠️ Migration warning: {e}")


# ========== AUTH DECORATORS ==========
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))

        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            flash('User not found. Please log in again.', 'warning')
            return redirect(url_for('login'))

        # Check if user has any app access (skip for admin)
        if not user.is_admin and not user.has_any_app_access():
            # Allow access to dashboard but show no apps message
            pass

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))

        if not session.get('is_admin', False):
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))

        return f(*args, **kwargs)

    return decorated_function


def app_access_required(app_name):
    """Decorator to check if user has access to a specific app"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))

            user = User.query.get(session['user_id'])
            if not user or not user.is_active:
                session.clear()
                flash('Your account is inactive or not found.', 'danger')
                return redirect(url_for('login'))

            if not user.is_admin and not user.has_app_access(app_name):
                flash(f'You do not have access to {app_name}. Please contact your administrator.', 'danger')
                return redirect(url_for('dashboard'))

            return f(*args, **kwargs)

        return decorated_function

    return decorator


# ========== CREATE MAIN APP ==========
def create_app():
    flask_app = Flask(__name__)

    flask_app.config.from_object("config.Config")
    flask_app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')

    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    with flask_app.app_context():
        migrate_database()
        db.create_all()

        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@example.com',
                full_name='Administrator',
                is_admin=True,
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.flush()

            for app_name in ['app1', 'app2', 'app3']:
                access = UserAppAccess(user_id=admin.id, app_name=app_name, has_access=True)
                db.session.add(access)

            db.session.commit()
            print("=" * 60)
            print("✅ Default admin user created!")
            print("👤 Username: admin")
            print("🔑 Password: admin123")
            print("=" * 60)

    return flask_app


main_app = create_app()


# ========== VALIDATION HELPERS ==========
def validate_username(username):
    if not username or len(username) < 3 or len(username) > 20:
        return False, "Username must be between 3 and 20 characters."
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Username can only contain letters, numbers, and underscores."
    return True, ""


def validate_password(password):
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
        return False, "Password must contain both letters and numbers."
    return True, ""


def validate_email(email):
    if not email:
        return False, "Email is required."
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False, "Please enter a valid email address."
    return True, ""


# ========== AUTH ROUTES ==========

@main_app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        full_name = request.form.get('full_name', '').strip()

        errors = []

        valid, msg = validate_username(username)
        if not valid:
            errors.append(msg)

        valid, msg = validate_email(email)
        if not valid:
            errors.append(msg)

        valid, msg = validate_password(password)
        if not valid:
            errors.append(msg)

        if password != confirm_password:
            errors.append("Passwords do not match.")

        if not full_name:
            errors.append("Full name is required.")

        if User.query.filter_by(username=username).first():
            errors.append("Username already taken. Please choose another.")

        if User.query.filter_by(email=email).first():
            errors.append("Email already registered. Please use another email.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html',
                                   username=username,
                                   email=email,
                                   full_name=full_name)

        # Create new user with NO app access by default
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            is_admin=False,
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)

        # NO app access assigned by default - admin must assign
        db.session.commit()

        flash('Registration successful! You can now log in. Contact your administrator to get access to applications.',
              'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@main_app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Please enter both username and password.', 'warning')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact an administrator.', 'danger')
                return render_template('login.html')

            session['user_id'] = user.id
            session['username'] = user.username
            session['full_name'] = user.full_name
            session['is_admin'] = user.is_admin

            # Update last login
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash(f'Welcome back, {user.full_name}!', 'success')

            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@main_app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@main_app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        flash('Session expired. Please log in again.', 'warning')
        return redirect(url_for('login'))

    accessible_apps = user.get_accessible_apps()
    has_apps = user.has_any_app_access() or user.is_admin

    app_info = {
        'app1': {'name': 'Liquidity Schedule', 'icon': 'fa-credit-card', 'color': 'primary',
                 'description': 'Payment and liquidity management'},
        'app2': {'name': 'Asset Register', 'icon': 'fa-boxes', 'color': 'success',
                 'description': 'Asset tracking and management'},
        'app3': {'name': 'Prepayment', 'icon': 'fa-cubes', 'color': 'info',
                 'description': 'Prepayment schedule management'}
    }

    apps = []
    for app_name in accessible_apps:
        info = app_info.get(app_name, {'name': app_name, 'icon': 'fa-app', 'color': 'secondary', 'description': ''})
        apps.append({
            'id': app_name,
            'name': info['name'],
            'icon': info['icon'],
            'color': info['color'],
            'description': info['description'],
            'url': f'/{app_name}/'
        })

    return render_template('dashboard.html',
                           user=user,
                           apps=apps,
                           has_apps=has_apps)


# ========== USER MANAGEMENT ROUTES (Admin Only) ==========

@main_app.route('/admin/users')
@admin_required
def manage_users():
    users = User.query.all()
    no_apps_count = len([u for u in users if not u.is_admin and not u.has_any_app_access()])

    return render_template('manage_users.html',
                           users=users,
                           no_apps_count=no_apps_count)


@main_app.route('/admin/users/no-apps')
@admin_required
def users_without_apps():
    """View users who have no app access"""
    users_no_apps = User.query.filter_by(is_admin=False).all()
    users_no_apps = [u for u in users_no_apps if not u.has_any_app_access()]
    return render_template('no_apps_users.html', users=users_no_apps)


@main_app.route('/admin/users/create', methods=['GET', 'POST'])
@admin_required
def create_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        is_admin = request.form.get('is_admin') == 'on'

        if not username or not password or not full_name:
            flash('Username, password, and full name are required.', 'danger')
            return render_template('create_user.html')

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('create_user.html')

        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('create_user.html')

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            is_admin=is_admin,
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        app1_access = request.form.get('app1_access') == 'on'
        app2_access = request.form.get('app2_access') == 'on'
        app3_access = request.form.get('app3_access') == 'on'

        if not any([app1_access, app2_access, app3_access]) and not is_admin:
            flash('Please assign at least one app access.', 'danger')
            db.session.rollback()
            return render_template('create_user.html')

        if app1_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app1', has_access=True))
        if app2_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app2', has_access=True))
        if app3_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app3', has_access=True))

        db.session.commit()
        flash(f'User {username} created successfully!', 'success')
        return redirect(url_for('manage_users'))

    return render_template('create_user.html')


@main_app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        user.full_name = request.form.get('full_name', '').strip()
        user.email = request.form.get('email', '').strip()
        user.is_admin = request.form.get('is_admin') == 'on'
        user.is_active = request.form.get('is_active') == 'on'

        new_password = request.form.get('password', '')
        if new_password:
            valid, msg = validate_password(new_password)
            if not valid:
                flash(msg, 'danger')
                return render_template('edit_user.html', user=user, access_apps=[])
            user.set_password(new_password)

        app1_access = request.form.get('app1_access') == 'on'
        app2_access = request.form.get('app2_access') == 'on'
        app3_access = request.form.get('app3_access') == 'on'

        UserAppAccess.query.filter_by(user_id=user.id).delete()

        if user.is_admin:
            app1_access = app2_access = app3_access = True

        if app1_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app1', has_access=True))
        if app2_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app2', has_access=True))
        if app3_access:
            db.session.add(UserAppAccess(user_id=user.id, app_name='app3', has_access=True))

        db.session.commit()
        flash(f'User {user.username} updated successfully!', 'success')
        return redirect(url_for('manage_users'))

    access_apps = [a.app_name for a in user.app_access.filter_by(has_access=True).all()]
    return render_template('edit_user.html', user=user, access_apps=access_apps)


@main_app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('You cannot deactivate yourself.', 'danger')
        return redirect(url_for('manage_users'))

    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.username} {status}.', 'success')
    return redirect(url_for('manage_users'))


# ========== HOME ROUTE ==========
@main_app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


# ========== Combine multiple Flask applications ==========

application = DispatcherMiddleware(
    main_app,
    {
        "/app1": app1,
        "/app2": app2,
        "/app3": app3
    }
)

app = application

if __name__ == "__main__":
    from werkzeug.serving import run_simple

    print("=" * 60)
    print("🚀 WEB APPLICATION PORTAL WITH AUTHENTICATION")
    print("=" * 60)
    print("📊 Database: auth.db")
    print("👤 Default admin: admin / admin123")
    print("📝 Users can sign up and choose their own password")
    print("✅ No approval needed - users can log in immediately")
    print("📱 Users must be assigned apps by admin to access them")
    print("📁 Apps mounted:")
    print("   - /app1/ - Liquidity Schedule")
    print("   - /app2/ - Asset Register")
    print("   - /app3/ - Prepayment")
    print("🌐 Access at: http://localhost:5000")
    print("=" * 60)

    run_simple(
        "localhost",
        5000,
        app,
        use_reloader=True
    )