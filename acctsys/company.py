# acctsys/company.py
"""
Multi-company support for the accounting system.

Responsibilities
----------------
1.  Defines the `Company` model.
2.  Exposes a blueprint with routes to list / create / switch / delete companies.
3.  Provides helpers: get_current_company(), set_current_company(),
    current_company_id() and company_required decorator.
4.  INJECTS the `company_id` column into scoped models at import time
    so that individual model classes in models.py don't have to declare it.
5.  Registers SQLAlchemy events that AUTOMATICALLY:
       * filter every SELECT on scoped models by the active company_id
       * stamp company_id on every new scoped row before it is inserted
6.  Provides a SQLite-friendly migration helper to add `company_id`
    to the relevant tables, and a startup function to seed a default company
    for existing data.

Wiring (in app.py):

    from acctsys.company import company_bp, init_company_support
    app.register_blueprint(company_bp)
    init_company_support(app, db)
"""

from contextlib import contextmanager
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, session, g, abort, has_request_context,
)
from flask_login import login_required, current_user
from sqlalchemy import Column, Integer, ForeignKey, event
from sqlalchemy.orm import with_loader_criteria

from extensions import db


# ------------------------------------------------------------------ #
#  MODEL
# ------------------------------------------------------------------ #

class Company(db.Model):
    __tablename__ = 'company'

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(150), nullable=False)
    code          = db.Column(db.String(20), unique=True, nullable=False)
    tax_id        = db.Column(db.String(50))
    address       = db.Column(db.Text)
    phone         = db.Column(db.String(30))
    email         = db.Column(db.String(120))
    base_currency = db.Column(db.String(3), default='USD')
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    is_default    = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    created_by    = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        return f"<Company {self.code} {self.name}>"


# ------------------------------------------------------------------ #
#  TABLES THAT NEED company_id (physical table names)
# ------------------------------------------------------------------ #

SCOPED_TABLES = [
    'invoice',
    'expense',
    'purchase',
    'payment_voucher',
    'journal_entry',
    'supplier',
    'customer',
    'chart_of_account',
    'account_type',
    'category',
    'general_ledger',
]


# Model class names, resolved lazily (models.py isn't imported yet here).
SCOPED_MODEL_NAMES = [
    'Invoice',
    'Expense',
    'Purchase',
    'PaymentVoucher',
    'JournalEntry',
    'Supplier',
    'Customer',
    'ChartOfAccount',
    'AccountType',
    'Category',
    'GeneralLedger',
]


# ------------------------------------------------------------------ #
#  BYPASS FLAG
# ------------------------------------------------------------------ #

_bypass_scoping = False
_columns_injected = False
_scoping_events_installed = False


@contextmanager
def bypass_scoping():
    """Context manager: temporarily disable company scoping."""
    global _bypass_scoping
    old = _bypass_scoping
    _bypass_scoping = True
    try:
        yield
    finally:
        _bypass_scoping = old


# ------------------------------------------------------------------ #
#  HELPERS
# ------------------------------------------------------------------ #

def get_current_company():
    cid = session.get('company_id') if has_request_context() else None
    if not cid:
        return None
    return db.session.get(Company, cid)


def set_current_company(company_id):
    session['company_id'] = company_id


def clear_current_company():
    session.pop('company_id', None)


def current_company_id():
    if _bypass_scoping:
        return None
    if not has_request_context():
        return None
    return session.get('company_id')


def company_required(f):
    """Ensures a company is selected; auto-selects if there's only one."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('company_id'):
            only = Company.query.filter_by(is_active=True).all()
            if len(only) == 1:
                set_current_company(only[0].id)
            else:
                flash('Please select a company to continue.', 'warning')
                return redirect(url_for('company.choose'))
        return f(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------ #
#  COLUMN INJECTION
# ------------------------------------------------------------------ #

def _scoped_model_classes():
    """
    Resolve the list of scoped model classes. Import inside a function
    to avoid circular imports with models.py / app.py.
    """
    from acctsys import models as m
    classes = []
    for attr in SCOPED_MODEL_NAMES:
        cls = getattr(m, attr, None)
        if cls is not None:
            classes.append(cls)
    return classes


def _inject_company_id_columns():
    """
    Ensure every scoped model has a `company_id` column. If a model class
    doesn't declare it, add it here via SQLAlchemy's Table.append_column.

    This lets models.py stay clean — company.py owns the multi-tenancy
    column entirely. Safe to call multiple times; only injects once.
    """
    global _columns_injected
    if _columns_injected:
        return

    for cls in _scoped_model_classes():
        if hasattr(cls, 'company_id'):
            continue  # already declared in models.py

        # Build a Column bound to the model's table.
        col = Column(
            'company_id',
            Integer,
            ForeignKey('company.id'),
            nullable=True,
            index=True,
        )
        cls.__table__.append_column(col)
        # Also expose it as a Python attribute on the class.
        setattr(cls, 'company_id', col)

        # Optional: nice `invoice.company` accessor. Only add if not already
        # defined (models.py may already have it).
        if not hasattr(cls, 'company'):
            try:
                from sqlalchemy.orm import relationship
                setattr(cls, 'company', relationship(
                    'Company', foreign_keys=[col], lazy=True,
                ))
            except Exception as e:
                print(f"[company] could not attach relationship on {cls.__name__}: {e}")

        print(f"[company] Injected company_id into {cls.__name__}")

    _columns_injected = True


# ------------------------------------------------------------------ #
#  BLUEPRINT
# ------------------------------------------------------------------ #

company_bp = Blueprint('company', __name__, url_prefix='/companies')


@company_bp.route('/')
@login_required
def list_companies():
    companies = Company.query.order_by(Company.name).all()
    return render_template(
        'companies.html',
        companies=companies,
        current_id=session.get('company_id'),
    )


@company_bp.route('/choose')
@login_required
def choose():
    companies = Company.query.filter_by(is_active=True).order_by(Company.name).all()
    return render_template(
        'companies.html',
        companies=companies,
        current_id=session.get('company_id'),
        chooser_mode=True,
    )


@company_bp.route('/switch/<int:company_id>')
@login_required
def switch(company_id):
    company = db.session.get(Company, company_id)
    if not company or not company.is_active:
        flash('Company not found or inactive.', 'danger')
        return redirect(url_for('company.list_companies'))

    set_current_company(company.id)
    flash(f'Switched to {company.name}.', 'success')

    nxt = request.args.get('next')
    if nxt and nxt.startswith('/'):
        return redirect(nxt)
    return redirect(url_for('dashboard'))


@company_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        code = (request.form.get('code') or '').strip().upper()
        tax_id = (request.form.get('tax_id') or '').strip()
        address = (request.form.get('address') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        email = (request.form.get('email') or '').strip()
        base_currency = (request.form.get('base_currency') or 'USD').strip().upper()

        errors = []
        if not name:
            errors.append('Company name is required.')
        if not code:
            errors.append('Company code is required.')
        if code and Company.query.filter_by(code=code).first():
            errors.append(f'Company code "{code}" is already in use.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('company.create'))

        company = Company(
            name=name, code=code,
            tax_id=tax_id or None, address=address or None,
            phone=phone or None, email=email or None,
            base_currency=base_currency, created_by=current_user.id,
        )
        db.session.add(company)
        db.session.commit()
        set_current_company(company.id)
        flash(f'Company "{company.name}" created. You are now working in it.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('companies.html',
                           companies=Company.query.all(),
                           current_id=session.get('company_id'),
                           create_mode=True)


@company_bp.route('/<int:company_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(company_id):
    company = db.session.get(Company, company_id)
    if not company:
        abort(404)

    if request.method == 'POST':
        company.name = (request.form.get('name') or '').strip() or company.name
        new_code = (request.form.get('code') or '').strip().upper()
        if new_code and new_code != company.code:
            if Company.query.filter_by(code=new_code).first():
                flash(f'Company code "{new_code}" is already in use.', 'danger')
                return redirect(url_for('company.edit', company_id=company.id))
            company.code = new_code
        company.tax_id = (request.form.get('tax_id') or '').strip() or None
        company.address = (request.form.get('address') or '').strip() or None
        company.phone = (request.form.get('phone') or '').strip() or None
        company.email = (request.form.get('email') or '').strip() or None
        company.base_currency = (request.form.get('base_currency') or company.base_currency).strip().upper()
        db.session.commit()
        flash(f'Company "{company.name}" updated.', 'success')
        return redirect(url_for('company.list_companies'))

    return render_template('companies.html',
                           companies=Company.query.all(),
                           current_id=session.get('company_id'),
                           edit_company=company)

@company_bp.route('/<int:company_id>/delete', methods=['POST'])
@login_required
def delete(company_id):
    """
    Hard-delete a company and all its scoped records.

    Guardrails:
      - If it's the ONLY company in the DB → refuse (you'd have nowhere to log in).
      - If it's currently active in your session → clear the session first.
      - Otherwise: cascade delete everything and remove the company row.
    """
    company = db.session.get(Company, company_id)
    if not company:
        abort(404)

    # Refuse if this is the last remaining company
    total_companies = Company.query.count()
    if total_companies <= 1:
        flash(
            'Cannot delete the last remaining company. '
            'Create another company first.',
            'danger',
        )
        return redirect(url_for('company.list_companies'))

    company_name = company.name

    # Clear session if we're deleting the active company
    if session.get('company_id') == company.id:
        clear_current_company()

    try:
        with bypass_scoping():
            counts = _hard_delete_company(company.id)
            db.session.delete(company)
            db.session.commit()

        total = sum(counts.values())
        flash(
            f'Company "{company_name}" and all its data '
            f'({total} records) have been permanently deleted.',
            'success',
        )
    except Exception as e:
        db.session.rollback()
        print(f"[company] hard delete failed for {company_id}: {e}")
        flash(f'Error deleting company: {str(e)}', 'danger')

    return redirect(url_for('company.list_companies'))

# ------------------------------------------------------------------ #
#  AUTOMATIC SCOPING (SQLAlchemy events)
# ------------------------------------------------------------------ #
from sqlalchemy.orm import Session as _OrmSession

def _install_scoping_events(app=None):
    """
    Install SQLAlchemy ORM Session event listeners exactly once.

    IMPORTANT:
        Listeners MUST be attached to SQLAlchemy's ORM Session class,
        not to Flask-SQLAlchemy's db.session scoped proxy.

        db.session is a request-scoped/session proxy. Attaching event
        listeners to that proxy can associate them with a particular
        session instance, causing them not to survive when the request
        session is recycled.

    The listeners below are therefore registered against _OrmSession
    (the actual SQLAlchemy Session class) and protected by a module-level
    flag so repeated calls to init_company_support() do not create
    duplicate listeners.
    """
    global _scoping_events_installed

    if _scoping_events_installed:
        return

    def _models_with_company_id():
        return [
            cls for cls in _scoped_model_classes()
            if hasattr(cls, 'company_id')
        ]

    def _filter_query_by_company(execute_state):
        """Apply the active-company filter to SELECT statements."""
        if _bypass_scoping:
            return

        if not has_request_context():
            return

        if not execute_state.is_select:
            return

        company_id = session.get('company_id')
        if not company_id:
            return

        for cls in _models_with_company_id():
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    cls,
                    lambda cls_: cls_.company_id == company_id,
                    include_aliases=True,
                    track_closure_variables=True,
                )
            )

    def _stamp_company_id(sess, flush_context, instances):
        """Stamp new scoped ORM objects with the active company_id."""
        if _bypass_scoping:
            return

        if not has_request_context():
            return

        company_id = session.get('company_id')
        if not company_id:
            return

        scoped = set(_models_with_company_id())

        for obj in sess.new:
            if type(obj) in scoped and getattr(obj, 'company_id', None) is None:
                obj.company_id = company_id

    # CRITICAL:
    # Register against the ORM Session CLASS, never db.session.
    event.listen(_OrmSession, 'do_orm_execute', _filter_query_by_company)
    event.listen(_OrmSession, 'before_flush', _stamp_company_id)

    _scoping_events_installed = True
    print("[company] SQLAlchemy company-scoping events installed on ORM Session.")


# ------------------------------------------------------------------ #
#  REQUEST HOOKS + BOOTSTRAP
# ------------------------------------------------------------------ #

def init_company_support(app, db_):
    """
    1. Inject company_id columns into scoped models (models.py stays clean).
    2. Wire up before_request, context_processor.
    3. Install SQLAlchemy scoping events.
    4. Bootstrap the default company and DB columns.
    """
    # Must happen BEFORE any query runs against the scoped models.
    _inject_company_id_columns()

    @app.before_request
    def _load_active_company():
        g.company = None

        # Read the company selected in the current Flask session for EVERY
        # request. Do not cache this value at module level.
        selected_company_id = session.get('company_id')
        g.company_id = selected_company_id

        if current_user.is_authenticated and not g.company_id:
            default = Company.query.filter_by(is_default=True, is_active=True).first()
            if not default:
                actives = Company.query.filter_by(is_active=True).all()
                if len(actives) == 1:
                    default = actives[0]
            if default:
                session['company_id'] = default.id
                g.company_id = default.id

        if g.company_id:
            g.company = db_.session.get(Company, g.company_id)

            # Never allow a stale/deactivated company id to remain active.
            if g.company is None or not g.company.is_active:
                session.pop('company_id', None)
                g.company = None
                g.company_id = None

            # Keep the request context synchronized with the actual selected
            # company. The ORM event listener reads Flask's session directly.
            else:
                g.company_id = g.company.id

    @app.context_processor
    def _inject_company():
        return dict(
            active_company=getattr(g, 'company', None),
            all_companies=Company.query.filter_by(is_active=True)
                                      .order_by(Company.name).all(),
            has_multiple_companies=Company.query.filter_by(is_active=True).count() > 1,
        )

    _install_scoping_events(app)

    with app.app_context():
        _ensure_default_company()

    return app


# ------------------------------------------------------------------ #
#  HARD DELETE (cascade)
# ------------------------------------------------------------------ #

def _hard_delete_company(company_id):
    """
    Physically delete a company and ALL scoped records that belong to it.
    Order matters because of foreign keys:
        1. Line items (children of invoices/purchases/vouchers)
        2. Vouchers / invoices / purchases / journal entries / expenses
        3. General ledger
        4. Customers / suppliers
        5. Chart of accounts (children first, then parents)
        6. Account types, categories
        7. Finally, the company row itself

    Returns a dict with counts for reporting.
    """
    from sqlalchemy import text
    from acctsys import models as m

    counts = {}

    # ---- 1. Line items ----
    counts['invoice_line'] = db.session.query(m.InvoiceLine).filter(
        m.InvoiceLine.invoice_id.in_(
            db.session.query(m.Invoice.id).filter_by(company_id=company_id)
        )
    ).delete(synchronize_session=False)

    counts['purchase_line'] = db.session.query(m.PurchaseLine).filter(
        m.PurchaseLine.purchase_id.in_(
            db.session.query(m.Purchase.id).filter_by(company_id=company_id)
        )
    ).delete(synchronize_session=False)

    counts['payment_voucher_line'] = db.session.query(m.PaymentVoucherLine).filter(
        m.PaymentVoucherLine.payment_voucher_id.in_(
            db.session.query(m.PaymentVoucher.id).filter_by(company_id=company_id)
        )
    ).delete(synchronize_session=False)

    # ---- 2. Header documents ----
    counts['journal_entry']     = m.JournalEntry.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['invoice']           = m.Invoice.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['purchase']          = m.Purchase.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['payment_voucher']   = m.PaymentVoucher.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['expense']           = m.Expense.query.filter_by(company_id=company_id).delete(synchronize_session=False)

    # ---- 3. General ledger ----
    counts['general_ledger'] = m.GeneralLedger.query.filter_by(company_id=company_id).delete(synchronize_session=False)

    # ---- 4. Customers / suppliers ----
    counts['customer'] = m.Customer.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['supplier'] = m.Supplier.query.filter_by(company_id=company_id).delete(synchronize_session=False)

    # ---- 5. Chart of accounts (children first) ----
    # Delete sub-accounts (those with a parent) before parents
    counts['chart_of_account'] = m.ChartOfAccount.query.filter_by(company_id=company_id).delete(synchronize_session=False)

    # ---- 6. Account types & categories ----
    counts['account_type'] = m.AccountType.query.filter_by(company_id=company_id).delete(synchronize_session=False)
    counts['category']     = m.Category.query.filter_by(company_id=company_id).delete(synchronize_session=False)

    db.session.flush()
    return counts

# ------------------------------------------------------------------ #
#  MIGRATION / SEEDING
# ------------------------------------------------------------------ #

def _ensure_default_company():
    from sqlalchemy import text, inspect

    with bypass_scoping():
        default = Company.query.filter_by(is_default=True).first()
        if not default:
            default = Company(
                name='Default Company', code='DEFAULT',
                base_currency='USD', is_active=True, is_default=True,
            )
            db.session.add(default)
            db.session.commit()
            print(f"[company] Seeded default company (id={default.id}).")

        for tbl in SCOPED_TABLES:
            _add_company_id_column_if_missing(tbl)

        for tbl in SCOPED_TABLES:
            try:
                db.session.execute(
                    text(f"UPDATE {tbl} SET company_id = :cid WHERE company_id IS NULL"),
                    {'cid': default.id},
                )
            except Exception as e:
                print(f"[company] backfill {tbl} failed: {e}")

        db.session.commit()
        print(f"[company] Default company ready (id={default.id}).")


def _add_company_id_column_if_missing(table_name):
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(db.engine)
        if table_name not in inspector.get_table_names():
            return
        cols = [c['name'] for c in inspector.get_columns(table_name)]
        if 'company_id' in cols:
            return
        db.session.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN company_id INTEGER REFERENCES company(id)")
        )
        db.session.commit()
        print(f"[company] Added company_id to {table_name}.")
    except Exception as e:
        db.session.rollback()
        print(f"[company] Could not add company_id to {table_name}: {e}")