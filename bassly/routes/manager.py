import csv
import io
from datetime import datetime

from flask import Response, abort, redirect, render_template, request, url_for
from flask_login import current_user

from bassly.auth import manager_required
from bassly.extensions import db
from bassly.models import Booking, DJApplication, DJProfile, DJStatus, User
from bassly.services.notifications import send_notification
from bassly.services.public import (
    all_dj_profiles_for_manager,
    booking_conflicts,
    find_public_dj,
    public_djs,
    serialize_profiles_for_manager,
    sync_dj_directory_records,
    sync_dj_status_records,
)
from bassly.utils import serialize_application, serialize_booking


def register_manager_routes(app):
    @app.route("/manager/login", methods=["GET", "POST"])
    def manager_login():
        destination = request.args.get("next") or url_for("manager")
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=destination))
        if current_user.role != "admin":
            abort(403)
        return redirect(destination)

    @app.route("/manager/logout")
    def manager_logout():
        return redirect(url_for("logout"))

    @app.route("/manager")
    @manager_required
    def manager():
        pending = Booking.query.filter_by(status="pending").order_by(Booking.event_date.asc(), Booking.start_time.asc()).all()
        accepted = Booking.query.filter_by(status="accepted").order_by(Booking.event_date.asc(), Booking.start_time.asc()).all()
        applications = DJApplication.query.order_by(DJApplication.created_at.desc()).all()
        dj_profiles = all_dj_profiles_for_manager()
        return render_template(
            "manager.html",
            pending=[serialize_booking(booking) for booking in pending],
            accepted=[serialize_booking(booking) for booking in accepted],
            applications=[serialize_application(application) for application in applications],
            dj_profiles=serialize_profiles_for_manager(dj_profiles),
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

        conflicts = booking_conflicts(
            booking.dj,
            booking.event_date,
            booking.start_time,
            booking.end_time,
            exclude_public_id=booking.public_id,
        )
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
            subject="Update over je DJ-aanmelding bij Bassly",
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
