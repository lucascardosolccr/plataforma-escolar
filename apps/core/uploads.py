import os
import uuid

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


ALLOWED_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_PHOTO_SIZE_MB = 2
MAX_PHOTO_SIZE_BYTES = MAX_PHOTO_SIZE_MB * 1024 * 1024


def validate_photo(file):
    if file is None:
        return
    if file.size > MAX_PHOTO_SIZE_BYTES:
        raise ValidationError(
            f"A imagem excede o limite de {MAX_PHOTO_SIZE_MB} MB."
        )
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise ValidationError(
            "Formato não permitido. Use JPG, PNG ou WEBP."
        )


def safe_photo_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        ext = ".jpg"
    return f"photos/{uuid.uuid4().hex}{ext}"