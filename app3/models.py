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

