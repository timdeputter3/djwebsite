import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, redirect, render_template, request, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_FILE = BASE_DIR / "bookings.json"

DJ_PROFILES = [
    {
        "name": "Nova Luxe",
        "genre": "Open format / premium events",
        "bio": "Verbindt classy cocktails, volle dansvloeren en een vlekkeloze opbouw naar prime time.",
        "image": "dj-nova.svg",
    },
    {
        "name": "AURIC",
        "genre": "House / afro / sunset grooves",
        "bio": "Bekend voor warme, stijlvolle sets met internationale flair en veel gevoel voor sfeeropbouw.",
        "image": "dj-auric.svg",
    },
    {
        "name": "Vicle",
        "genre": "Club / techno / late-night energy",
        "bio": "Levert een strakke, moderne sound voor events die langer mogen nazinderen dan de laatste track.",
        "image": "dj-vicle.svg",
    },
]


def ensure_booking_store():
    if not BOOKINGS_FILE.exists():
        BOOKINGS_FILE.write_text("[]", encoding="utf-8")


def load_bookings():
    ensure_booking_store()
    return json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))


def save_bookings(bookings):
    BOOKINGS_FILE.write_text(
        json.dumps(bookings, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def parse_booking_datetime(booking):
    try:
        return datetime.strptime(
            f"{booking['event_date']} {booking['start_time']}",
            "%Y-%m-%d %H:%M",
        )
    except (KeyError, ValueError):
        return datetime.max


def accepted_bookings():
    bookings = [booking for booking in load_bookings() if booking["status"] == "accepted"]
    return sorted(bookings, key=parse_booking_datetime)


@app.route("/")
def home():
    agenda = accepted_bookings()[:4]
    return render_template("index.html", djs=DJ_PROFILES, agenda=agenda)


@app.route("/djs")
def djs():
    return render_template("djs.html", djs=DJ_PROFILES)


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        bookings = load_bookings()
        booking = {
            "id": uuid4().hex[:10],
            "name": request.form["name"].strip(),
            "email": request.form["email"].strip(),
            "phone": request.form["phone"].strip(),
            "company": request.form.get("company", "").strip(),
            "event_type": request.form["event_type"].strip(),
            "event_date": request.form["event_date"],
            "start_time": request.form["start_time"],
            "end_time": request.form["end_time"],
            "location": request.form["location"].strip(),
            "guests": request.form["guests"].strip(),
            "dj": request.form["dj"].strip(),
            "notes": request.form.get("notes", "").strip(),
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        bookings.append(booking)
        save_bookings(bookings)
        return redirect(url_for("book", success="1"))

    return render_template(
        "booking.html",
        djs=DJ_PROFILES,
        success=request.args.get("success") == "1",
    )


@app.route("/manager")
def manager():
    bookings = load_bookings()
    pending = sorted(
        [booking for booking in bookings if booking["status"] == "pending"],
        key=parse_booking_datetime,
    )
    accepted = sorted(
        [booking for booking in bookings if booking["status"] == "accepted"],
        key=parse_booking_datetime,
    )
    return render_template(
        "manager.html",
        pending=pending,
        accepted=accepted,
        total_bookings=len(bookings),
    )


@app.route("/manager/bookings/<booking_id>/accept", methods=["POST"])
def accept_booking(booking_id):
    bookings = load_bookings()
    for booking in bookings:
        if booking["id"] == booking_id:
            booking["status"] = "accepted"
            booking["accepted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_bookings(bookings)
            return redirect(url_for("manager"))
    abort(404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
