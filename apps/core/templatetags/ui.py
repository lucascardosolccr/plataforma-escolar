"""Componentes de interface usados pelos templates.

``{% icon "house" %}`` desenha um ícone do sprite local (static/icons). O
ícone é sempre decorativo (aria-hidden): quem precisa de nome acessível é o
botão ou link que o contém.
"""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, extra_class=""):
    href = static("icons/sprite.svg")
    css = f"ds-icon {extra_class}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}#i-{}"></use></svg>',
        css, href, name,
    )


@register.filter
def count_where(items, key):
    """Quantos itens têm ``key`` verdadeiro: ``{{ medias|count_where:"below" }}``."""
    return sum(1 for item in items or () if item.get(key))
