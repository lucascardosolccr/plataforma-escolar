"""Componentes dos painéis de BI.

``{% metric_info "chave" %}`` mostra, num ``<details>`` acessível por teclado
e toque, a definição do indicador vinda de ``analytics.metrics`` — a mesma
fonte da página de metodologia.
"""

from django import template
from django.urls import reverse
from django.utils.html import format_html

from ..metrics import METRICS

register = template.Library()


@register.filter
def num(value, places=1):
    """Número no padrão brasileiro; ausência de dado vira "—" (nunca 0)."""
    if value is None or value == "":
        return "—"
    try:
        places = int(places)
        return f"{float(value):.{places}f}".replace(".", ",")
    except (TypeError, ValueError):
        return value


@register.filter
def signed(value, places=1):
    """Variação com sinal: +1,2 / −0,8 / —."""
    if value is None:
        return "—"
    v = float(value)
    texto = f"{abs(v):.{int(places)}f}".replace(".", ",")
    return f"+{texto}" if v > 0 else (f"−{texto}" if v < 0 else texto)


@register.filter
def heat(value, scale=10):
    """Intensidade 0–1 para mapas de calor (célula vazia = 0)."""
    if value is None:
        return 0
    try:
        return round(max(0.0, min(1.0, float(value) / float(scale))), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def heat_level(value, scale=10):
    """Faixa 0–10 do mapa de calor, usada como classe (heat-0 … heat-10)."""
    return int(round(heat(value, scale) * 10))


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag
def metric_info(key):
    m = METRICS.get(key)
    if m is None:
        return ""
    url = reverse("analytics:methodology") + f"#{m.key}"
    return format_html(
        '<details class="metric-info">'
        '<summary aria-label="Como é calculado: {label}" title="Como é calculado">'
        '<span aria-hidden="true">i</span></summary>'
        '<div class="metric-pop" role="note">'
        '<p class="metric-pop-title">{label} <span class="metric-kind">{kind}</span></p>'
        "<p>{measures}</p>"
        "<dl><dt>Fórmula</dt><dd>{formula}</dd>"
        "<dt>Fonte</dt><dd>{source}</dd>"
        "<dt>Sem dado</dt><dd>{missing}</dd>"
        "<dt>Como ler</dt><dd>{interpretation}</dd>"
        "<dt>Limitações</dt><dd>{limitations}</dd></dl>"
        '<a href="{url}">Metodologia completa</a>'
        "</div></details>",
        label=m.label, kind=m.kind, measures=m.measures, formula=m.formula,
        source=m.source, missing=m.missing, interpretation=m.interpretation,
        limitations=m.limitations, url=url,
    )


@register.filter
def cat(value, arg):
    """Concatena como texto (o ``add`` do Django devolve vazio com decimais)."""
    return f"{'' if value is None else value}{'' if arg is None else arg}"


@register.filter
def pct_txt(value, places=1):
    """Percentual com "%"; ausência de dado vira "—" (sem "%" pendurado)."""
    if value is None or value == "":
        return "—"
    return f"{num(value, places)}%"
