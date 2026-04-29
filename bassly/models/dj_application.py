from datetime import datetime

from bassly.extensions import db


class DJApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(24), unique=True, nullable=False)
    stage_name = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    genres = db.Column(db.String(240), nullable=False)
    music_style = db.Column(db.Text, nullable=False)
    experience = db.Column(db.Text, nullable=False)
    equipment = db.Column(db.Text, nullable=True)
    socials = db.Column(db.Text, nullable=True)
    availability = db.Column(db.Text, nullable=True)
    bio = db.Column(db.Text, nullable=False)
    photo_paths = db.Column(db.Text, nullable=False, default="[]")
    status = db.Column(db.String(20), nullable=False, default="new")
    manager_note = db.Column(db.Text, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
