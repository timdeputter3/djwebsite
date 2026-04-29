import os
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LEGACY_BOOKINGS_FILE = BASE_DIR / "bookings.json"
LOCAL_DATABASE = BASE_DIR / "bassly.db"
DJ_IMAGE_ROOT = BASE_DIR / "static" / "img" / "djs"
APPLICATION_UPLOAD_ROOT = BASE_DIR / "static" / "uploads" / "dj-applications"
DJ_PROFILE_UPLOAD_ROOT = BASE_DIR / "static" / "uploads" / "dj-profiles"
UPLOAD_BACKEND = os.environ.get("UPLOAD_BACKEND", "local")
SUPABASE_PROJECT_URL = os.environ.get("SUPABASE_PROJECT_URL", "")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "bassly-media")

MANAGER_USERNAME = os.environ.get("MANAGER_USERNAME", "managertim")
MANAGER_PASSWORD_RAW = os.environ.get("MANAGER_PASSWORD", "managertim132")
MANAGER_PASSWORD_HASH = generate_password_hash(MANAGER_PASSWORD_RAW)
MANAGER_EMAIL = os.environ.get("MANAGER_EMAIL", "manager@bassly.local")

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME or "")
MANAGER_NOTIFY_EMAIL = os.environ.get("MANAGER_NOTIFY_EMAIL")

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def build_gallery(folder_name):
    folder = DJ_IMAGE_ROOT / folder_name
    if not folder.exists():
        return []

    files = sorted(
        [
            file
            for file in folder.iterdir()
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


def get_database_uri():
    database_url = os.environ.get("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url and database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url or f"sqlite:///{LOCAL_DATABASE.as_posix()}"
