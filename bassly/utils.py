import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from bassly.config import ALLOWED_IMAGE_EXTENSIONS


def current_database_label(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        return "sqlite"
    if uri.startswith("postgresql://") or uri.startswith("postgresql+psycopg://"):
        return "postgresql"
    return "unknown"


def slugify_name(value):
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or uuid4().hex[:8]


def normalized_email(value):
    return (value or "").strip().lower()


def parse_availability(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return sorted(parsed)
    except json.JSONDecodeError:
        pass
    return [value]


def allowed_image(filename):
    return Path(filename).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS


def role_label(role):
    return {
        "customer": "Klant",
        "dj": "DJ",
        "admin": "Admin",
    }.get(role, role.title())


def booking_bounds(date_value, start_time_value, end_time_value):
    start_at = datetime.combine(date_value, start_time_value)
    end_at = datetime.combine(date_value, end_time_value)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    return start_at, end_at


def serialize_booking(booking):
    start_at, end_at = booking_bounds(booking.event_date, booking.start_time, booking.end_time)
    return {
        "id": booking.public_id,
        "name": booking.name,
        "email": booking.email,
        "phone": booking.phone,
        "company": booking.company or "",
        "event_type": booking.event_type,
        "event_date": booking.event_date.strftime("%Y-%m-%d"),
        "start_time": booking.start_time.strftime("%H:%M"),
        "end_time": booking.end_time.strftime("%H:%M"),
        "location": booking.location,
        "guests": booking.guests,
        "dj": booking.dj,
        "notes": booking.notes or "",
        "status": booking.status,
        "created_at": booking.created_at.strftime("%Y-%m-%d %H:%M"),
        "accepted_at": booking.accepted_at.strftime("%Y-%m-%d %H:%M") if booking.accepted_at else "",
        "overnight": end_at.date() != start_at.date(),
    }


def serialize_application(application):
    return {
        "id": application.public_id,
        "stage_name": application.stage_name,
        "contact_name": application.contact_name,
        "email": application.email,
        "phone": application.phone,
        "city": application.city,
        "genres": application.genres,
        "music_style": application.music_style,
        "experience": application.experience,
        "equipment": application.equipment or "",
        "socials": application.socials or "",
        "availability": parse_availability(application.availability),
        "bio": application.bio,
        "photo_paths": json.loads(application.photo_paths or "[]"),
        "status": application.status,
        "manager_note": application.manager_note or "",
        "created_at": application.created_at.strftime("%Y-%m-%d %H:%M"),
        "decided_at": application.decided_at.strftime("%Y-%m-%d %H:%M") if application.decided_at else "",
    }


def serialize_dj_profile(profile):
    return {
        "id": profile.id,
        "slug": profile.slug,
        "stage_name": profile.stage_name,
        "city": profile.city or "",
        "genres": profile.genres,
        "music_style": profile.music_style or "",
        "experience": profile.experience or "",
        "equipment": profile.equipment or "",
        "socials": profile.socials or "",
        "availability": parse_availability(profile.availability),
        "bio": profile.bio,
        "photo_paths": json.loads(profile.photo_paths or "[]"),
        "is_approved": profile.is_approved,
        "is_bookable": profile.is_bookable,
        "created_at": profile.created_at.strftime("%Y-%m-%d %H:%M"),
        "user_email": profile.user.email if profile.user else "",
        "username": profile.user.username if profile.user else "",
        "source": "account" if profile.user_id else "directory",
    }


def database_uri_present():
    return bool(os.environ.get("DATABASE_URL"))
