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


# --- Anexos de apoio (atividades de casa) ---------------------------------
# Lista de permissão: só materiais de estudo. Executáveis, scripts e arquivos
# compactados ficam fora para que nada enviado possa ser executado.
ALLOWED_ATTACHMENT_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".doc",
    ".docx",
    ".odt",
    ".ppt",
    ".pptx",
    ".odp",
    ".xls",
    ".xlsx",
    ".ods",
    ".txt",
    ".csv",
)

ATTACHMENT_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

MAX_ATTACHMENT_SIZE_MB = 10
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_MB * 1024 * 1024


def attachment_extension(filename):
    return os.path.splitext(filename or "")[1].lower()


def validate_attachment(file):
    if file is None:
        return
    if file.size == 0:
        raise ValidationError("O arquivo está vazio.")
    if file.size > MAX_ATTACHMENT_SIZE_BYTES:
        raise ValidationError(
            f"O arquivo excede o limite de {MAX_ATTACHMENT_SIZE_MB} MB."
        )
    ext = attachment_extension(file.name)
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(
            "Formato não permitido. Envie PDF, imagem, documento, planilha "
            "ou apresentação."
        )


def safe_attachment_path(instance, filename):
    """Nome aleatório no disco: o nome original fica no banco, então um nome
    enviado pelo usuário nunca chega ao sistema de arquivos."""
    ext = attachment_extension(filename)
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        ext = ".bin"
    return f"activities/{uuid.uuid4().hex}{ext}"


def attachment_content_type(filename):
    """Tipo declarado a partir da extensão já validada. Desconhecido vira
    octet-stream para o navegador nunca renderizar o arquivo em linha."""
    return ATTACHMENT_CONTENT_TYPES.get(
        attachment_extension(filename), "application/octet-stream"
    )