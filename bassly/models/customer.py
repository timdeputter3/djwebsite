from datetime import datetime

from bassly.extensions import db


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    company = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship("User", back_populates="customer_profile")
