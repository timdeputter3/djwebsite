from email_validator import EmailNotValidError, validate_email

from bassly.extensions import db
from bassly.models import Customer, DJProfile, User
from bassly.utils import normalized_email, slugify_name


def create_user_with_profile(
    username,
    email,
    password,
    role,
    full_name="",
    phone="",
    company="",
    city="",
    stage_name="",
):
    try:
        email = normalized_email(validate_email(email, check_deliverability=False).normalized)
    except EmailNotValidError as exc:
        raise ValueError(f"Ongeldig e-mailadres: {exc}") from exc
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
