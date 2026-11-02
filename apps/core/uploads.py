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


# Assinatura (magic bytes) esperada por extensão. Sem esta conferência,
# renomear virus.exe para virus.pdf passa pela lista de extensões: o nome do
# arquivo é escolhido por quem envia e não prova nada sobre o conteúdo.
_ZIP = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")  # docx, xlsx, pptx, od*
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)  # doc, xls, ppt antigos

ATTACHMENT_SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    ".docx": _ZIP,
    ".xlsx": _ZIP,
    ".pptx": _ZIP,
    ".odt": _ZIP,
    ".ods": _ZIP,
    ".odp": _ZIP,
    ".doc": _OLE + _ZIP,
    ".xls": _OLE + _ZIP,
    ".ppt": _OLE + _ZIP,
}

# Conteúdo recusado em qualquer extensão: executável do Windows, binário ELF,
# classe Java e script com shebang.
EXECUTABLE_SIGNATURES = (
    b"MZ",
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",
    b"#!",
)

#: Extensões cujo conteúdo é texto puro e não tem assinatura própria.
TEXT_EXTENSIONS = (".txt", ".csv")


def validate_attachment_content(file):
    """Confere se o conteúdo corresponde à extensão declarada.

    Não substitui antivírus — um PDF malicioso continua sendo um PDF válido.
    O que isto impede é o caso simples e comum de trocar a extensão para
    passar pela lista de permissão.
    """
    if file is None:
        return
    pos = file.tell() if hasattr(file, "tell") else 0
    try:
        file.seek(0)
        head = file.read(2048)
    finally:
        try:
            file.seek(pos)
        except (OSError, ValueError):
            pass

    if not head:
        raise ValidationError("O arquivo está vazio.")

    for sig in EXECUTABLE_SIGNATURES:
        if head.startswith(sig):
            raise ValidationError(
                "Este arquivo é um programa executável e não pode ser enviado."
            )

    ext = attachment_extension(file.name)

    if ext in TEXT_EXTENSIONS:
        # Texto não tem assinatura; o byte nulo denuncia conteúdo binário.
        if b"\x00" in head:
            raise ValidationError(
                "O arquivo tem extensão de texto, mas o conteúdo é binário."
            )
        return

    expected = ATTACHMENT_SIGNATURES.get(ext)
    if expected and not any(head.startswith(sig) for sig in expected):
        raise ValidationError(
            f"O conteúdo do arquivo não corresponde a um {ext.lstrip('.').upper()}. "
            "Verifique se a extensão está correta."
        )


def safe_attachment_path(instance, filename, folder="activities"):
    """Nome aleatório no disco: o nome original fica no banco, então um nome
    enviado pelo usuário nunca chega ao sistema de arquivos."""
    ext = attachment_extension(filename)
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        ext = ".bin"
    return f"{folder}/{uuid.uuid4().hex}{ext}"


def safe_message_attachment_path(instance, filename):
    """Anexo de mensagem: mesma regra, em pasta própria."""
    return safe_attachment_path(instance, filename, folder="messages")


def attachment_content_type(filename):
    """Tipo declarado a partir da extensão já validada. Desconhecido vira
    octet-stream para o navegador nunca renderizar o arquivo em linha."""
    return ATTACHMENT_CONTENT_TYPES.get(
        attachment_extension(filename), "application/octet-stream"
    )