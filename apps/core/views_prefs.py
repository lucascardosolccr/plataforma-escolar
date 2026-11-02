"""Favoritos e filtros salvos na conta (antes, só no navegador)."""

import json
import re
from urllib.parse import urlsplit

from django.http import HttpResponseBadRequest, JsonResponse
from django.urls import Resolver404, resolve
from django.views.decorators.http import require_POST

from .models import UserPreference

MAX_FAVORITES = 8
MAX_FILTERS = 10
KEY_RE = re.compile(r"^[\w:.-]{1,60}$")


def _clean_filter(item):
    """Só endereço interno, de rota existente e com filtros; rótulo curto."""
    if not isinstance(item, dict):
        return None
    url, label = item.get("url"), item.get("label")
    if not isinstance(url, str) or not isinstance(label, str) or len(url) > 500:
        return None
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not url.startswith("/") or url.startswith("//") or "\\" in url \
            or not parts.query:
        return None
    try:
        resolve(parts.path)
    except Resolver404:
        return None
    label = " ".join(label.split())[:80]
    return {"url": url, "label": label or parts.path}


@require_POST
def save_preferences(request):
    """Recebe {"favorites": [...]} e/ou {"filters": [...]} e devolve o que ficou salvo."""
    if len(request.body) > 16_000:
        return HttpResponseBadRequest("Grande demais.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponseBadRequest("JSON inválido.")
    if not isinstance(data, dict):
        return HttpResponseBadRequest("JSON inválido.")
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    fields = []
    if isinstance(data.get("favorites"), list):
        keys = []
        for k in data["favorites"]:
            if isinstance(k, str) and KEY_RE.match(k) and k not in keys:
                keys.append(k)
        pref.favorites = keys[:MAX_FAVORITES]
        fields.append("favorites")
    if isinstance(data.get("filters"), list):
        out = []
        for item in data["filters"]:
            f = _clean_filter(item)
            if f and all(f["url"] != o["url"] for o in out):
                out.append(f)
        pref.saved_filters = out[:MAX_FILTERS]
        fields.append("saved_filters")
    if fields:
        pref.save(update_fields=fields + ["updated_at"])
    return JsonResponse(pref.as_json())
