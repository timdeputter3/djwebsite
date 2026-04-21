import csv
import io
import json
import os
import smtplib
from calendar import month_name, monthrange
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from uuid import uuid4

from email_validator import EmailNotValidError, validate_email
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

LEGACY_BOOKINGS_FILE = BASE_DIR / "bookings.json"
LOCAL_DATABASE = BASE_DIR / "bassly.db"
DJ_IMAGE_ROOT = BASE_DIR / "static" / "img" / "djs"
APPLICATION_UPLOAD_ROOT = BASE_DIR / "static" / "uploads" / "dj-applications"
DJ_PROFILE_UPLOAD_ROOT = BASE_DIR / "static" / "uploads" / "dj-profiles"
UPLOAD_BACKEND = os.environ.get("UPLOAD_BACKEND", "local")
SUPABASE_PROJECT_URL = os.environ.get("SUPABASE_PROJECT_URL", "")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "bassly-media")

database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url and database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or f"sqlite:///{LOCAL_DATABASE.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bassly-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Log eerst in om verder te gaan."

MANAGER_USERNAME = os.environ.get("MANAGER_USERNAME", "managertim")
MANAGER_PASSWORD_RAW = os.environ.get("MANAGER_PASSWORD", "managertim132")
MANAGER_PASSWORD_HASH = generate_password_hash(MANAGER_PASSWORD_RAW)
MANAGER_EMAIL = os.environ.get("MANAGER_EMAIL", "manager@bassly.local")
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME or "")
MANAGER_NOTIFY_EMAIL = os.environ.get("MANAGER_NOTIFY_EMAIL")


def current_database_label():
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


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def build_gallery(folder_name):
    folder = DJ_IMAGE_ROOT / folder_name
    if not folder.exists():
        return []

    files = sorted(
        [
            file for file in folder.iterdir()
            if file.is_file() and file.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS
        ],
        key=lambda file: file.name.lower(),
    )
    return [f"img/djs/{folder_name}/{file.name}" for file in files]


DJ_PROFILES = [
    {
        "name": "DJ Vet & Vriend",
        "slug": "dj-vet-vriend",
        "genre": "Open format / all-round party / student events",
        "bio": "Een energiek duo uit de regio dat vlot schakelt tussen meezingers, party classics en moderne tracks om elk publiek meteen mee te krijgen.",
        "gallery": build_gallery("vet-vriend"),
        "availability": [],
        "socials": "",
        "source": "core",
        "active": True,
    },
    {
        "name": "Vicle",
        "slug": "vicle",
        "genre": "Club / house / late-night energy",
        "bio": "Brengt een frisse, hedendaagse sound met clubgevoel, sterke opbouw en de juiste energie voor avonden die mogen blijven hangen.",
        "gallery": build_gallery("vicle"),
        "availability": [],
        "socials": "",
        "source": "core",
        "active": True,
    },
]


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(24), unique=True, nullable=False, default=lambda: uuid4().hex[:12])
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer_profile = db.relationship("Customer", back_populates="user", uselist=False)
    dj_profile = db.relationship("DJProfile", back_populates="user", uselist=False)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def get_id(self):
        return str(self.id)


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


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(24), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(200), nullable=True)
    event_type = db.Column(db.String(120), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    guests = db.Column(db.Integer, nullable=False)
    dj = db.Column(db.String(120), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    dj_profile_id = db.Column(db.Integer, db.ForeignKey("djs.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)
    customer = db.relationship("Customer", foreign_keys=[customer_id])
    dj_profile = db.relationship("DJProfile", foreign_keys=[dj_profile_id])


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


class DJStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    source = db.Column(db.String(40), nullable=False, default="core")


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


def create_user_with_profile(username, email, password, role, full_name="", phone="", company="", city="", stage_name=""):
    try:
        email = normalized_email(validate_email(email, check_deliverability=False).normalized)
    except EmailNotValidError as exc:
        raise ValueError(f"Ongeldig e-mailadres: {exc}")
    username = (username or "").strip().lower()
    if role not in {"customer", "dj"}:
        raise ValueError("Ongeldige rol.")
    if not username or not email or not password:
        raise ValueError("Gebruikersnaam, e-mail en wachtwoord zijn verplicht.")
    if len(password) < 8:
        raise ValueError("Kies een wachtwoord van minstens 8 tekens.")
    if User.query.filter_by(username=username).first():
        raise ValueError("Deze gebruikersnaam is al in gebruik.")
    if User.query.filter_by(email=email).first():
        raise ValueError("Dit e-mailadres is al in gebruik.")

    user = User(username=username, email=email, role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    if role == "customer":
        profile = Customer(
            user_id=user.id,
            full_name=full_name.strip() or username,
            phone=(phone or "").strip(),
            company=(company or "").strip(),
            city=(city or "").strip(),
        )
        db.session.add(profile)
    else:
        slug_base = slugify_name(stage_name or username)
        slug = slug_base
        counter = 2
        while DJProfile.query.filter_by(slug=slug).first():
            slug = f"{slug_base}-{counter}"
            counter += 1
        profile = DJProfile(
            user_id=user.id,
            slug=slug,
            stage_name=(stage_name or username).strip(),
            city=(city or "").strip(),
            genres="Nog aan te vullen",
            music_style="",
            experience="",
            equipment="",
            socials="",
            availability="[]",
            bio="Dit DJ-profiel werd aangemaakt en wacht nog op verdere aanvulling en goedkeuring.",
            photo_paths="[]",
            is_approved=False,
            is_bookable=False,
        )
        db.session.add(profile)

    db.session.commit()
    return user


def save_application_photos(files, application_id):
    saved_paths = []
    target_dir = APPLICATION_UPLOAD_ROOT / application_id
    target_dir.mkdir(parents=True, exist_ok=True)

    for index, photo in enumerate(files, start=1):
        if not photo or not photo.filename or not allowed_image(photo.filename):
            continue

        safe_name = secure_filename(photo.filename)
        extension = Path(safe_name).suffix.lower()
        filename = f"{index:02d}-{uuid4().hex[:8]}{extension}"
        destination = target_dir / filename
        photo.save(destination)
        saved_paths.append(f"uploads/dj-applications/{application_id}/{filename}")

    return saved_paths


def save_dj_profile_photos(files, profile_folder, existing_paths=None):
    saved_paths = list(existing_paths or [])
    target_dir = DJ_PROFILE_UPLOAD_ROOT / profile_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    next_index = len(saved_paths) + 1
    for photo in files:
        if not photo or not photo.filename or not allowed_image(photo.filename):
            continue

        safe_name = secure_filename(photo.filename)
        extension = Path(safe_name).suffix.lower()
        filename = f"{next_index:02d}-{uuid4().hex[:8]}{extension}"
        destination = target_dir / filename
        photo.save(destination)
        saved_paths.append(f"uploads/dj-profiles/{profile_folder}/{filename}")
        next_index += 1

    return saved_paths


def send_notification(subject, body, to_address=None):
    recipient = to_address or MANAGER_NOTIFY_EMAIL
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM and recipient):
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)
    return True


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


def ensure_schema():
    inspector = inspect(db.engine)
    if "dj_application" not in inspector.get_table_names():
        pass
    else:
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


def sync_dj_status_records():
    existing = {record.slug: record for record in DJStatus.query.all()}

    for dj in DJ_PROFILES:
        if dj["slug"] not in existing:
            db.session.add(
                DJStatus(
                    slug=dj["slug"],
                    name=dj["name"],
                    active=True,
                    source="core",
                )
            )

    accepted_apps = DJApplication.query.filter_by(status="accepted").all()
    for application in accepted_apps:
        slug = slugify_name(application.stage_name)
        if slug not in existing:
            db.session.add(
                DJStatus(
                    slug=slug,
                    name=application.stage_name,
                    active=True,
                    source="application",
                )
            )

    db.session.commit()


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


def sync_dj_directory_records():
    existing = {record.slug: record for record in DJProfile.query.all()}
    status_map = {item.slug: item for item in DJStatus.query.all()}

    for dj in DJ_PROFILES:
        status = status_map.get(dj["slug"])
        is_bookable = dj.get("active", True) if status is None else status.active
        record = existing.get(dj["slug"])
        if record is None:
            db.session.add(
                DJProfile(
                    slug=dj["slug"],
                    stage_name=dj["name"],
                    city="Kortrijk",
                    genres=dj["genre"],
                    music_style="",
                    experience="",
                    equipment="",
                    socials=dj.get("socials", ""),
                    availability=json.dumps(dj.get("availability", [])),
                    bio=dj["bio"],
                    photo_paths=json.dumps(dj.get("gallery", [])),
                    is_approved=True,
                    is_bookable=is_bookable,
                )
            )
            continue

        changed = False
        if record.stage_name != dj["name"]:
            record.stage_name = dj["name"]
            changed = True
        if record.genres != dj["genre"]:
            record.genres = dj["genre"]
            changed = True
        if record.bio != dj["bio"]:
            record.bio = dj["bio"]
            changed = True
        if record.photo_paths != json.dumps(dj.get("gallery", [])):
            record.photo_paths = json.dumps(dj.get("gallery", []))
            changed = True
        if not record.is_approved:
            record.is_approved = True
            changed = True
        if record.is_bookable != is_bookable:
            record.is_bookable = is_bookable
            changed = True
        if changed:
            db.session.add(record)

    accepted_applications = DJApplication.query.filter_by(status="accepted").all()
    for application in accepted_applications:
        slug = slugify_name(application.stage_name)
        status = status_map.get(slug)
        is_bookable = True if status is None else status.active
        record = existing.get(slug)
        photo_paths = application.photo_paths or "[]"
        if record is None:
            db.session.add(
                DJProfile(
                    slug=slug,
                    stage_name=application.stage_name,
                    city=application.city,
                    genres=application.genres,
                    music_style=application.music_style,
                    experience=application.experience,
                    equipment=application.equipment or "",
                    socials=application.socials or "",
                    availability=application.availability or "[]",
                    bio=application.bio,
                    photo_paths=photo_paths,
                    is_approved=True,
                    is_bookable=is_bookable,
                )
            )
            continue

        record.stage_name = application.stage_name
        record.city = application.city
        record.genres = application.genres
        record.music_style = application.music_style
        record.experience = application.experience
        record.equipment = application.equipment or ""
        record.socials = application.socials or ""
        record.availability = application.availability or "[]"
        record.bio = application.bio
        record.photo_paths = photo_paths
        record.is_approved = True
        record.is_bookable = is_bookable
        db.session.add(record)

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


def accepted_bookings(limit=None):
    query = (
        Booking.query.filter_by(status="accepted")
        .order_by(Booking.event_date.asc(), Booking.start_time.asc())
    )
    bookings = query.limit(limit).all() if limit else query.all()
    return [serialize_booking(booking) for booking in bookings]


def public_djs():
    profiles = (
        DJProfile.query.filter_by(is_approved=True)
        .order_by(DJProfile.created_at.asc(), DJProfile.stage_name.asc())
        .all()
    )
    return [
        {
            "name": profile.stage_name,
            "slug": profile.slug,
            "genre": profile.genres,
            "bio": profile.bio,
            "gallery": json.loads(profile.photo_paths or "[]"),
            "availability": parse_availability(profile.availability),
            "socials": profile.socials or "",
            "music_style": profile.music_style or "",
            "experience": profile.experience or "",
            "city": profile.city or "",
            "source": "account" if profile.user_id else "directory",
            "active": profile.is_bookable,
        }
        for profile in profiles
    ]


def find_public_dj(slug):
    for dj in public_djs():
        if dj.get("slug") == slug:
            return dj
    return None


def active_public_djs():
    return [dj for dj in public_djs() if dj.get("active", True)]


def booking_conflicts(dj_name, event_date, start_time, end_time, exclude_public_id=None):
    requested_start, requested_end = booking_bounds(event_date, start_time, end_time)
    candidates = Booking.query.filter(
        Booking.dj == dj_name,
        Booking.status.in_(["pending", "accepted"]),
    ).all()

    conflicts = []
    for booking in candidates:
        if exclude_public_id and booking.public_id == exclude_public_id:
            continue
        existing_start, existing_end = booking_bounds(booking.event_date, booking.start_time, booking.end_time)
        if requested_start < existing_end and requested_end > existing_start:
            conflicts.append(serialize_booking(booking))
    return conflicts


def is_manager_logged_in():
    return session.get("manager_authenticated", False)


def is_admin_user():
    return current_user.is_authenticated and current_user.role == "admin"


def manager_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not (is_manager_logged_in() or is_admin_user()):
            return redirect(url_for("manager_login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator


def booking_form_defaults():
    if current_user.is_authenticated and current_user.role == "customer" and current_user.customer_profile:
        profile = current_user.customer_profile
        return {
            "name": profile.full_name or current_user.username,
            "email": current_user.email,
            "phone": profile.phone or "",
            "company": profile.company or "",
            "location": profile.city or "",
        }
    return {}


@app.context_processor
def inject_global_state():
    return {
        "manager_logged_in": is_manager_logged_in(),
        "manager_username": MANAGER_USERNAME,
        "signed_in_user": current_user if current_user.is_authenticated else None,
        "role_label": role_label,
        "upload_backend": UPLOAD_BACKEND,
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


with app.app_context():
    bootstrap_database()


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("account"))
    error = ""
    form_data = {}
    if request.method == "POST":
        form_data = request.form.to_dict()
        username = request.form.get("username", "")
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        role = request.form.get("role", "customer").strip().lower()
        full_name = request.form.get("full_name", "")
        phone = request.form.get("phone", "")
        company = request.form.get("company", "")
        city = request.form.get("city", "")
        stage_name = request.form.get("stage_name", "")

        try:
            user = create_user_with_profile(
                username=username,
                email=email,
                password=password,
                role=role,
                full_name=full_name,
                phone=phone,
                company=company,
                city=city,
                stage_name=stage_name,
            )
            login_user(user)
            flash("Je account is aangemaakt en je bent nu ingelogd.", "success")
            return redirect(url_for("account"))
        except ValueError as exc:
            error = str(exc)

    return render_template("register.html", error=error, form_data=form_data)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account"))
    error = ""
    next_url = request.args.get("next") or request.form.get("next") or ""
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            (User.username == identifier.lower()) | (User.email == normalized_email(identifier))
        ).first()

        if user and user.is_active and user.check_password(password):
            login_user(user)
            flash("Welkom terug bij Bassly.", "success")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("account"))
        error = "De logingegevens kloppen niet."

    return render_template("login.html", error=error, next_url=next_url)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Je bent uitgelogd.", "success")
    return redirect(url_for("home"))


@app.route("/account")
@login_required
def account():
    profile = current_user.customer_profile if current_user.role == "customer" else current_user.dj_profile
    return render_template("account.html", profile=profile)


@app.route("/customer/profile", methods=["GET", "POST"])
@role_required("customer")
def customer_profile_edit():
    profile = current_user.customer_profile
    if profile is None:
        abort(404)

    if request.method == "POST":
        profile.full_name = request.form.get("full_name", "").strip() or profile.full_name
        profile.phone = request.form.get("phone", "").strip()
        profile.company = request.form.get("company", "").strip()
        profile.city = request.form.get("city", "").strip()
        db.session.add(profile)
        db.session.commit()
        flash("Je klantprofiel is bijgewerkt.", "success")
        return redirect(url_for("customer_profile_edit"))

    return render_template("customer_profile_edit.html", profile=profile)


@app.route("/dj/profile", methods=["GET", "POST"])
@role_required("dj")
def dj_profile_edit():
    profile = current_user.dj_profile
    if profile is None:
        abort(404)

    if request.method == "POST":
        profile.stage_name = request.form.get("stage_name", "").strip() or profile.stage_name
        profile.city = request.form.get("city", "").strip()
        profile.genres = request.form.get("genres", "").strip() or "Nog aan te vullen"
        profile.music_style = request.form.get("music_style", "").strip()
        profile.experience = request.form.get("experience", "").strip()
        profile.equipment = request.form.get("equipment", "").strip()
        profile.socials = request.form.get("socials", "").strip()
        profile.bio = request.form.get("bio", "").strip() or profile.bio

        availability_dates = sorted(
            [item.strip() for item in request.form.get("availability_dates", "").split(",") if item.strip()]
        )
        profile.availability = json.dumps(availability_dates)

        existing_paths = json.loads(profile.photo_paths or "[]")
        new_paths = save_dj_profile_photos(
            request.files.getlist("photos"),
            profile_folder=profile.slug,
            existing_paths=existing_paths,
        )
        profile.photo_paths = json.dumps(new_paths)

        db.session.add(profile)
        db.session.commit()
        flash("Je DJ-profiel is bijgewerkt.", "success")
        return redirect(url_for("dj_profile_edit"))

    return render_template(
        "dj_profile_edit.html",
        profile=profile,
        availability=parse_availability(profile.availability),
        photos=json.loads(profile.photo_paths or "[]"),
    )


@app.route("/")
def home():
    agenda = accepted_bookings(limit=4)
    djs = public_djs()
    return render_template("index.html", djs=djs, agenda=agenda)


@app.route("/djs")
def djs():
    return render_template("djs.html", djs=public_djs())


@app.route("/djs/<slug>")
def dj_detail(slug):
    dj = find_public_dj(slug)
    if dj is None:
        abort(404)
    return render_template("dj_detail.html", dj=dj)


@app.route("/agenda")
def agenda():
    return render_template("agenda.html", agenda_events=accepted_bookings())


@app.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        application_id = uuid4().hex[:12]
        photo_paths = save_application_photos(request.files.getlist("photos"), application_id)
        availability_dates = sorted(
            [item.strip() for item in request.form.get("availability_dates", "").split(",") if item.strip()]
        )

        application = DJApplication(
            public_id=application_id,
            stage_name=request.form["stage_name"].strip(),
            contact_name=request.form["contact_name"].strip(),
            email=request.form["email"].strip(),
            phone=request.form["phone"].strip(),
            city=request.form["city"].strip(),
            genres=request.form["genres"].strip(),
            music_style=request.form["music_style"].strip(),
            experience=request.form["experience"].strip(),
            equipment=request.form.get("equipment", "").strip(),
            socials=request.form.get("socials", "").strip(),
            availability=json.dumps(availability_dates),
            bio=request.form["bio"].strip(),
            photo_paths=json.dumps(photo_paths),
            status="new",
        )
        db.session.add(application)
        db.session.commit()

        send_notification(
            subject=f"Nieuwe DJ-aanmelding: {application.stage_name}",
            body=(
                f"Nieuwe DJ-aanmelding ontvangen.\n\n"
                f"Naam: {application.stage_name}\n"
                f"Contact: {application.contact_name}\n"
                f"E-mail: {application.email}\n"
                f"Genres: {application.genres}\n"
            ),
        )
        return redirect(url_for("join", success="1"))

    return render_template("join.html", success=request.args.get("success") == "1")


@app.route("/book", methods=["GET", "POST"])
@role_required("customer", "admin")
def book():
    djs = active_public_djs()
    base_form_data = booking_form_defaults()
    if request.method == "POST":
        event_date = datetime.strptime(request.form["event_date"], "%Y-%m-%d").date()
        start_time = datetime.strptime(request.form["start_time"], "%H:%M").time()
        end_time = datetime.strptime(request.form["end_time"], "%H:%M").time()
        dj_name = request.form["dj"].strip()
        selected_dj = next((dj for dj in public_djs() if dj["name"] == dj_name), None)
        selected_dj_profile = DJProfile.query.filter_by(slug=selected_dj["slug"]).first() if selected_dj else None
        if selected_dj is None or not selected_dj.get("active", True):
            return render_template(
                "booking.html",
                djs=djs,
                success=False,
                conflicts=[],
                form_data=request.form.to_dict(),
                booking_error="Deze DJ staat momenteel op inactief en kan niet geboekt worden.",
            )
        conflicts = booking_conflicts(dj_name, event_date, start_time, end_time)
        if conflicts:
            return render_template(
                "booking.html",
                djs=djs,
                success=False,
                conflicts=conflicts,
                form_data=request.form.to_dict(),
                booking_error="",
            )

        customer_profile = current_user.customer_profile if current_user.is_authenticated and current_user.role == "customer" else None
        booking = Booking(
            public_id=datetime.utcnow().strftime("%y%m%d%H%M%S%f")[-10:],
            name=request.form["name"].strip(),
            email=request.form["email"].strip(),
            phone=request.form["phone"].strip(),
            company=request.form.get("company", "").strip(),
            event_type=request.form["event_type"].strip(),
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            location=request.form["location"].strip(),
            guests=int(request.form["guests"]),
            dj=dj_name,
            customer_id=customer_profile.id if customer_profile else None,
            dj_profile_id=selected_dj_profile.id if selected_dj_profile else None,
            notes=request.form.get("notes", "").strip(),
            status="pending",
        )
        db.session.add(booking)
        db.session.commit()

        send_notification(
            subject=f"Nieuwe booking voor {booking.dj}",
            body=(
                f"Nieuwe bookingaanvraag ontvangen.\n\n"
                f"DJ: {booking.dj}\n"
                f"Datum: {booking.event_date}\n"
                f"Tijd: {booking.start_time.strftime('%H:%M')} - {booking.end_time.strftime('%H:%M')}\n"
                f"Boeker: {booking.name}\n"
            ),
        )
        return redirect(url_for("book", success="1"))

    return render_template(
        "booking.html",
        djs=djs,
        success=request.args.get("success") == "1",
        conflicts=[],
        form_data=base_form_data,
        booking_error="",
    )


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/health/db")
def health_db():
    try:
        db.session.execute(text("SELECT 1"))
        status = "ok"
    except Exception as exc:
        status = "error"
        return {
            "status": status,
            "database_engine": current_database_label(),
            "database_uri_present": bool(os.environ.get("DATABASE_URL")),
            "message": str(exc),
        }, 500

    return {
        "status": status,
        "database_engine": current_database_label(),
        "database_uri_present": bool(os.environ.get("DATABASE_URL")),
    }


@app.route("/manager/login", methods=["GET", "POST"])
def manager_login():
    error = False
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == MANAGER_USERNAME and check_password_hash(MANAGER_PASSWORD_HASH, password):
            session["manager_authenticated"] = True
            session["manager_username"] = username
            destination = request.args.get("next") or url_for("manager")
            return redirect(destination)
        error = True

    return render_template("manager_login.html", error=error)


@app.route("/manager/logout")
def manager_logout():
    session.pop("manager_authenticated", None)
    session.pop("manager_username", None)
    return redirect(url_for("home"))


@app.route("/manager")
@manager_required
def manager():
    pending = (
        Booking.query.filter_by(status="pending")
        .order_by(Booking.event_date.asc(), Booking.start_time.asc())
        .all()
    )
    accepted = (
        Booking.query.filter_by(status="accepted")
        .order_by(Booking.event_date.asc(), Booking.start_time.asc())
        .all()
    )
    applications = DJApplication.query.order_by(DJApplication.created_at.desc()).all()
    dj_profiles = DJProfile.query.order_by(DJProfile.created_at.desc(), DJProfile.stage_name.asc()).all()
    return render_template(
        "manager.html",
        pending=[serialize_booking(booking) for booking in pending],
        accepted=[serialize_booking(booking) for booking in accepted],
        applications=[serialize_application(application) for application in applications],
        dj_profiles=[serialize_dj_profile(profile) for profile in dj_profiles],
        djs=public_djs(),
        total_bookings=Booking.query.count(),
        total_applications=DJApplication.query.count(),
        total_users=User.query.count(),
    )


@app.route("/manager/bookings/<booking_id>/accept", methods=["POST"])
@manager_required
def accept_booking(booking_id):
    booking = Booking.query.filter_by(public_id=booking_id).first()
    if booking is None:
        abort(404)

    conflicts = booking_conflicts(booking.dj, booking.event_date, booking.start_time, booking.end_time, exclude_public_id=booking.public_id)
    if conflicts:
        return redirect(url_for("manager", booking_conflict=booking.public_id))

    booking.status = "accepted"
    booking.accepted_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("manager"))


@app.route("/manager/applications/<application_id>/accept", methods=["POST"])
@manager_required
def accept_application(application_id):
    application = DJApplication.query.filter_by(public_id=application_id).first()
    if application is None:
        abort(404)

    application.status = "accepted"
    application.manager_note = request.form.get("manager_note", "").strip()
    application.decided_at = datetime.utcnow()
    db.session.commit()
    sync_dj_status_records()
    sync_dj_directory_records()

    send_notification(
        subject=f"Je DJ-aanmelding is geaccepteerd: {application.stage_name}",
        body=(
            f"Proficiat, je Bassly-aanmelding werd geaccepteerd.\n\n"
            f"DJ: {application.stage_name}\n"
            f"Status: geaccepteerd\n"
            f"Notitie: {application.manager_note or 'Geen extra notitie'}\n"
        ),
        to_address=application.email,
    )
    return redirect(url_for("manager"))


@app.route("/manager/applications/<application_id>/reject", methods=["POST"])
@manager_required
def reject_application(application_id):
    application = DJApplication.query.filter_by(public_id=application_id).first()
    if application is None:
        abort(404)

    application.status = "rejected"
    application.manager_note = request.form.get("manager_note", "").strip()
    application.decided_at = datetime.utcnow()
    db.session.commit()

    send_notification(
        subject=f"Update over je DJ-aanmelding bij Bassly",
        body=(
            f"Bedankt voor je aanmelding bij Bassly.\n\n"
            f"DJ: {application.stage_name}\n"
            f"Status: geweigerd\n"
            f"Notitie: {application.manager_note or 'Geen extra notitie'}\n"
        ),
        to_address=application.email,
    )
    return redirect(url_for("manager"))


@app.route("/manager/djs/<slug>/toggle", methods=["POST"])
@manager_required
def toggle_dj_status(slug):
    dj_status = DJStatus.query.filter_by(slug=slug).first()
    if dj_status is None:
        dj = find_public_dj(slug)
        if dj is None:
            abort(404)
        dj_status = DJStatus(slug=slug, name=dj["name"], active=False, source=dj.get("source", "core"))
        db.session.add(dj_status)
    else:
        dj_status.active = not dj_status.active
    db.session.commit()
    profile = DJProfile.query.filter_by(slug=slug).first()
    if profile:
        profile.is_bookable = dj_status.active
        db.session.add(profile)
        db.session.commit()
    return redirect(url_for("manager"))


@app.route("/manager/dj-profiles/<int:profile_id>/approve", methods=["POST"])
@manager_required
def approve_dj_profile(profile_id):
    profile = DJProfile.query.get_or_404(profile_id)
    profile.is_approved = True
    profile.is_bookable = True
    db.session.add(profile)
    db.session.commit()

    dj_status = DJStatus.query.filter_by(slug=profile.slug).first()
    if dj_status is None:
        dj_status = DJStatus(slug=profile.slug, name=profile.stage_name, active=True, source="account")
        db.session.add(dj_status)
    else:
        dj_status.name = profile.stage_name
        dj_status.active = True
        dj_status.source = "account"
    db.session.commit()
    return redirect(url_for("manager"))


@app.route("/manager/export/bookings.csv")
@manager_required
def export_bookings():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "email", "phone", "dj", "date", "start", "end", "status", "location"])
    for booking in Booking.query.order_by(Booking.event_date.asc(), Booking.start_time.asc()).all():
        writer.writerow(
            [
                booking.public_id,
                booking.name,
                booking.email,
                booking.phone,
                booking.dj,
                booking.event_date.isoformat(),
                booking.start_time.strftime("%H:%M"),
                booking.end_time.strftime("%H:%M"),
                booking.status,
                booking.location,
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bookings.csv"},
    )


@app.route("/manager/export/applications.csv")
@manager_required
def export_applications():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "stage_name", "contact_name", "email", "city", "genres", "status", "created_at"])
    for application in DJApplication.query.order_by(DJApplication.created_at.desc()).all():
        writer.writerow(
            [
                application.public_id,
                application.stage_name,
                application.contact_name,
                application.email,
                application.city,
                application.genres,
                application.status,
                application.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=dj-applications.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
