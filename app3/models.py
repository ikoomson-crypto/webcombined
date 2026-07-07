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
    __table_args__ = {'extend_existing': True}  # Add this to prevent redefinition error

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.Text, default='')
    phone = db.Column(db.String(20), default='')
    email = db.Column(db.String(120), default='')
    logo = db.Column(db.String(200), default='')  # New field for logo
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return self.name


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


class PrepaymentSchedule(db.Model):
    __tablename__ = 'prepayment_schedule'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    debit_account = db.Column(db.String(50), nullable=False)
    credit_account = db.Column(db.String(50), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    total_cost = db.Column(db.Numeric(15, 2), nullable=False)
    period_to_amortize = db.Column(db.Integer, nullable=False)
    amortize_start_period = db.Column(db.Date, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = db.relationship('Company', backref='schedules')
    created_by = db.relationship('User', backref='created_schedules')
    entries = db.relationship('AmortizationEntry', backref='schedule', cascade='all, delete-orphan')

    def get_amortization_schedule(self):
        """Generate amortization schedule"""
        schedule = []
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
        completed = [s for s in schedule if s['status'] == 'Completed']
        return float(self.total_cost) - sum(s['amount'] for s in completed)

    def __repr__(self):
        return f'<Schedule {self.id}: {self.description[:30]}>'


class AmortizationEntry(db.Model):
    __tablename__ = 'amortization_entry'
    __table_args__ = (
        db.UniqueConstraint('schedule_id', 'period', name='unique_period'),
        {'extend_existing': True}
    )

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('prepayment_schedule.id'), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    remaining_balance = db.Column(db.Numeric(15, 2), nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    paid_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)