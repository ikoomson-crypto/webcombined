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

