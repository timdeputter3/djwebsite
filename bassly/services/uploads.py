from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename

from bassly.config import APPLICATION_UPLOAD_ROOT, DJ_PROFILE_UPLOAD_ROOT
from bassly.utils import allowed_image


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
