from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'


class Company(db.Model):
    __tablename__ = 'company'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.String(500))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    logo = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Company {self.name}>'


class PrepaymentSchedule(db.Model):
    __tablename__ = 'prepayment_schedules'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    # REMOVED: user_id - not needed for this application

    # Account fields
    debit_account = db.Column(db.String(200), nullable=False)
    credit_account = db.Column(db.String(200), nullable=False)

    # Transaction details
    transaction_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(500), nullable=False)

    # Prepayment details
    total_cost = db.Column(db.Numeric(10, 2), nullable=False)
    period_to_amortize = db.Column(db.Integer, nullable=False)
    amortize_start_period = db.Column(db.Date, nullable=False)

    # Status and timestamps
    status = db.Column(db.String(50), default='ACTIVE')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = db.relationship('Company', backref='prepayment_schedules')
    amortization_entries = db.relationship('AmortizationEntry', backref='schedule', cascade='all, delete-orphan')

    def get_amortization_schedule(self):
        """Generate amortization schedule"""
        schedule = []
        if self.period_to_amortize <= 0:
            return schedule

        period_amount = float(self.total_cost) / self.period_to_amortize
        current_date = self.amortize_start_period
        remaining_balance = float(self.total_cost)

        for period in range(1, self.period_to_amortize + 1):
            amount = remaining_balance if period == self.period_to_amortize else period_amount
            schedule.append({
                'period': period,
                'date': current_date,
                'amount': amount,
                'remaining_balance': remaining_balance - amount,
                'status': 'Pending' if current_date > date.today() else 'Completed'
            })
            remaining_balance -= amount
            # Add 1 month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)
        return schedule

    @property
    def remaining_balance(self):
        """Calculate remaining balance"""
        schedule = self.get_amortization_schedule()
        if not schedule:
            return float(self.total_cost)
        completed = [s for s in schedule if s['status'] == 'Completed']
        return float(self.total_cost) - sum(s['amount'] for s in completed)

    def __repr__(self):
        return f'<PrepaymentSchedule {self.id}: {self.description[:30]}>'


class AmortizationEntry(db.Model):
    __tablename__ = 'amortization_entries'

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('prepayment_schedules.id'), nullable=False)

    period = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    remaining_balance = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(50), default='PENDING')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<AmortizationEntry {self.id}: Schedule {self.schedule_id}, Period {self.period}>'


# Keep CompanyUser if you need it for user-company relationships
class CompanyUser(db.Model):
    __tablename__ = 'company_user'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='company_assignments')
    company = db.relationship('Company', backref='user_assignments')