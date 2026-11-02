"""Arquivos estáticos com compressão e cache, para o servidor da escola.

A escola roda o próprio ``runserver`` com DEBUG=0 (``iniciar.bat``), e o
Django serve ``static/`` por ``django.views.static.serve``: sem compressão e
sem cabeçalho de cache, a tela de login baixava ~530 KB a cada visita
(Lighthouse, 02/11/2026). Aqui:

- CSS, JS, SVG e JSON saem com gzip quando o navegador aceita. Só arquivos
  estáticos públicos: HTML com dados de estudante NÃO é comprimido, para não
  abrir a porta ao ataque BREACH;
- ``vendor/`` e ``fonts/`` (que só mudam numa atualização de biblioteca)
  ficam 7 dias no cache do navegador; o resto revalida a cada página
  (``no-cache``) e recebe 304 quando não mudou, então uma alteração de CSS ou
  JS chega na hora.
"""

import gzip
import os
import posixpath
from functools import lru_cache

from django.http import HttpResponse
from django.utils._os import safe_join
from django.utils.cache import patch_vary_headers
from django.views.static import serve

COMPRESSIBLE = ("text/css", "text/javascript", "application/javascript", "image/svg+xml", "application/json")
LONG_CACHE_PREFIXES = ("vendor/", "fonts/")
LONG_CACHE = "public, max-age=604800"


@lru_cache(maxsize=64)
def _gzipped(fullpath, mtime_ns):
    with open(fullpath, "rb") as f:
        return gzip.compress(f.read(), compresslevel=6, mtime=0)


def serve_static(request, path, document_root):
    response = serve(request, path, document_root=document_root)
    clean = posixpath.normpath(path).lstrip("/")
    cache = LONG_CACHE if clean.startswith(LONG_CACHE_PREFIXES) else "no-cache"
    if response.status_code not in (200, 304):
        return response
    response["Cache-Control"] = cache
    content_type = response.get("Content-Type", "").split(";")[0].strip()
    if response.status_code != 200 or content_type not in COMPRESSIBLE:
        return response
    patch_vary_headers(response, ("Accept-Encoding",))
    if "gzip" not in request.headers.get("Accept-Encoding", ""):
        return response
    fullpath = safe_join(document_root, clean)
    body = _gzipped(fullpath, os.stat(fullpath).st_mtime_ns)
    response.close()  # FileResponse aberto pelo serve
    compressed = HttpResponse(body, content_type=response["Content-Type"])
    for header in ("Last-Modified", "Cache-Control", "Vary"):
        compressed[header] = response[header]
    compressed["Content-Encoding"] = "gzip"
    compressed["Content-Length"] = str(len(body))
    return compressed
