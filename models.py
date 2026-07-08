from extensions import db
from datetime import datetime


class Company(db.Model):
    __tablename__ = "company"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    logo = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# models.py - Updated PrepaymentSchedule class
class PrepaymentSchedule(db.Model):
    __tablename__ = "prepayment_schedule"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id")
    )

    description = db.Column(db.String(200))
    amount = db.Column(db.Float)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)

    # Add this line:
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

class AmortizationEntry(db.Model):
    __tablename__ = "amortization_entry"

    id = db.Column(db.Integer, primary_key=True)

    schedule_id = db.Column(
        db.Integer,
        db.ForeignKey("prepayment_schedule.id"),
        nullable=False
    )

    period = db.Column(db.Integer, nullable=False)

    due_date = db.Column(db.Date, nullable=False)

    amount = db.Column(db.Float, nullable=False)

    remaining_balance = db.Column(db.Float, default=0)

    status = db.Column(
        db.String(20),
        default="PENDING"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )