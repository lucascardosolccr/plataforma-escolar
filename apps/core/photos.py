"""Tratamento de fotografias enviadas (estudantes, famílias e equipe).

Toda foto passa por aqui antes de ir para o disco:

- confere que é mesmo uma imagem (o Pillow abre e decodifica), recusando
  arquivos gigantes em pixels ("bomba de descompressão");
- corrige a rotação do celular (EXIF) e recorta um quadrado central;
- reduz para no máximo 512×512 e grava em JPEG comprimido;
- descarta todos os metadados: fotos de celular trazem a localização GPS de
  onde foram tiradas, e isso não pode acompanhar a foto de uma criança.

O recorte fino é feito no navegador (``data-photo-crop`` em ``ds.js``); o
recorte central aqui garante o formato mesmo sem JavaScript.

A foto é só identificação visual: nada aqui faz nem permite reconhecimento
facial ou biometria.
"""

import io

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

SIZE = 512
MAX_PIXELS = 40_000_000  # ~40 megapixels: acima disso, recusa


def process_photo(uploaded, name_hint="foto"):
    """Devolve um ``ContentFile`` JPEG quadrado, ou levanta ValidationError."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        uploaded.seek(0)
    except (AttributeError, OSError):
        pass
    data = uploaded.read()
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # estrutura do arquivo
        img = Image.open(io.BytesIO(data))
        if img.format not in ("JPEG", "PNG", "WEBP", "MPO"):
            raise ValidationError("Formato não permitido. Use JPG, PNG ou WEBP.")
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValidationError("O arquivo não é uma imagem válida.")
    except Image.DecompressionBombError:
        raise ValidationError("A imagem é grande demais. Envie uma foto com menos resolução.")
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), Image.LANCZOS) if min(img.size) >= SIZE else _square(img)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)  # sem exif=: metadados ficam fora
    return ContentFile(out.getvalue(), name=f"{name_hint}.jpg")


def _square(img):
    """Foto pequena: recorta o quadrado central sem ampliar."""
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def save_photo(instance, field_name, uploaded, name_hint="foto"):
    """Processa e grava a foto no campo, apagando o arquivo anterior."""
    content = process_photo(uploaded, name_hint)
    field = getattr(instance, field_name)
    old_name = field.name if field else None
    field.save(content.name, content, save=False)
    if old_name and old_name != field.name:
        field.storage.delete(old_name)
    return field
