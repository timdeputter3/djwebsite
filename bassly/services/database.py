import json
from datetime import datetime

from sqlalchemy import inspect, text

from bassly.config import (
    APPLICATION_UPLOAD_ROOT,
    LEGACY_BOOKINGS_FILE,
    MANAGER_EMAIL,
    MANAGER_PASSWORD_RAW,
    MANAGER_USERNAME,
)
from bassly.extensions import db
from bassly.models import Booking, DJApplication, User
from bassly.services.public import sync_dj_directory_records, sync_dj_status_records
from bassly.utils import normalized_email


def ensure_schema():
    inspector = inspect(db.engine)
    if "dj_application" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("dj_application")}
        statements = []
        if "manager_note" not in columns:
            statements.append("ALTER TABLE dj_application ADD COLUMN manager_note TEXT")
        if "decided_at" not in columns:
            statements.append("ALTER TABLE dj_application ADD COLUMN decided_at DATETIME")

        if statements:
            with db.engine.begin() as connection:
                for statement in statements:
                    connection.execute(text(statement))

    if "booking" in inspector.get_table_names():
        booking_columns = {column["name"] for column in inspector.get_columns("booking")}
        booking_statements = []
        if "customer_id" not in booking_columns:
            booking_statements.append("ALTER TABLE booking ADD COLUMN customer_id INTEGER")
        if "dj_profile_id" not in booking_columns:
            booking_statements.append("ALTER TABLE booking ADD COLUMN dj_profile_id INTEGER")

        if booking_statements:
            with db.engine.begin() as connection:
                for statement in booking_statements:
                    connection.execute(text(statement))


def seed_admin_user():
    username = (MANAGER_USERNAME or "").strip().lower()
    email = normalized_email(MANAGER_EMAIL)
    password = MANAGER_PASSWORD_RAW or ""
    if not (username and email and password):
        return

    admin = User.query.filter_by(username=username).first()
    if admin is None:
        admin = User.query.filter_by(email=email).first()

    if admin is None:
        admin = User(
            username=username,
            email=email,
            role="admin",
            is_active=True,
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return

    changed = False
    if admin.email != email:
        admin.email = email
        changed = True
    if admin.role != "admin":
        admin.role = "admin"
        changed = True
    if not admin.is_active:
        admin.is_active = True
        changed = True
    if not admin.check_password(password):
        admin.set_password(password)
        changed = True

    if changed:
        db.session.commit()


def migrate_legacy_bookings():
    if not LEGACY_BOOKINGS_FILE.exists() or Booking.query.first() is not None:
        return

    legacy_bookings = json.loads(LEGACY_BOOKINGS_FILE.read_text(encoding="utf-8"))
    for item in legacy_bookings:
        accepted_at = item.get("accepted_at")
        booking = Booking(
            public_id=item["id"],
            name=item["name"],
            email=item["email"],
            phone=item["phone"],
            company=item.get("company", ""),
            event_type=item["event_type"],
            event_date=datetime.strptime(item["event_date"], "%Y-%m-%d").date(),
            start_time=datetime.strptime(item["start_time"], "%H:%M").time(),
            end_time=datetime.strptime(item["end_time"], "%H:%M").time(),
            location=item["location"],
            guests=int(item["guests"]),
            dj=item["dj"],
            notes=item.get("notes", ""),
            status=item.get("status", "pending"),
            created_at=datetime.strptime(item["created_at"], "%Y-%m-%d %H:%M"),
            accepted_at=datetime.strptime(accepted_at, "%Y-%m-%d %H:%M") if accepted_at else None,
        )
        db.session.add(booking)

    db.session.commit()


def bootstrap_database():
    APPLICATION_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    db.create_all()
    ensure_schema()
    migrate_legacy_bookings()
    seed_admin_user()
    sync_dj_status_records()
    sync_dj_directory_records()
