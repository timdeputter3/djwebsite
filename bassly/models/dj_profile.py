from datetime import datetime

from bassly.extensions import db


class DJProfile(db.Model):
    __tablename__ = "djs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    stage_name = db.Column(db.String(160), nullable=False)
    city = db.Column(db.String(120), nullable=True)
    genres = db.Column(db.String(240), nullable=False)
    music_style = db.Column(db.Text, nullable=True)
    experience = db.Column(db.Text, nullable=True)
    equipment = db.Column(db.Text, nullable=True)
    socials = db.Column(db.Text, nullable=True)
    availability = db.Column(db.Text, nullable=False, default="[]")
    bio = db.Column(db.Text, nullable=False)
    photo_paths = db.Column(db.Text, nullable=False, default="[]")
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    is_bookable = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship("User", back_populates="dj_profile")
