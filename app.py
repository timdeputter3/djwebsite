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

from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LEGACY_BOOKINGS_FILE = BASE_DIR / "bookings.json"
LOCAL_DATABASE = BASE_DIR / "bassly.db"
DJ_IMAGE_ROOT = BASE_DIR / "static" / "img" / "djs"
APPLICATION_UPLOAD_ROOT = BASE_DIR / "static" / "uploads" / "dj-applications"

database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or f"sqlite:///{LOCAL_DATABASE.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bassly-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024

db = SQLAlchemy(app)

MANAGER_USERNAME = os.environ.get("MANAGER_USERNAME", "managertim")
MANAGER_PASSWORD_RAW = os.environ.get("MANAGER_PASSWORD", "managertim132")
MANAGER_PASSWORD_HASH = generate_password_hash(MANAGER_PASSWORD_RAW)
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME or "")
MANAGER_NOTIFY_EMAIL = os.environ.get("MANAGER_NOTIFY_EMAIL")


def slugify_name(value):
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or uuid4().hex[:8]


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
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)


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
    sync_dj_status_records()


def accepted_bookings(limit=None):
    query = (
        Booking.query.filter_by(status="accepted")
        .order_by(Booking.event_date.asc(), Booking.start_time.asc())
    )
    bookings = query.limit(limit).all() if limit else query.all()
    return [serialize_booking(booking) for booking in bookings]


def public_djs():
    status_map = {item.slug: item for item in DJStatus.query.all()}
    accepted_applications = (
        DJApplication.query.filter_by(status="accepted")
        .order_by(DJApplication.created_at.desc())
        .all()
    )
    dynamic = []
    core = []
    for dj in DJ_PROFILES:
        status = status_map.get(dj["slug"])
        core.append({**dj, "active": True if status is None else status.active})

    for application in accepted_applications:
        photos = json.loads(application.photo_paths or "[]")
        slug = slugify_name(application.stage_name)
        status = status_map.get(slug)
        dynamic.append(
            {
                "name": application.stage_name,
                "slug": slug,
                "genre": application.genres,
                "bio": application.bio,
                "gallery": photos,
                "availability": parse_availability(application.availability),
                "socials": application.socials or "",
                "music_style": application.music_style,
                "experience": application.experience,
                "city": application.city,
                "source": "application",
                "active": True if status is None else status.active,
            }
        )
    return core + dynamic


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


def manager_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not is_manager_logged_in():
            return redirect(url_for("manager_login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_global_state():
    return {
        "manager_logged_in": is_manager_logged_in(),
        "manager_username": MANAGER_USERNAME,
    }


with app.app_context():
    bootstrap_database()


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
def book():
    djs = active_public_djs()
    if request.method == "POST":
        event_date = datetime.strptime(request.form["event_date"], "%Y-%m-%d").date()
        start_time = datetime.strptime(request.form["start_time"], "%H:%M").time()
        end_time = datetime.strptime(request.form["end_time"], "%H:%M").time()
        dj_name = request.form["dj"].strip()
        selected_dj = next((dj for dj in public_djs() if dj["name"] == dj_name), None)
        if selected_dj is None or not selected_dj.get("active", True):
            return render_template(
                "booking.html",
                djs=djs,
                success=False,
                conflicts=[],
                form_data=request.form,
                booking_error="Deze DJ staat momenteel op inactief en kan niet geboekt worden.",
            )
        conflicts = booking_conflicts(dj_name, event_date, start_time, end_time)
        if conflicts:
            return render_template(
                "booking.html",
                djs=djs,
                success=False,
                conflicts=conflicts,
                form_data=request.form,
                booking_error="",
            )

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
        form_data={},
        booking_error="",
    )


@app.route("/contact")
def contact():
    return render_template("contact.html")


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
    return render_template(
        "manager.html",
        pending=[serialize_booking(booking) for booking in pending],
        accepted=[serialize_booking(booking) for booking in accepted],
        applications=[serialize_application(application) for application in applications],
        djs=public_djs(),
        total_bookings=Booking.query.count(),
        total_applications=DJApplication.query.count(),
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
