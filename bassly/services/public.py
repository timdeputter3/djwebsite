import json

from flask_login import current_user

from bassly.config import DJ_PROFILES
from bassly.extensions import db
from bassly.models import Booking, DJApplication, DJProfile, DJStatus
from bassly.utils import booking_bounds, parse_availability, serialize_booking, serialize_dj_profile, slugify_name


def accepted_bookings(limit=None):
    query = Booking.query.filter_by(status="accepted").order_by(Booking.event_date.asc(), Booking.start_time.asc())
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


def sync_dj_status_records():
    existing = {record.slug: record for record in DJStatus.query.all()}

    for dj in DJ_PROFILES:
        if dj["slug"] not in existing:
            existing[dj["slug"]] = DJStatus(
                slug=dj["slug"],
                name=dj["name"],
                active=True,
                source="core",
            )
            db.session.add(existing[dj["slug"]])

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


def all_dj_profiles_for_manager():
    return DJProfile.query.order_by(DJProfile.created_at.desc(), DJProfile.stage_name.asc()).all()


def serialize_profiles_for_manager(profiles):
    return [serialize_dj_profile(profile) for profile in profiles]
