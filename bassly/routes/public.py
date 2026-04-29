import json
from datetime import datetime
from uuid import uuid4

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from bassly.auth import role_required
from bassly.extensions import db
from bassly.models import Booking, DJApplication, DJProfile, User
from bassly.services.accounts import create_user_with_profile
from bassly.services.notifications import send_notification
from bassly.services.public import (
    accepted_bookings,
    active_public_djs,
    available_public_djs_for_slot,
    booking_conflicts,
    booking_form_defaults,
    dj_is_available_on_date,
    find_public_dj,
    parse_slot_filters,
    public_djs,
)
from bassly.services.uploads import save_application_photos, save_dj_profile_photos
from bassly.utils import normalized_email, parse_availability


def register_public_routes(app):
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

    @app.route("/dj/availability", methods=["GET", "POST"])
    @role_required("dj")
    def dj_availability_edit():
        profile = current_user.dj_profile
        if profile is None:
            abort(404)

        if request.method == "POST":
            availability_dates = sorted(
                {item.strip() for item in request.form.get("availability_dates", "").split(",") if item.strip()}
            )
            profile.availability = json.dumps(availability_dates)
            db.session.add(profile)
            db.session.commit()
            flash("Je beschikbaarheden zijn bijgewerkt.", "success")
            return redirect(url_for("dj_availability_edit"))

        availability = parse_availability(profile.availability)
        return render_template(
            "dj_availability_edit.html",
            profile=profile,
            availability=availability,
            availability_count=len(availability),
        )

    @app.route("/")
    def home():
        agenda = accepted_bookings(limit=4)
        djs = public_djs()
        return render_template("index.html", djs=djs, agenda=agenda)

    @app.route("/djs")
    def djs():
        filter_state = {
            "event_date": request.args.get("event_date", ""),
            "start_time": request.args.get("start_time", ""),
            "end_time": request.args.get("end_time", ""),
        }
        slot_filter, filter_error = parse_slot_filters(
            filter_state["event_date"],
            filter_state["start_time"],
            filter_state["end_time"],
        )
        filtered_on_slot = False
        djs_list = public_djs()
        if slot_filter:
            djs_list = available_public_djs_for_slot(
                slot_filter["event_date"],
                slot_filter["start_time"],
                slot_filter["end_time"],
            )
            filtered_on_slot = True
        return render_template(
            "djs.html",
            djs=djs_list,
            filter_state=filter_state,
            filter_error=filter_error,
            filtered_on_slot=filtered_on_slot,
        )

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
    @role_required("dj")
    def join():
        profile = current_user.dj_profile
        if profile is None:
            abort(404)

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

        return render_template(
            "join.html",
            success=request.args.get("success") == "1",
            profile=profile,
            availability=parse_availability(profile.availability),
        )

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
            if not dj_is_available_on_date(selected_dj, event_date):
                return render_template(
                    "booking.html",
                    djs=djs,
                    success=False,
                    conflicts=[],
                    form_data=request.form.to_dict(),
                    booking_error="Deze DJ heeft zichzelf op die datum niet als beschikbaar gemarkeerd.",
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

            customer_profile = (
                current_user.customer_profile
                if current_user.is_authenticated and current_user.role == "customer"
                else None
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
