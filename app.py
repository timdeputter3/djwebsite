import json
import os
from calendar import month_name, monthrange
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LEGACY_BOOKINGS_FILE = BASE_DIR / "bookings.json"
LOCAL_DATABASE = BASE_DIR / "bassly.db"

database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or f"sqlite:///{LOCAL_DATABASE.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bassly-dev-secret-change-me")

db = SQLAlchemy(app)
MANAGER_PASSWORD = os.environ.get("MANAGER_PASSWORD", "Moustache09")

DJ_PROFILES = [
    {
        "name": "DJ Vet & Vriend",
        "genre": "Open format / all-round party / student events",
        "bio": "Een energiek duo uit de regio dat vlot schakelt tussen meezingers, party classics en moderne tracks om elk publiek meteen mee te krijgen.",
        "image": "dj-vet-vriend.png",
    },
    {
        "name": "Vicle",
        "genre": "Club / house / late-night energy",
        "bio": "Brengt een frisse, hedendaagse sound met clubgevoel, sterke opbouw en de juiste energie voor avonden die mogen blijven hangen.",
        "image": "vicle.jpg",
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


def serialize_booking(booking):
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
    }


def migrate_legacy_bookings():
    if not LEGACY_BOOKINGS_FILE.exists():
        return
    if Booking.query.first() is not None:
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
    db.create_all()
    migrate_legacy_bookings()


def accepted_bookings(limit=None):
    query = (
        Booking.query.filter_by(status="accepted")
        .order_by(Booking.event_date.asc(), Booking.start_time.asc())
    )
    bookings = query.limit(limit).all() if limit else query.all()
    return [serialize_booking(booking) for booking in bookings]


def add_month_bucket(months, date_value):
    month_key = (date_value.year, date_value.month)
    if month_key not in months:
        first_weekday, total_days = monthrange(date_value.year, date_value.month)
        months[month_key] = {
            "label": f"{month_name[date_value.month]} {date_value.year}",
            "year": date_value.year,
            "month": date_value.month,
            "total_days": total_days,
            "first_weekday": first_weekday,
            "days": [
                {
                    "day": day,
                    "weekday": ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"][
                        datetime(date_value.year, date_value.month, day).weekday()
                    ],
                }
                for day in range(1, total_days + 1)
            ],
            "timeline_events": [],
        }
    return months[month_key]


def build_agenda_months():
    bookings = accepted_bookings()
    months = {}
    for booking in bookings:
        start_date = datetime.strptime(booking["event_date"], "%Y-%m-%d").date()
        overnight = booking["end_time"] <= booking["start_time"]
        end_date = start_date + timedelta(days=1) if overnight else start_date

        current_date = start_date
        while current_date <= end_date:
            month_bucket = add_month_bucket(months, current_date)
            month_start = current_date.replace(day=1)
            month_end = current_date.replace(day=month_bucket["total_days"])

            segment_start = max(start_date, month_start)
            segment_end = min(end_date, month_end)

            month_bucket["timeline_events"].append(
                {
                    "id": booking["id"],
                    "dj": booking["dj"],
                    "location": booking["location"],
                    "start_time": booking["start_time"],
                    "end_time": booking["end_time"],
                    "event_type": booking["event_type"],
                    "start_day": segment_start.day,
                    "end_day": segment_end.day,
                    "starts_here": segment_start == start_date,
                    "ends_here": segment_end == end_date,
                    "is_overnight": overnight,
                }
            )

            current_date = month_end + timedelta(days=1)

    for month in months.values():
        month["timeline_events"].sort(
            key=lambda item: (item["start_day"], item["start_time"], item["dj"])
        )

    return [months[key] for key in sorted(months)]


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
    return {"manager_logged_in": is_manager_logged_in()}


with app.app_context():
    bootstrap_database()


@app.route("/")
def home():
    agenda = accepted_bookings(limit=4)
    return render_template("index.html", djs=DJ_PROFILES, agenda=agenda)


@app.route("/djs")
def djs():
    return render_template("djs.html", djs=DJ_PROFILES)


@app.route("/agenda")
def agenda():
    return render_template("agenda.html", agenda_events=accepted_bookings())


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        booking = Booking(
            public_id=datetime.utcnow().strftime("%y%m%d%H%M%S%f")[-10:],
            name=request.form["name"].strip(),
            email=request.form["email"].strip(),
            phone=request.form["phone"].strip(),
            company=request.form.get("company", "").strip(),
            event_type=request.form["event_type"].strip(),
            event_date=datetime.strptime(request.form["event_date"], "%Y-%m-%d").date(),
            start_time=datetime.strptime(request.form["start_time"], "%H:%M").time(),
            end_time=datetime.strptime(request.form["end_time"], "%H:%M").time(),
            location=request.form["location"].strip(),
            guests=int(request.form["guests"]),
            dj=request.form["dj"].strip(),
            notes=request.form.get("notes", "").strip(),
            status="pending",
        )
        db.session.add(booking)
        db.session.commit()
        return redirect(url_for("book", success="1"))

    return render_template(
        "booking.html",
        djs=DJ_PROFILES,
        success=request.args.get("success") == "1",
    )


@app.route("/manager/login", methods=["GET", "POST"])
def manager_login():
    error = False
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == MANAGER_PASSWORD:
            session["manager_authenticated"] = True
            destination = request.args.get("next") or url_for("manager")
            return redirect(destination)
        error = True

    return render_template("manager_login.html", error=error)


@app.route("/manager/logout")
def manager_logout():
    session.pop("manager_authenticated", None)
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
    return render_template(
        "manager.html",
        pending=[serialize_booking(booking) for booking in pending],
        accepted=[serialize_booking(booking) for booking in accepted],
        total_bookings=Booking.query.count(),
    )


@app.route("/manager/bookings/<booking_id>/accept", methods=["POST"])
@manager_required
def accept_booking(booking_id):
    booking = Booking.query.filter_by(public_id=booking_id).first()
    if booking is None:
        abort(404)

    booking.status = "accepted"
    booking.accepted_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("manager"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
